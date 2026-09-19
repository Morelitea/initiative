"""What ``record`` writes, and what it leaves out."""

import json

import pytest
from sqlmodel import select

from app.core.audit_events import SCHEMA_VERSION, AuditCategory, AuditEventType
from app.core.logging_config import configure_logging
from app.models.platform.audit_event import AuditEvent
from app.services import audit as audit_service
from app.testing import create_user

pytestmark = [pytest.mark.integration, pytest.mark.database]


@pytest.fixture(autouse=True)
def _served_logging():
    """The wiring ``app.main`` applies. No test below forces a level: what
    reaches stdout here is what reaches it in the served process."""
    configure_logging()


def _audit_lines(out: str) -> list[dict]:
    """The envelopes on a captured stdout, parsed."""
    return [
        json.loads(line)
        for line in out.splitlines()
        if line.startswith("{") and '"event_type"' in line
    ]


async def test_a_record_lands_in_the_callers_transaction(session):
    """Staged, not committed — which is what makes the record atomic with the
    action it describes."""
    actor = await create_user(session)
    subject = await create_user(session)

    await audit_service.record(
        session,
        event_type=AuditEventType.USER_AVATAR_REMOVED,
        actor_user_id=actor.id,
        target_user_id=subject.id,
        target_type="user",
        target_id=subject.id,
    )
    await session.commit()

    row = (
        await session.exec(
            select(AuditEvent).where(AuditEvent.actor_user_id == actor.id)
        )
    ).one()
    assert row.event_type == "user.avatar_removed"
    assert row.target_user_id == subject.id
    assert row.tier == 2


async def test_the_envelope_carries_ids_and_no_identity(session):
    """Names are resolved when the board is read. A name written into the
    record would outlive the erasure of the account it belongs to."""
    actor = await create_user(session, full_name="Ada Admin")
    subject = await create_user(session, full_name="Sam Subject")

    event = await audit_service.record(
        session,
        event_type=AuditEventType.USER_AVATAR_REMOVED,
        actor_user_id=actor.id,
        target_user_id=subject.id,
    )
    await session.commit()

    serialized = json.dumps(event.envelope)
    assert "Ada Admin" not in serialized
    assert "Sam Subject" not in serialized
    assert event.envelope["schema_version"] == SCHEMA_VERSION
    assert event.envelope["actor_user_id"] == actor.id


async def test_the_same_envelope_goes_to_stdout(session, capfd):
    """The ingestible seam: one bare JSON line on stdout per event, which an
    operator's existing container-log pipeline ships as-is. Read from the
    stream itself, under the served wiring, with no level forced."""
    actor = await create_user(session)
    capfd.readouterr()

    event = await audit_service.record(
        session,
        event_type=AuditEventType.USER_AVATAR_REMOVED,
        actor_user_id=actor.id,
    )
    await session.commit()

    assert _audit_lines(capfd.readouterr().out) == [event.envelope]


async def test_nothing_is_logged_until_the_write_lands(session, capfd):
    """The line is held until the transaction commits. Staged is not done, and
    a log that claimed otherwise would disagree with the table."""
    actor = await create_user(session)
    capfd.readouterr()

    await audit_service.record(
        session,
        event_type=AuditEventType.USER_AVATAR_REMOVED,
        actor_user_id=actor.id,
    )
    assert _audit_lines(capfd.readouterr().out) == []

    await session.commit()
    assert len(_audit_lines(capfd.readouterr().out)) == 1


async def test_a_rolled_back_action_tells_nobody(session, capfd):
    """An action that did not happen leaves no row and no line — the two sinks
    cannot disagree about it."""
    actor = await create_user(session)
    await session.commit()
    # Held before the rollback: it expires every loaded object, and reading an
    # attribute back would be a lazy load rather than the assertion we mean.
    actor_id = actor.id
    capfd.readouterr()

    await audit_service.record(
        session,
        event_type=AuditEventType.USER_AVATAR_REMOVED,
        actor_user_id=actor_id,
        target_type="user",
        target_id=actor_id,
    )
    await session.rollback()

    assert _audit_lines(capfd.readouterr().out) == []
    rows = (
        await session.exec(
            select(AuditEvent).where(AuditEvent.actor_user_id == actor_id)
        )
    ).all()
    assert rows == []


async def test_a_record_in_a_rolled_back_savepoint_tells_nobody(session, capfd):
    """A record staged inside a savepoint goes with it when the savepoint is
    rolled back, while one staged before it still lands with the commit."""
    actor = await create_user(session)
    await session.commit()
    actor_id = actor.id
    capfd.readouterr()

    kept = await audit_service.record(
        session,
        event_type=AuditEventType.USER_AVATAR_REMOVED,
        actor_user_id=actor_id,
    )
    savepoint = await session.begin_nested()
    await audit_service.record(
        session,
        event_type=AuditEventType.USER_USERNAME_CHANGED,
        actor_user_id=actor_id,
    )
    await savepoint.rollback()
    await session.commit()

    assert _audit_lines(capfd.readouterr().out) == [kept.envelope]
    rows = (
        await session.exec(
            select(AuditEvent).where(AuditEvent.actor_user_id == actor_id)
        )
    ).all()
    assert [r.event_type for r in rows] == ["user.avatar_removed"]


async def test_a_record_the_session_let_go_of_still_lands(session, capfd):
    """The row is written at the call, so a session that expunges everything
    afterwards — a sync hopping between communities does — still commits it,
    and the line still goes out."""
    actor = await create_user(session)
    await session.commit()
    actor_id = actor.id
    capfd.readouterr()

    event = await audit_service.record(
        session,
        event_type=AuditEventType.USER_AVATAR_REMOVED,
        actor_user_id=actor_id,
    )
    envelope = event.envelope
    session.expunge_all()
    await session.commit()

    assert _audit_lines(capfd.readouterr().out) == [envelope]
    rows = (
        await session.exec(
            select(AuditEvent).where(AuditEvent.actor_user_id == actor_id)
        )
    ).all()
    assert len(rows) == 1


async def test_a_record_survives_the_account_it_names(session):
    """No foreign key, by design: deleting the subject must not take the
    record of what was done to them with it."""
    actor = await create_user(session)
    subject = await create_user(session)
    subject_id = subject.id

    await audit_service.record(
        session,
        event_type=AuditEventType.USER_AVATAR_REMOVED,
        actor_user_id=actor.id,
        target_user_id=subject_id,
    )
    await session.commit()

    await session.delete(subject)
    await session.commit()

    row = (
        await session.exec(
            select(AuditEvent).where(AuditEvent.target_user_id == subject_id)
        )
    ).one()
    assert row.target_user_id == subject_id


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        # A flag and a number are copied both ways.
        (
            {"enabled": False, "port": 25},
            {"enabled": True, "port": 587},
            {
                "changed": ["enabled", "port"],
                "values": {
                    "enabled": {"from": False, "to": True},
                    "port": {"from": 25, "to": 587},
                },
            },
        ),
        # A string field is named and never copied.
        (
            {"password": "old", "host": "a"},
            {"password": "new", "host": "a"},
            {"changed": ["password"], "values": {}},
        ),
        # An enumeration is copied by value; a list of them too.
        (
            {"policy": AuditCategory.MODERATION, "methods": ["a", "b"]},
            {"policy": AuditCategory.PLATFORM, "methods": ["a"]},
            {
                "changed": ["methods", "policy"],
                "values": {"policy": {"from": "moderation", "to": "platform"}},
            },
        ),
        # Nothing moved, nothing said.
        ({"a": 1}, {"a": 1}, {"changed": [], "values": {}}),
        # A field on one side only moves from or to None.
        ({}, {"a": 1}, {"changed": ["a"], "values": {"a": {"from": None, "to": 1}}}),
    ],
)
def test_changed_fields_names_every_move_and_copies_only_safe_values(
    before, after, expected
):
    assert audit_service.changed_fields(before, after) == expected


def test_snapshot_reads_the_named_attributes():
    class Row:
        a = 1
        b = "x"
        c = None

    assert audit_service.snapshot(Row(), ["a", "b"]) == {"a": 1, "b": "x"}

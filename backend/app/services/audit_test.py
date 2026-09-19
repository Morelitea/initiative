"""What ``record`` writes, and what it leaves out."""

import json

import pytest
from app.core.audit_events import SCHEMA_VERSION, AuditCategory, AuditEventType
from app.core.logging_config import configure_logging
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
        if line.startswith("{") and '"stream":"audit"' in line
    ]


async def test_the_envelope_carries_ids_and_no_identity(session, capfd):
    """Names are resolved by whoever reads the stream, from ids. A name
    written into the record would outlive the erasure of the account."""
    actor = await create_user(session, full_name="Ada Admin")
    subject = await create_user(session, full_name="Sam Subject")
    actor_id, subject_id = actor.id, subject.id
    capfd.readouterr()

    envelope = await audit_service.record(
        session,
        event_type=AuditEventType.USER_AVATAR_REMOVED,
        actor_user_id=actor_id,
        target_user_id=subject_id,
        target_type="user",
        target_id=subject_id,
    )
    await session.commit()

    (line,) = _audit_lines(capfd.readouterr().out)
    assert line == envelope
    serialized = json.dumps(line)
    assert "Ada Admin" not in serialized and "Sam Subject" not in serialized
    assert line["schema_version"] == SCHEMA_VERSION
    assert line["event_type"] == "user.avatar_removed"
    assert line["actor_user_id"] == actor_id
    assert line["target_user_id"] == subject_id
    assert line["target"] == {"type": "user", "id": subject_id}
    assert line["tier"] == 2 and line["category"] == "moderation"


async def test_nothing_is_logged_until_the_write_lands(session, capfd):
    """The line is held until the transaction commits. Staged is not done."""
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
    """An action that did not happen leaves no line."""
    actor = await create_user(session)
    await session.commit()
    actor_id = actor.id
    capfd.readouterr()

    await audit_service.record(
        session,
        event_type=AuditEventType.USER_AVATAR_REMOVED,
        actor_user_id=actor_id,
    )
    await session.rollback()
    await session.commit()

    assert _audit_lines(capfd.readouterr().out) == []


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

    assert _audit_lines(capfd.readouterr().out) == [kept]


async def test_a_record_before_the_first_statement_lands_with_the_commit(
    session, capfd
):
    """Staged before the session has begun a transaction, the record rides
    the one the commit closes."""
    capfd.readouterr()
    envelope = await audit_service.record(
        session,
        event_type=AuditEventType.USER_AVATAR_REMOVED,
        actor_user_id=None,
    )
    await session.commit()
    assert _audit_lines(capfd.readouterr().out) == [envelope]


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

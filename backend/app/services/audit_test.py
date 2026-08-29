"""What ``record`` writes, and what it leaves out."""

import json
import logging

import pytest
from sqlmodel import select

from app.core.audit_events import SCHEMA_VERSION, AuditEventType
from app.models.platform.audit_event import AuditEvent
from app.services import audit as audit_service
from app.testing import create_user

pytestmark = [pytest.mark.integration, pytest.mark.database]


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


async def test_the_same_envelope_goes_to_the_log(session, caplog):
    """The ingestible seam: one JSON line on the ``audit`` logger, which an
    operator's existing container-log pipeline can ship as-is."""
    actor = await create_user(session)

    with caplog.at_level(logging.INFO, logger="audit"):
        event = await audit_service.record(
            session,
            event_type=AuditEventType.USER_AVATAR_REMOVED,
            actor_user_id=actor.id,
        )
        await session.commit()

    lines = [json.loads(r.message) for r in caplog.records if r.name == "audit"]
    assert lines == [event.envelope]


async def test_nothing_is_logged_until_the_write_lands(session, caplog):
    """The line is held until the transaction commits. Staged is not done, and
    a log that claimed otherwise would disagree with the table."""
    actor = await create_user(session)

    with caplog.at_level(logging.INFO, logger="audit"):
        await audit_service.record(
            session,
            event_type=AuditEventType.USER_AVATAR_REMOVED,
            actor_user_id=actor.id,
        )
        staged = [r for r in caplog.records if r.name == "audit"]
        assert staged == []

        await session.commit()
        assert len([r for r in caplog.records if r.name == "audit"]) == 1


async def test_a_rolled_back_action_tells_nobody(session, caplog):
    """An action that did not happen leaves no row and no line — the two sinks
    cannot disagree about it."""
    actor = await create_user(session)
    await session.commit()
    # Held before the rollback: it expires every loaded object, and reading an
    # attribute back would be a lazy load rather than the assertion we mean.
    actor_id = actor.id

    with caplog.at_level(logging.INFO, logger="audit"):
        await audit_service.record(
            session,
            event_type=AuditEventType.USER_AVATAR_REMOVED,
            actor_user_id=actor_id,
            target_type="user",
            target_id=actor_id,
        )
        await session.rollback()

    assert [r for r in caplog.records if r.name == "audit"] == []
    rows = (
        await session.exec(
            select(AuditEvent).where(AuditEvent.actor_user_id == actor_id)
        )
    ).all()
    assert rows == []


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

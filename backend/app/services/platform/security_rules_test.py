"""The refused sign-in rule: when it fires, what it names, and what it cannot do."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from app.core.audit_events import AuditEventType
from app.core.intake import IntakeStream
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.platform.audit_event import AuditEvent
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.models.tenant.task import Task
from app.services.platform import security_rules
from app.testing import create_guild, create_initiative, create_project, create_user

pytestmark = pytest.mark.integration


async def _refusals(session, *, user_id: int, count: int, age: timedelta | None = None):
    """Write ``count`` refused sign-ins against an account, as the app does."""
    occurred = datetime.now(timezone.utc) - (age or timedelta(0))
    for _ in range(count):
        session.add(
            AuditEvent(
                event_type=AuditEventType.AUTH_SIGN_IN_FAILED.value,
                occurred_at=occurred,
                actor_user_id=None,
                target_user_id=user_id,
                target_type="user",
                target_id=user_id,
                tier=2,
            )
        )
    await session.commit()


@pytest.fixture
async def bound(session):
    """A deployment with the security stream bound to a project."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)

    await set_rls_context(session)
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        row = AppSetting(id=1)
    row.operations_guild_id = guild.id
    session.add(row)
    await session.commit()

    await set_rls_context(session, guild_id=guild.id, guild_role="admin")
    session.add(IntakeBinding(stream=IntakeStream.security, project_id=project.id))
    await session.commit()
    await set_rls_context(session)
    return {"user": user, "guild": guild, "project": project}


async def test_below_the_threshold_nothing_is_opened(session, bound):
    subject = await create_user(session)
    await _refusals(
        session, user_id=subject.id, count=security_rules.SIGN_IN_REFUSAL_THRESHOLD - 1
    )

    assert await security_rules.note_failed_sign_in(subject.id) is None


async def test_crossing_the_threshold_opens_one_case(session, bound):
    subject = await create_user(session)
    await _refusals(
        session, user_id=subject.id, count=security_rules.SIGN_IN_REFUSAL_THRESHOLD
    )

    outcome = await security_rules.note_failed_sign_in(subject.id)
    assert outcome is not None
    assert outcome.opened is True

    await set_rls_context(session, guild_id=bound["guild"].id, guild_role="admin")
    task = (await session.exec(select(Task).where(Task.id == outcome.task_id))).one()
    assert task.project_id == bound["project"].id
    # The account is named by id, and nothing that was typed is carried.
    assert str(subject.id) in task.title


async def test_it_fires_at_or_above_rather_than_on_equality(session, bound):
    """Two refusals committing together can carry the count past the line."""
    subject = await create_user(session)
    await _refusals(
        session, user_id=subject.id, count=security_rules.SIGN_IN_REFUSAL_THRESHOLD + 3
    )

    assert await security_rules.note_failed_sign_in(subject.id) is not None


async def test_refusals_outside_the_window_do_not_count(session, bound):
    subject = await create_user(session)
    await _refusals(
        session,
        user_id=subject.id,
        count=security_rules.SIGN_IN_REFUSAL_THRESHOLD * 2,
        age=security_rules.SIGN_IN_REFUSAL_WINDOW + timedelta(minutes=5),
    )

    assert await security_rules.note_failed_sign_in(subject.id) is None


async def test_a_sustained_run_stays_one_case(session, bound):
    subject = await create_user(session)
    await _refusals(
        session, user_id=subject.id, count=security_rules.SIGN_IN_REFUSAL_THRESHOLD
    )

    first = await security_rules.note_failed_sign_in(subject.id)
    assert first is not None
    for _ in range(3):
        await _refusals(session, user_id=subject.id, count=1)
        again = await security_rules.note_failed_sign_in(subject.id)
        assert again is not None
        assert again.task_id == first.task_id
        assert again.opened is False

    await set_rls_context(session, guild_id=bound["guild"].id, guild_role="admin")
    cases = (
        await session.exec(
            select(IntakeCase).where(IntakeCase.task_id == first.task_id)
        )
    ).all()
    assert len(cases) == 1
    assert cases[0].occurrences == 4


async def test_one_account_crossing_does_not_open_a_case_for_another(session, bound):
    noisy = await create_user(session)
    quiet = await create_user(session)
    await _refusals(
        session, user_id=noisy.id, count=security_rules.SIGN_IN_REFUSAL_THRESHOLD
    )

    assert await security_rules.note_failed_sign_in(noisy.id) is not None
    assert await security_rules.note_failed_sign_in(quiet.id) is None


async def test_with_nothing_bound_the_rule_is_a_no_op(session):
    """The state every install starts in: the audit row still stands."""
    await set_rls_context(session)
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        row = AppSetting(id=1)
    row.operations_guild_id = None
    session.add(row)
    await session.commit()

    subject = await create_user(session)
    await _refusals(
        session, user_id=subject.id, count=security_rules.SIGN_IN_REFUSAL_THRESHOLD
    )

    assert await security_rules.note_failed_sign_in(subject.id) is None

    recorded = (
        await session.exec(
            select(AuditEvent).where(AuditEvent.target_user_id == subject.id)
        )
    ).all()
    assert len(recorded) == security_rules.SIGN_IN_REFUSAL_THRESHOLD


async def test_a_failure_inside_the_rule_never_reaches_the_caller(
    session, bound, monkeypatch
):
    """A detective control is not worth an availability risk."""
    subject = await create_user(session)
    await _refusals(
        session, user_id=subject.id, count=security_rules.SIGN_IN_REFUSAL_THRESHOLD
    )

    async def boom(*args, **kwargs):
        raise RuntimeError("the writer fell over")

    monkeypatch.setattr(security_rules, "open_case", boom)

    # Swallowed, and returns the same thing a quiet window returns.
    assert await security_rules.note_failed_sign_in(subject.id) is None


async def test_a_failure_is_logged_rather_than_hidden(
    session, bound, monkeypatch, caplog
):
    """The swallow is broad, so a real error has to be visible in the log."""
    subject = await create_user(session)
    await _refusals(
        session, user_id=subject.id, count=security_rules.SIGN_IN_REFUSAL_THRESHOLD
    )

    async def boom(*args, **kwargs):
        raise RuntimeError("the writer fell over")

    monkeypatch.setattr(security_rules, "open_case", boom)
    with caplog.at_level("ERROR"):
        await security_rules.note_failed_sign_in(subject.id)

    assert any("note_failed_sign_in" in record.message for record in caplog.records)

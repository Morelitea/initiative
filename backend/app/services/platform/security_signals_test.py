"""Counting what the security rules watch, and opening one case when a key
crosses its threshold — however many instances counted it."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlmodel import select

from app.core.audit_events import AuditEventType
from app.core.intake import IntakeStream
from app.core.security_rules import (
    BY_NAME,
    COLLAPSED_KEY,
    MAX_KEYS_PER_RULE,
    Signal,
)
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.services import audit as audit_service
from app.services.platform import security_signals
from app.testing import (
    create_guild,
    create_initiative,
    create_project,
    create_user,
    emitted,
)

#: Inside one ten-minute window, whenever the test runs.
_AT = datetime(2026, 10, 9, 12, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fresh_counts():
    security_signals.discard()
    yield
    security_signals.discard()


@pytest.fixture
async def security_desk(session):
    """A deployment whose security stream lands in a project."""
    staff = await create_user(session)
    ops_guild = await create_guild(session, creator=staff)
    initiative = await create_initiative(session, ops_guild, staff)
    project = await create_project(session, initiative, staff)
    await set_rls_context(session, Unattributed())
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        row = AppSetting(id=1)
    row.operations_guild_id = ops_guild.id
    session.add(row)
    await session.commit()
    await set_rls_context(session, SystemGuild(ops_guild.id))
    session.add(IntakeBinding(stream=IntakeStream.security, project_id=project.id))
    await session.commit()
    await set_rls_context(session, Unattributed())
    return ops_guild


def _failed_sign_in(ip: str) -> dict:
    return {
        "event_type": AuditEventType.AUTH_SIGN_IN_FAILED.value,
        "event_uuid": "evt",
        "actor_user_id": None,
        "target_user_id": None,
        "guild_id": None,
        "target": None,
        "detail": {},
        "context": {"source_ip": ip},
    }


async def _cases(session, guild_id: int) -> list[IntakeCase]:
    await set_rls_context(session, SystemGuild(guild_id))
    cases = list((await session.exec(select(IntakeCase))).all())
    await set_rls_context(session, Unattributed())
    return cases


async def test_one_short_of_the_threshold_opens_nothing_and_the_threshold_opens_one(
    session, security_desk
):
    for _ in range(49):
        security_signals.observe(_failed_sign_in("198.51.100.4"), now=_AT)
    assert await security_signals.flush() == []
    assert await _cases(session, security_desk.id) == []

    security_signals.observe(_failed_sign_in("198.51.100.4"), now=_AT)
    (crossing,) = await security_signals.flush()
    assert crossing.rule.name == "sign_in_spray"
    assert crossing.count == 50
    (case,) = await _cases(session, security_desk.id)
    assert case.dedupe_key == f"rule:sign_in_spray:{crossing.key}"
    # What the table holds names no address.
    assert "198.51.100.4" not in crossing.key


async def test_counts_from_two_instances_add_up_and_cross_once(session, security_desk):
    """Each flush adds to the shared row, as another process's would."""
    for _ in range(30):
        security_signals.observe(_failed_sign_in("198.51.100.5"), now=_AT)
    assert await security_signals.flush() == []
    for _ in range(25):
        security_signals.observe(_failed_sign_in("198.51.100.5"), now=_AT)
    assert len(await security_signals.flush()) == 1
    # Past the threshold already: counted, and no second crossing.
    for _ in range(25):
        security_signals.observe(_failed_sign_in("198.51.100.5"), now=_AT)
    assert await security_signals.flush() == []
    assert len(await _cases(session, security_desk.id)) == 1

    await set_rls_context(session, Unattributed())
    total = (
        await session.exec(
            text(
                "SELECT count FROM security_signal_windows WHERE rule = 'sign_in_spray'"
            )
        )
    ).scalar_one()
    assert total == 80


async def test_keys_past_the_cap_collapse_into_one(session):
    for n in range(MAX_KEYS_PER_RULE + 1):
        security_signals.observe(
            _failed_sign_in(f"10.{n // 65536}.{n // 256 % 256}.{n % 256}"), now=_AT
        )
    assert security_signals.pending() == MAX_KEYS_PER_RULE + 1
    buckets = security_signals._counts.rules["sign_in_spray"]
    assert (
        COLLAPSED_KEY,
        security_signals.window_start(_AT, BY_NAME["sign_in_spray"].window),
    ) in buckets


async def test_a_signal_writes_no_line_and_a_trip_writes_one(
    session, security_desk, capfd
):
    rule = BY_NAME["csrf_burst"]
    from app.core import audit_context

    emitted(capfd)
    _, token = audit_context.begin(request_id="t", source_ip="192.0.2.9")
    try:
        for _ in range(rule.threshold):
            security_signals.signal(Signal.csrf_rejected)
    finally:
        audit_context.end(token)
    assert emitted(capfd) == []

    (crossing,) = await security_signals.flush()
    assert crossing.rule is rule
    (crossed,) = emitted(capfd, AuditEventType.SECURITY_THRESHOLD_CROSSED)
    assert crossed["detail"]["rule"] == "csrf_burst"
    # The audit line is the record: it names what was counted.
    assert crossed["detail"]["key"] == "192.0.2.9"


async def test_every_audit_line_is_shown_to_the_rules(session):
    for _ in range(3):
        audit_service.emit(
            event_type=AuditEventType.AUTH_SIGN_IN_LOCKED,
            actor_user_id=None,
            target_user_id=42,
        )
    assert security_signals.pending() == 1
    buckets = security_signals._counts.rules["account_held"]
    (bucket,) = buckets.values()
    assert bucket.count == 3 and bucket.subject_user == 42


async def test_old_windows_are_forgotten(session):
    security_signals.observe(_failed_sign_in("198.51.100.6"), now=_AT)
    await security_signals.flush()
    await set_rls_context(session, Unattributed())
    from app.db import cohorts

    async with cohorts.system_session(None) as system:
        gone = await security_signals.forget_old(
            system, now=datetime(2026, 10, 20, tzinfo=timezone.utc)
        )
        await system.commit()
    assert gone >= 1

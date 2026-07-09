"""Logic tests for the session lifecycle (create / rotate / revoke).

Exercises the real ``auth_sessions`` table on the setup (privileged) session —
the role-security wall (request path can't touch the table) is proven separately
in ``app.db.auth_sessions_rls_test``. These focus on the rotation + theft-
detection behaviour the refresh endpoint will depend on.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.platform.auth_session import AuthSession
from app.services.auth import sessions as session_service
from app.services.auth.sessions import RefreshOutcome
from app.testing import create_user

pytestmark = [pytest.mark.integration, pytest.mark.database]


def _at(*, days: int = 0, minutes: int = 0) -> datetime:
    """A fixed instant offset from a stable base — keeps TTL math deterministic
    without ``datetime.now`` (and without the frozen-time helpers)."""
    base = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(days=days, minutes=minutes)


async def _rotate_ok(session, raw, when, **kwargs):
    """Rotate, assert it succeeded, and return the resulting IssuedSession."""
    result = await session_service.rotate_session(
        session, raw_refresh_token=raw, now=when, **kwargs
    )
    assert result.ok, f"expected ROTATED, got {result.outcome}"
    return result.issued


async def test_create_session_persists_hash_and_returns_raw(session):
    user = await create_user(session)
    issued = await session_service.create_session(
        session,
        user_id=user.id,
        amr=["pwd"],
        satisfied_providers=[7],
        user_agent="pytest",
        ip="203.0.113.9",
        now=_at(),
    )

    # The raw token is returned once; only its SHA-256 is stored.
    assert issued.refresh_token
    stored = await session.get(AuthSession, issued.session.id)
    assert stored is not None
    assert (
        stored.refresh_token_hash
        == hashlib.sha256(issued.refresh_token.encode()).digest()
    )
    assert stored.amr == ["pwd"]
    assert stored.satisfied_providers == [7]
    assert stored.revoked_at is None
    assert stored.parent_id is None
    assert stored.expires_at == _at(days=30)
    assert str(stored.ip) == "203.0.113.9"


async def test_rotate_spends_parent_and_carries_context(session):
    user = await create_user(session)
    first = await session_service.create_session(
        session,
        user_id=user.id,
        amr=["oidc:acme"],
        satisfied_providers=[3],
        device_name="Pixel",
        now=_at(),
    )

    second = await _rotate_ok(session, first.refresh_token, _at(minutes=5))

    assert second.refresh_token != first.refresh_token
    assert second.session.id != first.session.id
    assert second.session.parent_id == first.session.id
    # amr / providers / device carry forward when not overridden.
    assert second.session.amr == ["oidc:acme"]
    assert second.session.satisfied_providers == [3]
    assert second.session.device_name == "Pixel"
    # Sliding window: the child expires 30d from the rotation, not from creation.
    assert second.session.expires_at == _at(days=30, minutes=5)

    await session.refresh(first.session)
    assert first.session.revoked_at == _at(minutes=5)
    assert first.session.last_used_at == _at(minutes=5)


async def test_rotate_can_widen_amr_and_providers(session):
    """A step-up rotation replaces the satisfied set instead of carrying it."""
    user = await create_user(session)
    first = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_at()
    )

    second = await _rotate_ok(
        session,
        first.refresh_token,
        _at(minutes=1),
        amr=["pwd", "otp"],
        satisfied_providers=[9],
    )

    assert second.session.amr == ["pwd", "otp"]
    assert second.session.satisfied_providers == [9]


async def test_rotate_unknown_token_returns_unknown(session):
    result = await session_service.rotate_session(
        session, raw_refresh_token="never-issued", now=_at()
    )
    assert result.outcome is RefreshOutcome.UNKNOWN
    assert result.issued is None


async def test_rotate_expired_token_returns_expired(session):
    user = await create_user(session)
    issued = await session_service.create_session(
        session,
        user_id=user.id,
        amr=["pwd"],
        satisfied_providers=[],
        refresh_ttl=timedelta(minutes=10),
        now=_at(),
    )

    result = await session_service.rotate_session(
        session, raw_refresh_token=issued.refresh_token, now=_at(minutes=11)
    )
    assert result.outcome is RefreshOutcome.EXPIRED


async def test_reuse_of_spent_token_revokes_whole_chain(session):
    """Theft detection: replaying an already-rotated token kills the entire
    chain — including the live tail the legitimate client is still using."""
    user = await create_user(session)
    r1 = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_at()
    )
    r2 = await _rotate_ok(session, r1.refresh_token, _at(minutes=1))
    r3 = await _rotate_ok(session, r2.refresh_token, _at(minutes=2))

    # Attacker replays r1's (long-spent) token.
    result = await session_service.rotate_session(
        session, raw_refresh_token=r1.refresh_token, now=_at(minutes=3)
    )
    assert result.outcome is RefreshOutcome.REUSED
    assert result.issued is None

    # The live tail (r3) is now revoked — the attacker gained nothing and the
    # real user is forced to re-authenticate.
    for issued in (r1, r2, r3):
        await session.refresh(issued.session)
        assert issued.session.revoked_at is not None


async def test_revoke_session_is_idempotent(session):
    user = await create_user(session)
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_at()
    )

    revoked = await session_service.revoke_session(
        session, session_id=issued.session.id, now=_at(minutes=1)
    )
    assert revoked == 1

    # Already revoked ⇒ no-op.
    again = await session_service.revoke_session(
        session, session_id=issued.session.id, now=_at(minutes=2)
    )
    assert again == 0

    await session.refresh(issued.session)
    assert issued.session.revoked_at == _at(minutes=1)


async def test_revoked_session_cannot_rotate(session):
    user = await create_user(session)
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_at()
    )
    await session_service.revoke_session(
        session, session_id=issued.session.id, now=_at(minutes=1)
    )

    result = await session_service.rotate_session(
        session, raw_refresh_token=issued.refresh_token, now=_at(minutes=2)
    )
    assert result.outcome is RefreshOutcome.REUSED


async def test_revoke_all_for_user_scoped_to_that_user(session):
    user = await create_user(session)
    other = await create_user(session)
    a = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_at()
    )
    b = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_at()
    )
    c = await session_service.create_session(
        session, user_id=other.id, amr=["pwd"], satisfied_providers=[], now=_at()
    )

    revoked = await session_service.revoke_all_for_user(
        session, user_id=user.id, now=_at(minutes=1)
    )
    assert revoked == 2

    for issued in (a, b):
        await session.refresh(issued.session)
        assert issued.session.revoked_at == _at(minutes=1)
    await session.refresh(c.session)
    assert c.session.revoked_at is None


async def test_revoke_chain_from_any_member_revokes_all(session):
    """Given a middle node, the whole chain (ancestors + descendants) is revoked."""
    user = await create_user(session)
    r1 = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[], now=_at()
    )
    r2 = await _rotate_ok(session, r1.refresh_token, _at(minutes=1))
    r3 = await _rotate_ok(session, r2.refresh_token, _at(minutes=2))
    # r2 is already revoked (it rotated); re-run from r2 to prove reachability
    # both up (r1) and down (r3). r1/r2 stay revoked, r3 gets revoked.
    revoked = await session_service.revoke_chain(
        session, session_id=r2.session.id, now=_at(minutes=3)
    )
    assert revoked == 1  # only r3 was still live

    for issued in (r1, r2, r3):
        await session.refresh(issued.session)
        assert issued.session.revoked_at is not None


async def test_revoke_chain_missing_id_is_noop(session):
    revoked = await session_service.revoke_chain(
        session, session_id=uuid.uuid4(), now=_at()
    )
    assert revoked == 0

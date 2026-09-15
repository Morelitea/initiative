"""Server-side session lifecycle for the new login model (auth rewrite, Phase 0).

This is the substrate that makes the stateless access token revocable
(history/auth-detailed-design.md §3.2–§3.3). One ``auth_sessions`` row = one
login; each ``/auth/refresh`` **rotates** it — mints a fresh row pointing at the
one it replaces (``parent_id`` chain) and single-use-revokes the old one. Reuse
of an already-spent refresh token is treated as **theft** and kills the whole
chain, including its still-live tail. One client's own windows renewing
together are told apart from that by :data:`REFRESH_REUSE_GRACE_SECONDS`.

**Runs on the system engine (``app_admin``).** Session validation is a pre-auth
lookup *by refresh-token hash* — the user is unknown until it resolves — so it
structurally cannot run under own-row RLS. The request path holds no grant on
``auth_sessions`` at all (migration 20260706_0132); these functions take the
admin session, like ``services.platform.access_grants``.

Nothing calls this yet — the ``/auth/refresh`` endpoint + dual-verify wiring land
in the next slice. This PR is the tested logic layer only (additive-first).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.platform.auth_session import AuthSession

logger = logging.getLogger(__name__)

__all__ = [
    "IssuedSession",
    "RefreshOutcome",
    "RotationResult",
    "create_session",
    "get_live_session_by_refresh_token",
    "rotate_session",
    "revoke_session",
    "revoke_chain",
    "revoke_all_for_user",
    "delete_all_for_user",
    "purge_dead_sessions",
    "process_dead_session_purge",
    "SESSION_PURGE_POLL_SECONDS",
    "SESSION_RETENTION_DAYS",
    "REFRESH_REUSE_GRACE_SECONDS",
]

# 256 bits of entropy — infeasible to guess, so the hash (not a slow KDF) is the
# only thing that needs storing.
_REFRESH_TOKEN_BYTES = 32

#: How long a session row outlives its own usefulness. A row carries a user
#: agent, an IP and a device label for the "your active sessions" screen; once
#: the session can no longer be used, that is all it carries, so it is kept for
#: a window and then removed.
SESSION_RETENTION_DAYS = 30

#: ``auth_sessions`` is app_admin-only, so the sweep runs on AdminSessionLocal
#: with no guild routing — the same shape as the expired-token purge.
SESSION_PURGE_POLL_SECONDS = 3600

#: How close together two presentations of one refresh token are read as a
#: single client renewing from more than one window.
#:
#: A browser holds one refresh cookie for every window open on the app, and
#: each renews on its own schedule, so two waking together present the same
#: token milliseconds apart. Inside this window the second is continued from
#: the chain's live tip, which leaves both windows holding a current
#: credential. Kept short: it is sized for that, and nothing else.
REFRESH_REUSE_GRACE_SECONDS = 10

#: How many times a racing rotation re-reads the chain's tip before giving up.
#: Each attempt loses only to another rotation landing in between, which is
#: itself progress — a third window, not an unbounded retry.
_TIP_ROTATE_ATTEMPTS = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_refresh_token() -> str:
    """A fresh opaque refresh token (URL-safe, never persisted in the clear)."""
    return secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)


def _hash_refresh_token(raw: str) -> bytes:
    """SHA-256 of the raw token — *deterministic* so a presented token maps to
    exactly one session by an indexed lookup. The token is 256-bit random, so a
    plain fast hash is safe here (a salted/slow KDF would defeat the O(1) lookup
    that ``uq_auth_sessions_refresh_token_hash`` exists to serve). The raw token
    is returned to the client once and never stored."""
    return hashlib.sha256(raw.encode("utf-8")).digest()


@dataclass(frozen=True)
class IssuedSession:
    """A newly created/rotated session plus its raw refresh token.

    ``refresh_token`` is the *only* time the raw token exists — hand it to the
    client (cookie / secure storage) and drop it; only its hash is persisted.
    """

    session: AuthSession
    refresh_token: str


class RefreshOutcome(str, Enum):
    """The result of a rotation attempt. The string values double as machine-
    readable codes the endpoint maps to an HTTP status + localized message."""

    ROTATED = "rotated"
    UNKNOWN = "unknown_refresh_token"
    EXPIRED = "refresh_token_expired"
    REUSED = "refresh_token_reused"


@dataclass(frozen=True)
class RotationResult:
    """Outcome of :func:`rotate_session`.

    ``rotate_session`` **returns** this rather than raising, deliberately: on
    ``REUSED`` it has written a theft-revocation to the caller's session, and an
    exception there would let a conventional ``try/commit … except/rollback``
    handler silently discard that security response. Returning keeps the outcome
    on the caller's normal control flow — a single commit persists whichever
    write happened (the rotation on ``ROTATED``, the chain kill on ``REUSED``).
    """

    outcome: RefreshOutcome
    issued: IssuedSession | None = None  # present iff ``outcome is ROTATED``
    #: Whose session the token belonged to. Set whenever the token resolved to
    #: a row, so a ``REUSED`` rejection — where there is no ``issued`` — can
    #: still say whose chain was killed. ``None`` for a token that matched
    #: nothing at all.
    user_id: int | None = None

    @property
    def ok(self) -> bool:
        return self.outcome is RefreshOutcome.ROTATED


@dataclass(frozen=True)
class _Carried:
    """What a rotation may override on the successor, each ``None`` meaning
    "keep what the spent session had". Only a step-up passes any of them."""

    amr: list[str] | None = None
    satisfied_providers: list[int] | None = None
    provider_auth: dict[str, Any] | None = None
    user_agent: str | None = None
    ip: str | None = None
    device_name: str | None = None


# Revoke every session in a token's rotation chain, in both directions, given any
# member id. On reuse the live continuation is a *descendant* of the replayed
# node (ancestors are already revoked), but we walk both ways for defense in
# depth. The graph is a strict in-tree — ``parent_id`` always points at an older,
# pre-existing row, and ``ck_auth_sessions_parent_not_self`` blocks the only
# reachable self-loop — so the recursion terminates.
_REVOKE_CHAIN_SQL = text(
    """
    WITH RECURSIVE
    ancestors AS (
        SELECT id, parent_id FROM auth_sessions WHERE id = :sid
        UNION
        SELECT s.id, s.parent_id
        FROM auth_sessions s JOIN ancestors a ON s.id = a.parent_id
    ),
    descendants AS (
        SELECT id, parent_id FROM auth_sessions WHERE id = :sid
        UNION
        SELECT s.id, s.parent_id
        FROM auth_sessions s JOIN descendants d ON s.parent_id = d.id
    )
    UPDATE auth_sessions SET revoked_at = :now
    WHERE revoked_at IS NULL
      AND id IN (SELECT id FROM ancestors UNION SELECT id FROM descendants)
    """
)

# The one session in a chain that can still be spent, given any member id. A
# chain is single-use all the way down, so at most one row satisfies this: every
# rotation revokes the row it spent as it mints the successor. Walks descendants
# only — ancestors are spent by definition, being what the walk started from.
_LIVE_TIP_SQL = text(
    """
    WITH RECURSIVE descendants AS (
        SELECT id, parent_id, revoked_at, expires_at
        FROM auth_sessions WHERE id = :sid
        UNION
        SELECT s.id, s.parent_id, s.revoked_at, s.expires_at
        FROM auth_sessions s JOIN descendants d ON s.parent_id = d.id
    )
    SELECT id FROM descendants
    WHERE revoked_at IS NULL AND expires_at > :now
    LIMIT 1
    """
)


async def create_session(
    session: AsyncSession,
    *,
    user_id: int,
    amr: list[str],
    satisfied_providers: list[int],
    provider_auth: dict[str, Any] | None = None,
    user_agent: str | None = None,
    ip: str | None = None,
    device_name: str | None = None,
    refresh_ttl: timedelta | None = None,
    now: datetime | None = None,
) -> IssuedSession:
    """Open a new session for ``user_id`` and mint its first refresh token.

    ``amr`` / ``satisfied_providers`` record which factors/providers this login
    satisfied — they are mirrored into the access token so the per-guild
    auth-policy gate and step-up read them locally. ``provider_auth`` carries
    each satisfied provider's own account of its authentication event (see
    ``services.auth.assurance``).
    """
    issued = now or _now()
    ttl = refresh_ttl or timedelta(days=settings.AUTH_REFRESH_TTL_DAYS)
    raw = _generate_refresh_token()
    row = AuthSession(
        user_id=user_id,
        refresh_token_hash=_hash_refresh_token(raw),
        amr=list(amr),
        satisfied_providers=list(satisfied_providers),
        provider_auth=dict(provider_auth or {}),
        created_at=issued,
        expires_at=issued + ttl,
        user_agent=user_agent,
        ip=ip,
        device_name=device_name,
    )
    session.add(row)
    await session.flush()
    return IssuedSession(session=row, refresh_token=raw)


async def rotate_session(
    session: AsyncSession,
    *,
    raw_refresh_token: str,
    amr: list[str] | None = None,
    satisfied_providers: list[int] | None = None,
    provider_auth: dict[str, Any] | None = None,
    user_agent: str | None = None,
    ip: str | None = None,
    device_name: str | None = None,
    refresh_ttl: timedelta | None = None,
    now: datetime | None = None,
) -> RotationResult:
    """Single-use rotate: spend the presented refresh token, mint its successor.

    Carries ``amr``/``satisfied_providers``/``provider_auth`` (and device
    metadata) forward from the parent unless overridden — a step-up rotation
    passes the widened set.

    **Returns** a :class:`RotationResult` (never raises for a bad token) —
    ``ROTATED`` carries the new :class:`IssuedSession`; ``UNKNOWN``/``EXPIRED``/
    ``REUSED`` are rejections. On ``REUSED`` the whole chain has been revoked on
    ``session`` (theft response). A token presented again within
    :data:`REFRESH_REUSE_GRACE_SECONDS` of being spent is one client renewing
    from two windows, and ``ROTATED``s from the chain's live tip instead.
    Returning rather than raising is the point: the
    caller commits on its normal path, so one commit durably persists whichever
    write occurred and a rollback-on-exception handler can't drop the chain kill.

    **Caller contract:** commit ``session`` before acting on the outcome —
    ``rotate → commit → branch`` — so both the rotation and the theft-revocation
    are persisted regardless of how the request ends.
    """
    issued = now or _now()
    ttl = refresh_ttl or timedelta(days=settings.AUTH_REFRESH_TTL_DAYS)
    presented_hash = _hash_refresh_token(raw_refresh_token)
    carried = _Carried(
        amr=amr,
        satisfied_providers=satisfied_providers,
        provider_auth=provider_auth,
        user_agent=user_agent,
        ip=ip,
        device_name=device_name,
    )

    row = (
        await session.exec(
            select(AuthSession).where(AuthSession.refresh_token_hash == presented_hash)
        )
    ).one_or_none()
    if row is None:
        return RotationResult(RefreshOutcome.UNKNOWN)

    # Already spent (rotated or explicitly revoked). Just-spent is one client
    # renewing from two windows; anything older is a replay of a dead token.
    if row.revoked_at is not None:
        if issued - row.revoked_at <= timedelta(seconds=REFRESH_REUSE_GRACE_SECONDS):
            raced = await _rotate_live_tip(
                session, root_id=row.id, issued=issued, ttl=ttl, carried=carried
            )
            if raced is not None:
                return RotationResult(RefreshOutcome.ROTATED, issued=raced)
        await revoke_chain(session, session_id=row.id, now=issued)
        return RotationResult(RefreshOutcome.REUSED, user_id=row.user_id)

    if row.expires_at <= issued:
        return RotationResult(RefreshOutcome.EXPIRED, user_id=row.user_id)

    minted = await _spend_and_mint(
        session, row, issued=issued, ttl=ttl, carried=carried
    )
    if minted is None:
        # Lost the single-use claim to a concurrent rotation. The winner held
        # the row lock until it committed, so its successor is readable now.
        raced = await _rotate_live_tip(
            session, root_id=row.id, issued=issued, ttl=ttl, carried=carried
        )
        if raced is not None:
            return RotationResult(RefreshOutcome.ROTATED, issued=raced)
        await revoke_chain(session, session_id=row.id, now=issued)
        return RotationResult(RefreshOutcome.REUSED, user_id=row.user_id)
    return RotationResult(RefreshOutcome.ROTATED, issued=minted)


async def _spend_and_mint(
    session: AsyncSession,
    row: AuthSession,
    *,
    issued: datetime,
    ttl: timedelta,
    carried: _Carried,
) -> IssuedSession | None:
    """Spend ``row`` and mint its successor, or ``None`` if it was already spent.

    The claim is atomic: only one caller can flip ``revoked_at`` NULL→now, so
    two rotations of the same session can't both mint a successor.
    """
    claimed = (
        await session.exec(
            text(
                "UPDATE auth_sessions SET revoked_at = :now, last_used_at = :now "
                "WHERE id = :id AND revoked_at IS NULL RETURNING id"
            ),
            params={"now": issued, "id": row.id},
        )
    ).first()
    if claimed is None:
        return None
    # Keep the in-session parent honest (the raw UPDATE bypassed the ORM).
    await session.refresh(row)

    raw = _generate_refresh_token()
    child = AuthSession(
        user_id=row.user_id,
        refresh_token_hash=_hash_refresh_token(raw),
        amr=list(carried.amr) if carried.amr is not None else list(row.amr),
        satisfied_providers=(
            list(carried.satisfied_providers)
            if carried.satisfied_providers is not None
            else list(row.satisfied_providers)
        ),
        provider_auth=(
            dict(carried.provider_auth)
            if carried.provider_auth is not None
            else dict(row.provider_auth)
        ),
        parent_id=row.id,
        created_at=issued,
        expires_at=issued + ttl,
        user_agent=(
            carried.user_agent if carried.user_agent is not None else row.user_agent
        ),
        ip=carried.ip if carried.ip is not None else row.ip,
        device_name=(
            carried.device_name if carried.device_name is not None else row.device_name
        ),
    )
    session.add(child)
    await session.flush()
    return IssuedSession(session=child, refresh_token=raw)


async def _rotate_live_tip(
    session: AsyncSession,
    *,
    root_id: uuid.UUID,
    issued: datetime,
    ttl: timedelta,
    carried: _Carried,
) -> IssuedSession | None:
    """Rotate the chain's live tip on behalf of a caller whose own token was
    spent moments ago, or ``None`` when the chain has no spendable session.

    The session continues from its newest point, which is where the window that
    renewed first left it.
    """
    for _ in range(_TIP_ROTATE_ATTEMPTS):
        tip_id = (
            await session.exec(_LIVE_TIP_SQL, params={"sid": root_id, "now": issued})
        ).first()
        if tip_id is None:
            return None
        tip = await session.get(AuthSession, tip_id[0])
        if tip is None:
            return None
        minted = await _spend_and_mint(
            session, tip, issued=issued, ttl=ttl, carried=carried
        )
        if minted is not None:
            return minted
    return None


async def get_live_session_by_refresh_token(
    session: AsyncSession,
    raw_refresh_token: str,
    *,
    now: datetime | None = None,
) -> AuthSession | None:
    """The live (unrevoked, unexpired) session a presented refresh token
    belongs to, or ``None`` — a read-only lookup with none of ``rotate``'s
    side effects. Used by a completing provider login to carry the current
    session's satisfied set forward into the replacement session."""
    row = (
        await session.exec(
            select(AuthSession).where(
                AuthSession.refresh_token_hash == _hash_refresh_token(raw_refresh_token)
            )
        )
    ).one_or_none()
    current = now or _now()
    if row is None or row.revoked_at is not None or row.expires_at <= current:
        return None
    return row


async def revoke_session(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    now: datetime | None = None,
) -> int:
    """Revoke one session (logout, unlink, disable MFA). Its access token still
    expires within the short TTL. Returns the number of rows revoked (0 if it was
    already revoked/absent)."""
    result = await session.exec(
        text(
            "UPDATE auth_sessions SET revoked_at = :now "
            "WHERE id = :id AND revoked_at IS NULL"
        ),
        params={"now": now or _now(), "id": session_id},
    )
    return result.rowcount


async def revoke_chain(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    now: datetime | None = None,
) -> int:
    """Revoke every still-live session in ``session_id``'s rotation chain (theft
    response, or unlink-provider cleanup). Returns the number of rows revoked."""
    result = await session.exec(
        _REVOKE_CHAIN_SQL, params={"sid": session_id, "now": now or _now()}
    )
    return result.rowcount


async def revoke_all_for_user(
    session: AsyncSession,
    *,
    user_id: int,
    now: datetime | None = None,
) -> int:
    """Revoke all of a user's live sessions — the refresh-side of "sign out
    everywhere" (paired with the ``users.token_version`` bump that invalidates
    outstanding access tokens). Returns the number of rows revoked."""
    result = await session.exec(
        text(
            "UPDATE auth_sessions SET revoked_at = :now "
            "WHERE user_id = :uid AND revoked_at IS NULL"
        ),
        params={"now": now or _now(), "uid": user_id},
    )
    return result.rowcount


async def delete_all_for_user(session: AsyncSession, *, user_id: int) -> int:
    """Remove every session row for a user. Returns the number removed.

    The erasure counterpart to :func:`revoke_all_for_user`. A password change
    revokes, because the rows are still the record of where somebody was
    signed in. Erasing the account removes them, because by then the row is
    only a user agent, an IP and a device label belonging to a person who
    asked to be forgotten. A hard delete gets this from the ``users`` foreign
    key; an anonymize keeps the row, so it comes through here.

    Stages only — the caller commits, so this lands with the rest of the
    erasure or not at all.
    """
    result = await session.exec(
        text("DELETE FROM auth_sessions WHERE user_id = :uid"),
        params={"uid": user_id},
    )
    return result.rowcount


async def purge_dead_sessions(
    session: AsyncSession,
    *,
    retention_days: int = SESSION_RETENTION_DAYS,
    now: datetime | None = None,
) -> int:
    """Remove sessions that can no longer be used and are past the retention
    window. Returns the number removed.

    A row qualifies once it is expired, or was revoked, longer ago than
    ``retention_days``. A live session matches neither. ``parent_id`` is a
    plain uuid rather than a self-reference, so removing one end of a rotation
    chain leaves the rest intact.
    """
    horizon = (now or _now()) - timedelta(days=retention_days)
    result = await session.exec(
        text(
            "DELETE FROM auth_sessions "
            "WHERE expires_at < :horizon "
            "   OR (revoked_at IS NOT NULL AND revoked_at < :horizon)"
        ),
        params={"horizon": horizon},
    )
    await session.commit()
    return result.rowcount


async def process_dead_session_purge() -> None:
    """Hourly background sweep over ``auth_sessions`` (see
    :data:`SESSION_RETENTION_DAYS`)."""
    from app.db.session import AdminSessionLocal

    async with AdminSessionLocal() as session:
        removed = await purge_dead_sessions(session)
        if removed:
            logger.info("session purge removed %d dead session row(s)", removed)

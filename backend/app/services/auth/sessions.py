"""Server-side session lifecycle for the new login model (auth rewrite, Phase 0).

This is the substrate that makes the stateless access token revocable
(history/auth-detailed-design.md §3.2–§3.3). One ``auth_sessions`` row = one
login; each ``/auth/refresh`` **rotates** it — mints a fresh row pointing at the
one it replaces (``parent_id`` chain) and single-use-revokes the old one. Reuse
of an already-spent refresh token is treated as **theft** and kills the whole
chain, including its still-live tail.

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
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.platform.auth_session import AuthSession

__all__ = [
    "IssuedSession",
    "RefreshError",
    "create_session",
    "rotate_session",
    "revoke_session",
    "revoke_chain",
    "revoke_all_for_user",
]

# 256 bits of entropy — infeasible to guess, so the hash (not a slow KDF) is the
# only thing that needs storing.
_REFRESH_TOKEN_BYTES = 32


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


class RefreshError(Exception):
    """A presented refresh token could not be rotated. ``code`` is machine-
    readable so the endpoint maps it to an HTTP status + localized message."""

    UNKNOWN = "unknown_refresh_token"
    EXPIRED = "refresh_token_expired"
    REUSED = "refresh_token_reused"

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


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


async def create_session(
    session: AsyncSession,
    *,
    user_id: int,
    amr: list[str],
    satisfied_providers: list[int],
    user_agent: str | None = None,
    ip: str | None = None,
    device_name: str | None = None,
    refresh_ttl: timedelta | None = None,
    now: datetime | None = None,
) -> IssuedSession:
    """Open a new session for ``user_id`` and mint its first refresh token.

    ``amr`` / ``satisfied_providers`` record which factors/providers this login
    satisfied — they are mirrored into the access token so the per-guild
    auth-policy gate and step-up read them locally.
    """
    issued = now or _now()
    ttl = refresh_ttl or timedelta(days=settings.AUTH_REFRESH_TTL_DAYS)
    raw = _generate_refresh_token()
    row = AuthSession(
        user_id=user_id,
        refresh_token_hash=_hash_refresh_token(raw),
        amr=list(amr),
        satisfied_providers=list(satisfied_providers),
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
    user_agent: str | None = None,
    ip: str | None = None,
    device_name: str | None = None,
    refresh_ttl: timedelta | None = None,
    now: datetime | None = None,
) -> IssuedSession:
    """Single-use rotate: spend the presented refresh token, mint its successor.

    Carries ``amr``/``satisfied_providers`` (and device metadata) forward from the
    parent unless overridden — a step-up rotation passes the widened set.

    Raises :class:`RefreshError`:
    - ``UNKNOWN`` — no session matches the token.
    - ``EXPIRED`` — the refresh window has lapsed (benign; log back in).
    - ``REUSED`` — the token was already spent ⇒ **theft**. The whole chain has
      been revoked on ``session``; the caller **must commit that** (do not roll
      back) before surfacing the 401, or the theft response is lost.
    """
    issued = now or _now()
    ttl = refresh_ttl or timedelta(days=settings.AUTH_REFRESH_TTL_DAYS)
    presented_hash = _hash_refresh_token(raw_refresh_token)

    row = (
        await session.exec(
            select(AuthSession).where(AuthSession.refresh_token_hash == presented_hash)
        )
    ).one_or_none()
    if row is None:
        raise RefreshError(RefreshError.UNKNOWN)

    # Already spent (rotated or explicitly revoked) ⇒ replay of a dead token.
    if row.revoked_at is not None:
        await revoke_chain(session, session_id=row.id, now=issued)
        raise RefreshError(RefreshError.REUSED)

    if row.expires_at <= issued:
        raise RefreshError(RefreshError.EXPIRED)

    # Atomic single-use claim: only one caller can flip revoked_at NULL→now, so
    # two concurrent refreshes with the same token can't both mint a child.
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
        # Lost the race to a concurrent rotation — same danger as a replay.
        await revoke_chain(session, session_id=row.id, now=issued)
        raise RefreshError(RefreshError.REUSED)
    # Keep the in-session parent honest (the raw UPDATE bypassed the ORM).
    await session.refresh(row)

    raw = _generate_refresh_token()
    child = AuthSession(
        user_id=row.user_id,
        refresh_token_hash=_hash_refresh_token(raw),
        amr=list(amr) if amr is not None else list(row.amr),
        satisfied_providers=(
            list(satisfied_providers)
            if satisfied_providers is not None
            else list(row.satisfied_providers)
        ),
        parent_id=row.id,
        created_at=issued,
        expires_at=issued + ttl,
        user_agent=user_agent if user_agent is not None else row.user_agent,
        ip=ip if ip is not None else row.ip,
        device_name=device_name if device_name is not None else row.device_name,
    )
    session.add(child)
    await session.flush()
    return IssuedSession(session=child, refresh_token=raw)


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

"""Opening the session a sign-in earned, whatever proved it.

The password route was the only way in for long enough that this lived there.
It is now shared: a password, a password plus a second factor, and a passkey
all end the same way — a server-side session, an access token, a refresh
cookie, and one audit record saying which of them it was.

What each route keeps for itself is the proving. What they hand over is
``amr`` (what this sign-in actually proved) and ``audit_detail`` (what the
record should say), so the one place that writes a session does not have to
know how many ways there are to reach it.

:func:`replace_session` is the same idea for the changes that retire every
credential an account holds: the caller revokes, and this opens the session the
caller carries on with.

:func:`upgrade_session` is the same idea for a session that is already open:
the step-ups prove something more against it and hand over the ``amr`` that
adds, and the one place that rewrites a session does the rest. It is shared for
the same reason — two step-ups that each carried their own copy would be two
places for the carry-forward to diverge.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.platform_endpoints.session_cookies import (
    set_refresh_cookie,
    set_session_cookie,
)
from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.login_methods import LoginMethod
from app.core.messages import AuthMessages, SettingsMessages
from app.core.rate_limit import get_inet_client_ip
from app.core.security import REFRESH_COOKIE_NAME, mint_access_token
from app.models.platform.auth_session import AuthSession
from app.models.platform.user import User
from app.schemas.platform.token import Token
from app.services import audit as audit_service
from app.services.auth import sessions as session_service
from app.services.auth import sign_in_locks
from app.services.auth import subject as subject_service
from app.services.platform import auth_posture

logger = logging.getLogger(__name__)

#: Where a phone's sign-in comes back to. The app registers this scheme and
#: ``useDeepLinks`` routes it; the OIDC callback and the passkey relay both
#: hand the app a device token at this address.
MOBILE_CALLBACK_URI = "initiative://oidc/callback"


async def require_login_method(session: AsyncSession, method: LoginMethod) -> None:
    """Refuse a sign-in by a route this deployment does not permit.

    Server-side, so withdrawing a method closes the route rather than only
    hiding its form. Existing sessions are untouched — this gates opening a new
    one, not holding one already open.
    """
    if not await auth_posture.login_method_allowed(session, method):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=SettingsMessages.LOGIN_METHOD_NOT_PERMITTED,
        )


def current_session_row(request: Request) -> uuid.UUID | None:
    """The server-side session this request is on, or ``None``.

    Named by the request's own access token: every client carries one of
    those, and a credential that is not a session — a device token, an API
    key — names none.
    """
    raw = getattr(request.state, "session_id", None)
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


def require_session_row(request: Request) -> uuid.UUID:
    """The server-side session this request is on, or 403.

    The step-ups add to a session, so this is what they have to be holding
    before a ceremony is worth starting. Signing out has something to do
    either way, and reads :func:`current_session_row` instead.
    """
    session_id = current_session_row(request)
    if session_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMessages.SESSION_REQUIRED,
        )
    return session_id


# Walk a session back up its rotation chain and read the oldest row there.
# ``parent_id`` always points at an older, pre-existing row and
# ``ck_auth_sessions_parent_not_self`` blocks the only reachable self-loop, so
# the graph is a strict in-tree and the recursion terminates.
_CHAIN_ROOT_SQL = text(
    """
    WITH RECURSIVE ancestors AS (
        SELECT id, parent_id, created_at FROM auth_sessions WHERE id = :sid
        UNION
        SELECT s.id, s.parent_id, s.created_at
        FROM auth_sessions s JOIN ancestors a ON s.id = a.parent_id
    )
    SELECT created_at FROM ancestors ORDER BY created_at LIMIT 1
    """
)


async def chain_started_at(
    system_session: AsyncSession, *, session_id: uuid.UUID
) -> datetime | None:
    """When the sign-in this session descends from was opened.

    Every refresh mints a new row pointing at the one it replaced, so a session
    that has been renewed for a week is still the same chain; its root is the
    sign-in. A step-up and a replacement each start a chain of their own, so
    both read as the moment they happened.

    ``None`` where there is no such row.
    """
    # One round trip on the session's own connection: a chain gains a row per
    # refresh, so walking it a row at a time would be as many.
    connection = await system_session.connection()
    result = await connection.execute(_CHAIN_ROOT_SQL, {"sid": session_id})
    return result.scalar_one_or_none()


async def record_sign_in_failure(
    system_session: AsyncSession,
    user: User | None,
    *,
    method: str,
    reason: str,
) -> None:
    """Write down a refused sign-in and commit it.

    The account is the **target**, when one resolved, and there is no actor: the
    request that made the attempt is unauthenticated. An unknown address still
    records the refusal but retains no submitted identity.

    ``method`` is how the sign-in was being attempted — a password, a passkey —
    so the board can tell one run of refusals from another.


    Its own commit because the request is about to raise.
    """
    target_user_id = user.id if user is not None else None
    await audit_service.record(
        system_session,
        event_type=AuditEventType.AUTH_SIGN_IN_FAILED,
        actor_user_id=None,
        target_user_id=target_user_id,
        target_type="user" if target_user_id is not None else None,
        target_id=target_user_id,
        detail={"method": method, "reason": reason},
    )
    await system_session.commit()


def access_ttl_for(row: AuthSession, *, now: datetime) -> timedelta | None:
    """How long an access token for this session may live.

    ``None`` leaves the deployment's own ``AUTH_ACCESS_TTL_MINUTES`` in place,
    which is every ordinary session. Where the refresh row ends sooner than
    that — a community held to the compliance standard narrows it — the token
    ends with it: a token outliving the session it names would be the one gap
    in a control the row's own expiry otherwise keeps.

    Read off the row rather than resolved again, so the two clocks cannot
    disagree and no path pays a second query for the answer.
    """
    standard = timedelta(minutes=settings.AUTH_ACCESS_TTL_MINUTES)
    remaining = row.expires_at - now
    return remaining if remaining < standard else None


async def refuse_if_locked(system_session: AsyncSession, user_id: int) -> None:
    """Refuse a password or code for an account whose password and codes are
    turned off right now.

    Asked before the answer is checked, so a right one is refused too.
    """
    if await sign_in_locks.is_locked(system_session, user_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=AuthMessages.SIGN_IN_LOCKED,
        )


async def count_wrong_answer(system_session: AsyncSession, user_id: int) -> None:
    """Count a wrong password or code against the account, commit it, and tell
    the holder if that placed a lock they have not heard about."""
    failure = await sign_in_locks.record_failure(system_session, user_id)
    await system_session.commit()
    if not failure.notify:
        return
    from app.services import email as email_service

    user = await system_session.get(User, user_id)
    if user is not None:
        await email_service.announce_sign_in_locked(
            system_session,
            user,
            held=failure.outcome is sign_in_locks.Outcome.held,
        )


async def open_session(
    request: Request,
    response: Response,
    system_session: AsyncSession,
    *,
    user_id: int,
    token_version: int,
    amr: list[str],
    audit_detail: dict[str, Any],
    return_refresh_token: bool = False,
) -> Token:
    """Open the session a sign-in earned, and hand back its token.

    The login model end-to-end (history/auth-detailed-design.md §3): the
    server-side session is load-bearing — the access token carries sid/amr/sat
    and lives AUTH_ACCESS_TTL_MINUTES; the rotating refresh cookie carries the
    session (the SPA renews silently). Session writes run on the system engine
    (auth_sessions is app_admin-only).

    A sign-in *is* the session. If it cannot be written the request says so
    rather than handing back a lesser credential — ``auth_sessions`` shares a
    database with everything the next request would need anyway.

    ``amr`` is what this sign-in proved: a password alone records ``pwd``, a
    password plus a factor records what the factor was, and a passkey records
    which kind of key answered alongside ``mfa``.

    Anything the caller staged in ``system_session`` — a device token, a
    credential's counter — commits with the session, or goes with it.
    """
    try:
        issued = await session_service.create_session(
            system_session,
            user_id=user_id,
            amr=amr,
            satisfied_providers=[],
            user_agent=request.headers.get("user-agent"),
            ip=get_inet_client_ip(request),
        )
        await audit_service.record(
            system_session,
            event_type=AuditEventType.AUTH_SIGNED_IN,
            actor_user_id=user_id,
            detail=audit_detail,
        )
        # The name the token will carry, minted in the same transaction as the
        # session it belongs to.
        subject = await subject_service.subject_for_user(
            system_session, user_id=user_id
        )
        # Signed in, so the wrong answers before this no longer add up to a lock.
        await sign_in_locks.record_success(system_session, user_id)
        await system_session.commit()
    except Exception as exc:
        await system_session.rollback()
        logger.exception("Could not open a session for user %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AuthMessages.SESSION_STORE_UNAVAILABLE,
        ) from exc

    access_token, access_max_age = mint_access_token(
        subject=subject,
        token_version=token_version,
        session_id=issued.session.id,
        amr=issued.session.amr,
        satisfied_providers=issued.session.satisfied_providers,
        provider_auth=issued.session.provider_auth,
        expires_in=access_ttl_for(issued.session, now=issued.session.created_at),
    )
    set_session_cookie(response, access_token, max_age=access_max_age)
    set_refresh_cookie(response, issued.refresh_token)
    return Token(
        access_token=access_token,
        refresh_token=issued.refresh_token if return_refresh_token else None,
    )


async def replace_session(
    request: Request,
    response: Response,
    system_session: AsyncSession,
    *,
    user: User,
    amr: list[str],
    satisfied_providers: list[int],
    provider_auth: dict[str, Any] | None = None,
) -> Token:
    """Open a session in place of the one this request is on, and hand the
    caller back onto it.

    For the changes that retire every credential an account holds — a password
    set, a password given up — which would otherwise take the caller's own
    session with them. What the account held is revoked by the caller and
    staged on ``system_session``; the session opened here joins that staging, so
    one commit carries both and a failure leaves the account holding what it
    had.

    Both cookies are re-issued: the access token names the new session, and the
    refresh cookie is the chain it rotates on. What carries into it is the
    caller's to decide — ``amr`` is what the replacement may claim was proved,
    and the satisfied providers and their own account of it come forward where
    the request has one to carry.

    A session is the only credential there is, so a store that cannot be
    written ends the request rather than answering with a lesser one.
    """
    # Read before the writes below: ``user`` may be staged on ``system_session``,
    # and a rollback leaves its columns to be fetched again.
    user_id = user.id
    token_version = user.token_version
    try:
        issued = await session_service.create_session(
            system_session,
            user_id=user_id,
            amr=amr,
            satisfied_providers=satisfied_providers,
            provider_auth=provider_auth,
            user_agent=request.headers.get("user-agent"),
            ip=get_inet_client_ip(request),
        )
        # The name the token will carry, minted in the same transaction as the
        # session it belongs to.
        subject = await subject_service.subject_for_user(
            system_session, user_id=user_id
        )
        await system_session.commit()
    except Exception as exc:
        await system_session.rollback()
        logger.exception("Could not open a session for user %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AuthMessages.SESSION_STORE_UNAVAILABLE,
        ) from exc

    access_token, access_max_age = mint_access_token(
        subject=subject,
        token_version=token_version,
        session_id=issued.session.id,
        amr=issued.session.amr,
        satisfied_providers=issued.session.satisfied_providers,
        provider_auth=issued.session.provider_auth,
    )
    set_session_cookie(response, access_token, max_age=access_max_age)
    set_refresh_cookie(response, issued.refresh_token)
    return Token(access_token=access_token)


async def upgrade_session(
    request: Request,
    response: Response,
    system_session: AsyncSession,
    *,
    user: User,
    add_amr: list[str],
) -> Token:
    """Add what was just proved to the session already signed in.

    A community that asks for something a session never presented refuses it,
    and signing out to sign back in would be a strange way to answer that. So
    the factor — a code, a passkey — is taken against the live session and this
    is what records it.

    The session is upgraded rather than replaced from nothing: its ``amr``, its
    satisfied providers and each provider's account of its own authentication
    carry forward, and the old row is retired. Satisfying one community's
    requirement never un-satisfies another's.

    The session upgraded is the one this request is *on*, named by its own
    access token: every client carries that, and only a browser also carries a
    refresh cookie. A credential that is not a session is refused — this
    endpoint upgrades one, and there is nothing else here to add to.
    """
    prior = await system_session.get(AuthSession, require_session_row(request))
    if prior is not None and (prior.user_id != user.id or prior.revoked_at is not None):
        prior = None
    if prior is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMessages.SESSION_REQUIRED,
        )

    amr = sorted(set(prior.amr) | set(add_amr))
    satisfied = sorted(set(prior.satisfied_providers))
    provider_auth = prior.provider_auth

    try:
        issued = await session_service.create_session(
            system_session,
            user_id=user.id,
            amr=amr,
            satisfied_providers=satisfied,
            provider_auth=provider_auth,
            user_agent=request.headers.get("user-agent"),
            ip=get_inet_client_ip(request),
        )
        # The chain, not the one row: rotation can have left descendants, and
        # the session issued just above is what replaces all of them. The
        # provider step-up revokes the chain for the same reason. ``prior`` is
        # not optional here — the request is refused above where there is none.
        await session_service.revoke_chain(system_session, session_id=prior.id)
        subject = await subject_service.subject_for_user(
            system_session, user_id=user.id
        )
        await system_session.commit()
    except Exception as exc:
        await system_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AuthMessages.SESSION_STORE_UNAVAILABLE,
        ) from exc

    access_token, access_max_age = mint_access_token(
        subject=subject,
        token_version=user.token_version,
        session_id=issued.session.id,
        amr=issued.session.amr,
        satisfied_providers=issued.session.satisfied_providers,
        provider_auth=issued.session.provider_auth,
    )
    set_session_cookie(response, access_token, max_age=access_max_age)
    set_refresh_cookie(response, issued.refresh_token)
    return Token(
        access_token=access_token,
        # The app keeps its own refresh token; a browser reads one from the
        # cookie set above and is handed nothing here.
        refresh_token=(
            issued.refresh_token
            if request.cookies.get(REFRESH_COOKIE_NAME) is None
            else None
        ),
    )

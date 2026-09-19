"""Opening the session a sign-in earned, whatever proved it.

The password route was the only way in for long enough that this lived there.
It is now shared: a password, a password plus a second factor, and a passkey
all end the same way — a server-side session, an access token, a refresh
cookie, and one audit record saying which of them it was.

What each route keeps for itself is the proving. What they hand over is
``amr`` (what this sign-in actually proved) and ``audit_detail`` (what the
record should say), so the one place that writes a session does not have to
know how many ways there are to reach it.

:func:`upgrade_session` is the same idea for a session that is already open:
the step-ups prove something more against it and hand over the ``amr`` that
adds, and the one place that rewrites a session does the rest. It is shared for
the same reason — two step-ups that each carried their own copy would be two
places for the carry-forward to diverge.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.platform_endpoints.session_cookies import (
    set_refresh_cookie,
    set_session_cookie,
)
from app.core.audit_events import AuditEventType
from app.core.login_methods import LoginMethod
from app.core.messages import AuthMessages, SettingsMessages
from app.core.rate_limit import get_inet_client_ip
from app.core.security import REFRESH_COOKIE_NAME, mint_access_token
from app.models.platform.auth_session import AuthSession
from app.models.platform.user import User
from app.schemas.platform.token import Token
from app.services import audit as audit_service
from app.services.auth import sessions as session_service
from app.services.auth import subject as subject_service
from app.services.platform import auth_posture
from app.services.platform import security_rules

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


def require_session_row(request: Request) -> uuid.UUID:
    """The server-side session this request is on, or 403.

    Named by the request's own access token: every client carries one of
    those, and a credential that is not a session — a device token, an API
    key — names none. The step-ups add to a session, so this is what they
    have to be holding before a ceremony is worth starting.
    """
    raw = getattr(request.state, "session_id", None)
    if raw:
        try:
            return uuid.UUID(str(raw))
        except ValueError:
            pass
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=AuthMessages.SESSION_REQUIRED,
    )


async def record_sign_in_failure(
    admin_session: AsyncSession,
    user: User | None,
    *,
    method: str,
    reason: str,
    watch: bool = True,
) -> None:
    """Write down a refused sign-in and commit it.

    The account is the **target**, when one resolved, and there is no actor: the
    request that made the attempt is unauthenticated. An unknown address still
    records the refusal but retains no submitted identity.

    ``method`` is how the sign-in was being attempted — a password, a passkey —
    so the board can tell one run of refusals from another.

    ``watch`` is whether the refusal counts toward the repeated-refusal rule.
    A route sets it aside where what was refused says nothing about the account
    the record names; the record itself is written either way.

    Its own commit because the request is about to raise, and ``audit_events``
    is reached on the system engine — the request-path role holds nothing on
    that table.
    """
    target_user_id = user.id if user is not None else None
    event = await audit_service.record(
        admin_session,
        event_type=AuditEventType.AUTH_SIGN_IN_FAILED,
        actor_user_id=None,
        target_user_id=target_user_id,
        target_type="user" if target_user_id is not None else None,
        target_id=target_user_id,
        detail={"method": method, "reason": reason},
    )
    await admin_session.commit()

    # The refusal is recorded; a rule now reads the window it belongs to. Only
    # where an account resolved, because a rule names the account and an
    # address nobody holds names nothing. Detached from this request, which is
    # about to refuse regardless.
    if watch and target_user_id is not None:
        security_rules.watch(
            security_rules.note_failed_sign_in(
                target_user_id, event_uuid=str(event.event_uuid)
            )
        )


async def open_session(
    request: Request,
    response: Response,
    admin_session: AsyncSession,
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

    Anything the caller staged in ``admin_session`` — a device token, a
    credential's counter — commits with the session, or goes with it.
    """
    try:
        issued = await session_service.create_session(
            admin_session,
            user_id=user_id,
            amr=amr,
            satisfied_providers=[],
            user_agent=request.headers.get("user-agent"),
            ip=get_inet_client_ip(request),
        )
        await audit_service.record(
            admin_session,
            event_type=AuditEventType.AUTH_SIGNED_IN,
            actor_user_id=user_id,
            detail=audit_detail,
        )
        # The name the token will carry, minted in the same transaction as the
        # session it belongs to.
        subject = await subject_service.subject_for_user(admin_session, user_id=user_id)
        await admin_session.commit()
    except Exception as exc:
        await admin_session.rollback()
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
    return Token(
        access_token=access_token,
        refresh_token=issued.refresh_token if return_refresh_token else None,
    )


async def upgrade_session(
    request: Request,
    response: Response,
    admin_session: AsyncSession,
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
    prior = await admin_session.get(AuthSession, require_session_row(request))
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
            admin_session,
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
        await session_service.revoke_chain(admin_session, session_id=prior.id)
        subject = await subject_service.subject_for_user(admin_session, user_id=user.id)
        await admin_session.commit()
    except Exception as exc:
        await admin_session.rollback()
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

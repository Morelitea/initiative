"""Opening the session a sign-in earned, whatever proved it.

Every way in ends the same way — a server-side session, an access token bounded
by it, a refresh token, and one audit record saying which way it was — and
:func:`issue_session` is the one place that writes a session and mints its
token. It stages; :func:`session_store` commits what the caller staged beside
it, or rolls all of it back and answers 503. :func:`mint_for` is the one place
an access token is given its lifetime, so a session narrowed by a community's
compliance setting narrows every token minted for it, on every path.

What each route keeps for itself is the proving. :func:`prove_password` is that
proving for the two routes that take a password, and
:func:`second_factor_outstanding` is what both of them, and the emailed code,
answer with when the account holds a second factor.

:func:`open_session` is a fresh sign-in, :func:`replace_session` the session a
caller carries on with after retiring every credential the account held, and
:func:`upgrade_session` a step-up against the session already open.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlmodel import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel.ext.asyncio.session import AsyncSession as SqlModelSession

from app.api.v1.platform_endpoints.session_cookies import (
    set_refresh_cookie,
    set_session_cookie,
)
from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.login_methods import LoginMethod
from app.core.messages import AuthMessages, SettingsMessages
from app.core.rate_limit import (
    clear_sign_in_failures,
    count_sign_in_failure,
    get_inet_client_ip,
    sign_in_allowance_left,
)
from app.core.security import (
    REFRESH_COOKIE_NAME,
    get_password_hash,
    mint_access_token,
    password_needs_rehash,
    verify_sign_in_password,
)
from app.models.platform.auth_session import AuthSession
from app.models.platform.user import SIGN_IN_STATUSES, User
from app.schemas.platform.token import Token
from app.services import audit as audit_service
from app.services.auth import addresses
from app.services.auth import challenges as challenge_service
from app.services.auth import sessions as session_service
from app.services.auth import sign_in_locks
from app.services.auth import subject as subject_service
from app.services.auth import totp as totp_service
from app.services.platform import auth_posture

logger = logging.getLogger(__name__)

#: Where a phone's sign-in comes back to. The app registers this scheme and
#: ``useDeepLinks`` routes it; the OIDC callback and the passkey relay both
#: hand the app a one-time code at this address (see ``native_handoff``).
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


async def _upgrade_password_hash(
    system_session: SqlModelSession, *, user: User, password: str
) -> None:
    """Re-hash a password that verified against outdated hashing parameters.

    Runs on the system engine. The row is the sign-in's own, but this happens
    before a session exists, so there is no request-path identity for the
    own-row rule on ``public.users`` to match against.

    Best-effort: a transient failure must not turn a successful authentication
    into a 500. The next sign-in retries the upgrade, and the stored hash keeps
    verifying until then.
    """
    try:
        new_hash = get_password_hash(password)
        await system_session.exec(
            sql_update(User).where(User.id == user.id).values(hashed_password=new_hash)
        )
        await system_session.commit()
        user.hashed_password = new_hash
    except Exception:
        await system_session.rollback()
        logger.exception("Failed to upgrade password hash for user %s", user.id)


async def prove_password(
    session: AsyncSession,
    system_session: SqlModelSession,
    *,
    email: str,
    password: str,
) -> User:
    """The account an address and password sign in to, or the refusal.

    The one proving for every route that takes a password, so each asks the
    same questions in the same order: whether the deployment permits passwords
    at all, whether the address has refusals left, whether the account is
    locked, whether the password matches, and whether the account and address
    may sign in. Every refusal is recorded.

    The password is checked whether or not the address resolved, so every
    attempt pays the same work.
    """
    await require_login_method(session, LoginMethod.password)
    normalized_email = email.lower().strip()
    if not await sign_in_allowance_left(normalized_email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=AuthMessages.SIGN_IN_LOCKED,
        )
    # Any of the account's addresses signs it in, resolved on the system engine
    # because there is nobody to scope a policy to until it returns.
    user = await addresses.find_user_by_address(system_session, normalized_email)
    # An address its holder has not confirmed admits nobody, but it is worth
    # saying so: resolved here only so the refusal below can name the reason.
    unconfirmed = (
        await addresses.account_awaiting_confirmation(system_session, normalized_email)
        if user is None
        else None
    )
    user = user or unconfirmed
    if user is not None:
        await refuse_if_locked(system_session, user.id)
    password_matches = verify_sign_in_password(
        password, user.hashed_password if user is not None else None
    )
    if not user or not password_matches:
        # Recorded whether or not the address resolved; the record keeps no
        # identity when there was none to keep.
        await count_sign_in_failure(normalized_email)
        await record_sign_in_failure(
            system_session, user, method="password", reason="bad_password"
        )
        if user is not None:
            await count_wrong_answer(system_session, user.id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.INCORRECT_CREDENTIALS,
        )

    # Refused even though the password matched. SIGN_IN_STATUSES rather than
    # active: an account waiting out its erasure window signs in precisely so
    # that signing in can call the deletion off.
    if user.status not in SIGN_IN_STATUSES:
        await record_sign_in_failure(
            system_session, user, method="password", reason="inactive"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER
        )
    if unconfirmed is not None:
        await record_sign_in_failure(
            system_session, user, method="password", reason="email_unverified"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_NOT_VERIFIED,
        )

    if password_needs_rehash(user.hashed_password):
        await _upgrade_password_hash(system_session, user=user, password=password)
    # Which of the account's addresses was used, for the account page and for
    # telling an address in use from one nobody has signed in with.
    await addresses.note_sign_in(system_session, email=normalized_email)
    await clear_sign_in_failures(normalized_email)
    return user


@dataclass(frozen=True)
class FirstLeg:
    """What a sign-in proved before its second factor was asked for.

    Carried across to the second leg by the purpose of the challenge that holds
    the sign-in open, so the session it opens records both halves.
    """

    method: str
    amr: tuple[str, ...]
    purpose: challenge_service.ChallengePurpose
    native_purpose: challenge_service.ChallengePurpose


PASSWORD_LEG = FirstLeg(
    method="password",
    amr=("pwd",),
    purpose=challenge_service.ChallengePurpose.sign_in,
    native_purpose=challenge_service.ChallengePurpose.sign_in_native,
)
EMAIL_CODE_LEG = FirstLeg(
    method="email_otp",
    amr=("otp",),
    purpose=challenge_service.ChallengePurpose.sign_in_after_code,
    native_purpose=challenge_service.ChallengePurpose.sign_in_after_code_native,
)
FIRST_LEGS: tuple[FirstLeg, ...] = (PASSWORD_LEG, EMAIL_CODE_LEG)

#: Every purpose a second-factor challenge is opened with.
SECOND_FACTOR_PURPOSES: tuple[challenge_service.ChallengePurpose, ...] = tuple(
    purpose for leg in FIRST_LEGS for purpose in (leg.purpose, leg.native_purpose)
)


def first_leg_of(purpose: str) -> tuple[FirstLeg, bool]:
    """The first leg a second-factor challenge was opened after, and whether
    it was the native sign-in's."""
    for leg in FIRST_LEGS:
        if purpose == leg.purpose.value:
            return leg, False
        if purpose == leg.native_purpose.value:
            return leg, True
    raise ValueError(f"not a second-factor challenge: {purpose!r}")


async def second_factor_outstanding(
    session: AsyncSession,
    system_session: AsyncSession,
    *,
    user_id: int,
    leg: FirstLeg,
    native: bool,
) -> JSONResponse | None:
    """The challenge to present a second factor against, where one is owed.

    ``None`` when the account holds no second factor, or the deployment does
    not permit one, and the sign-in is finished. Otherwise the challenge is
    committed and the 401 that hands it to the client comes back for the route
    to return.
    """
    if not await auth_posture.login_method_allowed(session, LoginMethod.totp):
        return None
    if not await totp_service.is_enrolled(system_session, user_id=user_id):
        return None
    issued = await challenge_service.create(
        system_session,
        user_id=user_id,
        purpose=leg.native_purpose if native else leg.purpose,
    )
    await system_session.commit()
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": AuthMessages.TOTP_REQUIRED, "challenge": issued.value},
    )


def mint_for(row: AuthSession, *, subject: str, token_version: int) -> tuple[str, int]:
    """The access token for one session, bounded by the session.

    The only place an access token is given its lifetime. Returns the token and
    its lifetime in seconds.
    """
    return mint_access_token(
        subject=subject,
        token_version=token_version,
        session_id=row.id,
        amr=row.amr,
        satisfied_providers=row.satisfied_providers,
        provider_auth=row.provider_auth,
        expires_in=access_ttl_for(row, now=row.created_at),
    )


@dataclass(frozen=True)
class OpenedSession:
    """A session staged by :func:`issue_session` and the tokens that carry it.

    ``refresh_token`` exists only here until a response carries it.
    """

    session: AuthSession
    access_token: str
    access_max_age: int
    refresh_token: str

    def to_token(self, *, include_refresh: bool) -> Token:
        return Token(
            access_token=self.access_token,
            refresh_token=self.refresh_token if include_refresh else None,
        )

    def set_cookies(self, response: Response) -> None:
        set_session_cookie(response, self.access_token, max_age=self.access_max_age)
        set_refresh_cookie(response, self.refresh_token)


@asynccontextmanager
async def session_store(
    system_session: AsyncSession, *, user_id: int
) -> AsyncIterator[None]:
    """Commit a session and everything staged beside it, or none of it.

    A sign-in *is* the session. If it cannot be written the request says so
    with a 503 rather than handing back a lesser credential. Anything the
    caller stages inside — a device token, an audit record, the revocation of
    the session it replaces — commits with the session, or goes with it.
    """
    try:
        yield
        await system_session.commit()
    except Exception as exc:
        await system_session.rollback()
        logger.exception("Could not open a session for user %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AuthMessages.SESSION_STORE_UNAVAILABLE,
        ) from exc


async def issue_session(
    request: Request,
    system_session: AsyncSession,
    *,
    user_id: int,
    token_version: int,
    amr: Sequence[str],
    satisfied_providers: Sequence[int] = (),
    provider_auth: dict[str, Any] | None = None,
    device_name: str | None = None,
    replaces: uuid.UUID | None = None,
) -> OpenedSession:
    """Stage a session and mint the access token for it.

    Called inside :func:`session_store`, which commits it. Session writes run
    on the system engine (``auth_sessions`` is ``app_admin``-only).

    ``amr`` is what the session may claim was proved. ``replaces`` names a
    session this one takes the place of: its whole rotation chain is revoked in
    the same transaction, since a refresh can have left descendants the new
    session also replaces. The new session is a fresh chain root, so the walk
    never reaches it.
    """
    issued = await session_service.create_session(
        system_session,
        user_id=user_id,
        amr=list(dict.fromkeys(amr)),
        satisfied_providers=sorted(set(satisfied_providers)),
        provider_auth=provider_auth,
        user_agent=request.headers.get("user-agent"),
        ip=get_inet_client_ip(request),
        device_name=device_name,
    )
    if replaces is not None:
        await session_service.revoke_chain(system_session, session_id=replaces)
    # The name the token will carry, in the same transaction as the session.
    subject = await subject_service.subject_for_user(system_session, user_id=user_id)
    access_token, access_max_age = mint_for(
        issued.session, subject=subject, token_version=token_version
    )
    return OpenedSession(
        session=issued.session,
        access_token=access_token,
        access_max_age=access_max_age,
        refresh_token=issued.refresh_token,
    )


async def open_session(
    request: Request,
    response: Response,
    system_session: AsyncSession,
    *,
    user_id: int,
    token_version: int,
    amr: Sequence[str],
    audit_detail: dict[str, Any],
    return_refresh_token: bool = False,
) -> Token:
    """Open the session a sign-in earned, and hand back its token.

    The access token carries sid/amr/sat; the rotating refresh cookie carries
    the session (history/auth-detailed-design.md §3). ``amr`` is what this
    sign-in proved. ``return_refresh_token`` hands the refresh token back in
    the body too, for the app, which keeps its own.

    Anything the caller staged in ``system_session`` — a credential's counter,
    a spent challenge — commits with the session, or goes with it.
    """
    async with session_store(system_session, user_id=user_id):
        await audit_service.record(
            system_session,
            event_type=AuditEventType.AUTH_SIGNED_IN,
            actor_user_id=user_id,
            detail=audit_detail,
        )
        # Signed in, so the wrong answers before this no longer add up to a lock.
        await sign_in_locks.record_success(system_session, user_id)
        issued = await issue_session(
            request,
            system_session,
            user_id=user_id,
            token_version=token_version,
            amr=amr,
        )
    issued.set_cookies(response)
    return issued.to_token(include_refresh=return_refresh_token)


async def replace_session(
    request: Request,
    response: Response,
    system_session: AsyncSession,
    *,
    user: User,
    amr: Sequence[str],
    satisfied_providers: Sequence[int],
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

    What carries into it is the caller's to decide — ``amr`` is what the
    replacement may claim was proved, and the satisfied providers and their own
    account of it come forward where the request has one to carry.
    """
    # Read before the writes below: ``user`` may be staged on ``system_session``,
    # and a rollback leaves its columns to be fetched again.
    user_id = user.id
    token_version = user.token_version
    async with session_store(system_session, user_id=user_id):
        issued = await issue_session(
            request,
            system_session,
            user_id=user_id,
            token_version=token_version,
            amr=amr,
            satisfied_providers=satisfied_providers,
            provider_auth=provider_auth,
        )
    issued.set_cookies(response)
    return issued.to_token(include_refresh=False)


async def live_session_of(
    system_session: AsyncSession, *, session_id: uuid.UUID | None, user_id: int
) -> AuthSession | None:
    """The session ``session_id`` names, while it is live and ``user_id``'s."""
    if session_id is None:
        return None
    row = await system_session.get(AuthSession, session_id)
    if row is None or row.user_id != user_id or row.revoked_at is not None:
        return None
    return row


async def upgrade_session(
    request: Request,
    response: Response,
    system_session: AsyncSession,
    *,
    user: User,
    add_amr: Sequence[str],
) -> Token:
    """Add what was just proved to the session already signed in.

    A community that asks for something a session never presented refuses it,
    and signing out to sign back in would be a strange way to answer that. So
    the factor — a code, a passkey — is taken against the live session and this
    is what records it.

    The session is upgraded rather than replaced from nothing: its ``amr``, its
    satisfied providers and each provider's account of its own authentication
    carry forward, and the old chain is retired. Satisfying one community's
    requirement never un-satisfies another's.

    The session upgraded is the one this request is *on*, named by its own
    access token: every client carries that, and only a browser also carries a
    refresh cookie. A credential that is not a session is refused — this
    endpoint upgrades one, and there is nothing else here to add to.
    """
    prior = await live_session_of(
        system_session, session_id=require_session_row(request), user_id=user.id
    )
    if prior is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMessages.SESSION_REQUIRED,
        )

    async with session_store(system_session, user_id=user.id):
        issued = await issue_session(
            request,
            system_session,
            user_id=user.id,
            token_version=user.token_version,
            amr=sorted(set(prior.amr) | set(add_amr)),
            satisfied_providers=prior.satisfied_providers,
            provider_auth=prior.provider_auth,
            replaces=prior.id,
        )
    issued.set_cookies(response)
    # The app keeps its own refresh token; a browser reads one from the cookie
    # set above and is handed nothing here.
    return issued.to_token(
        include_refresh=request.cookies.get(REFRESH_COOKIE_NAME) is None
    )

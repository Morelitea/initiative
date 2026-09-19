"""An account that signs in without a password.

Mounted under ``/auth`` beside the passkeys that make it possible. Two routes:
giving the password up, for an account that holds another way in, and getting
one back with a recovery code, for an account that holds none.

Every route runs on the system engine for the same reason the second-factor
routes do: the tables they read are app_admin-only.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, require_first_party_session
from app.api.v1.platform_endpoints.password_recheck import require_password
from app.api.v1.platform_endpoints.session_cookies import (
    set_refresh_cookie,
    set_session_cookie,
)
from app.api.v1.platform_endpoints.session_opening import require_login_method
from app.core.audit_events import AuditEventType
from app.core.login_methods import LoginMethod
from app.core.messages import AuthMessages
from app.core.password_policy import enforce_password_policy
from app.core.rate_limit import get_inet_client_ip, limiter
from app.core.security import (
    get_password_hash,
    has_usable_password,
    mint_access_token,
)
from app.db.session import get_admin_session, get_session
from app.models.platform.auth_session import AuthSession
from app.models.platform.user import User, UserStatus
from app.schemas.platform.auth import VerificationSendResponse
from app.schemas.platform.passwordless import PasswordRecover, PasswordRemove
from app.schemas.platform.second_factor import RecoveryCodes
from app.services import audit as audit_service
from app.services import email as email_service
from app.services.auth import addresses
from app.services.auth import identity as identity_service
from app.services.auth import sessions as session_service
from app.services.auth import subject as subject_service
from app.services.auth import totp as totp_service
from app.services.platform import user_tokens

logger = logging.getLogger(__name__)

router = APIRouter()

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_active_user)]
#: Giving up a way in is done by the person in a session of their own rather
#: than through a standing credential.
FirstPartyOnly = Depends(require_first_party_session)


def _recovery_code_invalid() -> HTTPException:
    """The one answer every miss gets: an address nobody holds, an account that
    is not active, an account that holds a password, and a code that did not
    match are all the same refusal."""
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=AuthMessages.RECOVERY_CODE_INVALID,
    )


async def _record_recovery_refusal(
    admin_session: AsyncSession, *, user_id: int
) -> None:
    """Write down a refused recovery, against the account it named.

    No actor: the request is unauthenticated, the same shape the sign-in's own
    second-factor leg records. Its own commit, because the request is about to
    refuse.
    """
    await audit_service.record(
        admin_session,
        event_type=AuditEventType.AUTH_SECOND_FACTOR_FAILED,
        actor_user_id=None,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={"method": "recovery_code", "during": "recover"},
    )
    await admin_session.commit()


@router.post("/password/remove", response_model=RecoveryCodes)
@limiter.limit("5/15minutes")
async def remove_password(
    request: Request,
    response: Response,
    session: SessionDep,
    admin_session: AdminSessionDep,
    current_user: CurrentUser,
    payload: PasswordRemove,
    _first_party: str = FirstPartyOnly,
) -> RecoveryCodes:
    """Give up the password, keeping the passkey or the sign-in provider that
    will open sessions from now on.

    Hands back a recovery set when the account holds none yet — the one time
    those exist in the clear — and an empty list when it already does.
    """
    if not has_usable_password(current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.PASSWORD_NOT_HELD,
        )
    require_password(current_user, payload.current_password)

    # What the account would be left with. The deployment's posture is half of
    # that answer: a credential it does not accept opens nothing, so an account
    # holding only one keeps its password.
    remaining = await identity_service.ways_in(
        admin_session, user_id=current_user.id
    ) - {LoginMethod.password}
    if not remaining:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthMessages.PASSWORD_IS_LAST_METHOD,
        )

    # The session this request is on, read before the revocation below retires
    # it: the one that replaces it carries what it had proved.
    prior_id = getattr(request.state, "session_id", None)
    prior = (
        await admin_session.get(AuthSession, uuid.UUID(str(prior_id)))
        if prior_id
        else None
    )
    carried_amr = (
        sorted(set(prior.amr))
        if prior is not None and prior.user_id == current_user.id
        else []
    )

    # Device tokens are revoked and committed on the request path first: they
    # live on a table the system engine holds no UPDATE on, so the two halves
    # cannot share a transaction. A failure after this point signs the account
    # out everywhere and leaves the password where it was.
    await user_tokens.revoke_active_device_tokens(session, user_id=current_user.id)
    await session.commit()

    # The row is written on the system engine, which is where the rest of this
    # request's writes land.
    account = await admin_session.get(User, current_user.id)
    if account is None:  # pragma: no cover - resolved a moment ago
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    account.hashed_password = None
    account.password_set_at = None
    account.updated_at = datetime.now(timezone.utc)
    admin_session.add(account)
    await audit_service.record(
        admin_session,
        event_type=AuditEventType.AUTH_PASSWORD_REMOVED,
        actor_user_id=account.id,
    )
    # Bump token_version and retire the API keys, refresh sessions and
    # half-finished sign-ins that rested on the password.
    #
    # Staged, not committed: the replacement session below joins them in one
    # transaction, so the account keeps what it had if that fails.
    await user_tokens.revoke_user_sessions(
        session, user=account, admin_session=admin_session, commit=False
    )

    # A recovery set exists from the moment the account becomes passwordless,
    # because a code is now how it gets a password back — on a deployment with
    # no mail configured, which is the self-hosted case, it is the only way.
    # An account that already holds codes keeps them; they are still good.
    codes: list[str] = []
    held = await totp_service.remaining_recovery_codes(
        admin_session, user_id=account.id
    )
    if held == 0:
        codes = await totp_service.issue_recovery_codes(
            admin_session, user_id=account.id
        )
        await audit_service.record(
            admin_session,
            event_type=AuditEventType.AUTH_RECOVERY_CODES_ISSUED,
            actor_user_id=account.id,
        )

    # ...and keep THIS device signed in: the revocation above took the caller's
    # own access token and refresh chain with everything else, so a fresh
    # session is opened and both cookies re-issued. Its ``amr`` is what the
    # session it replaces had proved.
    #
    # A session is the only credential there is, so a store that cannot be
    # written ends the request rather than answering with a lesser one.
    try:
        issued = await session_service.create_session(
            admin_session,
            user_id=account.id,
            amr=carried_amr,
            satisfied_providers=[],
            user_agent=request.headers.get("user-agent"),
            ip=get_inet_client_ip(request),
        )
        # The name the token will carry, minted in the same transaction as the
        # session it belongs to.
        subject = await subject_service.subject_for_user(
            admin_session, user_id=account.id
        )
        # One commit for the password, the record, the revocations, the codes
        # and the session that stands in for this device's.
        await admin_session.commit()
    except Exception as exc:
        await admin_session.rollback()
        logger.exception(
            "Could not open a session for user %s after removing its password",
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AuthMessages.SESSION_STORE_UNAVAILABLE,
        ) from exc
    await session.commit()

    access_token, access_max_age = mint_access_token(
        subject=subject,
        token_version=account.token_version,
        session_id=issued.session.id,
        amr=issued.session.amr,
        satisfied_providers=issued.session.satisfied_providers,
    )
    set_session_cookie(response, access_token, max_age=access_max_age)
    set_refresh_cookie(response, issued.refresh_token)

    await email_service.announce_password_removed(admin_session, account)
    return RecoveryCodes(codes=codes)


@router.post("/password/recover", response_model=VerificationSendResponse)
@limiter.limit("5/15minutes")
async def recover_with_code(
    request: Request,
    session: SessionDep,
    admin_session: AdminSessionDep,
    payload: PasswordRecover,
) -> VerificationSendResponse:
    """Set a password with a recovery code, for an account that holds none.

    The way back in when the passkey is gone and no mail can be sent. An
    account that holds a password recovers it through the mailed reset instead.

    No session is opened here. The password is what the account signs in with
    afterwards, and the authenticator is still asked for where one is enrolled.
    """
    await require_login_method(session, LoginMethod.password)
    # The policy runs before anything is spent: a candidate this deployment
    # would not take must not cost the account one of its codes.
    await enforce_password_policy(payload.password)

    user = await addresses.find_user_by_address(admin_session, payload.email)
    if user is None:
        raise _recovery_code_invalid()
    if user.status != UserStatus.active or has_usable_password(user.hashed_password):
        await _record_recovery_refusal(admin_session, user_id=user.id)
        raise _recovery_code_invalid()
    if not await totp_service.consume_recovery_code(
        admin_session, user_id=user.id, code=payload.recovery_code
    ):
        await _record_recovery_refusal(admin_session, user_id=user.id)
        raise _recovery_code_invalid()

    # Device tokens are revoked and committed on the request path first: they
    # live on a table the system engine holds no UPDATE on, so the two halves
    # cannot share a transaction. A failure after this point signs the account
    # out everywhere and leaves it passwordless, which is where it began.
    await user_tokens.revoke_active_device_tokens(session, user_id=user.id)
    await session.commit()

    user.hashed_password = get_password_hash(payload.password)
    user.password_set_at = datetime.now(timezone.utc)
    # Staged before ``revoke_user_sessions`` below, which commits this session:
    # ``user`` is bound to it, so the password, the spent code and these two
    # records land on one commit.
    await audit_service.record(
        admin_session,
        event_type=AuditEventType.AUTH_RECOVERY_CODE_USED,
        actor_user_id=user.id,
        detail={
            "remaining": await totp_service.remaining_recovery_codes(
                admin_session, user_id=user.id
            )
        },
    )
    await audit_service.record(
        admin_session,
        event_type=AuditEventType.AUTH_PASSWORD_CHANGED,
        actor_user_id=user.id,
        detail={"via": "recovery_code"},
    )
    # Bump token_version and retire the device tokens, API keys and refresh
    # sessions the account held before it was recovered.
    await user_tokens.revoke_user_sessions(
        session, user=user, admin_session=admin_session
    )
    user.updated_at = datetime.now(timezone.utc)
    admin_session.add(user)
    await session.commit()
    await admin_session.commit()
    return VerificationSendResponse(status="reset")

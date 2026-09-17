"""Enrolling, proving and removing the account's own second factor.

Mounted under ``/auth`` beside the sign-in it changes. The sign-in itself — the
challenge and the code answered against it — stays in ``auth.py``, with the
password leg it continues.

Every route here runs on the system engine: ``user_totp`` and its companions
are app_admin-only, because a factor is presented while signing in, before
there is anybody to scope a policy to.
"""

import uuid
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.deps import get_current_active_user, require_first_party_session
from app.core.audit_events import AuditEventType
from app.core.login_methods import LoginMethod
from app.core.messages import AuthMessages, UserMessages
from app.core.rate_limit import get_inet_client_ip, limiter
from app.core.security import (
    REFRESH_COOKIE_NAME,
    has_usable_password,
    mint_access_token,
    verify_password,
)
from app.api.v1.platform_endpoints.session_cookies import (
    set_refresh_cookie,
    set_session_cookie,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_admin_session
from app.models.platform.auth_session import AuthSession
from app.models.platform.user import User
from app.schemas.platform.token import Token
from app.schemas.platform.second_factor import (
    SecondFactorStepUpAnswer,
    RecoveryCodes,
    RecoveryCodesRegenerate,
    SecondFactorConfirm,
    SecondFactorDisable,
    SecondFactorEnrolment,
    SecondFactorEnrolStart,
    SecondFactorStatus,
)
from app.services import audit as audit_service
from app.services import email as email_service
from app.services.auth import addresses
from app.services.auth import challenges as challenge_service
from app.services.auth import totp as totp_service
from app.services.platform import auth_posture
from app.services.auth import sessions as session_service
from app.services.auth import subject as subject_service
from app.services.auth.assurance import SECOND_FACTOR_AMR

router = APIRouter()

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]

CurrentUser = Annotated[User, Depends(get_current_active_user)]
#: Enrolling and removing a factor change how the account is signed into, so
#: they are done by the person in a session of their own rather than through a
#: standing credential.
FirstPartyOnly = Depends(require_first_party_session)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _require_password(user: User, supplied: Optional[str]) -> None:
    """Re-check the password, as a password change does.

    The exemption is for an account that holds no password to re-check — one
    provisioned through an identity provider. Holding a federated identity is
    not the same question: an account can have both, and one that has a
    password is asked for it. Nor is "the column is NULL": a hash no scheme
    verifies is not a password either, and asking for one nobody can supply
    would shut the account out of its own settings.
    """
    if not has_usable_password(user.hashed_password):
        return
    if not supplied:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.CURRENT_PASSWORD_REQUIRED,
        )
    if not verify_password(supplied, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.CURRENT_PASSWORD_INCORRECT,
        )


@router.get("/totp", response_model=SecondFactorStatus)
async def read_second_factor(
    current_user: CurrentUser,
    admin_session: AdminSessionDep,
) -> SecondFactorStatus:
    """What the account holds. A started-but-unproved enrolment reads as not
    enrolled, because that is what the sign-in makes of it too."""
    offered = await auth_posture.login_method_allowed(admin_session, LoginMethod.totp)
    password_required = has_usable_password(current_user.hashed_password)
    factor = await totp_service.get_factor(admin_session, user_id=current_user.id)
    if factor is None or factor.confirmed_at is None:
        return SecondFactorStatus(password_required=password_required, offered=offered)
    return SecondFactorStatus(
        enrolled=True,
        password_required=password_required,
        offered=offered,
        confirmed_at=_iso(factor.confirmed_at),
        last_used_at=_iso(factor.last_used_at),
        recovery_codes_remaining=await totp_service.remaining_recovery_codes(
            admin_session, user_id=current_user.id
        ),
    )


@router.post("/totp/enroll", response_model=SecondFactorEnrolment)
@limiter.limit("10/hour")
async def begin_second_factor(
    request: Request,
    current_user: CurrentUser,
    admin_session: AdminSessionDep,
    payload: SecondFactorEnrolStart,
    _first_party: str = FirstPartyOnly,
) -> SecondFactorEnrolment:
    """Mint a seed and hand it over, once.

    Nothing is asked for at sign-in until it is confirmed, so an enrolment
    begun and abandoned costs the account nothing. Beginning again replaces it.
    """
    if not await auth_posture.login_method_allowed(admin_session, LoginMethod.totp):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMessages.TOTP_NOT_PERMITTED,
        )
    if await totp_service.is_enrolled(admin_session, user_id=current_user.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthMessages.TOTP_ALREADY_ENROLLED,
        )
    _require_password(current_user, payload.current_password)

    # What the authenticator app shows under the issuer. The address the
    # person signs in with where there is one, so an account with two entries
    # is told apart; the handle otherwise.
    account = (
        await addresses.primary_address(admin_session, user_id=current_user.id)
        or current_user.username
    )
    enrolment = await totp_service.begin_enrolment(
        admin_session,
        user_id=current_user.id,
        account=account,
        issuer=totp_service.issuer_name(),
    )
    await admin_session.commit()
    return SecondFactorEnrolment(secret=enrolment.secret, otpauth_uri=enrolment.uri)


@router.post("/totp/confirm", response_model=RecoveryCodes)
@limiter.limit("10/15minutes")
async def confirm_second_factor(
    request: Request,
    current_user: CurrentUser,
    admin_session: AdminSessionDep,
    payload: SecondFactorConfirm,
    _first_party: str = FirstPartyOnly,
) -> RecoveryCodes:
    """Prove the enrolment with a code it produced, and hand back the recovery
    set — the one time those exist in the clear.

    Sessions are left alone: the person is where they are and has just proved
    it.
    """
    factor = await totp_service.get_factor(admin_session, user_id=current_user.id)
    if factor is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.TOTP_NOT_ENROLLED,
        )
    if factor.confirmed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthMessages.TOTP_ALREADY_ENROLLED,
        )
    if not await totp_service.confirm_enrolment(
        admin_session, user_id=current_user.id, code=payload.code
    ):
        await audit_service.record(
            admin_session,
            event_type=AuditEventType.AUTH_SECOND_FACTOR_FAILED,
            actor_user_id=current_user.id,
            detail={"method": "totp", "during": "enrolment"},
        )
        await admin_session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.TOTP_INVALID
        )

    codes = await totp_service.issue_recovery_codes(
        admin_session, user_id=current_user.id
    )
    await audit_service.record(
        admin_session,
        event_type=AuditEventType.AUTH_SECOND_FACTOR_ENROLLED,
        actor_user_id=current_user.id,
        detail={"method": "totp"},
    )
    await admin_session.commit()
    await email_service.announce_second_factor_change(
        admin_session, current_user, enabled=True
    )
    return RecoveryCodes(codes=codes)


@router.post("/totp/disable", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/15minutes")
async def disable_second_factor(
    request: Request,
    current_user: CurrentUser,
    admin_session: AdminSessionDep,
    payload: SecondFactorDisable,
    _first_party: str = FirstPartyOnly,
) -> None:
    """Remove the factor, its seed and its recovery codes.

    Asks for the password and for the factor itself — a live code, or one of
    the recovery codes. Every other session goes with it; this one stays.
    """
    if not await totp_service.is_enrolled(admin_session, user_id=current_user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.TOTP_NOT_ENROLLED,
        )
    _require_password(current_user, payload.current_password)

    if payload.recovery_code:
        proved = await totp_service.consume_recovery_code(
            admin_session, user_id=current_user.id, code=payload.recovery_code
        )
        refusal = AuthMessages.RECOVERY_CODE_INVALID
    else:
        proved = await totp_service.verify_code(
            admin_session, user_id=current_user.id, code=payload.code or ""
        )
        refusal = AuthMessages.TOTP_INVALID
    if not proved:
        await audit_service.record(
            admin_session,
            event_type=AuditEventType.AUTH_SECOND_FACTOR_FAILED,
            actor_user_id=current_user.id,
            detail={"method": "totp", "during": "removal"},
        )
        await admin_session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=refusal)

    await totp_service.disable(admin_session, user_id=current_user.id)
    await challenge_service.revoke_for_user(admin_session, user_id=current_user.id)
    # Every other session, and not this one: the change was made from a page
    # that should still be signed in when it finishes.
    await session_service.revoke_all_for_user(
        admin_session,
        user_id=current_user.id,
        except_session_id=getattr(request.state, "session_id", None),
    )
    await audit_service.record(
        admin_session,
        event_type=AuditEventType.AUTH_SECOND_FACTOR_DISABLED,
        actor_user_id=current_user.id,
        detail={"method": "totp"},
    )
    await admin_session.commit()
    await email_service.announce_second_factor_change(
        admin_session, current_user, enabled=False
    )


@router.post("/step-up/totp", response_model=Token)
@limiter.limit("10/15minutes")
async def step_up_with_factor(
    request: Request,
    response: Response,
    current_user: CurrentUser,
    admin_session: AdminSessionDep,
    payload: SecondFactorStepUpAnswer,
    _first_party: str = FirstPartyOnly,
) -> Token:
    """Add the account's second factor to the session already signed in.

    A community that asks for one refuses a session that never presented it,
    and signing out to sign back in would be a strange way to answer that. This
    takes the code against the live session instead.

    The session is upgraded rather than replaced from nothing: its factors and
    its satisfied providers carry forward and the old row is revoked, the same
    shape the provider step-up uses — satisfying one community's requirement
    never un-satisfies another's.
    """
    if not await totp_service.is_enrolled(admin_session, user_id=current_user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.TOTP_NOT_ENROLLED,
        )

    if payload.recovery_code:
        accepted = await totp_service.consume_recovery_code(
            admin_session, user_id=current_user.id, code=payload.recovery_code
        )
        method, factor_amr = "recovery_code", [SECOND_FACTOR_AMR]
        refusal = AuthMessages.RECOVERY_CODE_INVALID
    else:
        accepted = await totp_service.verify_code(
            admin_session, user_id=current_user.id, code=payload.code or ""
        )
        method, factor_amr = "totp", ["otp", SECOND_FACTOR_AMR]
        refusal = AuthMessages.TOTP_INVALID

    if not accepted:
        await audit_service.record(
            admin_session,
            event_type=AuditEventType.AUTH_SECOND_FACTOR_FAILED,
            actor_user_id=current_user.id,
            detail={"method": method, "during": "step_up"},
        )
        await admin_session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=refusal)

    # The session this request is *on*, named by its own access token. Every
    # client carries that; only a browser also carries a refresh cookie, so the
    # token is what identifies the session to add the factor to.
    prior_id = getattr(request.state, "session_id", None)
    prior = (
        await admin_session.get(AuthSession, uuid.UUID(str(prior_id)))
        if prior_id
        else None
    )
    if prior is not None and (
        prior.user_id != current_user.id or prior.revoked_at is not None
    ):
        prior = None
    if prior is None:
        # Nothing to add the factor to: this endpoint upgrades a session, and a
        # credential that is not one carries no assurance to carry forward.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMessages.SESSION_REQUIRED,
        )

    amr = sorted(set(prior.amr) | set(factor_amr))
    satisfied = sorted(set(prior.satisfied_providers))
    provider_auth = prior.provider_auth

    try:
        issued = await session_service.create_session(
            admin_session,
            user_id=current_user.id,
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
        subject = await subject_service.subject_for_user(
            admin_session, user_id=current_user.id
        )
        await admin_session.commit()
    except Exception as exc:
        await admin_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AuthMessages.SESSION_STORE_UNAVAILABLE,
        ) from exc

    access_token, access_max_age = mint_access_token(
        subject=subject,
        token_version=current_user.token_version,
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


@router.post("/recovery-codes/regenerate", response_model=RecoveryCodes)
@limiter.limit("5/hour")
async def regenerate_recovery_codes(
    request: Request,
    current_user: CurrentUser,
    admin_session: AdminSessionDep,
    payload: RecoveryCodesRegenerate,
    _first_party: str = FirstPartyOnly,
) -> RecoveryCodes:
    """Retire the account's codes and hand over a fresh set, once."""
    if not await totp_service.is_enrolled(admin_session, user_id=current_user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.TOTP_NOT_ENROLLED,
        )
    _require_password(current_user, payload.current_password)

    codes = await totp_service.issue_recovery_codes(
        admin_session, user_id=current_user.id
    )
    await audit_service.record(
        admin_session,
        event_type=AuditEventType.AUTH_RECOVERY_CODES_ISSUED,
        actor_user_id=current_user.id,
    )
    await admin_session.commit()
    return RecoveryCodes(codes=codes)

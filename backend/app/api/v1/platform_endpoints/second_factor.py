"""Enrolling, proving and removing the account's own second factor.

Mounted under ``/auth`` beside the sign-in it changes. The sign-in itself — the
challenge and the code answered against it — stays in ``auth.py``, with the
password leg it continues.

Every route here runs on the system engine: ``user_totp`` and its companions
are app_admin-only, because a factor is presented while signing in, before
there is anybody to scope a policy to.
"""

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_current_active_user, require_first_party_session
from app.core.audit_events import AuditEventType
from app.core.messages import AuthMessages, UserMessages
from app.core.rate_limit import limiter
from app.core.security import verify_password
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_admin_session
from app.models.platform.user import User
from app.schemas.platform.second_factor import (
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
from app.services.auth.identity import has_federated_identity
from app.services.auth import sessions as session_service

router = APIRouter()

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]

CurrentUser = Annotated[User, Depends(get_current_active_user)]
#: Enrolling and removing a factor change how the account is signed into, so
#: they are done by the person in a session of their own rather than through a
#: standing credential.
FirstPartyOnly = Depends(require_first_party_session)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


async def _require_password(
    admin_session,
    user: User,
    supplied: Optional[str],
) -> None:
    """Re-check the password, as a password change does.

    An account with no usable password — one that only ever arrived through an
    identity provider — is asked for nothing, the same exemption the password
    change already makes.
    """
    if await has_federated_identity(admin_session, user_id=user.id):
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
    factor = await totp_service.get_factor(admin_session, user_id=current_user.id)
    if factor is None or factor.confirmed_at is None:
        return SecondFactorStatus()
    return SecondFactorStatus(
        enrolled=True,
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
    if await totp_service.is_enrolled(admin_session, user_id=current_user.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthMessages.TOTP_ALREADY_ENROLLED,
        )
    await _require_password(admin_session, current_user, payload.current_password)

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
    the recovery codes. Every other session goes with it.
    """
    if not await totp_service.is_enrolled(admin_session, user_id=current_user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.TOTP_NOT_ENROLLED,
        )
    await _require_password(admin_session, current_user, payload.current_password)

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
    await session_service.revoke_all_for_user(admin_session, user_id=current_user.id)
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
    await _require_password(admin_session, current_user, payload.current_password)

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

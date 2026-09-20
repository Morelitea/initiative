"""Signing in with a one-time code sent to an address.

Two routes. :func:`send_sign_in_code` opens a challenge and posts the code;
:func:`verify_sign_in_code` takes the code back and opens the session.

Asking about an address answers the same way whoever holds it — a challenge
is opened either way, and only whether a letter goes out differs. The handle
in that answer is half the proof; the code in the mailbox is the other half,
and neither is a sign-in alone.

Everything runs on the system engine, like the rest of the sign-in routes:
there is nobody to scope a policy to until one of them returns.
"""

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.platform_endpoints.session_opening import (
    open_session,
    record_sign_in_failure,
    require_login_method,
)
from app.core.audit_events import AuditEventType
from app.core.login_methods import LoginMethod
from app.core.messages import AuthMessages
from app.core.rate_limit import get_real_client_ip, limiter
from app.db.session import get_admin_session, get_session
from app.models.platform.user import User, UserStatus
from app.models.platform.user_email import UserEmail
from app.schemas.platform.email_otp import EmailOtpSend, EmailOtpSent, EmailOtpVerify
from app.schemas.platform.token import Token
from app.services import audit as audit_service
from app.services import captcha as captcha_service
from app.services import email as email_service
from app.services.auth import addresses
from app.services.auth import challenges as challenge_service
from app.services.auth import email_otp as email_otp_service
from app.services.auth import totp as totp_service
from app.services.platform import auth_posture
from app.services.platform import user_tokens

logger = logging.getLogger(__name__)

router = APIRouter()

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _retire_credentials_predating_proof(
    session: AsyncSession, *, user: User
) -> None:
    """Drop every credential the account held before this address was proved.

    Reached only where the code confirmed an address nobody had proved. The
    account keeps its handle, its memberships and its content; what it gives
    up is the password and the standing credentials that were set while the
    address was unproven. Whoever proved it signs in, and sets a password
    afterwards if they want one.
    """
    user.hashed_password = None
    user.password_set_at = None
    session.add(user)
    # Staged rather than committed: the session this sign-in opens lands in
    # the same transaction, so the account never sits with nothing.
    await user_tokens.revoke_user_sessions(
        session, user=user, admin_session=session, commit=False
    )
    await audit_service.record(
        session,
        event_type=AuditEventType.AUTH_CREDENTIALS_RETIRED,
        actor_user_id=user.id,
        target_user_id=user.id,
        target_type="user",
        target_id=user.id,
        detail={"reason": "address_first_proved"},
    )


@router.post("/email-otp/send", response_model=EmailOtpSent)
@limiter.limit("5/15minutes")
async def send_sign_in_code(
    request: Request,
    payload: EmailOtpSend,
    session: SessionDep,
    admin_session: AdminSessionDep,
) -> EmailOtpSent:
    """Post a code to an address, and hand back the handle that names it.

    The captcha is answered before the address is resolved: it says something
    about the request, not about the address, so it is the one refusal this
    route makes.
    """
    await require_login_method(session, LoginMethod.email_otp)
    await captcha_service.verify_or_raise(
        payload.captcha_token, remote_ip=get_real_client_ip(request)
    )
    if not await email_service.email_configured(admin_session):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_OTP_CANNOT_SEND,
        )

    address = payload.email.lower().strip()
    user = await addresses.account_holding(admin_session, address)
    # An account that cannot sign in is not one to send a code to, and reads
    # from here exactly like an address nobody holds.
    recipient = user if user is not None and user.status == UserStatus.active else None
    row = (
        await addresses.row_for(admin_session, address)
        if recipient is not None
        else None
    )

    issued = await email_otp_service.issue(
        admin_session,
        user_id=recipient.id if recipient is not None else None,
        user_email_id=row.id if row is not None else None,
        native=payload.native,
    )
    if recipient is not None:
        try:
            await email_service.send_sign_in_code_email(
                admin_session,
                recipient,
                email=address,
                code=issued.code,
                minutes=int(email_otp_service.CODE_TTL.total_seconds() // 60),
            )
        except email_service.EmailNotConfiguredError:  # pragma: no cover
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=AuthMessages.EMAIL_OTP_CANNOT_SEND,
            ) from None
    await admin_session.commit()
    return EmailOtpSent(challenge=issued.handle)


@router.post("/email-otp/verify", response_model=Token)
@limiter.limit("10/15minutes")
async def verify_sign_in_code(
    request: Request,
    response: Response,
    payload: EmailOtpVerify,
    session: SessionDep,
    admin_session: AdminSessionDep,
) -> Token | Response:
    """Take the code back and open the session it earned."""
    await require_login_method(session, LoginMethod.email_otp)
    challenge = await email_otp_service.claim(
        admin_session, handle=payload.challenge, code=payload.code
    )
    if challenge is None or challenge.user_id is None:
        # The attempt is counted whether or not the code was any good, so the
        # commit comes before the refusal.
        await admin_session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_OTP_INVALID,
        )

    user_id = challenge.user_id
    user = await admin_session.get(User, user_id)
    if user is None or user.status != UserStatus.active:
        await record_sign_in_failure(
            admin_session, user, method="email_otp", reason="inactive"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER
        )

    if not await challenge_service.consume(admin_session, challenge):
        # Spent between the claim and here, so the session it bought is not
        # this request's to open a second time.
        await admin_session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_OTP_INVALID,
        )

    # Arriving at the address is what proves it, so an address the account had
    # never proved is proved now — and what the account held before that goes.
    if challenge.user_email_id is not None:
        first_proof = await addresses.mark_proved(
            admin_session, address_id=challenge.user_email_id
        )
        if first_proof:
            await _retire_credentials_predating_proof(admin_session, user=user)
        row = await admin_session.get(UserEmail, challenge.user_email_id)
        if row is not None:
            row.last_login_at = datetime.now(timezone.utc)
            admin_session.add(row)

    native = email_otp_service.is_native(challenge)
    # The code proved the address; an account holding a second factor still
    # presents it, the same way a password sign-in does.
    if await auth_posture.login_method_allowed(
        session, LoginMethod.totp
    ) and await totp_service.is_enrolled(admin_session, user_id=user_id):
        follow_on = await challenge_service.create(
            admin_session,
            user_id=user_id,
            purpose=(
                challenge_service.ChallengePurpose.sign_in_native
                if native
                else challenge_service.ChallengePurpose.sign_in
            ),
        )
        await admin_session.commit()
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "detail": AuthMessages.TOTP_REQUIRED,
                "challenge": follow_on.value,
            },
        )

    return await open_session(
        request,
        response,
        admin_session,
        user_id=user_id,
        token_version=user.token_version,
        amr=["otp"],
        audit_detail={"method": "email_otp"},
        return_refresh_token=native,
    )

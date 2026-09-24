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
from app.core.email_i18n import SUPPORTED_EMAIL_LOCALES
from app.core.rate_limit import get_real_client_ip, limiter
from app.db.session import get_system_session, get_session
from app.models.platform.user import SIGN_IN_STATUSES, User
from app.models.platform.user_email import UserEmail
from app.schemas.platform.email_otp import (
    EmailOtpRegister,
    EmailOtpSend,
    EmailOtpSent,
    EmailOtpVerify,
)
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
from app.services.stream_authz import authority as stream_authority

logger = logging.getLogger(__name__)

router = APIRouter()

SystemSessionDep = Annotated[AsyncSession, Depends(get_system_session)]
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
    await user_tokens.revoke_user_sessions(session, user=user, commit=False)
    await audit_service.record(
        session,
        event_type=AuditEventType.AUTH_CREDENTIALS_RETIRED,
        actor_user_id=user.id,
        target_user_id=user.id,
        target_type="user",
        target_id=user.id,
        detail={"reason": "address_first_proved"},
    )


def _requested_locale(request: Request) -> str:
    """The language to write to somebody who has no account to have set one.

    The first tag of ``Accept-Language``, narrowed to the languages this
    deployment writes in; English where it names none of them.
    """
    header = request.headers.get("accept-language", "")
    for part in header.split(","):
        tag = part.split(";")[0].strip().lower()[:2]
        if tag in SUPPORTED_EMAIL_LOCALES:
            return tag
    return "en"


async def _registration_open(
    request: Request, session: AsyncSession, *, address: str, invite: str | None
) -> bool:
    """Whether a sign-up at this address would be taken.

    The registration gates, asked here so that a code is only posted where an
    account could follow from it. The captcha among them was answered by the
    route above, and a token is spent by being checked, so it is not asked for
    a second time.

    A refusal is an answer, not an error: the route says the same thing either
    way, and only whether a letter goes out differs.
    """
    from app.api.v1.platform_endpoints.auth import _registration_gate

    try:
        await _registration_gate(
            request,
            session,
            email=address,
            invite=invite,
            captcha_token=None,
            check_captcha=False,
        )
    except HTTPException:
        return False
    return True


@router.post("/email-otp/send", response_model=EmailOtpSent)
@limiter.limit("5/15minutes")
async def send_sign_in_code(
    request: Request,
    payload: EmailOtpSend,
    session: SessionDep,
    system_session: SystemSessionDep,
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
    if not await email_service.email_configured(system_session):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_OTP_CANNOT_SEND,
        )

    address = payload.email.lower().strip()
    user = await addresses.account_holding(system_session, address)
    # An account that cannot sign in is not one to send a code to, and reads
    # from here exactly like an address nobody holds.
    recipient = user if user is not None and user.status in SIGN_IN_STATUSES else None
    row = (
        await addresses.row_for(system_session, address)
        if recipient is not None
        else None
    )
    # An address nobody holds is a sign-up, where this deployment takes one.
    # Asked with the captcha already spent, because it was answered above.
    signing_up = user is None and await _registration_open(
        request, system_session, address=address, invite=payload.invite_code
    )

    issued = await email_otp_service.issue(
        system_session,
        user_id=recipient.id if recipient is not None else None,
        user_email_id=row.id if row is not None else None,
        native=payload.native,
        email=address if signing_up else None,
    )
    minutes = int(email_otp_service.CODE_TTL.total_seconds() // 60)
    try:
        if recipient is not None:
            await email_service.send_sign_in_code_email(
                system_session,
                recipient,
                email=address,
                code=issued.code,
                minutes=minutes,
            )
        elif signing_up:
            await email_service.send_sign_up_code_email(
                system_session,
                email=address,
                code=issued.code,
                minutes=minutes,
                locale=_requested_locale(request),
            )
    except email_service.EmailNotConfiguredError:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_OTP_CANNOT_SEND,
        ) from None
    await system_session.commit()
    return EmailOtpSent(challenge=issued.handle)


@router.post("/email-otp/verify", response_model=Token)
@limiter.limit("10/15minutes")
async def verify_sign_in_code(
    request: Request,
    response: Response,
    payload: EmailOtpVerify,
    session: SessionDep,
    system_session: SystemSessionDep,
) -> Token | Response:
    """Take the code back and open the session it earned."""
    await require_login_method(session, LoginMethod.email_otp)
    challenge = await email_otp_service.claim(
        system_session, handle=payload.challenge, code=payload.code
    )
    if challenge is None:
        # The attempt is counted whether or not the code was any good, so the
        # commit comes before the refusal.
        await system_session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_OTP_INVALID,
        )

    if challenge.user_id is None:
        pending = challenge_service.address_of(challenge)
        if pending is None:
            # A code was asked for at an address nobody holds and no sign-up
            # followed from. There is nothing for it to open.
            await system_session.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=AuthMessages.EMAIL_OTP_INVALID,
            )
        if not await challenge_service.consume(system_session, challenge):
            await system_session.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=AuthMessages.EMAIL_OTP_INVALID,
            )
        ticket = await email_otp_service.issue_ticket(
            system_session,
            email=pending,
            native=email_otp_service.is_native(challenge),
        )
        await system_session.commit()
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"registration_ticket": ticket},
        )

    user_id = challenge.user_id
    user = await system_session.get(User, user_id)
    if user is None or user.status not in SIGN_IN_STATUSES:
        await record_sign_in_failure(
            system_session, user, method="email_otp", reason="inactive"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER
        )

    if not await challenge_service.consume(system_session, challenge):
        # Spent between the claim and here, so the session it bought is not
        # this request's to open a second time.
        await system_session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_OTP_INVALID,
        )

    # Arriving at the address is what proves it, so an address the account had
    # never proved is proved now — and what the account held before that goes.
    retired = False
    if challenge.user_email_id is not None:
        first_proof = await addresses.mark_proved(
            system_session, address_id=challenge.user_email_id
        )
        if first_proof:
            await _retire_credentials_predating_proof(system_session, user=user)
            retired = True
        row = await system_session.get(UserEmail, challenge.user_email_id)
        if row is not None:
            row.last_login_at = datetime.now(timezone.utc)
            system_session.add(row)

    native = email_otp_service.is_native(challenge)
    # The code proved the address; an account holding a second factor still
    # presents it, the same way a password sign-in does.
    if await auth_posture.login_method_allowed(
        session, LoginMethod.totp
    ) and await totp_service.is_enrolled(system_session, user_id=user_id):
        follow_on = await challenge_service.create(
            system_session,
            user_id=user_id,
            purpose=(
                challenge_service.ChallengePurpose.sign_in_native
                if native
                else challenge_service.ChallengePurpose.sign_in
            ),
        )
        await system_session.commit()
        if retired:
            await stream_authority.revoke_user_everywhere(user_id)
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "detail": AuthMessages.TOTP_REQUIRED,
                "challenge": follow_on.value,
            },
        )

    opened = await open_session(
        request,
        response,
        system_session,
        user_id=user_id,
        token_version=user.token_version,
        amr=["otp"],
        audit_detail={"method": "email_otp"},
        return_refresh_token=native,
    )
    if retired:
        # Connections opened on the credentials retired above close now.
        await stream_authority.revoke_user_everywhere(user_id)
    return opened


@router.post(
    "/email-otp/register",
    response_model=Token,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/15minutes")
async def register_with_code(
    request: Request,
    response: Response,
    payload: EmailOtpRegister,
    session: SessionDep,
    system_session: SystemSessionDep,
) -> Token:
    """Make the account a proved address earned, and sign it in.

    The gates are asked again here — the ticket says which address, and
    nothing else about the registration was settled when it was issued. The
    captcha is not among them: it was answered when the code was asked for,
    and a token is spent by being checked.

    The account is made with no password. Its way in is the address it just
    proved; it sets a password afterwards if it wants one.
    """
    from app.api.v1.platform_endpoints.auth import (
        RegistrationDetails,
        _register_account,
    )

    await require_login_method(session, LoginMethod.email_otp)
    ticket = await email_otp_service.claim_ticket(
        system_session, ticket=payload.registration_ticket
    )
    address = challenge_service.address_of(ticket) if ticket is not None else None
    if ticket is None or address is None:
        await system_session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_OTP_INVALID,
        )
    if not await challenge_service.consume(system_session, ticket):
        await system_session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_OTP_INVALID,
        )

    registered = await _register_account(
        request,
        system_session,
        details=RegistrationDetails(
            email=address,
            username=payload.username,
            full_name=payload.full_name,
            timezone=payload.timezone,
        ),
        invite_code=payload.invite_code,
        hashed_password=None,
        check_captcha=False,
        address_proved=True,
    )
    return await open_session(
        request,
        response,
        system_session,
        user_id=registered.user.id,
        token_version=registered.user.token_version,
        amr=["otp"],
        audit_detail={"method": "email_otp", "during": "registration"},
        return_refresh_token=email_otp_service.is_native(ticket),
    )

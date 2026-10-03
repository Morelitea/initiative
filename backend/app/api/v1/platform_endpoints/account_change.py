"""Answering an account letter: "This wasn't me".

Every account notice but a lockout carries a link to a page that reads the
token here, says what it will do, and on confirmation signs the account out
everywhere. The caller holds a token, not a session, so everything runs on the
system engine.
"""

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import SystemSessionDep
from app.core.audit_events import AuditEventType
from app.core.messages import AuthMessages
from app.core.rate_limit import limiter
from app.models.platform.user import User
from app.models.platform.user_token import UserTokenPurpose
from app.schemas.platform.auth import (
    AccountChangeRead,
    AccountChangeToken,
    VerificationSendResponse,
)
from app.services import audit as audit_service
from app.services.content_sockets import sockets as content_sockets
from app.services.platform import user_tokens

router = APIRouter()


def _invalid() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=AuthMessages.INVALID_OR_EXPIRED_TOKEN,
    )


@router.post("/account-change/read", response_model=AccountChangeRead)
@limiter.limit("30/15minutes")
async def read_account_change(
    request: Request,
    payload: AccountChangeToken,
    system_session: SystemSessionDep,
) -> AccountChangeRead:
    """What a link answers, for its page to say before anything is done.
    Reading spends nothing."""
    record = await user_tokens.get_valid_token(
        system_session, token=payload.token, purpose=UserTokenPurpose.account_change
    )
    if record is None:
        raise _invalid()
    return AccountChangeRead(notice=(record.change or {}).get("notice", ""))


@router.post("/account-change/sign-out", response_model=VerificationSendResponse)
@limiter.limit("10/15minutes")
async def sign_out_everywhere(
    request: Request,
    payload: AccountChangeToken,
    system_session: SystemSessionDep,
) -> VerificationSendResponse:
    """Sign the account out of every browser, phone and computer, and turn off
    its API keys. Its password, addresses and other ways in stay as they are.
    The link is spent."""
    record = await user_tokens.consume_token(
        system_session, token=payload.token, purpose=UserTokenPurpose.account_change
    )
    if record is None:
        raise _invalid()
    user = await system_session.get(User, record.user_id)
    if user is None:
        raise _invalid()
    await audit_service.record(
        system_session,
        event_type=AuditEventType.AUTH_SESSION_REVOKED,
        actor_user_id=user.id,
        target_user_id=user.id,
        target_type="auth_session",
        detail={
            "scope": "everywhere",
            "via": "account_notice",
            "notice": (record.change or {}).get("notice"),
        },
    )
    # ``token_version`` is bumped on ``user``, bound to this session, so it
    # lands on the same commit as the revocations and the record.
    await user_tokens.revoke_user_sessions(system_session, user=user, commit=False)
    system_session.add(user)
    await system_session.commit()
    # Open connections stand on the sessions just ended.
    await content_sockets.revoke_user_everywhere(user.id)
    return VerificationSendResponse(status="signed_out")

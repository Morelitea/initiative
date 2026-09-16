from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import UserSessionDep, get_current_active_user
from app.core.auth_context import device_token_id
from app.models.platform.user import User
from app.schemas.platform.push import (
    PushTokenRegisterRequest,
    PushTokenUnregisterRequest,
    PushTokenResponse,
)
from app.services.platform import push_tokens

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_active_user)]


@router.post("/register", response_model=PushTokenResponse)
async def register_push_token(
    session: UserSessionDep,
    current_user: CurrentUser,
    request: PushTokenRegisterRequest,
) -> PushTokenResponse:
    """Register a push notification token for the current user.

    This endpoint registers a new push token or updates an existing one.
    The token will be used to send push notifications to the user's device.

    Which installation the token belongs to is read off the credential that
    made the call, not the body: it is the same handle the device's message key
    store records, and matching the two is what lets a message wake the phone
    that can actually read it.
    """
    await push_tokens.register_push_token(
        session=session,
        user_id=current_user.id,
        push_token=request.push_token,
        platform=request.platform,
        device_token_id=device_token_id(),
    )
    return PushTokenResponse(status="registered")


@router.delete("/unregister", response_model=PushTokenResponse)
async def unregister_push_token(
    session: UserSessionDep,
    current_user: CurrentUser,
    request: PushTokenUnregisterRequest,
) -> PushTokenResponse:
    """Unregister a push notification token.

    This endpoint removes a push token from the database. The device will
    no longer receive push notifications.
    """
    await push_tokens.delete_push_token(
        session, user_id=current_user.id, push_token=request.push_token
    )
    return PushTokenResponse(status="unregistered")

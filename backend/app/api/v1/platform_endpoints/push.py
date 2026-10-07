from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import UserSessionDep, CurrentUser, require_first_party_session
from app.core import auth_context
from app.schemas.platform.push import (
    PushTokenRegisterRequest,
    PushTokenUnregisterRequest,
    PushTokenResponse,
)
from app.core.messages import NotificationMessages
from app.services.platform import app_settings, push_tokens

router = APIRouter()


@router.post("/register", response_model=PushTokenResponse)
async def register_push_token(
    session: UserSessionDep,
    current_user: CurrentUser,
    request: PushTokenRegisterRequest,
    _first_party: Annotated[str, Depends(require_first_party_session)],
) -> PushTokenResponse:
    """Register a push notification token for the current user.

    This endpoint registers a new push token or updates an existing one.
    The token will be used to send push notifications to the user's device.

    Which installation the token belongs to is read off the session that made
    the call, not the body: the device's message key store names the same
    sign-in, and matching the two is what lets a message wake the phone that can
    actually read it. A device is sent to while that sign-in stands, and the app
    registers again each time it starts.
    Only a sign-in registers one: a device receives the account's notifications
    from every community, which is more than any key or app is lent.

    A deployment that has switched push notifications off declines (403) and
    stores nothing: there is nothing for the token to be used for, and holding
    it would be keeping an address this deployment has said it does not send to.
    """
    if not (await app_settings.get_app_settings(session)).push_notifications_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=NotificationMessages.PUSH_DISABLED,
        )
    credential = auth_context.current().session_credential
    await push_tokens.register_push_token(
        session=session,
        user_id=current_user.id,
        push_token=request.push_token,
        platform=request.platform,
        session_id=credential.session_id if credential else None,
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

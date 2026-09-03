"""The direct-message transport: keys in, ciphertext through, nothing kept.

All of it on ``UserSessionDep`` — a platform-tier session, RLS enforced. Every
table these routes touch is own-row for the caller, with two exceptions the
database itself gates: reading another account's public keys, and claiming one
of its prekeys, both only where an accepted message grant already exists.

There is no route that returns a conversation's history, because the server has
none to return. A collected message is deleted; the client is the archive.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status

from app.api.deps import UserSessionDep, get_current_active_user
from app.core.messages import DirectMessageTransportMessages as Messages
from app.core.user_display import handle_of
from app.models.platform.user import User
from app.schemas.platform.dm_transport import (
    DmConversationCreate,
    DmConversationRead,
    DmConversationsResponse,
    DmDeviceRegistration,
    DmDevicesResponse,
    DmOneTimeKeyBatch,
    DmQueueAck,
    DmQueueResponse,
    DmSafetyNumberResponse,
    DmSendRequest,
    DmSendResponse,
    DmSessionKeysResponse,
)
from app.services.platform import dm_notifications, dm_stream
from app.services.platform import dm_transport as service

me_router = APIRouter()
user_router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_active_user)]
TargetUserId = Annotated[int, Path(ge=1)]

#: Every refusal that is about the pair answers the same way, so the endpoint is
#: not a way to learn which of them it was.
_STATUS = {
    Messages.DEVICE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    Messages.CONVERSATION_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    Messages.MALFORMED_KEY: status.HTTP_422_UNPROCESSABLE_CONTENT,
    Messages.DUPLICATE_KEY_ID: status.HTTP_409_CONFLICT,
    Messages.TOO_MANY_KEYS: status.HTTP_409_CONFLICT,
    Messages.NOT_REACHABLE: status.HTTP_409_CONFLICT,
    Messages.CANNOT_MESSAGE_SELF: status.HTTP_409_CONFLICT,
    Messages.MESSAGE_TOO_LARGE: status.HTTP_413_CONTENT_TOO_LARGE,
    Messages.RECIPIENT_QUEUE_FULL: status.HTTP_507_INSUFFICIENT_STORAGE,
}


def _error(exc: service.DmTransportError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS.get(exc.code, status.HTTP_409_CONFLICT),
        detail=exc.code,
    )


@me_router.post(
    "/dm/devices", response_model=DmDevicesResponse, status_code=status.HTTP_201_CREATED
)
async def register_device(
    body: DmDeviceRegistration,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> DmDevicesResponse:
    """Publish this installed client's public keys."""
    try:
        await service.register_device(
            session,
            user_id=current_user.id,
            identity_key=body.identity_key,
            fingerprint_key=body.fingerprint_key,
            fallback_key=body.fallback_key,
            one_time_keys=body.one_time_keys,
            label=body.label,
        )
    except service.DmTransportError as exc:
        raise _error(exc) from exc
    await session.commit()
    return DmDevicesResponse(
        devices=await service.list_devices(session, user_id=current_user.id)
    )


@me_router.get("/dm/devices", response_model=DmDevicesResponse)
async def list_devices(
    session: UserSessionDep, current_user: CurrentUser
) -> DmDevicesResponse:
    return DmDevicesResponse(
        devices=await service.list_devices(session, user_id=current_user.id)
    )


@me_router.delete("/dm/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_device(
    device_id: uuid.UUID,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> Response:
    """Stop encrypted messaging on one device, without signing it out.

    Takes its queued messages with it, which is the one thing that removes an
    undelivered message and is a visible act by the person who owns it.
    """
    try:
        await service.remove_device(
            session, user_id=current_user.id, device_id=device_id
        )
    except service.DmTransportError as exc:
        raise _error(exc) from exc
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.post("/dm/one-time-keys", response_model=DmDevicesResponse)
async def top_up_keys(
    body: DmOneTimeKeyBatch,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> DmDevicesResponse:
    try:
        await service.add_one_time_keys(
            session,
            user_id=current_user.id,
            device_id=body.device_id,
            keys=body.one_time_keys,
        )
    except service.DmTransportError as exc:
        raise _error(exc) from exc
    await session.commit()
    return DmDevicesResponse(
        devices=await service.list_devices(session, user_id=current_user.id)
    )


@user_router.post("/{user_id}/dm/session-keys", response_model=DmSessionKeysResponse)
async def claim_session_keys(
    user_id: TargetUserId,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> DmSessionKeysResponse:
    """Claim what is needed to open a session with each of that account's
    devices.

    A POST rather than a GET because a claim spends a prekey — this writes.
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=Messages.CANNOT_MESSAGE_SELF,
        )
    try:
        devices = await service.claim_session_keys(session, target_id=user_id)
    except service.DmTransportError as exc:
        raise _error(exc) from exc
    await session.commit()
    return DmSessionKeysResponse(user_id=user_id, devices=devices)


@user_router.get("/{user_id}/dm/safety-number", response_model=DmSafetyNumberResponse)
async def safety_number(
    user_id: TargetUserId,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> DmSafetyNumberResponse:
    """Both parties' fingerprints, so the client can render the comparison."""
    try:
        theirs = await service.fingerprints(session, user_id=user_id)
    except service.DmTransportError as exc:
        raise _error(exc) from exc
    if not theirs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=Messages.DEVICE_NOT_FOUND,
        )
    return DmSafetyNumberResponse(
        user_id=user_id,
        their_fingerprints=theirs,
        my_fingerprints=await service.fingerprints(session, user_id=current_user.id),
    )


@me_router.post(
    "/dm/conversations",
    response_model=DmConversationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    body: DmConversationCreate,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> DmConversationRead:
    try:
        conversation = await service.create_conversation(
            session, actor_id=current_user.id, other_id=body.user_id
        )
    except service.DmTransportError as exc:
        raise _error(exc) from exc
    await session.commit()
    return DmConversationRead(
        id=conversation.id,
        other_user_id=body.user_id,
        created_at=conversation.created_at,
    )


@me_router.get("/dm/conversations", response_model=DmConversationsResponse)
async def list_conversations(
    session: UserSessionDep, current_user: CurrentUser
) -> DmConversationsResponse:
    return DmConversationsResponse(
        conversations=await service.list_conversations(session, user_id=current_user.id)
    )


@me_router.delete(
    "/dm/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def leave_conversation(
    conversation_id: uuid.UUID,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> Response:
    try:
        await service.leave_conversation(
            session, user_id=current_user.id, conversation_id=conversation_id
        )
    except service.DmTransportError as exc:
        raise _error(exc) from exc
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.post(
    "/dm/conversations/{conversation_id}/messages", response_model=DmSendResponse
)
async def send_messages(
    conversation_id: uuid.UUID,
    body: DmSendRequest,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> DmSendResponse:
    """Hand the server one already-encrypted copy per destination device."""
    try:
        written, recipient_id = await service.send(
            session,
            user_id=current_user.id,
            conversation_id=conversation_id,
            messages=body.messages,
        )
    except service.DmTransportError as exc:
        raise _error(exc) from exc
    await session.commit()

    # The sender's own tabs always have something to collect; the recipient only
    # where the message actually reached them, and they are never told about the
    # difference.
    await dm_stream.signal_dm(current_user.id)
    if recipient_id is not None:
        await dm_notifications.notify(
            recipient_id=recipient_id,
            sender=current_user,
            sender_name=handle_of(current_user),
            conversation_id=conversation_id,
        )
    return DmSendResponse(accepted=written)


@me_router.get("/dm/queue", response_model=DmQueueResponse)
async def collect_queue(
    device_id: uuid.UUID,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> DmQueueResponse:
    """Everything waiting for one device, oldest first."""
    try:
        items = await service.collect(
            session, user_id=current_user.id, device_id=device_id
        )
    except service.DmTransportError as exc:
        raise _error(exc) from exc
    await session.commit()
    return DmQueueResponse(items=items)


@me_router.post("/dm/queue/ack", status_code=status.HTTP_204_NO_CONTENT)
async def acknowledge_queue(
    body: DmQueueAck,
    session: UserSessionDep,
    current_user: CurrentUser,
) -> Response:
    """Delete what this device has taken."""
    try:
        await service.acknowledge(
            session,
            user_id=current_user.id,
            device_id=body.device_id,
            message_ids=body.message_ids,
        )
    except service.DmTransportError as exc:
        raise _error(exc) from exc
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

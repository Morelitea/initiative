import asyncio
import contextlib
import json
import logging

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import text

from app.api.deps import UserSessionDep, get_current_active_user
from app.core.security import SESSION_COOKIE_NAME
from app.db.session import CONNECTION_RESET_SQL, AsyncSessionLocal
from app.models.platform.user import User
from app.schemas.platform.notification import (
    NotificationCountResponse,
    NotificationListResponse,
    NotificationRead,
)
from app.core.messages import NotificationMessages
from app.services.platform import notification_stream, presence
from app.services.platform import user_notifications as notifications_service
from app.services.platform.ws_auth import authenticate_ws_token

router = APIRouter()
logger = logging.getLogger(__name__)

# Message type for authentication — the same first-frame handshake the guild
# events, queue, counter and collaboration sockets use.
MSG_AUTH = 5

# "Somebody just did something in this tab." One byte, no payload: it says only
# that the person is at their keyboard, which is the whole of what idle needs
# to know. The client throttles it hard, so this is a frame a minute at most.
MSG_ACTIVE = 6

# How long an accepted socket may go without sending that frame. Generous
# against a slow network, short against a socket that will never send one.
AUTH_TIMEOUT_SECONDS = 10.0


@router.get("/", response_model=NotificationListResponse)
async def list_notifications(
    session: UserSessionDep,
    current_user: User = Depends(get_current_active_user),
    limit: int = Query(default=20, ge=1, le=100),
) -> NotificationListResponse:
    notifications, unread_count = await notifications_service.list_notifications(
        session,
        user_id=current_user.id,
        limit=limit,
    )
    return NotificationListResponse(
        notifications=notifications, unread_count=unread_count
    )


@router.get("/unread-count", response_model=NotificationCountResponse)
async def unread_notifications_count(
    session: UserSessionDep,
    current_user: User = Depends(get_current_active_user),
) -> NotificationCountResponse:
    count = await notifications_service.unread_count(session, user_id=current_user.id)
    return NotificationCountResponse(unread_count=count)


@router.post("/{notification_id}/read", response_model=NotificationRead)
async def mark_notification_read(
    notification_id: int,
    session: UserSessionDep,
    current_user: User = Depends(get_current_active_user),
) -> NotificationRead:
    notification = await notifications_service.mark_notification_read(
        session,
        user_id=current_user.id,
        notification_id=notification_id,
    )
    if not notification:
        raise HTTPException(status_code=404, detail=NotificationMessages.NOT_FOUND)
    return NotificationRead.model_validate(notification)


@router.post("/read-all", response_model=NotificationCountResponse)
async def mark_all_notifications_read(
    session: UserSessionDep,
    current_user: User = Depends(get_current_active_user),
) -> NotificationCountResponse:
    await notifications_service.mark_all_notifications_read(
        session, user_id=current_user.id
    )
    count = await notifications_service.unread_count(session, user_id=current_user.id)
    return NotificationCountResponse(unread_count=count)


@router.websocket("/stream")
async def websocket_notifications(websocket: WebSocket):
    """Push channel for the notification bell, scoped to one user.

    Replaces the bell's 30s poll of ``GET /notifications/``. There is no guild
    in the address because the inbox has none: it gathers a user's
    notifications from every guild they are in, and some from no guild at all.

    Protocol: the client sends ``MSG_AUTH`` with ``{"token": "..."}`` as its
    first (binary) frame, exactly as on the guild events socket; web sessions
    may send ``{"token": null}`` and be authenticated from the session cookie.
    After that the server sends id envelopes, and the only thing the client
    sends back is ``MSG_ACTIVE`` — a sign that its person is at the keyboard,
    which is what keeps them from reading as idle. It names nobody: the socket
    already knows whose it is.

    Authorization is connect-time only. The stream says "your inbox changed"
    and never what changed, so the decision that matters is made by the refetch
    it provokes: the REST endpoints above resolve the inbox from
    ``current_user`` on a freshly validated credential. Content-bearing
    channels (collaboration, counters, queues) ride the ``stream_authz`` spine
    with continuous re-authorization instead.

    A socket that never sends its first frame is closed at
    ``AUTH_TIMEOUT_SECONDS`` rather than held open indefinitely.
    """
    await websocket.accept()

    try:
        auth_data = await asyncio.wait_for(
            websocket.receive_bytes(), AUTH_TIMEOUT_SECONDS
        )
        if len(auth_data) < 2 or auth_data[0] != MSG_AUTH:
            logger.warning("Notifications WS: expected MSG_AUTH as first message")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        try:
            auth_payload = json.loads(auth_data[1:].decode())
            token = auth_payload.get("token")
            if not token:
                # Fall back to the session cookie (web sessions after refresh).
                token = websocket.cookies.get(SESSION_COOKIE_NAME)
            if not token:
                raise ValueError("Missing token")
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning(f"Notifications WS: invalid auth payload: {exc}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except asyncio.TimeoutError:
        logger.warning("Notifications WS: no auth frame within the timeout")
        with contextlib.suppress(Exception):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    except WebSocketDisconnect:
        logger.info("Notifications WS: client disconnected before auth")
        return

    # Validate in a SHORT-LIVED session and release it before the keepalive
    # loop — holding one for the socket's lifetime parks a connection
    # idle-in-transaction, whose locks block DDL like guild deletion's DROP
    # SCHEMA. Mirrors the events/queue/counter sockets.
    async with AsyncSessionLocal() as session:
        # Clear any stale GUCs the pooled connection carries (a SET ROLE to a
        # since-dropped guild role would make the auth query error);
        # AsyncSessionLocal skips get_session's per-request reset.
        await session.exec(text(CONNECTION_RESET_SQL))
        user = await authenticate_ws_token(token, session)
        if user is None:
            logger.warning("Notifications WS: auth failed")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        user_id = user.id
        chosen_presence = user.presence

    await notification_stream.stream.connect(
        user_id, websocket, chosen_presence=chosen_presence
    )
    try:
        while True:
            # Awaiting keeps the socket open and surfaces the disconnect; the
            # one frame the client does send is its person's activity.
            frame = await websocket.receive()
            if frame.get("type") == "websocket.disconnect":
                break
            data = frame.get("bytes")
            if data and data[0] == MSG_ACTIVE:
                presence.online.active(user_id)
    except WebSocketDisconnect:
        pass
    except Exception:
        with contextlib.suppress(Exception):
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
    finally:
        # Unconditional, including cancellation (a BaseException, so past both
        # excepts above) — a registry entry left behind would keep sending to a
        # dead socket until the first write failed.
        await notification_stream.stream.disconnect(websocket)

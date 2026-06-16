import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import text

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal, set_rls_context
from app.models.user import User
from app.services import access_grants as access_grants_service
from app.services import guilds as guilds_service
from app.services.realtime import manager
from app.services.ws_auth import authenticate_ws_token

router = APIRouter()
logger = logging.getLogger(__name__)

# Message type for authentication (matches frontend)
MSG_AUTH = 5


async def _user_from_token(token: str, session: AsyncSession) -> Optional[User]:
    """Validate a session JWT or device token and return the user, or None.

    Delegates to the shared ``authenticate_ws_token`` helper so the
    ``token_version`` revocation check stays in lockstep with the HTTP auth
    path and the other realtime WebSocket endpoints (SEC-4).
    """
    return await authenticate_ws_token(token, session)


async def _user_can_access_guild(
    session: AsyncSession, *, user: User, guild_id: int
) -> bool:
    """True if the user may subscribe to ``guild_id``'s event stream.

    A standing guild membership qualifies; so does a currently-live PAM read
    grant for that guild (mirrors how get_guild_membership in deps.py falls back
    to a live grant). RLS context is set first so the membership lookup runs
    against the right guild's policies.
    """
    await set_rls_context(session, user_id=user.id, guild_id=guild_id)
    membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=user.id
    )
    if membership is not None:
        return True
    grant = await access_grants_service.get_live_grant(
        session, user_id=user.id, guild_id=guild_id
    )
    return grant is not None


@router.websocket("/updates")
async def websocket_updates(websocket: WebSocket, guild_id: int):
    """
    WebSocket endpoint for real-time updates, scoped to a single guild.

    The guild comes from the ``/g/{guild_id}`` path segment — a separate socket
    per guild, so different tabs/windows can subscribe to different guilds at
    once. Authentication is done via MSG_AUTH message sent immediately after
    connection, not via URL query parameters (for security - prevents token
    leakage in logs): ``{"token": "..."}``. The server verifies the user
    belongs to (or holds a live PAM grant for) the path-addressed guild and
    only then registers the socket under it, so events never cross the tenancy
    boundary.
    """
    await websocket.accept()

    # Wait for authentication message (must be first message)
    try:
        auth_data = await websocket.receive_bytes()
        if len(auth_data) < 2 or auth_data[0] != MSG_AUTH:
            logger.warning("Events WebSocket: Expected MSG_AUTH as first message")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Parse auth payload
        try:
            auth_payload = json.loads(auth_data[1:].decode())
            token = auth_payload.get("token")
            if not token:
                # Fall back to session cookie (web sessions after page refresh)
                token = websocket.cookies.get(settings.COOKIE_NAME)
            if not token:
                raise ValueError("Missing token")
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"Events WebSocket: Invalid auth payload: {e}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    except WebSocketDisconnect:
        logger.info("Events WebSocket: Client disconnected before auth")
        return

    # Validate the token in a SHORT-LIVED session and release it before the
    # keepalive loop. Holding a request-scoped session for the websocket's whole
    # lifetime keeps a connection idle-in-transaction, whose locks block DDL like
    # DROP SCHEMA (guild deletion). Mirrors the queue/counter websockets.
    async with AsyncSessionLocal() as session:
        # Reset any stale GUCs the pooled connection may carry (e.g. a SET ROLE to
        # a since-dropped guild role would make every query error) before the auth
        # query — AsyncSessionLocal doesn't run get_session's per-request reset.
        await session.execute(
            text(
                "SELECT set_config('role', 'none', false), set_config('search_path', 'public', false)"
            )
        )
        user = await _user_from_token(token, session)
        # Scope the socket to the path-addressed guild — only a member (or live
        # PAM grantee) may subscribe, so events for a guild never reach
        # outsiders. Checked inside this session block: after the ``async with``
        # exits the session would silently re-acquire a pooled connection
        # WITHOUT the GUC reset above.
        authorized = user is not None and await _user_can_access_guild(
            session, user=user, guild_id=guild_id
        )
    if not user:
        logger.warning("Events WebSocket: Auth failed")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if not authorized:
        logger.warning(
            f"Events WebSocket: user {user.id} not authorized for guild {guild_id}"
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(guild_id, websocket)
    logger.info(f"Events WS: user {user.id} subscribed to guild {guild_id}")
    try:
        while True:
            # Keep the connection alive by awaiting incoming messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(guild_id, websocket)
    except Exception:
        await manager.disconnect(guild_id, websocket)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)

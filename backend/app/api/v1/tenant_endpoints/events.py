import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import text
from sqlmodel import select

from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import establish_guild_access, GuildAccessError
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.tenant.initiative import Initiative
from app.models.platform.user import User
from app.services.membership import initiative_scope_clause
from app.services.realtime import manager
from app.services.platform.ws_auth import authenticate_ws_token

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


async def _accessible_initiative_ids(
    session: AsyncSession, *, user_id: int
) -> list[int]:
    """The initiative rooms this user may join in the already-established guild.

    Reuses the single source of truth — ``initiative_scope_clause`` →
    ``public.initiative_access`` — so the rooms a socket joins are exactly the
    initiatives whose content it could read over REST: member initiatives, plus
    every initiative for a guild admin / PAM / break-glass session (those legs
    come free from the GUCs ``establish_guild_access`` set). A guild member who
    is in no initiative joins no rooms and is never poked.
    """
    rows = await session.exec(
        select(Initiative.id).where(initiative_scope_clause(user_id, Initiative.id))
    )
    return list(rows.all())


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
        await session.exec(
            text(
                "SELECT set_config('role', 'none', false), set_config('search_path', 'public', false)"
            )
        )
        user = await _user_from_token(token, session)
        if user is None:
            logger.warning("Events WebSocket: Auth failed")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        # Establish guild access (membership / live PAM / break-glass) through the
        # single entry point, then resolve which initiative rooms this user may
        # join. Both run inside this session block: after the ``async with`` exits
        # the session would silently re-acquire a pooled connection WITHOUT the
        # GUC reset above.
        try:
            await establish_guild_access(session, user, guild_id)
        except GuildAccessError:
            logger.warning(
                f"Events WebSocket: user {user.id} not authorized for guild {guild_id}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        initiative_ids = await _accessible_initiative_ids(session, user_id=user.id)

    # Initiative-scoped subscription: the socket joins exactly the rooms whose
    # content the user can read, so a signal for an initiative never reaches a
    # non-member. (A member of no initiative joins nothing — correct: they have
    # no content to be notified about.)
    await manager.connect(guild_id, initiative_ids, websocket)
    logger.info(
        f"Events WS: user {user.id} joined {len(initiative_ids)} initiative room(s) in guild {guild_id}"
    )
    try:
        while True:
            # Keep the connection alive by awaiting incoming messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:
        await manager.disconnect(websocket)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)

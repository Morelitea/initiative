"""
WebSocket endpoint for real-time document collaboration.

Handles:
- Token-based authentication
- Document permission checks
- Yjs sync protocol
- Awareness (cursor presence)
"""

import json
import logging
from typing import Optional

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import (
    RLSSessionDep,
    SessionDep,
    UploadUserDep,
    establish_guild_access,
    get_current_active_user,
    get_guild_membership,
    GuildAccessError,
    GuildContext,
)
from app.core.config import settings
from app.db.session import AsyncSessionLocal, set_rls_context
from app.models.document import Document
from app.models.resource_grant import ResourceGrant
from app.models.initiative import Initiative, InitiativeMember
from app.models.user import User
from app.services.collaboration import (
    CollaboratorInfo,
    collaboration_manager,
)
from app.services import documents as documents_service
from app.services import permissions as permissions_service
from app.services.stream_authz import authority as stream_authority
from app.services.ws_auth import authenticate_ws_token

router = APIRouter()
logger = logging.getLogger(__name__)

# Message types for the collaboration protocol
MSG_SYNC_STEP1 = 0  # Client requests current state
MSG_SYNC_STEP2 = 1  # Server sends current state
MSG_UPDATE = 2  # Incremental Yjs update
MSG_AWARENESS = 3  # Cursor/selection awareness (JSON)
MSG_AWARENESS_BINARY = 4  # y-protocols awareness (binary, relayed as-is)
MSG_AUTH = 5  # Authentication message (JSON: {token, guild_id})


async def _get_user_from_token(token: str, session) -> Optional[User]:
    """Validate a session JWT or device token and return the user, or None.

    Delegates to the shared ``authenticate_ws_token`` helper so the
    ``token_version`` revocation check stays in lockstep with the HTTP auth
    path and the other realtime WebSocket endpoints (SEC-4).
    """
    return await authenticate_ws_token(token, session)


async def _get_document_with_permissions(
    session,
    document_id: int,
    guild_id: int,
) -> Optional[Document]:
    """Get document with all relationships needed for permission checks."""
    stmt = (
        select(Document)
        .where(Document.id == document_id)
        .options(
            selectinload(Document.initiative)
            .selectinload(Initiative.memberships)
            .selectinload(InitiativeMember.role_ref),
            selectinload(Document.grants).selectinload(ResourceGrant.role),
        )
    )
    result = await session.exec(stmt)
    document = result.one_or_none()

    if not document:
        return None

    # Verify document belongs to a guild the user has access to
    if document.initiative and document.initiative.guild_id != guild_id:
        return None

    return document


@router.websocket("/documents/{document_id}/collaborate")
async def websocket_collaborate(
    websocket: WebSocket,
    guild_id: int,
    document_id: int,
):
    """
    WebSocket endpoint for collaborative document editing.

    Protocol:
    1. Client connects and sends MSG_AUTH with {token} as first message; the
       guild comes from the ``/g/{guild_id}`` path segment
    2. Server validates auth and sends current Yjs state (SYNC_STEP2)
    3. Client sends incremental updates (UPDATE)
    4. Server broadcasts updates to other clients
    5. Awareness messages (AWARENESS) for cursor positions

    Message format (binary):
    - First byte: message type
    - Rest: payload (Yjs update bytes or JSON for awareness)

    Note: This endpoint manages its own database sessions to avoid holding
    connections open for the entire WebSocket lifetime.
    """
    # Must accept WebSocket before we can close it properly
    # If we try to close before accept, the HTTP upgrade never completes
    # and the client sees an abnormal closure (1006)
    await websocket.accept()
    logger.info(f"Collaboration: WebSocket accepted for document {document_id}")

    # Wait for authentication message (must be first message)
    try:
        auth_data = await websocket.receive_bytes()
        if len(auth_data) < 2 or auth_data[0] != MSG_AUTH:
            logger.warning(
                f"Collaboration: Expected MSG_AUTH as first message for document {document_id}"
            )
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
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(
                f"Collaboration: Invalid auth payload for document {document_id}: {e}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    except WebSocketDisconnect:
        logger.info(
            f"Collaboration: Client disconnected before auth for document {document_id}"
        )
        return

    # Authenticate and check permissions using a short-lived session
    async with AsyncSessionLocal() as session:
        user = await _get_user_from_token(token, session)
        if not user:
            logger.warning(f"Collaboration: Auth failed for document {document_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Establish the guild access context through the single entry point —
        # real membership, a live PAM grant, or break-glass — so the document
        # checks below see the *same* context (guild-admin DAC bypass, PAM scope,
        # break-glass elevation, delegation pin) the REST path would. Hand-rolling
        # this here is exactly what let a guild admin be denied on the socket
        # while allowed on the REST read.
        try:
            await establish_guild_access(session, user, guild_id)
        except GuildAccessError:
            logger.warning(
                f"Collaboration: {user.email} has no access to guild {guild_id}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Get document and check permissions
        document = await _get_document_with_permissions(session, document_id, guild_id)
        if not document:
            logger.warning(
                f"Collaboration: Document {document_id} not found or not in guild {guild_id}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Per-document level via the shared DAC engine — guild-admin / break-glass
        # bypass (→ owner), a live PAM grant lifted to its level, or the document's
        # explicit user/role/all-members grants. The active role + grant context
        # was established above, and establish_guild_access already proved guild
        # reach, so the only open question is the document level.
        level = permissions_service.compute_document_permission(document, user.id)
        if level is None:
            logger.warning(
                f"Collaboration: User {user.email} has no read access to document {document_id}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        can_write = level in ("write", "owner")

        # Get or create the document room (needs session for initial load)
        room = await collaboration_manager.get_or_create_room(document_id, session)

    logger.info(f"Collaboration: {user.email} authenticated for document {document_id}")

    # Create collaborator info
    collaborator = CollaboratorInfo(
        user_id=user.id,
        name=user.full_name or user.email,
        websocket=websocket,
        can_write=can_write,
        avatar_url=user.avatar_url,
        avatar_base64=user.avatar_base64,
    )

    # Add to room
    await room.add_collaborator(collaborator)

    # Govern this socket with continuous, every-level re-authorization. A
    # grant / membership / role / PAM change disconnects it — immediately for
    # guild- and initiative-level removal (via revoke_user), within the bounded
    # interval for within-initiative DAC changes. The check re-runs the FULL join
    # (establish_guild_access → load the document under RLS → DAC), so every gate
    # is re-enforced in one place. ``needs_write`` makes a writer who loses write
    # disconnect too (hard-disconnect, no mid-session downgrade), so the stale
    # ``can_write`` below can't outlive the user's actual write access.
    needs_write = can_write

    async def _authorize(check_session, check_user):
        doc = await _get_document_with_permissions(check_session, document_id, guild_id)
        if doc is None:
            return False  # initiative removed (RLS hides it) or document gone
        current = permissions_service.compute_document_permission(doc, check_user.id)
        if current is None:
            return False  # read access revoked
        return not needs_write or current in ("write", "owner")

    await stream_authority.join(
        websocket,
        user,
        guild_id=guild_id,
        initiative_id=document.initiative_id,
        resource_type="document",
        resource_id=document_id,
        authorize=_authorize,
    )

    try:
        # Send initial sync state
        state = room.get_state()
        sync_message = bytes([MSG_SYNC_STEP2]) + state
        logger.info(
            f"Collaboration: Sending initial sync to {user.email}, state size: {len(state)} bytes"
        )
        await websocket.send_bytes(sync_message)

        # Send current collaborator list
        collaborators_message = json.dumps(
            {
                "type": "collaborators",
                "data": room.get_collaborator_list(),
            }
        ).encode()
        await websocket.send_bytes(bytes([MSG_AWARENESS]) + collaborators_message)

        # Broadcast that a new user joined
        await room.broadcast_awareness(
            {
                "type": "join",
                "user": {
                    "user_id": user.id,
                    "name": collaborator.name,
                    "avatar_url": user.avatar_url,
                    "avatar_base64": user.avatar_base64,
                },
            },
            origin_user_id=user.id,
        )

        # Main message loop
        while True:
            data = await websocket.receive_bytes()
            if len(data) < 1:
                continue

            msg_type = data[0]
            payload = data[1:]

            if msg_type == MSG_SYNC_STEP1:
                # Client requesting sync with their state vector
                # Use state vector to compute diff - only send updates client is missing
                logger.info(
                    f"Collaboration: Received SYNC_STEP1 from {user.email}, state vector size: {len(payload)}"
                )
                state = room.get_state_diff(payload) if payload else room.get_state()
                sync_message = bytes([MSG_SYNC_STEP2]) + state
                logger.info(
                    f"Collaboration: Sending SYNC_STEP2 to {user.email}, diff size: {len(state)}"
                )
                await websocket.send_bytes(sync_message)

            elif msg_type == MSG_UPDATE:
                # Yjs update from client
                if not can_write:
                    logger.warning(
                        f"Collaboration: Read-only user {user.email} tried to send update"
                    )
                    continue

                try:
                    logger.info(
                        f"Collaboration: Received MSG_UPDATE from {user.email}, payload size: {len(payload)}"
                    )
                    room.apply_update(payload, origin=user.id)
                    logger.info(
                        f"Collaboration: Applied update, broadcasting to {len(room.collaborators) - 1} other clients"
                    )
                    # Broadcast to other clients
                    await room.broadcast_update(
                        bytes([MSG_UPDATE]) + payload,
                        origin_user_id=user.id,
                    )
                except Exception as e:
                    logger.warning(f"Failed to apply Yjs update: {e}")

            elif msg_type == MSG_AWARENESS:
                # Awareness update (cursor position, etc.) - JSON format
                try:
                    awareness_data = json.loads(payload.decode())
                    collaborator.cursor_position = awareness_data.get("cursor")
                    await room.broadcast_awareness(
                        {"type": "cursor", "user_id": user.id, **awareness_data},
                        origin_user_id=user.id,
                    )
                except json.JSONDecodeError:
                    pass

            elif msg_type == MSG_AWARENESS_BINARY:
                # y-protocols awareness update - relay as-is to other clients
                logger.debug(
                    f"Collaboration: Relaying awareness update from {user.email}, size: {len(payload)}"
                )
                await room.broadcast_update(
                    bytes([MSG_AWARENESS_BINARY]) + payload,
                    origin_user_id=user.id,
                )

    except WebSocketDisconnect:
        logger.info(
            f"Collaboration: {user.email} disconnected from document {document_id}"
        )
    except Exception as e:
        logger.error(
            f"Collaboration error for {user.email} on document {document_id}: {e}"
        )
    finally:
        # Stop governing this socket (idempotent if the spine already closed it).
        await stream_authority.leave(websocket)

        # Remove from room
        await room.remove_collaborator(user.id)

        # Broadcast that user left
        await room.broadcast_awareness(
            {"type": "leave", "user_id": user.id},
            origin_user_id=user.id,
        )

        # Persist and potentially clean up room (using a new short-lived session)
        async with AsyncSessionLocal() as session:
            await set_rls_context(session, user_id=user.id, guild_id=guild_id)
            await collaboration_manager.persist_room(document_id, session)
        await collaboration_manager.remove_room(document_id)


@router.get("/documents/{document_id}/collaborators")
async def get_document_collaborators(
    document_id: int,
    session: RLSSessionDep,
    _current_user: Annotated[User, Depends(get_current_active_user)],
    _guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> list[dict]:
    """Get the list of current collaborators on a document."""
    room = collaboration_manager.get_room(document_id)
    if not room:
        return []
    return room.get_collaborator_list()


@router.post("/documents/{document_id}/sync-content")
async def sync_document_content(
    document_id: int,
    guild_id: int,
    request: Request,
    session: SessionDep,
    user: UploadUserDep,
):
    """
    Sync Lexical content from the frontend to the database.

    Called via a ``keepalive`` fetch on page unload to keep the content column
    in sync with yjs_state. Authenticates with the same header-less scheme as
    ``/uploads/*`` and document downloads (``UploadUserDep``): the HttpOnly
    session cookie on web, a short-lived uploads-scoped ``?token=`` on native —
    so the long-lived session JWT never rides in a URL (SEC-12), unlike the
    earlier ``?token=<session jwt>`` version. The guild comes from the
    ``/g/{guild_id}`` path — the document being synced was open inside it.

    The request body should contain the Lexical serialized state as JSON.
    """
    # Parse the JSON body (the keepalive fetch sends a raw body)
    try:
        content = await request.json()
    except Exception as e:
        logger.warning(f"Sync content: Failed to parse JSON body: {e}")
        return {"status": "error", "message": "Invalid JSON body"}

    # Establish the guild access context through the single entry point (same as
    # the REST path and the collaboration socket). The path is only a selector;
    # this validates real membership / a live PAM grant / break-glass and applies
    # the full RLS + role + grant context. Previously this endpoint did a
    # membership-only check, so a break-glass admin or PAM grantee couldn't sync.
    try:
        await establish_guild_access(session, user, guild_id)
    except GuildAccessError:
        logger.warning(
            f"Sync content: user {user.id} has no access to guild {guild_id}"
        )
        return {"status": "error", "message": "No guild access"}

    # Get document and check write permission
    document = await _get_document_with_permissions(session, document_id, guild_id)
    if not document:
        logger.warning(f"Sync content: Document {document_id} not found")
        return {"status": "error", "message": "Document not found"}

    # Write level via the shared DAC engine (guild-admin / break-glass / PAM /
    # explicit grants), against the context establish_guild_access set above.
    level = permissions_service.compute_document_permission(document, user.id)
    if level not in ("write", "owner"):
        logger.warning(
            f"Sync content: User {user.email} has no write access to document {document_id}"
        )
        return {"status": "error", "message": "No write access"}

    # Update the content column
    try:
        # Sync wikilinks to document_links table, and fix any stale wikilinks
        # that point to deleted documents
        fixed_content = await documents_service.sync_document_links(
            session,
            document_id=document_id,
            content=content,
            guild_id=guild_id,
            fix_content=True,
        )
        # Use the fixed content if wikilinks were corrected, otherwise use original
        document.content = fixed_content if fixed_content else content
        session.add(document)
        await session.commit()
        logger.info(
            f"Sync content: Updated content for document {document_id} by {user.email}"
        )
        return {"status": "ok"}
    except Exception as e:
        # Log the full error server-side; return a generic message so internal
        # detail (e.g. DB error text) isn't exposed to the caller.
        logger.error(f"Sync content: Failed to update document {document_id}: {e}")
        await session.rollback()
        return {"status": "error", "message": "Failed to sync content"}

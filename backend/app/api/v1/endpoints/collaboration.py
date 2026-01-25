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

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect, status
from jose import JWTError, jwt
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import SessionDep
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.document import Document, DocumentPermissionLevel
from app.models.guild import GuildMembership, GuildRole
from app.models.initiative import Initiative, InitiativeRole
from app.models.user import User
from app.schemas.token import TokenPayload
from app.services.collaboration import (
    CollaboratorInfo,
    collaboration_manager,
)

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
    """Validate JWT token and return the user."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        token_data = TokenPayload(**payload)
    except JWTError:
        return None

    if not token_data.sub:
        return None

    statement = select(User).where(User.id == int(token_data.sub))
    result = await session.exec(statement)
    user = result.one_or_none()

    if not user or not user.is_active:
        return None

    return user


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
            selectinload(Document.initiative).selectinload(Initiative.memberships),
            selectinload(Document.permissions),
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


async def _check_document_access(
    session,
    document: Document,
    user: User,
    guild_id: int,
) -> tuple[bool, bool]:
    """
    Check if user has access to the document.

    Returns:
        (can_read, can_write)
    """
    # Get guild membership
    stmt = select(GuildMembership).where(
        GuildMembership.guild_id == guild_id,
        GuildMembership.user_id == user.id,
    )
    result = await session.exec(stmt)
    guild_membership = result.one_or_none()

    if not guild_membership:
        return False, False

    # Guild admins have full access
    if guild_membership.role == GuildRole.admin:
        return True, True

    # Check initiative membership
    initiative_memberships = getattr(document.initiative, "memberships", []) or []
    user_initiative_membership = next(
        (m for m in initiative_memberships if m.user_id == user.id),
        None,
    )

    if not user_initiative_membership:
        return False, False

    # Initiative managers have full write access
    if user_initiative_membership.role == InitiativeRole.project_manager:
        return True, True

    # Check explicit document permissions
    permissions = getattr(document, "permissions", []) or []
    has_write_permission = any(
        p.user_id == user.id and p.level == DocumentPermissionLevel.write
        for p in permissions
    )

    # All initiative members can read
    return True, has_write_permission


@router.websocket("/documents/{document_id}/collaborate")
async def websocket_collaborate(
    websocket: WebSocket,
    document_id: int,
):
    """
    WebSocket endpoint for collaborative document editing.

    Protocol:
    1. Client connects and sends MSG_AUTH with {token, guild_id} as first message
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
            logger.warning(f"Collaboration: Expected MSG_AUTH as first message for document {document_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Parse auth payload
        try:
            auth_payload = json.loads(auth_data[1:].decode())
            token = auth_payload.get("token")
            guild_id = auth_payload.get("guild_id")
            if not token or not guild_id:
                raise ValueError("Missing token or guild_id")
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Collaboration: Invalid auth payload for document {document_id}: {e}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    except WebSocketDisconnect:
        logger.info(f"Collaboration: Client disconnected before auth for document {document_id}")
        return

    # Authenticate and check permissions using a short-lived session
    async with AsyncSessionLocal() as session:
        user = await _get_user_from_token(token, session)
        if not user:
            logger.warning(f"Collaboration: Auth failed for document {document_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Get document and check permissions
        document = await _get_document_with_permissions(session, document_id, guild_id)
        if not document:
            logger.warning(f"Collaboration: Document {document_id} not found or not in guild {guild_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        can_read, can_write = await _check_document_access(session, document, user, guild_id)
        if not can_read:
            logger.warning(f"Collaboration: User {user.email} has no read access to document {document_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Get or create the document room (needs session for initial load)
        room = await collaboration_manager.get_or_create_room(document_id, session)

    logger.info(f"Collaboration: {user.email} authenticated for document {document_id}")

    # Create collaborator info
    collaborator = CollaboratorInfo(
        user_id=user.id,
        name=user.full_name or user.email,
        websocket=websocket,
        can_write=can_write,
    )

    # Add to room
    await room.add_collaborator(collaborator)

    try:
        # Send initial sync state
        state = room.get_state()
        sync_message = bytes([MSG_SYNC_STEP2]) + state
        logger.info(f"Collaboration: Sending initial sync to {user.email}, state size: {len(state)} bytes")
        await websocket.send_bytes(sync_message)

        # Send current collaborator list
        collaborators_message = json.dumps({
            "type": "collaborators",
            "data": room.get_collaborator_list(),
        }).encode()
        await websocket.send_bytes(bytes([MSG_AWARENESS]) + collaborators_message)

        # Broadcast that a new user joined
        await room.broadcast_awareness(
            {"type": "join", "user": {"user_id": user.id, "name": collaborator.name}},
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
                logger.info(f"Collaboration: Received SYNC_STEP1 from {user.email}, state vector size: {len(payload)}")
                state = room.get_state()
                sync_message = bytes([MSG_SYNC_STEP2]) + state
                logger.info(f"Collaboration: Sending SYNC_STEP2 to {user.email}, state size: {len(state)}")
                await websocket.send_bytes(sync_message)

            elif msg_type == MSG_UPDATE:
                # Yjs update from client
                if not can_write:
                    logger.warning(f"Collaboration: Read-only user {user.email} tried to send update")
                    continue

                try:
                    logger.info(f"Collaboration: Received MSG_UPDATE from {user.email}, payload size: {len(payload)}")
                    room.apply_update(payload, origin=user.id)
                    logger.info(f"Collaboration: Applied update, broadcasting to {len(room.collaborators) - 1} other clients")
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
                logger.debug(f"Collaboration: Relaying awareness update from {user.email}, size: {len(payload)}")
                await room.broadcast_update(
                    bytes([MSG_AWARENESS_BINARY]) + payload,
                    origin_user_id=user.id,
                )

    except WebSocketDisconnect:
        logger.info(f"Collaboration: {user.email} disconnected from document {document_id}")
    except Exception as e:
        logger.error(f"Collaboration error for {user.email} on document {document_id}: {e}")
    finally:
        # Remove from room
        await room.remove_collaborator(user.id)

        # Broadcast that user left
        await room.broadcast_awareness(
            {"type": "leave", "user_id": user.id},
            origin_user_id=user.id,
        )

        # Persist and potentially clean up room (using a new short-lived session)
        async with AsyncSessionLocal() as session:
            await collaboration_manager.persist_room(document_id, session)
        await collaboration_manager.remove_room(document_id)


@router.get("/documents/{document_id}/collaborators")
async def get_document_collaborators(
    document_id: int,
    session: SessionDep,
) -> list[dict]:
    """Get the list of current collaborators on a document."""
    room = collaboration_manager.get_room(document_id)
    if not room:
        return []
    return room.get_collaborator_list()


@router.post("/documents/{document_id}/sync-content")
async def sync_document_content(
    document_id: int,
    request: Request,
    session: SessionDep,
    token: str = Query(...),
    guild_id: int = Query(...),
):
    """
    Sync Lexical content from the frontend to the database.

    This endpoint is called via navigator.sendBeacon when the page unloads
    to ensure the content column stays in sync with yjs_state.

    The request body should contain the Lexical serialized state as JSON.
    """
    # Parse the JSON body (sendBeacon sends raw body)
    try:
        content = await request.json()
    except Exception as e:
        logger.warning(f"Sync content: Failed to parse JSON body: {e}")
        return {"status": "error", "message": "Invalid JSON body"}

    # Authenticate
    user = await _get_user_from_token(token, session)
    if not user:
        logger.warning(f"Sync content: Auth failed for document {document_id}")
        return {"status": "error", "message": "Authentication failed"}

    # Get document and check write permission
    document = await _get_document_with_permissions(session, document_id, guild_id)
    if not document:
        logger.warning(f"Sync content: Document {document_id} not found")
        return {"status": "error", "message": "Document not found"}

    can_read, can_write = await _check_document_access(session, document, user, guild_id)
    if not can_write:
        logger.warning(f"Sync content: User {user.email} has no write access to document {document_id}")
        return {"status": "error", "message": "No write access"}

    # Update the content column
    try:
        document.content = content
        session.add(document)
        await session.commit()
        logger.info(f"Sync content: Updated content for document {document_id} by {user.email}")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Sync content: Failed to update document {document_id}: {e}")
        await session.rollback()
        return {"status": "error", "message": str(e)}

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

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError, jwt
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import SessionDep
from app.core.config import settings
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
MSG_AWARENESS = 3  # Cursor/selection awareness


async def _get_user_from_token(token: str, session: SessionDep) -> Optional[User]:
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
    session: SessionDep,
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
    session: SessionDep,
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
    session: SessionDep,
    token: str = Query(...),
    guild_id: int = Query(...),
):
    """
    WebSocket endpoint for collaborative document editing.

    Protocol:
    1. Client connects with JWT token and guild_id
    2. Server validates auth and sends current Yjs state (SYNC_STEP2)
    3. Client sends incremental updates (UPDATE)
    4. Server broadcasts updates to other clients
    5. Awareness messages (AWARENESS) for cursor positions

    Message format (binary):
    - First byte: message type
    - Rest: payload (Yjs update bytes or JSON for awareness)
    """
    # Authenticate
    user = await _get_user_from_token(token, session)
    if not user:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Get document and check permissions
    document = await _get_document_with_permissions(session, document_id, guild_id)
    if not document:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    can_read, can_write = await _check_document_access(session, document, user, guild_id)
    if not can_read:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Accept the WebSocket connection
    await websocket.accept()
    logger.info(f"Collaboration: {user.email} connected to document {document_id}")

    # Get or create the document room
    room = await collaboration_manager.get_or_create_room(document_id, session)

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
                # Client requesting sync
                state = room.get_state()
                sync_message = bytes([MSG_SYNC_STEP2]) + state
                await websocket.send_bytes(sync_message)

            elif msg_type == MSG_UPDATE:
                # Yjs update from client
                if not can_write:
                    # Read-only users can't send updates
                    continue

                try:
                    room.apply_update(payload, origin=user.id)
                    # Broadcast to other clients
                    await room.broadcast_update(
                        bytes([MSG_UPDATE]) + payload,
                        origin_user_id=user.id,
                    )
                except Exception as e:
                    logger.warning(f"Failed to apply Yjs update: {e}")

            elif msg_type == MSG_AWARENESS:
                # Awareness update (cursor position, etc.)
                try:
                    awareness_data = json.loads(payload.decode())
                    collaborator.cursor_position = awareness_data.get("cursor")
                    await room.broadcast_awareness(
                        {"type": "cursor", "user_id": user.id, **awareness_data},
                        origin_user_id=user.id,
                    )
                except json.JSONDecodeError:
                    pass

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

        # Persist and potentially clean up room
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

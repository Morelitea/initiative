"""
Real-time document collaboration service using Yjs (via pycrdt).

This module manages collaborative editing sessions:
- DocumentRoom: In-memory Yjs document with connected clients
- Persistence: Load/save Yjs state to PostgreSQL
- Awareness: Track connected users and cursor positions
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket
from pycrdt import Doc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.document import Document

logger = logging.getLogger(__name__)


class CollaboratorInfo:
    """Information about a connected collaborator."""

    def __init__(
        self,
        user_id: int,
        name: str,
        websocket: WebSocket,
        can_write: bool = False,
    ):
        self.user_id = user_id
        self.name = name
        self.websocket = websocket
        self.can_write = can_write
        self.cursor_position: Optional[Dict[str, Any]] = None
        self.connected_at = datetime.now(timezone.utc)


class DocumentRoom:
    """
    Manages a collaborative editing session for a single document.

    Handles:
    - Yjs document state
    - Connected collaborators
    - Broadcasting updates
    - Awareness (cursor positions)
    """

    def __init__(self, document_id: int):
        self.document_id = document_id
        self.doc = Doc()
        self.collaborators: Dict[int, CollaboratorInfo] = {}
        self._lock = asyncio.Lock()
        self._initialized = False
        self._pending_updates: list[bytes] = []

    async def initialize_from_db(self, yjs_state: Optional[bytes], lexical_content: Optional[dict]) -> None:
        """Initialize the Y.Doc from database state.

        Note: We don't try to convert Lexical content to Yjs here because Lexical's
        Yjs binding uses a specific structure that's complex to recreate server-side.
        Instead, the frontend handles migration via CollaborationPlugin's shouldBootstrap
        and initialEditorState props.
        """
        async with self._lock:
            if self._initialized:
                return

            if yjs_state:
                # Restore from existing Yjs state
                try:
                    self.doc.apply_update(yjs_state)
                    logger.info(f"Document {self.document_id}: restored from Yjs state")
                except Exception as e:
                    logger.warning(f"Document {self.document_id}: failed to restore Yjs state: {e}")
            else:
                # First time collaborative edit - Yjs doc starts empty
                # Frontend will bootstrap with existing Lexical content via initialEditorState
                logger.info(f"Document {self.document_id}: no Yjs state, frontend will bootstrap")

            self._initialized = True

    def get_state(self) -> bytes:
        """Get the current Y.Doc state as an update that can be applied by clients."""
        # get_update() with empty state vector returns the full document as an update
        # This is compatible with JavaScript Yjs's Y.applyUpdate()
        return bytes(self.doc.get_update())

    def get_state_diff(self, state_vector: bytes) -> bytes:
        """Get only the updates the client is missing based on their state vector.

        This is more efficient than get_state() when the client already has
        some of the document state.
        """
        if not state_vector:
            return self.get_state()
        return bytes(self.doc.get_update(state_vector))

    def apply_update(self, update: bytes, origin: Optional[int] = None) -> None:
        """Apply a Yjs update from a client."""
        self.doc.apply_update(update)

    async def add_collaborator(self, collaborator: CollaboratorInfo) -> None:
        """Add a collaborator to the room."""
        async with self._lock:
            self.collaborators[collaborator.user_id] = collaborator
            logger.info(
                f"Document {self.document_id}: {collaborator.name} joined "
                f"(total: {len(self.collaborators)})"
            )

    async def remove_collaborator(self, user_id: int) -> None:
        """Remove a collaborator from the room."""
        async with self._lock:
            if user_id in self.collaborators:
                collaborator = self.collaborators.pop(user_id)
                logger.info(
                    f"Document {self.document_id}: {collaborator.name} left "
                    f"(total: {len(self.collaborators)})"
                )

    async def broadcast_update(self, update: bytes, origin_user_id: Optional[int] = None) -> None:
        """Broadcast a Yjs update to all collaborators except the origin."""
        async with self._lock:
            collaborators = list(self.collaborators.values())

        sent_count = 0
        for collaborator in collaborators:
            if collaborator.user_id == origin_user_id:
                continue
            try:
                # Send as binary WebSocket message
                await collaborator.websocket.send_bytes(update)
                sent_count += 1
                logger.info(
                    f"Document {self.document_id}: sent update ({len(update)} bytes) to {collaborator.name}"
                )
            except Exception as e:
                logger.warning(
                    f"Document {self.document_id}: failed to send update to "
                    f"{collaborator.name}: {e}"
                )

        logger.info(f"Document {self.document_id}: broadcast complete, sent to {sent_count} clients")

    async def broadcast_awareness(self, awareness_data: dict, origin_user_id: Optional[int] = None) -> None:
        """Broadcast awareness (cursor, selection) updates."""
        async with self._lock:
            collaborators = list(self.collaborators.values())

        # Message format: [MSG_AWARENESS byte] + JSON payload
        # Must include the type prefix for frontend to process correctly
        MSG_AWARENESS = 3
        json_payload = json.dumps({"type": "awareness", "data": awareness_data}).encode()
        message = bytes([MSG_AWARENESS]) + json_payload

        for collaborator in collaborators:
            if collaborator.user_id == origin_user_id:
                continue
            try:
                await collaborator.websocket.send_bytes(message)
            except Exception:
                pass  # Ignore send errors for awareness

    def get_collaborator_list(self) -> list[dict]:
        """Get list of current collaborators for awareness."""
        return [
            {
                "user_id": c.user_id,
                "name": c.name,
                "can_write": c.can_write,
                "cursor": c.cursor_position,
            }
            for c in self.collaborators.values()
        ]

    def is_empty(self) -> bool:
        """Check if the room has no collaborators (non-locking, for quick checks)."""
        return len(self.collaborators) == 0

    async def is_empty_locked(self) -> bool:
        """Check if the room has no collaborators (with lock for safe concurrent access)."""
        async with self._lock:
            return len(self.collaborators) == 0


class CollaborationManager:
    """
    Manages all active document collaboration rooms.

    Handles:
    - Room lifecycle (create, destroy)
    - Persistence scheduling
    - Global state tracking
    """

    def __init__(self):
        self._rooms: Dict[int, DocumentRoom] = {}
        self._lock = asyncio.Lock()
        self._persistence_interval = 30  # seconds
        self._persistence_task: Optional[asyncio.Task] = None

    async def get_or_create_room(
        self,
        document_id: int,
        session: AsyncSession,
    ) -> DocumentRoom:
        """Get an existing room or create a new one."""
        async with self._lock:
            if document_id not in self._rooms:
                room = DocumentRoom(document_id)

                # Load document from database
                stmt = select(Document).where(Document.id == document_id)
                result = await session.exec(stmt)
                document = result.one_or_none()

                if document:
                    await room.initialize_from_db(
                        yjs_state=document.yjs_state,
                        lexical_content=document.content,
                    )

                self._rooms[document_id] = room
                logger.info(f"Created collaboration room for document {document_id}")

            return self._rooms[document_id]

    async def remove_room(self, document_id: int) -> None:
        """Remove a room if it exists and is empty.

        Uses two-phase check to prevent race condition where a collaborator
        joins between checking is_empty() and deleting the room.
        """
        async with self._lock:
            room = self._rooms.get(document_id)
            if not room:
                return
            # Acquire room lock to ensure no collaborator is joining concurrently
            # This prevents the race where add_collaborator runs between our check and delete
            async with room._lock:
                if room.is_empty():
                    del self._rooms[document_id]
                    logger.info(f"Removed empty collaboration room for document {document_id}")

    async def persist_room(self, document_id: int, session: AsyncSession) -> None:
        """Persist the current room state to the database."""
        # Capture state while holding the lock to ensure consistency
        async with self._lock:
            room = self._rooms.get(document_id)
            if not room:
                return
            # Get state snapshot while holding lock to prevent concurrent modifications
            state = room.get_state()

        # Database operations can happen outside the lock
        try:
            stmt = select(Document).where(Document.id == document_id)
            result = await session.exec(stmt)
            document = result.one_or_none()

            if document:
                document.yjs_state = state
                document.yjs_updated_at = datetime.now(timezone.utc)
                session.add(document)
                await session.commit()
                logger.debug(f"Persisted Yjs state for document {document_id}")
        except Exception as e:
            logger.error(f"Failed to persist Yjs state for document {document_id}: {e}")
            await session.rollback()

    def get_active_rooms(self) -> Set[int]:
        """Get the set of document IDs with active rooms."""
        return set(self._rooms.keys())

    def get_room(self, document_id: int) -> Optional[DocumentRoom]:
        """Get a room without creating it."""
        return self._rooms.get(document_id)

    def has_active_collaborators(self, document_id: int) -> bool:
        """Check if a document has active collaborators."""
        room = self._rooms.get(document_id)
        return room is not None and not room.is_empty()


# Global collaboration manager instance
collaboration_manager = CollaborationManager()

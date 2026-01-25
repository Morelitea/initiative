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
from pycrdt import Doc, Text
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

    @property
    def content(self) -> Text:
        """Get the shared text content from the Y.Doc."""
        return self.doc.get("content", type=Text)

    async def initialize_from_db(self, yjs_state: Optional[bytes], lexical_content: Optional[dict]) -> None:
        """Initialize the Y.Doc from database state or Lexical content."""
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
                    # Fall back to Lexical content
                    self._init_from_lexical(lexical_content)
            else:
                # First time collaborative edit - convert from Lexical
                self._init_from_lexical(lexical_content)

            self._initialized = True

    def _init_from_lexical(self, lexical_content: Optional[dict]) -> None:
        """Initialize Y.Doc from Lexical JSON state (one-time migration)."""
        if not lexical_content:
            return

        # Extract plain text from Lexical state for initial Yjs content
        # The frontend will handle full Lexical <-> Yjs binding
        try:
            text_content = self._extract_text_from_lexical(lexical_content)
            if text_content:
                self.content += text_content
                logger.info(f"Document {self.document_id}: initialized from Lexical content")
        except Exception as e:
            logger.warning(f"Document {self.document_id}: failed to extract Lexical text: {e}")

    def _extract_text_from_lexical(self, state: dict) -> str:
        """Extract plain text from Lexical editor state."""
        texts = []

        def extract_from_node(node: dict) -> None:
            if node.get("type") == "text":
                texts.append(node.get("text", ""))
            elif node.get("type") == "linebreak":
                texts.append("\n")
            children = node.get("children", [])
            for child in children:
                extract_from_node(child)
            # Add paragraph breaks
            if node.get("type") in ("paragraph", "heading", "quote"):
                texts.append("\n")

        root = state.get("root", {})
        extract_from_node(root)
        return "".join(texts).strip()

    def get_state(self) -> bytes:
        """Get the current Y.Doc state as bytes."""
        return self.doc.get_state()

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

        for collaborator in collaborators:
            if collaborator.user_id == origin_user_id:
                continue
            try:
                # Send as binary WebSocket message
                await collaborator.websocket.send_bytes(update)
            except Exception as e:
                logger.warning(
                    f"Document {self.document_id}: failed to send update to "
                    f"{collaborator.name}: {e}"
                )

    async def broadcast_awareness(self, awareness_data: dict, origin_user_id: Optional[int] = None) -> None:
        """Broadcast awareness (cursor, selection) updates."""
        async with self._lock:
            collaborators = list(self.collaborators.values())

        message = json.dumps({"type": "awareness", "data": awareness_data}).encode()

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
        """Check if the room has no collaborators."""
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
        """Remove a room if it exists and is empty."""
        async with self._lock:
            room = self._rooms.get(document_id)
            if room and room.is_empty():
                del self._rooms[document_id]
                logger.info(f"Removed empty collaboration room for document {document_id}")

    async def persist_room(self, document_id: int, session: AsyncSession) -> None:
        """Persist the current room state to the database."""
        async with self._lock:
            room = self._rooms.get(document_id)
            if not room:
                return

        try:
            state = room.get_state()
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

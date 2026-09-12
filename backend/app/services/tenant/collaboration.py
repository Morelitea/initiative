"""
Real-time document collaboration service using Yjs (via pycrdt).

A room is the Yjs document plus its persistence. It deliberately does **not**
keep a list of who is connected: that register lives once, in
:mod:`app.services.stream_authz`, keyed by socket. A channel that keeps its own
copy has to keep the two in step, and the moment they disagree — which is every
time one account opens a second tab — delivery and authorization stop matching
the sockets that actually exist.
"""

import asyncio
import json
import logging
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set, Tuple

from pycrdt import Doc
from sqlalchemy import update as sa_update
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.db.session import AsyncSessionLocal, set_rls_context
from app.models.tenant.document import Document
from app.services.stream_authz import authority as stream_authority

logger = logging.getLogger(__name__)

# The spine's room namespace for this channel. Rooms there are
# (guild_id, resource_type, resource_id); documents claim "document".
RESOURCE_TYPE = "document"


class DocumentRoom:
    """The live Yjs state of one document, and what it owes the database.

    Holds the merged ``Doc`` every connection reads and writes, the JSON
    ``content`` an editor last reported for it, and enough bookkeeping to know
    whether either has moved since it was last written down.
    """

    def __init__(self, guild_id: int, document_id: int):
        self.guild_id = guild_id
        self.document_id = document_id
        self.doc = Doc()
        self._lock = asyncio.Lock()
        self._initialized = False
        # Reading this room's state out of the database is the one slow thing a
        # room does, and it happens once. It gets a lock of its own so it is not
        # done under the lock the registry uses.
        self._load_lock = asyncio.Lock()
        self._loaded = False
        # One writer at a time. A sweep and a disconnect can reach the same
        # room together, and the row must end up holding the newer of the two
        # snapshots rather than whichever commits last.
        self._write_lock = asyncio.Lock()
        # Connections that have been handed this room but have not yet reached
        # the register. They are on their way in, so the room is not idle.
        self._holds = 0
        # The connection whose update the document currently reflects. A
        # rendering of the document is only current if it came from the tab
        # that last moved it.
        self._last_writer: Any = None
        # A room dropped from the registry. Nothing should reach one — the
        # registry only drops rooms with no connections — but a write that does
        # would go nowhere, so it says so instead of swallowing it.
        self.detached = False
        # Revisions, not a boolean: a write serializes a snapshot and then
        # commits, and an edit landing in between must not be marked saved.
        self._revision = 0
        self._persisted_revision = 0
        self._content: Optional[dict] = None
        # The revision the held rendering was made from. Below ``_revision``
        # means the document has moved since, and a live tab has a newer
        # rendering on the way.
        self._content_revision = -1

    @property
    def is_loaded(self) -> bool:
        """Whether this room has had its one read of the database."""
        return self._loaded

    @property
    def is_dirty(self) -> bool:
        """Whether anything has changed since the last successful write."""
        return self._revision != self._persisted_revision

    def connection_count(self) -> int:
        """How many sockets are in this room, asked of the one register."""
        return stream_authority.room_size(
            self.guild_id, RESOURCE_TYPE, self.document_id
        )

    def is_empty(self) -> bool:
        """Whether nothing is in this room and nothing is arriving.

        A connection is handed its room before it reaches the register, so
        the count alone would read a room as idle during that gap.
        """
        return self.connection_count() == 0 and self._holds == 0

    def hold(self) -> None:
        """Claim this room for a connection that is joining."""
        self._holds += 1

    def release(self) -> None:
        """Drop a claim, once the connection holding it has reached the
        register or given up."""
        if self._holds > 0:
            self._holds -= 1

    async def load_once(self, session: AsyncSession) -> None:
        """Read this room's stored state, once, however many callers arrive.

        Callers can reach a room the moment it is claimed, before anyone has
        loaded it. The first one through does the read and the rest wait on it
        rather than repeating it. A document that is no longer there still
        counts as read: the room stays empty rather than asking again.

        ``session`` must be routed to the guild whose schema holds the row.
        """
        if self._loaded:
            return
        async with self._load_lock:
            if self._loaded:
                return
            statement = select(Document).where(Document.id == self.document_id)
            document = (await session.exec(statement)).one_or_none()
            if document:
                await self.initialize_from_db(
                    yjs_state=document.yjs_state,
                    lexical_content=document.content,
                )
            self._loaded = True

    async def initialize_from_db(
        self, yjs_state: Optional[bytes], lexical_content: Optional[dict]
    ) -> None:
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
                    logger.warning(
                        f"Document {self.document_id}: failed to restore Yjs state: {e}"
                    )
            else:
                # First time collaborative edit - Yjs doc starts empty
                # Frontend will bootstrap with existing Lexical content via initialEditorState
                logger.info(
                    f"Document {self.document_id}: no Yjs state, frontend will bootstrap"
                )

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

    def state_vector(self) -> bytes:
        """What this room already has, for a client to answer with the rest.

        The other half of the sync handshake: a client that reconnects holding
        work the room never saw can only hand it over if it is asked, and this
        is the asking.
        """
        return bytes(self.doc.get_state())

    def apply_update(self, update: bytes, connection: Any = None) -> None:
        """Apply a Yjs update from a client."""
        self.doc.apply_update(update)
        self._revision += 1
        self._last_writer = connection

    def offer_content(self, content: dict, connection: Any = None) -> bool:
        """Record the JSON an editor says this document now reads as.

        ``content`` and ``yjs_state`` are two views of one document, and a row
        whose two views disagree is a document that loads as something other
        than what was edited. The room writes both together, from one
        snapshot, and takes the rendering from the connection that last moved
        the document — that is the tab whose view of it is current. Another
        tab's rendering is of the document as it stood before, and its own
        next offer will carry the merged state.

        Returns whether the offer was taken.
        """
        if self._last_writer is not None and connection is not self._last_writer:
            return False
        self._content = content
        self._revision += 1
        self._content_revision = self._revision
        return True

    def snapshot(self) -> Tuple[int, bytes, Optional[dict]]:
        """The revision being written, and the views of it that are current.

        A rendering older than the document is held back while editors are
        here: the one that moved the document reports a fresh rendering on its
        next pass, and that is the one worth pairing with this state. Once the
        room is empty no fresher rendering is coming, so the best one held is
        written.
        """
        content = self._content
        if (
            content is not None
            and self._content_revision < self._revision
            and not self.is_empty()
        ):
            content = None
        return self._revision, self.get_state(), content

    def mark_persisted(self, revision: int) -> None:
        """Record that ``revision`` reached the database.

        Only moves forward: an edit that landed while the write was in flight
        leaves the room dirty, so the next sweep picks it up.
        """
        if revision > self._persisted_revision:
            self._persisted_revision = revision


# A room is identified by (guild_id, document_id). The guild_id is part of the
# key because documents live in per-guild schemas (`guild_<id>.documents`, `id
# SERIAL`): document ids are per-schema sequences, so id 5 names a different
# document in every guild that has one. This manager is a single process-global
# structure, so the id alone does not identify a document. Never key
# collaboration state by a guild-schema-local id alone.
RoomKey = Tuple[int, int]

# How often the sweeper writes rooms that have changed.
PERSISTENCE_INTERVAL_SECONDS = 30


class CollaborationManager:
    """
    Manages all active document collaboration rooms.

    Handles:
    - Room lifecycle (create, destroy)
    - Persistence scheduling
    - Global state tracking
    """

    def __init__(self):
        self._rooms: Dict[RoomKey, DocumentRoom] = {}
        self._lock = asyncio.Lock()
        self._persistence_interval = PERSISTENCE_INTERVAL_SECONDS
        self._persistence_task: Optional[asyncio.Task] = None

    async def get_or_create_room(
        self,
        guild_id: int,
        document_id: int,
        session: AsyncSession,
    ) -> DocumentRoom:
        """Get an existing room or create a new one.

        ``session`` must be routed to ``guild_id`` — the document is loaded
        through it, from that guild's schema.
        """
        key = (guild_id, document_id)
        # The registry lock is held only long enough to claim the room's slot.
        # Reading its state is database I/O, and doing that here would make one
        # slow document a wait for every other room in the process, in every
        # guild. It happens below, guarded by the room itself.
        async with self._lock:
            room = self._rooms.get(key)
            if room is None:
                room = DocumentRoom(guild_id, document_id)
                self._rooms[key] = room
                logger.info(
                    f"Created collaboration room for document {document_id} "
                    f"in guild {guild_id}"
                )

        await room.load_once(session)
        return room

    async def remove_room(self, guild_id: int, document_id: int) -> None:
        """Remove a room once nothing is connected to it."""
        key = (guild_id, document_id)
        async with self._lock:
            room = self._rooms.get(key)
            if not room:
                return
            # A room that has been claimed but not yet read in is empty because
            # nobody has arrived yet, not because everyone has left. Whoever is
            # loading it is about to join it.
            if not room.is_loaded:
                return
            if not room.is_empty():
                return
            # Anything unsaved is written by the caller before this point; a
            # room still dirty here would lose it, so it stays until the sweep.
            if room.is_dirty:
                return
            room.detached = True
            del self._rooms[key]
            logger.info(f"Removed empty collaboration room for document {document_id}")

    async def invalidate_room_if_empty(self, guild_id: int, document_id: int) -> bool:
        """Remove a room if it exists and has no active connections.

        Used when document content is modified externally (e.g. unresolving
        wikilinks when a target document is deleted) so the next session loads
        fresh state from the database instead of stale in-memory state.

        Returns True if the room was removed, False if it is still in use (in
        which case its connections hold their state until reload).
        """
        key = (guild_id, document_id)
        async with self._lock:
            room = self._rooms.get(key)
            if not room:
                return True  # No room, nothing to invalidate
            if not room.is_loaded:
                # Being read in right now: leave it to the caller doing that,
                # who is about to join it.
                return False
            if room.is_empty():
                if room.is_dirty:
                    # Empty but still owing the database: the sweep has it.
                    logger.info(
                        f"Document {document_id} has unsaved state; keeping its "
                        "room until it is written"
                    )
                    return False
                room.detached = True
                del self._rooms[key]
                logger.info(
                    f"Invalidated empty collaboration room for document {document_id}"
                )
                return True
            else:
                logger.warning(
                    f"Document {document_id} has active collaborators - "
                    "they may see stale wikilinks until reload"
                )
                return False

    async def persist_room(
        self, guild_id: int, document_id: int, session: AsyncSession
    ) -> None:
        """Persist the current room state to the database.

        ``session`` must be routed to ``guild_id``, whose schema holds the row
        being written.
        """
        async with self._lock:
            room = self._rooms.get((guild_id, document_id))
        if room is None:
            return
        await self._write_room(room, session)

    async def _write_room(self, room: DocumentRoom, session: AsyncSession) -> None:
        """Write both views of one room in a single statement.

        ``content`` only joins the write once an editor in the room has
        reported one; a room nobody has offered content for leaves the column
        as it stands rather than blanking it.
        """
        async with room._write_lock:
            await self._write_room_locked(room, session)

    async def _write_room_locked(
        self, room: DocumentRoom, session: AsyncSession
    ) -> None:
        revision, state, content = room.snapshot()
        values: Dict[str, Any] = {
            "yjs_state": state,
            "yjs_updated_at": datetime.now(timezone.utc),
        }
        if content is not None:
            # Imported here rather than at module scope: the sync reaches back
            # into this registry to retire idle rooms.
            from app.core.search import SearchEntityType
            from app.services.tenant import content_references
            from app.services.tenant.relationships import Endpoint

            try:
                fixed = await content_references.sync_for_entity(
                    session,
                    Endpoint(SearchEntityType.document, room.document_id),
                    body=content,
                    fix_content=True,
                )
            except Exception:
                logger.exception(
                    f"Failed to sync references for document {room.document_id}"
                )
                fixed = None
            values["content"] = fixed if fixed else content
        try:
            result = await session.exec(
                sa_update(Document)
                .where(Document.id == room.document_id)
                .values(**values)
            )
            await session.commit()
            if result.rowcount:
                room.mark_persisted(revision)
                logger.debug(f"Persisted Yjs state for document {room.document_id}")
            else:
                # The row was not reachable on this session — deleted, or the
                # context was not routed to its guild. Either way nothing was
                # written, and the room stays dirty rather than reporting a
                # save that did not happen.
                logger.warning(
                    f"Persisting document {room.document_id} in guild "
                    f"{room.guild_id} matched no row; leaving it unsaved"
                )
        except Exception as e:
            logger.error(
                f"Failed to persist Yjs state for document {room.document_id}: {e}"
            )
            await session.rollback()

    async def persist_dirty_rooms(self) -> int:
        """Write every room that has changed since it was last written.

        Returns how many were written. A room nobody has touched costs nothing:
        serializing an unchanged document and rewriting its column every sweep
        is the kind of idle work that scales with how many documents are open
        rather than with how much is happening in them.
        """
        async with self._lock:
            targets = [room for room in self._rooms.values() if room.is_dirty]
        for room in targets:
            try:
                async with AsyncSessionLocal() as session:
                    # No user is doing this, so it routes as the guild's own
                    # admin — the level this write needs to reach the row.
                    await set_rls_context(
                        session, guild_id=room.guild_id, guild_role="admin"
                    )
                    await self._write_room(room, session)
            except Exception:
                logger.exception(f"Sweep failed to persist document {room.document_id}")
        return len(targets)

    def ensure_persistence_loop(self) -> None:
        """Start the sweeper if it isn't already running."""
        if self._persistence_task is None or self._persistence_task.done():
            self._persistence_task = asyncio.create_task(self._persistence_loop())

    async def stop_persistence_loop(self) -> None:
        """Stop the sweeper, writing anything outstanding on the way out.

        A shutdown is the last chance to write what is open, so it takes it
        rather than waiting out the rest of the interval.
        """
        task = self._persistence_task
        self._persistence_task = None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        try:
            await self.persist_dirty_rooms()
        except Exception:
            logger.exception("final collaboration persistence sweep failed")

    async def _persistence_loop(self) -> None:
        """Write changed rooms on an interval.

        Durability that depends on a clean disconnect is durability a crash,
        a restart or a dropped connection takes with it. This bounds what an
        abnormal exit can cost to one interval's worth of edits.
        """
        while True:
            await asyncio.sleep(self._persistence_interval)
            try:
                await self.persist_dirty_rooms()
            except Exception:
                logger.exception("collaboration persistence sweep failed")

    def get_active_rooms(self) -> Set[RoomKey]:
        """Get the set of (guild, document) pairs with active rooms."""
        return set(self._rooms.keys())

    def get_room(self, guild_id: int, document_id: int) -> Optional[DocumentRoom]:
        """Get a room without creating it."""
        return self._rooms.get((guild_id, document_id))

    def has_active_collaborators(self, guild_id: int, document_id: int) -> bool:
        """Check if a document has any live connection."""
        room = self._rooms.get((guild_id, document_id))
        return room is not None and not room.is_empty()


def room_roster(guild_id: int, document_id: int) -> list[dict]:
    """Who is editing a document, one entry per person.

    Read from the connection register, so it cannot drift from the sockets
    that exist. Two tabs are two connections and one collaborator: the roster
    is about people, and a person is here if any of their connections is. They
    can write if any of those connections may.
    """
    by_user: Dict[int, dict] = {}
    for member in stream_authority.room_members(guild_id, RESOURCE_TYPE, document_id):
        user_id = member.user.id
        if user_id is None:
            continue
        entry = by_user.get(user_id)
        if entry is None:
            by_user[user_id] = {
                "user_id": user_id,
                "name": member.meta.get("name") or "",
                "can_write": bool(member.meta.get("can_write")),
                "avatar_url": member.meta.get("avatar_url"),
            }
        elif member.meta.get("can_write"):
            entry["can_write"] = True
    return list(by_user.values())


def user_has_connection(guild_id: int, document_id: int, user_id: int) -> bool:
    """Whether this account still holds any connection to a document.

    A person leaves a document when their last tab does, not when one of
    several does.
    """
    return any(
        member.user.id == user_id
        for member in stream_authority.room_members(
            guild_id, RESOURCE_TYPE, document_id
        )
    )


async def broadcast_awareness(
    guild_id: int,
    document_id: int,
    awareness_data: dict,
    *,
    exclude=None,
) -> None:
    """Send a JSON awareness frame to a document's room.

    ``exclude`` is the originating connection, never its account — the frame
    is about one socket's cursor, and the same person's other tab has its own.
    """
    MSG_AWARENESS = 3
    message = (
        bytes([MSG_AWARENESS])
        + json.dumps({"type": "awareness", "data": awareness_data}).encode()
    )
    await stream_authority.emit_bytes(
        guild_id, RESOURCE_TYPE, document_id, message, exclude=exclude
    )


# Global collaboration manager instance
collaboration_manager = CollaborationManager()

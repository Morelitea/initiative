"""
Real-time collaboration service using Yjs (via pycrdt).

A room is the Yjs document plus its persistence, for ANY body several people
can write at once — a native document, a wiki page. Which row a room is a body
of, and whose sharing decides who may open it, is declared once in
:mod:`app.services.tenant.collaborative_resources`; nothing here knows about
documents in particular.

A room deliberately does **not**
keep a list of who is connected: that register lives once, in
:mod:`app.services.content_sockets`, keyed by socket. A channel that keeps its own
copy has to keep the two in step, and the moment they disagree — which is every
time one account opens a second tab — delivery and authorization stop matching
the sockets that actually exist.
"""

import asyncio
import hashlib
import json
import logging
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from pycrdt import Decoder, Doc
from sqlalchemy import update as sa_update
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.core.identity_boundary import MentionForm, without_mention_names
from app.db import cohorts
from app.db.session import set_rls_context
from app.services import editor_engine
from app.services.content_sockets import resource_room, sockets
from app.services.tenant import attachments as attachments_service
from app.services.tenant.collaborative_resources import (
    YJS_STATE_COLUMN,
    YJS_UPDATED_COLUMN,
    resource_for,
)
from app.db.request_context import SystemGuild

logger = logging.getLogger(__name__)


def _clocks(state_vector: bytes) -> dict[int, int]:
    """A Yjs state vector as ``{client: clock}``: a count, then that many
    ``(client, clock)`` pairs, all variable-length unsigned integers."""
    decoder = Decoder(state_vector)
    return {
        decoder.read_var_uint(): decoder.read_var_uint()
        for _ in range(decoder.read_var_uint())
    }


class CollaborationRoom:
    """The live Yjs state of one body, and what it owes the database.

    Holds the merged ``Doc`` every connection reads and writes, the JSON
    ``content`` an editor last reported for it, and enough bookkeeping to know
    whether either has moved since it was last written down.
    """

    def __init__(self, guild_id: int, resource_type: str, resource_id: int):
        self.guild_id = guild_id
        #: Which kind of body this is — the key into the resource registry, and
        #: the namespace this room occupies in the stream register.
        self.resource_type = resource_type
        self.resource_id = resource_id
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
        # One versioned write at a time, so two naming the same version cannot
        # both find it current.
        self._edit_lock = asyncio.Lock()
        # Connections that have been handed this room but have not yet reached
        # the register. They are on their way in, so the room is not idle.
        self._holds = 0
        # The connection whose update the document currently reflects. A
        # rendering of the document is only current if it came from the tab
        # that last moved it.
        self._last_writer: Any = None
        #: Everyone who has changed the document in this room.
        self.writers: set[int] = set()
        # A room dropped from the registry. Nothing should reach one — the
        # registry only drops rooms with no connections — but a write that does
        # would go nowhere, so it says so instead of swallowing it.
        self.detached = False
        # Revisions, not a boolean: a write serializes a snapshot and then
        # commits, and an edit landing in between must not be marked saved.
        self._revision = 0
        self._persisted_revision = 0
        #: Whether the body is the document editor's: the server made its
        #: Yjs state and renders its content, so no tab reports one.
        self.renders_content = False
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
        return sockets.room_size(
            resource_room(self.guild_id, self.resource_type, self.resource_id)
        )

    def is_empty(self) -> bool:
        """Whether nothing is in this room and nothing is arriving.

        A connection is handed its room before it reaches the register, so
        the count alone would read a room as idle during that gap.
        """
        return self.connection_count() == 0 and self._holds == 0

    def hold(self) -> None:
        """Claim this room for a connection that is joining, or a write that is
        on its way in."""
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
            spec = resource_for(self.resource_type)
            statement = select(
                getattr(spec.model, YJS_STATE_COLUMN), spec.editor_body()
            ).where(spec.model.id == self.resource_id)
            row = (await session.exec(statement)).one_or_none()
            if row:
                state, self.renders_content = row[0], bool(row[1])
                if state is None and self.renders_content:
                    state = await _bootstrapped(
                        self.guild_id, self.resource_type, self.resource_id
                    )
                await self.initialize_from_db(yjs_state=state)
            self._loaded = True

    async def initialize_from_db(self, yjs_state: Optional[bytes]) -> None:
        """Initialize the Y.Doc from database state.

        An editor body arrives with a state the server made; any other body
        with none yet starts empty, and the first browser editing it fills it.
        """
        async with self._lock:
            if self._initialized:
                return

            if yjs_state:
                # Restore from existing Yjs state
                try:
                    self.doc.apply_update(yjs_state)
                    logger.info(
                        f"{self.resource_type} {self.resource_id}: restored from Yjs state"
                    )
                except Exception as e:
                    logger.warning(
                        f"{self.resource_type} {self.resource_id}: "
                        f"failed to restore Yjs state: {e}"
                    )
            else:
                logger.info(
                    f"{self.resource_type} {self.resource_id}: no Yjs state, "
                    "the first editor will fill it"
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

    def known_to(self, state_vector: bytes) -> bool:
        """Whether a client at ``state_vector`` has everything this room has.

        Only then is that client's rendering a rendering of this room: one that
        is missing somebody else's edits describes an older document.
        """
        theirs = _clocks(state_vector)
        return all(
            clock <= theirs.get(client, 0)
            for client, clock in _clocks(self.state_vector()).items()
        )

    def apply_update(
        self, update: bytes, connection: Any = None, user_id: int | None = None
    ) -> None:
        """Apply a Yjs update from a client, sent by ``user_id``."""
        self.doc.apply_update(update)
        self._revision += 1
        self._last_writer = connection
        if user_id is not None:
            self.writers.add(user_id)

    async def rendering(self) -> dict:
        """What this editor body reads as now, rendered from its live document."""
        return without_mention_names(
            await editor_engine.render(self.get_state()), MentionForm.lexical
        )

    async def write(self, content: dict, version: str, user_id: Optional[int]) -> bool:
        """Write ``content`` into this editor body's live document, as the
        server's editor makes it read, if the body still reads as ``version``,
        and hand the change to everyone in the room. It is saved as their
        edits are.

        Returns whether it was written. The room is held until the write is in
        it, so it stays registered for the save; one the last editor left in
        the meantime is saved and retired here.
        """
        self.hold()
        try:
            async with self._edit_lock:
                if content_version(await self.rendering()) != version:
                    return False
                update = await editor_engine.apply(self.get_state(), content)
                self.apply_update(update, user_id=user_id)
                sockets.emit_bytes(
                    resource_room(self.guild_id, self.resource_type, self.resource_id),
                    bytes([MSG_UPDATE]) + update,
                )
                return True
        finally:
            self.release()
            await collaboration_manager.leave(
                self.guild_id, self.resource_type, self.resource_id
            )

    def offer_content(self, content: dict, connection: Any = None) -> bool:
        """Record the JSON an editor says this document now reads as.

        ``content`` and ``yjs_state`` are two views of one document, and a row
        whose two views disagree is a document that loads as something other
        than what was edited. The room writes both together, from one
        snapshot, and takes the rendering from the connection that last moved
        the document — that is the tab whose view of it is current. Another
        tab's rendering is of the document as it stood before, and its own
        next offer will carry the merged state. A mention in it is kept by id
        with no name, as every other write keeps one.

        Returns whether the offer was taken.
        """
        if self._last_writer is not None and connection is not self._last_writer:
            return False
        self._content = without_mention_names(content, MentionForm.lexical)
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


def _editor_state(content: Any) -> Optional[dict]:
    """``content`` as the editor can start from it, or ``None`` for an empty
    document. A body nobody has written is stored as ``{}``, or as a root with
    no children, and the editor refuses both as a starting state."""
    root = content.get("root") if isinstance(content, dict) else None
    children = root.get("children") if isinstance(root, dict) else None
    return content if isinstance(children, list) and children else None


async def _bootstrapped(
    guild_id: int, resource_type: str, resource_id: int
) -> Optional[bytes]:
    """An editor body's Yjs state, made from its content by the server's
    editor when the row has none.

    Taken under the row's lock on a system session, so rooms opening the same
    row together make it once, and a reader opening it can still have it made.
    """
    spec = resource_for(resource_type)
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        row = (
            await session.exec(
                select(
                    getattr(spec.model, YJS_STATE_COLUMN),
                    getattr(spec.model, spec.content_column),
                )
                .where(spec.model.id == resource_id)
                .with_for_update()
            )
        ).one_or_none()
        if row is None:
            return None
        state, content = row
        if state is None:
            state = await editor_engine.bootstrap(_editor_state(content))
            await session.exec(
                sa_update(spec.model)
                .where(spec.model.id == resource_id)
                .values(
                    {
                        YJS_STATE_COLUMN: state,
                        YJS_UPDATED_COLUMN: datetime.now(timezone.utc),
                    }
                )
            )
            await session.commit()
        return state


async def written_into(state: Optional[bytes], content: dict) -> Optional[bytes]:
    """An editor body's stored Yjs state with ``content`` written into it.

    The server's editor rewrites only what changed, so the state keeps the
    history its editors made and a session reopening it starts from this
    content. A body with no state keeps none: the room makes it when it opens.
    Content the editor refuses leaves no state either, and the room makes one
    from the content in the same way.
    """
    if state is None:
        return None
    try:
        update = await editor_engine.apply(state, content)
    except editor_engine.EditorError:
        logger.exception("The editor could not write content into a stored state")
        return None
    doc = Doc()
    doc.apply_update(state)
    doc.apply_update(update)
    return bytes(doc.get_update())


#: The socket frame that carries a Yjs update.
MSG_UPDATE = 2


def content_version(content: dict) -> str:
    """A body's version, as a write names the one it read: a digest of the
    content, so it moves exactly when what the body reads as does."""
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


async def current_content(
    guild_id: int, resource_type: str, resource_id: int, stored: dict
) -> dict:
    """What a body reads as now: an open editor room's rendering of its live
    document, or ``stored`` while no room is open."""
    room = collaboration_manager.live_room(guild_id, resource_type, resource_id)
    if room is None or not room.renders_content:
        return stored
    return await room.rendering()


async def versioned(read: Any, guild_id: int, resource_type: str) -> Any:
    """``read`` with the content its body reads as now and that content's
    version, for the next write to name."""
    read.content = await current_content(guild_id, resource_type, read.id, read.content)
    read.content_version = content_version(read.content)
    return read


# A room is identified by (guild_id, resource_type, resource_id). The guild_id
# is part of the key because bodies live in per-guild schemas (`guild_<id>.…`,
# `id SERIAL`): ids are per-schema sequences, so id 5 names a different row in
# every guild that has one. The resource_type is part of it because two kinds
# number independently — document 5 and wiki page 5 are both real. This manager
# is a single process-global structure, so neither the id nor the pair without
# the guild identifies a body. Never key collaboration state by a
# guild-schema-local id alone.
RoomKey = Tuple[int, str, int]

# How often the sweeper writes rooms that have changed.
PERSISTENCE_INTERVAL_SECONDS = 30


class CollaborationManager:
    """
    Manages every active collaboration room, of every kind.

    Handles:
    - Room lifecycle (create, destroy)
    - Persistence scheduling
    - Global state tracking
    """

    def __init__(self):
        self._rooms: Dict[RoomKey, CollaborationRoom] = {}
        self._lock = asyncio.Lock()
        self._persistence_interval = PERSISTENCE_INTERVAL_SECONDS
        self._persistence_task: Optional[asyncio.Task] = None

    async def get_or_create_room(
        self,
        guild_id: int,
        resource_type: str,
        resource_id: int,
        session: AsyncSession,
    ) -> CollaborationRoom:
        """Get an existing room or create a new one.

        ``session`` must be routed to ``guild_id`` — the body is loaded through
        it, from that guild's schema.
        """
        key = (guild_id, resource_type, resource_id)
        # The registry lock is held only long enough to claim the room's slot.
        # Reading its state is database I/O, and doing that here would make one
        # slow document a wait for every other room in the process, in every
        # guild. It happens below, guarded by the room itself.
        async with self._lock:
            room = self._rooms.get(key)
            if room is None:
                room = CollaborationRoom(guild_id, resource_type, resource_id)
                self._rooms[key] = room
                logger.info(
                    f"Created collaboration room for {resource_type} "
                    f"{resource_id} in guild {guild_id}"
                )

        await room.load_once(session)
        return room

    async def remove_room(
        self, guild_id: int, resource_type: str, resource_id: int
    ) -> None:
        """Remove a room once nothing is connected to it."""
        key = (guild_id, resource_type, resource_id)
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
            logger.info(
                f"Removed empty collaboration room for {resource_type} {resource_id}"
            )

    async def invalidate_room_if_empty(
        self, guild_id: int, resource_type: str, resource_id: int
    ) -> bool:
        """Remove a room if it exists and has no active connections.

        Used when document content is modified externally (e.g. unresolving
        wikilinks when a target document is deleted) so the next session loads
        fresh state from the database instead of stale in-memory state.

        Returns True if the room was removed, False if it is still in use (in
        which case its connections hold their state until reload).
        """
        key = (guild_id, resource_type, resource_id)
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
                        f"{resource_type} {resource_id} has unsaved state; keeping its "
                        "room until it is written"
                    )
                    return False
                room.detached = True
                del self._rooms[key]
                logger.info(
                    f"Invalidated empty collaboration room for {resource_type} {resource_id}"
                )
                return True
            else:
                logger.warning(
                    f"{resource_type} {resource_id} has active collaborators - "
                    "they may see stale wikilinks until reload"
                )
                return False

    async def save(self, room: CollaborationRoom) -> None:
        """Write one room, on a system session from its community's cohort
        routed into it.

        The one way a room reaches the database: the sweep, the last
        connection leaving and a handed-over edit all come here, so none of
        them depends on whose request happened to be last in the room.
        """
        async with cohorts.system_session(room.guild_id) as session:
            await set_rls_context(session, SystemGuild(room.guild_id))
            await self._write_room(room, session)

    async def leave(self, guild_id: int, resource_type: str, resource_id: int) -> None:
        """Save a room nothing is connected to any more, and retire it.

        A room somebody is still in, or on their way into, is left alone. A
        save that fails leaves the room dirty, and the sweep tries again.
        """
        async with self._lock:
            room = self._rooms.get((guild_id, resource_type, resource_id))
        if room is None or not room.is_empty():
            return
        if room.is_dirty:
            try:
                await self.save(room)
            except Exception:
                logger.exception(f"Failed to save {resource_type} {resource_id}")
        await self.remove_room(guild_id, resource_type, resource_id)

    async def _write_room(self, room: CollaborationRoom, session: AsyncSession) -> None:
        """Write both views of one room in a single statement.

        ``content`` only joins the write once an editor in the room has
        reported one; a room nobody has offered content for leaves the column
        as it stands rather than blanking it.
        """
        async with room._write_lock:
            await self._write_room_locked(room, session)

    async def _write_room_locked(
        self, room: CollaborationRoom, session: AsyncSession
    ) -> None:
        spec = resource_for(room.resource_type)
        revision, state, content = room.snapshot()
        if room.renders_content:
            content = without_mention_names(
                await editor_engine.render(state), MentionForm.lexical
            )
        values: Dict[str, Any] = {
            YJS_STATE_COLUMN: state,
            YJS_UPDATED_COLUMN: datetime.now(timezone.utc),
        }
        if content is not None:
            # Imported here rather than at module scope: the sync reaches back
            # into this registry to retire idle rooms.
            from app.services.tenant import content_references
            from app.services.tenant.relationships import Endpoint

            try:
                fixed = await content_references.sync_for_entity(
                    session,
                    Endpoint(spec.entity_type, room.resource_id),
                    body=content,
                    fix_content=True,
                )
            except Exception:
                logger.exception(
                    f"Failed to sync references for {room.resource_type} "
                    f"{room.resource_id}"
                )
                fixed = None
            values[spec.content_column] = fixed if fixed else content
        try:
            result = await session.exec(
                sa_update(spec.model)
                .where(spec.model.id == room.resource_id)
                .values(**values)
            )
            if content is not None and result.rowcount:
                # The files its writers uploaded are claimed. Nothing is copied:
                # the content is the editors' rendering of the room's document,
                # which the next save writes again as they hold it.
                await attachments_service.claim_uploads(
                    session,
                    await session.get(spec.model, room.resource_id),
                    uploaded_by=room.writers,
                )
            await session.commit()
            if result.rowcount:
                room.mark_persisted(revision)
                logger.debug(
                    f"Persisted Yjs state for {room.resource_type} {room.resource_id}"
                )
            else:
                # The row was not reachable on this session — deleted, or the
                # context was not routed to its guild. Either way nothing was
                # written, and the room stays dirty rather than reporting a
                # save that did not happen.
                logger.warning(
                    f"Persisting {room.resource_type} {room.resource_id} in guild "
                    f"{room.guild_id} matched no row; leaving it unsaved"
                )
        except Exception as e:
            logger.error(
                f"Failed to persist Yjs state for {room.resource_type} "
                f"{room.resource_id}: {e}"
            )
            await session.rollback()

    async def persist_dirty_rooms(self) -> int:
        """Write every room that has changed since it was last written, then
        retire the ones nobody is in.

        Returns how many were written. A room nobody has touched costs nothing
        to keep open, and one nobody is in any more — its last save failed, or
        the connection that left could not finish — is retired here once it is
        saved, rather than held for the life of the process.
        """
        async with self._lock:
            targets = [room for room in self._rooms.values() if room.is_dirty]
        for room in targets:
            try:
                await self.save(room)
            except Exception:
                logger.exception(
                    f"Sweep failed to persist {room.resource_type} {room.resource_id}"
                )
        async with self._lock:
            idle = [key for key, room in self._rooms.items() if room.is_empty()]
        for key in idle:
            await self.remove_room(*key)
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

    def has_active_collaborators(
        self, guild_id: int, resource_type: str, resource_id: int
    ) -> bool:
        """Check if a document has any live connection."""
        return self.live_room(guild_id, resource_type, resource_id) is not None

    def live_room(
        self, guild_id: int, resource_type: str, resource_id: int
    ) -> Optional[CollaborationRoom]:
        """The room a body is being edited in, if anyone is connected to it."""
        room = self._rooms.get((guild_id, resource_type, resource_id))
        return room if room is not None and not room.is_empty() else None


def room_roster(guild_id: int, resource_type: str, resource_id: int) -> list[dict]:
    """Who is editing a document, one entry per person.

    Read from the connection register, so it cannot drift from the sockets
    that exist. Two tabs are two connections and one collaborator: the roster
    is about people, and a person is here if any of their connections is. They
    can write if any of those connections may.
    """
    by_user: Dict[int, dict] = {}
    for member in sockets.room_members(
        resource_room(guild_id, resource_type, resource_id)
    ):
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


def user_has_connection(
    guild_id: int, resource_type: str, resource_id: int, user_id: int
) -> bool:
    """Whether this account still holds any connection to a document.

    A person leaves a document when their last tab does, not when one of
    several does.
    """
    return any(
        member.user.id == user_id
        for member in sockets.room_members(
            resource_room(guild_id, resource_type, resource_id)
        )
    )


def broadcast_awareness(
    guild_id: int,
    resource_type: str,
    resource_id: int,
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
    sockets.emit_bytes(
        resource_room(guild_id, resource_type, resource_id), message, exclude=exclude
    )


# Global collaboration manager instance
collaboration_manager = CollaborationManager()

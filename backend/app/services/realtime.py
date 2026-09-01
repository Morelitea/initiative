import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Set, Tuple

from fastapi import WebSocket

# A room is identified by (guild_id, initiative_id). The guild_id is REQUIRED in
# the key: initiatives live in per-guild schemas (`guild_<id>.initiatives`, `id
# SERIAL`), so initiative ids are per-schema sequences and collide across guilds
# (id 5 exists in many guilds). This manager is a single process-global
# structure, so without the guild_id a broadcast to "initiative 5" would reach
# sockets from every guild that has an initiative 5 — a cross-guild leak. Never
# key realtime state by a guild-schema-local id alone.
RoomKey = Tuple[int, int]


class OnlineRoll:
    """Who has Initiative open — the person, not the place.

    Deliberately separate from the guild presence the manager below keeps.
    That one answers "how busy is this guild right now", and a guild is the
    unit it counts in. This one answers "is this account online", which is a
    fact about the person: they are online whether the tab they left open is a
    guild they share with the asker, a guild they don't, or no guild at all.
    Reading the guild roll for that answer would make someone look offline to
    everyone who happens not to be in the guild they are sitting in.

    Fed by the same connect/disconnect the rooms are, so there is one place a
    socket is accounted for. Counted per user rather than per socket, so two
    tabs are one person.

    Bounded the same way the guild roll is: these are one process's own
    sockets, held in memory. Where the API runs as more than one worker, each
    holds a share, so this can say "no" about someone another worker is
    serving. It drives a dot beside a name — a hint, not a fact anything
    depends on.
    """

    def __init__(self) -> None:
        # user_id -> how many of that user's sockets are open on this process.
        self._sockets: Dict[int, int] = {}

    def arrived(self, user_id: int) -> None:
        self._sockets[user_id] = self._sockets.get(user_id, 0) + 1

    def left(self, user_id: int) -> None:
        remaining = self._sockets.get(user_id, 0) - 1
        if remaining > 0:
            self._sockets[user_id] = remaining
        else:
            self._sockets.pop(user_id, None)

    def is_online(self, user_id: int) -> bool:
        return user_id in self._sockets

    def online_users(self, user_ids: Iterable[int]) -> Set[int]:
        """Which of these accounts are online, for a page of them at a time."""
        return {user_id for user_id in user_ids if user_id in self._sockets}


class ConnectionManager:
    """Initiative-scoped WebSocket fan-out for the `/events/updates` stream.

    Connections are bucketed by ``(guild_id, initiative_id)``: a socket joins
    exactly the initiative rooms its user can reach in that guild (resolved at
    connect via ``initiative_access`` — the same function RLS uses), and a
    broadcast for an initiative reaches only the sockets in that room. This is
    the tenancy boundary for the signal stream — a non-member is never poked,
    and the guild_id in the key keeps per-guild ids from colliding.

    The stream carries **id envelopes only** (no tooling content), so even a
    routing mistake cannot leak data: the authoritative gate is the RLS-gated
    refetch the client performs in response to a signal. Routing is therefore a
    performance + existence-hiding optimization, never the trust boundary.

    A socket may live in several rooms at once (a user reaches several
    initiatives), so we keep a reverse index for O(1) disconnect.

    It also answers who is *present* in a guild: a socket on this stream is a
    user with the app open in that guild, tracked per guild rather than per
    room, because a member of no initiative joins no rooms and is still here.
    Presence is counted per user, not per socket, so two tabs are one person.
    Whether a *person* is online at all is a different question and a different
    object — ``self.online`` (see :class:`OnlineRoll`), fed from the same
    connect/disconnect.

    What that count is bounded by is worth stating: this is one process's own
    sockets, held in memory. Where the API runs as more than one worker each
    holds a share, and a count read from one of them is that share rather than
    the whole. A number that is only ever compared with itself (how busy is this
    guild) survives that; anything that has to be exact does not, and wants a
    store the processes share.
    """

    def __init__(self) -> None:
        self._rooms: Dict[RoomKey, Set[WebSocket]] = {}
        self._socket_rooms: Dict[WebSocket, Set[RoomKey]] = {}
        # guild_id -> user_id -> how many of that user's sockets are open here.
        self._present: Dict[int, Dict[int, int]] = {}
        self._socket_identity: Dict[WebSocket, Tuple[int, int]] = {}
        # "Is this person online at all", which is not a guild question — see
        # ``OnlineRoll``. Same sockets, different question.
        self.online = OnlineRoll()
        self._lock = asyncio.Lock()

    async def connect(
        self,
        guild_id: int,
        initiative_ids: Iterable[int],
        websocket: WebSocket,
        *,
        user_id: int,
    ) -> None:
        """Register an already-accepted socket under each of its initiative rooms,
        namespaced to ``guild_id``, and mark its user present in that guild."""
        async with self._lock:
            joined = self._socket_rooms.setdefault(websocket, set())
            for initiative_id in initiative_ids:
                key = (guild_id, initiative_id)
                self._rooms.setdefault(key, set()).add(websocket)
                joined.add(key)
            self._socket_identity[websocket] = (guild_id, user_id)
            present = self._present.setdefault(guild_id, {})
            present[user_id] = present.get(user_id, 0) + 1
            self.online.arrived(user_id)

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a socket from every room it joined, and from its guild's roll."""
        async with self._lock:
            for key in self._socket_rooms.pop(websocket, set()):
                room = self._rooms.get(key)
                if room is not None:
                    room.discard(websocket)
                    if not room:
                        del self._rooms[key]
            identity = self._socket_identity.pop(websocket, None)
            if identity is None:
                return
            guild_id, user_id = identity
            self.online.left(user_id)
            present = self._present.get(guild_id)
            if present is None:
                return
            # A user's last socket takes the user out; the last user takes the
            # guild out, so an empty guild costs nothing to have had someone in.
            remaining = present.get(user_id, 0) - 1
            if remaining > 0:
                present[user_id] = remaining
            else:
                present.pop(user_id, None)
                if not present:
                    del self._present[guild_id]

    async def broadcast(
        self, guild_id: int, initiative_id: int, message: Dict[str, Any]
    ) -> None:
        key = (guild_id, initiative_id)
        async with self._lock:
            connections = list(self._rooms.get(key, set()))
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception:
                await self.disconnect(websocket)

    def room_size(self, guild_id: int, initiative_id: int) -> int:
        return len(self._rooms.get((guild_id, initiative_id), set()))

    def present_count(self, guild_id: int) -> int:
        """How many distinct users have this guild open on this process."""
        return len(self._present.get(guild_id, {}))

    def present_counts(self, guild_ids: Iterable[int]) -> Dict[int, int]:
        """``present_count`` for several guilds, for a page of them at a time."""
        return {guild_id: self.present_count(guild_id) for guild_id in guild_ids}


manager = ConnectionManager()


async def broadcast_event(
    guild_id: int,
    initiative_id: int,
    resource: str,
    action: str,
    ids: Dict[str, Any],
) -> None:
    """Fan a **content-free** signal out to one initiative's room in one guild.

    ``ids`` carries only the identifiers the client needs to invalidate/refetch
    (e.g. ``{"task_id": …, "project_id": …}``) — never a serialized model. The
    client refetches through the RLS-gated REST path, which is the actual
    authorization gate (see ``history/realtime-authorization-design.md``).

    ``guild_id`` is required and part of the room key — initiative ids are
    per-guild-schema sequences, so a broadcast must name its guild or it would
    cross the tenancy boundary.
    """
    await manager.broadcast(
        guild_id,
        initiative_id,
        {
            "resource": resource,
            "action": action,
            "ids": ids,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

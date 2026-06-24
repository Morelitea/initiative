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
    """

    def __init__(self) -> None:
        self._rooms: Dict[RoomKey, Set[WebSocket]] = {}
        self._socket_rooms: Dict[WebSocket, Set[RoomKey]] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self, guild_id: int, initiative_ids: Iterable[int], websocket: WebSocket
    ) -> None:
        """Register an already-accepted socket under each of its initiative rooms,
        namespaced to ``guild_id``."""
        async with self._lock:
            joined = self._socket_rooms.setdefault(websocket, set())
            for initiative_id in initiative_ids:
                key = (guild_id, initiative_id)
                self._rooms.setdefault(key, set()).add(websocket)
                joined.add(key)

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a socket from every room it joined."""
        async with self._lock:
            for key in self._socket_rooms.pop(websocket, set()):
                room = self._rooms.get(key)
                if room is not None:
                    room.discard(websocket)
                    if not room:
                        del self._rooms[key]

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

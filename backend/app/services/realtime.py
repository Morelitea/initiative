import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Set

from fastapi import WebSocket


class ConnectionManager:
    """Guild-scoped WebSocket fan-out for the global ``/events/updates`` stream.

    Connections are bucketed by ``guild_id`` so a broadcast only reaches sockets
    that authenticated against that guild. This is the tenancy boundary for the
    event stream: payloads are serialized in the HTTP handler and pushed
    out-of-band, so RLS cannot help here — the manager itself must enforce
    isolation. Mirrors the room-based counter/queue managers.
    """

    def __init__(self) -> None:
        self._rooms: Dict[int, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, guild_id: int, websocket: WebSocket) -> None:
        """Register an already-accepted connection under a guild."""
        async with self._lock:
            self._rooms.setdefault(guild_id, set()).add(websocket)

    async def disconnect(self, guild_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            room = self._rooms.get(guild_id)
            if room is not None:
                room.discard(websocket)
                if not room:
                    del self._rooms[guild_id]

    async def broadcast(self, guild_id: int, message: Dict[str, Any]) -> None:
        async with self._lock:
            connections = list(self._rooms.get(guild_id, set()))
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception:
                await self.disconnect(guild_id, websocket)

    def room_size(self, guild_id: int) -> int:
        return len(self._rooms.get(guild_id, set()))


manager = ConnectionManager()


async def broadcast_event(
    guild_id: int, resource: str, action: str, payload: Dict[str, Any]
) -> None:
    """Fan an event out to every socket subscribed to ``guild_id`` only."""
    await manager.broadcast(
        guild_id,
        {
            "resource": resource,
            "action": action,
            "data": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

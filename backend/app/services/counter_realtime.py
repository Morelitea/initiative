"""Room-based WebSocket manager for counter group real-time updates."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Set

from fastapi import WebSocket


class CounterConnectionManager:
    """Manages WebSocket connections grouped by counter-group room."""

    def __init__(self) -> None:
        self._rooms: Dict[int, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, group_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            if group_id not in self._rooms:
                self._rooms[group_id] = set()
            self._rooms[group_id].add(websocket)

    async def disconnect(self, group_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            if group_id in self._rooms:
                self._rooms[group_id].discard(websocket)
                if not self._rooms[group_id]:
                    del self._rooms[group_id]

    async def broadcast(
        self, group_id: int, event_type: str, data: Dict[str, Any]
    ) -> None:
        async with self._lock:
            connections = list(self._rooms.get(group_id, set()))

        message = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception:
                await self.disconnect(group_id, websocket)

    def room_size(self, group_id: int) -> int:
        return len(self._rooms.get(group_id, set()))


counter_manager = CounterConnectionManager()

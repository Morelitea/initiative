"""Room-based WebSocket manager for queue real-time updates.

Unlike the Yjs-based document collaboration, queue WebSocket is
server-to-client broadcast only. Mutations happen via REST endpoints,
and all connected clients receive updates via WebSocket.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Set

from fastapi import WebSocket


class QueueConnectionManager:
    """Manages WebSocket connections grouped by queue room."""

    def __init__(self) -> None:
        self._rooms: Dict[int, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, queue_id: int, websocket: WebSocket) -> None:
        """Add a WebSocket to a queue room."""
        async with self._lock:
            if queue_id not in self._rooms:
                self._rooms[queue_id] = set()
            self._rooms[queue_id].add(websocket)

    async def disconnect(self, queue_id: int, websocket: WebSocket) -> None:
        """Remove a WebSocket from a queue room."""
        async with self._lock:
            if queue_id in self._rooms:
                self._rooms[queue_id].discard(websocket)
                if not self._rooms[queue_id]:
                    del self._rooms[queue_id]

    async def broadcast(self, queue_id: int, event_type: str, data: Dict[str, Any]) -> None:
        """Send a JSON message to all connections in a queue room."""
        async with self._lock:
            connections = list(self._rooms.get(queue_id, set()))

        message = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception:
                await self.disconnect(queue_id, websocket)

    def room_size(self, queue_id: int) -> int:
        """Return the number of connections in a queue room."""
        return len(self._rooms.get(queue_id, set()))


queue_manager = QueueConnectionManager()

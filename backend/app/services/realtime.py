import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Set

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and add a WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def add_connection(self, websocket: WebSocket) -> None:
        """Add an already-accepted WebSocket connection."""
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        async with self._lock:
            connections = list(self._connections)
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception:
                await self.disconnect(websocket)


manager = ConnectionManager()


async def broadcast_event(resource: str, action: str, payload: Dict[str, Any]) -> None:
    await manager.broadcast(
        {
            "resource": resource,
            "action": action,
            "data": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )

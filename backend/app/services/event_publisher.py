"""Event publisher for automation triggers.

Publishes domain events to Redis Streams after task mutations. The automation
engine consumes these events via a Beam pipeline.

This module is a no-op when ENABLE_AUTOMATIONS=false — no Redis dependency.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis = None
_background_tasks: set[asyncio.Task] = set()  # Strong references to prevent GC


async def connect() -> None:
    """Establish Redis connection on startup (only when automations enabled)."""
    global _redis
    if not settings.ENABLE_AUTOMATIONS or not settings.REDIS_URL:
        logger.debug("Automations disabled; event publisher is a no-op")
        return

    try:
        import redis.asyncio as aioredis
        _redis = await aioredis.from_url(settings.REDIS_URL, decode_responses=False)
        await _redis.ping()
        logger.info("Event publisher connected to Redis: %s", settings.REDIS_URL)
    except Exception as e:
        logger.warning("Could not connect to Redis for event publishing: %s", e)
        _redis = None


async def close() -> None:
    """Cancel in-flight publish tasks and close Redis connection on shutdown."""
    global _redis
    for task in _background_tasks:
        task.cancel()
    _background_tasks.clear()
    if _redis:
        await _redis.close()
        _redis = None


async def publish_event(
    event_type: str,
    payload: dict[str, Any],
    guild_id: int,
    initiative_id: int,
) -> bool:
    """Publish a domain event to Redis Streams (non-blocking).

    Returns True if published, False if automations disabled or failed.
    """
    if not settings.ENABLE_AUTOMATIONS:
        return False

    message = {
        "type": event_type,
        "guild_id": guild_id,
        "initiative_id": initiative_id,
        "payload": payload,
    }
    task = asyncio.create_task(_publish_background(message))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return True


async def _publish_background(message: dict[str, Any]) -> None:
    """Background task — does not block the API response."""
    global _redis

    if not _redis:
        try:
            await connect()
        except Exception:
            pass

    if not _redis:
        logger.warning("Event %s: Redis unavailable, dropping event", message["type"])
        return

    try:
        await _redis.xadd(
            "initiative:events",
            {"data": json.dumps(message)},
        )
        logger.debug("Event %s published to initiative:events", message["type"])
    except Exception as e:
        logger.warning("Failed to publish event %s: %s", message["type"], e)

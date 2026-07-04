"""Purge notifications to the advanced tool's backend.

The advanced tool service (initiative-auto) keeps a scheduling mirror per
``advanced_tools`` row. Soft delete and archive need no push — the mirror
discovers them by reading our API (404 → hidden, times preserved). A HARD
purge is different: the row is gone forever, so the mirror must be deleted
too, and only we know the purge happened. Hence this one outbound call.

Mechanics:

* Pairs are QUEUED on ``session.info`` while ``hard_purge_entity`` walks
  its doomed rows, and DRAINED by the caller **after commit** — notifying
  before commit could delete a mirror for a purge that then rolls back.
* Delivery is best-effort: the purge itself must never fail or roll back
  because the tool's backend is down. A missed notification leaves an
  orphaned mirror whose next sync sees our 404 and hides it — safe, just
  untidy.
* The envelope reuses the webhook dispatch signature format
  (``sha256=<hex>`` over ``{timestamp}.{body}``) with the dedicated
  ``ADVANCED_TOOL_PURGE_SECRET``, so the receiving side verifies it the
  same way it verifies event deliveries.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_SESSION_INFO_KEY = "purged_advanced_tools"
_TIMEOUT_SECONDS = 5.0


def queue_purged_advanced_tool(
    session: Any, *, guild_id: int, advanced_tool_id: int
) -> None:
    """Record a purged (guild_id, advanced_tool_id) pair on the session,
    to be drained after the purge transaction commits."""
    session.info.setdefault(_SESSION_INFO_KEY, []).append((guild_id, advanced_tool_id))


def drain_purged_advanced_tools(session: Any) -> list[tuple[int, int]]:
    """Take (and clear) the queued pairs. Call after commit."""
    return session.info.pop(_SESSION_INFO_KEY, [])


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), digestmod=hashlib.sha256)
    mac.update(timestamp.encode("utf-8"))
    mac.update(b".")
    mac.update(body)
    return f"sha256={mac.hexdigest()}"


async def notify_purged_advanced_tools(pairs: list[tuple[int, int]]) -> None:
    """Tell the advanced tool's backend these rows are gone forever.

    No-op when the server-to-server link isn't configured. Failures are
    logged, never raised — see module docstring for why that is safe.
    """
    if not pairs:
        return
    if (
        not settings.ADVANCED_TOOL_BACKEND_URL
        or not settings.ADVANCED_TOOL_PURGE_SECRET
    ):
        return

    base = settings.ADVANCED_TOOL_BACKEND_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        for guild_id, advanced_tool_id in pairs:
            body = json.dumps(
                {"guild_id": guild_id, "advanced_tool_id": advanced_tool_id}
            ).encode("utf-8")
            timestamp = str(int(time.time()))
            headers = {
                "Content-Type": "application/json",
                "X-Initiative-Timestamp": timestamp,
                "X-Initiative-Signature": _sign(
                    settings.ADVANCED_TOOL_PURGE_SECRET, timestamp, body
                ),
            }
            try:
                response = await client.post(
                    f"{base}/automations/purged", content=body, headers=headers
                )
                if response.status_code >= 400:
                    logger.warning(
                        "advanced-tool purge notification rejected "
                        "(guild=%s tool=%s): %s %s",
                        guild_id,
                        advanced_tool_id,
                        response.status_code,
                        response.text[:200],
                    )
            except httpx.HTTPError as exc:
                logger.warning(
                    "advanced-tool purge notification failed (guild=%s tool=%s): %s",
                    guild_id,
                    advanced_tool_id,
                    exc,
                )

"""Fire-and-forget guild claim to the external billing service.

Names the user a newly created guild belongs to. Sent server-to-server at
creation, independently of the billing-portal tab the client opens; the service
treats the two as the same claim, so whichever arrives second changes nothing.

* the payload is one signed handoff token and nothing else — the user id and
  guild id travel inside it, never in the clear;
* no retry queue and no delivery guarantee;
* guild creation must never fail or slow because the service is down: the send
  runs as a detached task with a tight timeout and swallows every error.

FOSS balance: on a self-hosted install (``BILLING_SERVICE_URL`` /
``HANDOFF_SIGNING_PRIVATE_KEY_PEM`` unset — the default)
:func:`claim_new_guild` returns before doing anything: no outbound call, no
queued work, no logging.

The credential is the same RS256 billing-portal handoff a browser carries, so
the service authenticates a claim the way it authenticates the tab.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.core.config import settings
from app.core.security import (
    HandoffSigningNotConfiguredError,
    create_billing_portal_handoff_token,
)

logger = logging.getLogger(__name__)

CLAIM_PATH = "/api/v1/guilds/claim"

# The same short deadline the membership ping uses: this runs detached, but a
# hung connection would still hold a task and a socket for as long as it lasts.
_CLAIM_TIMEOUT = httpx.Timeout(3.0, connect=2.0)

# Strong references so an in-flight claim isn't garbage-collected mid-send
# (asyncio keeps only weak refs to tasks).
_pending_claims: set[asyncio.Task] = set()


def billing_claim_enabled() -> bool:
    """True only when a hosted deployment configured the outbound side.

    The claim's credential is the RS256 handoff, so it is the signing key that
    is required here rather than the ping's shared secret.
    """
    return bool(
        settings.BILLING_SERVICE_URL and settings.HANDOFF_SIGNING_PRIVATE_KEY_PEM
    )


async def _send_claim(user_id: int, guild_id: int) -> None:
    """One attempt, no retry; never raises."""
    try:
        token, _ = create_billing_portal_handoff_token(
            user_id=user_id, guild_id=guild_id, guild_role="admin"
        )
        url = settings.BILLING_SERVICE_URL.rstrip("/") + CLAIM_PATH
        async with httpx.AsyncClient(timeout=_CLAIM_TIMEOUT) as client:
            await client.post(url, json={"handoff_token": token})
    except HandoffSigningNotConfiguredError:
        # Checked before the task was spawned; only reachable if the setting
        # changed underneath us. Not worth a stack trace.
        logger.debug("billing: no handoff signing key; guild %s not claimed", guild_id)
    except Exception:
        logger.debug("billing: claim for guild %s failed", guild_id)


def claim_new_guild(*, user_id: int, guild_id: int) -> None:
    """Tell billing that ``user_id`` holds ``guild_id``.

    Call **after the guild's rows are committed**: the claim states that the
    guild exists, so it is dispatched once that is true.
    """
    if not billing_claim_enabled():
        return
    task = asyncio.create_task(_send_claim(int(user_id), int(guild_id)))
    _pending_claims.add(task)
    task.add_done_callback(_pending_claims.discard)

"""Domain event publisher.

Publishes encrypted event envelopes after domain mutations. The current
backend is AWS Kinesis; the inititative_infra automation engine consumes
the stream via a Beam pipeline. The module name stays implementation-
neutral so call sites don't move if the transport changes.

Gated by ENABLE_EVENT_PUBLISHING — when false, connect() is a no-op and
aioboto3 is never imported, so the OSS image can ship without it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.core.encryption import SALT_EVENT_PUBLISHER_PAYLOAD, encrypt_field

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
PARTITION_KEY_FIELD = "guild_id"  # see migration spec §6 — keeps per-tenant ordering

_session = None  # aioboto3.Session
_client_cm = None  # async context manager wrapping the kinesis client
_client = None  # active kinesis client
_background_tasks: set[asyncio.Task] = set()
# Latched once startup hits a non-recoverable misconfig (missing AWS_REGION
# or aioboto3). Without this, every dispatched event would re-enter connect()
# and re-emit the same error log line indefinitely.
_misconfigured = False


async def connect() -> None:
    """Open the Kinesis client on startup. No-op when the flag is off."""
    global _session, _client_cm, _client, _misconfigured

    if _misconfigured or not settings.ENABLE_EVENT_PUBLISHING:
        return

    if not settings.AWS_REGION:
        logger.error(
            "ENABLE_EVENT_PUBLISHING=true but AWS_REGION is not set; "
            "event publishing disabled until config is fixed and service restarted"
        )
        _misconfigured = True
        return

    try:
        import aioboto3
    except ImportError:
        logger.error(
            "ENABLE_EVENT_PUBLISHING=true but aioboto3 is not installed; "
            "rebuild with INSTALL_INFRA_EXTRAS=true or disable event publishing"
        )
        _misconfigured = True
        return

    try:
        _session = aioboto3.Session()
        client_kwargs: dict[str, Any] = {"region_name": settings.AWS_REGION}
        if settings.AWS_ENDPOINT_URL:
            client_kwargs["endpoint_url"] = settings.AWS_ENDPOINT_URL
        _client_cm = _session.client("kinesis", **client_kwargs)
        _client = await _client_cm.__aenter__()
        logger.info(
            "Kinesis publisher connected: stream=%s region=%s endpoint=%s",
            settings.KINESIS_STREAM_NAME,
            settings.AWS_REGION,
            settings.AWS_ENDPOINT_URL or "<aws default>",
        )
    except Exception as e:
        # Transient failures (network, AWS unreachable) — retry on next event.
        logger.warning("Could not initialize Kinesis client: %s", e)
        _client = None
        _client_cm = None


async def close() -> None:
    """Cancel in-flight publishes and close the Kinesis client on shutdown."""
    global _client, _client_cm, _session, _misconfigured

    for task in _background_tasks:
        task.cancel()
    _background_tasks.clear()

    if _client_cm is not None:
        try:
            await _client_cm.__aexit__(None, None, None)
        except Exception as e:
            logger.warning("Error closing Kinesis client: %s", e)
    _client = None
    _client_cm = None
    _session = None
    # Reset latch so a fresh process starts with a clean slate; the connect()
    # call on startup is what re-decides whether the env is healthy.
    _misconfigured = False


async def publish_event(
    event_type: str,
    payload: dict[str, Any],
    guild_id: int,
    initiative_id: int,
) -> bool:
    """Publish a domain event envelope to Kinesis (non-blocking).

    Returns True if scheduled, False if event publishing is disabled.
    Failures inside the background task are logged but never propagate —
    the API response must not depend on Kinesis availability.
    """
    if not settings.ENABLE_EVENT_PUBLISHING:
        return False

    envelope = _build_envelope(event_type, payload, guild_id, initiative_id)
    task = asyncio.create_task(_publish_background(envelope))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return True


def _build_envelope(
    event_type: str,
    payload: dict[str, Any],
    guild_id: int,
    initiative_id: int,
) -> dict[str, Any]:
    """Build the canonical event envelope.

    The payload is Fernet-encrypted (key derived from SECRET_KEY via HKDF
    with SALT_EVENT_PUBLISHER_PAYLOAD) so PHI never lands on the wire in
    plaintext. Top-level fields stay clear so consumers can route by
    event_type / guild_id without decrypting.
    """
    encrypted = encrypt_field(json.dumps(payload, default=str), SALT_EVENT_PUBLISHER_PAYLOAD)
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "guild_id": guild_id,
        "initiative_id": initiative_id,
        "actor_user_id": None,  # plumbed in a follow-up
        "payload_encrypted": encrypted,
    }


async def _publish_background(envelope: dict[str, Any]) -> None:
    """Background task — does not block the API response."""
    global _client

    if _misconfigured:
        # Already logged once at startup; subsequent events drop silently
        # so the log isn't flooded.
        return

    if _client is None:
        try:
            await connect()
        except Exception:
            pass

    if _client is None:
        logger.warning(
            "Event %s: Kinesis unavailable, dropping event", envelope["event_type"]
        )
        return

    try:
        await _client.put_record(
            StreamName=settings.KINESIS_STREAM_NAME,
            Data=json.dumps(envelope).encode("utf-8"),
            PartitionKey=str(envelope[PARTITION_KEY_FIELD]),
        )
        logger.debug(
            "Event %s published to %s",
            envelope["event_type"],
            settings.KINESIS_STREAM_NAME,
        )
    except Exception as e:
        logger.warning(
            "Failed to publish event %s: %s", envelope["event_type"], e
        )

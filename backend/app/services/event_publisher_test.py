"""Tests for the domain event publisher.

These tests cover the invariants that hold regardless of whether aioboto3
is installed or AWS is reachable:

  - Module imports cleanly when the flag is off.
  - publish_event is a no-op when the flag is off.
  - The canonical envelope has only the documented top-level fields.
  - PHI from the input payload never appears outside payload_encrypted.
"""

import json

import pytest

from app.core import encryption
from app.core.config import settings
from app.services import event_publisher


CANONICAL_ENVELOPE_KEYS = {
    "schema_version",
    "event_id",
    "event_type",
    "occurred_at",
    "guild_id",
    "initiative_id",
    "actor_user_id",
    "payload_encrypted",
}


@pytest.mark.unit
async def test_publish_event_returns_false_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_EVENT_PUBLISHING", False)
    result = await event_publisher.publish_event(
        "task_created",
        {"task_id": 1},
        guild_id=1,
        initiative_id=1,
    )
    assert result is False


@pytest.mark.unit
async def test_connect_is_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_EVENT_PUBLISHING", False)
    await event_publisher.connect()
    assert event_publisher._client is None


@pytest.mark.unit
async def test_misconfig_is_logged_once_then_latches(monkeypatch, caplog):
    """Missing AWS_REGION while ENABLE_EVENT_PUBLISHING=true must log the
    error exactly once. Subsequent connects + publishes drop silently — no
    repeated stack of error/warning lines per dispatched event."""
    monkeypatch.setattr(settings, "ENABLE_EVENT_PUBLISHING", True)
    monkeypatch.setattr(settings, "AWS_REGION", None)
    monkeypatch.setattr(event_publisher, "_misconfigured", False)
    monkeypatch.setattr(event_publisher, "_client", None)

    import logging
    with caplog.at_level(logging.ERROR, logger=event_publisher.logger.name):
        await event_publisher.connect()
        await event_publisher.connect()
        await event_publisher.connect()

    error_lines = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(error_lines) == 1, f"expected exactly 1 error log, got {len(error_lines)}"
    assert event_publisher._misconfigured is True


@pytest.mark.unit
def test_envelope_has_only_canonical_top_level_fields():
    envelope = event_publisher._build_envelope(
        "task_created",
        {"task_id": 1, "title": "anything"},
        guild_id=42,
        initiative_id=7,
    )
    assert set(envelope.keys()) == CANONICAL_ENVELOPE_KEYS


@pytest.mark.unit
def test_envelope_routing_fields_are_unencrypted():
    """event_type, guild_id, event_id, schema_version must stay readable so
    consumers can route without decrypting."""
    envelope = event_publisher._build_envelope(
        "task_created",
        {"task_id": 1},
        guild_id=42,
        initiative_id=7,
    )
    assert envelope["event_type"] == "task_created"
    assert envelope["guild_id"] == 42
    assert envelope["initiative_id"] == 7
    assert envelope["schema_version"] == event_publisher.SCHEMA_VERSION
    assert isinstance(envelope["event_id"], str)


@pytest.mark.unit
def test_payload_keys_do_not_leak_outside_encrypted_blob():
    """The whole reason for payload_encrypted: ensure no PHI-shaped key from
    the payload accidentally ends up at the envelope top level."""
    secret_keys = {"patient_name", "diagnosis_code", "ssn"}
    payload = {k: "highly-sensitive" for k in secret_keys}
    payload["task_id"] = 99

    envelope = event_publisher._build_envelope(
        "task_updated", payload, guild_id=1, initiative_id=1
    )

    top_level_keys = set(envelope.keys()) - {"payload_encrypted"}
    assert top_level_keys.isdisjoint(secret_keys)
    # And the plaintext values aren't sitting in some other field either.
    serialized_top_level = json.dumps({k: envelope[k] for k in top_level_keys})
    assert "highly-sensitive" not in serialized_top_level


@pytest.mark.unit
def test_payload_round_trips_through_encrypted_blob():
    payload = {"task_id": 99, "title": "draft", "nested": {"a": 1}}
    envelope = event_publisher._build_envelope(
        "task_updated", payload, guild_id=1, initiative_id=1
    )
    decrypted = encryption.decrypt_field(
        envelope["payload_encrypted"], encryption.SALT_EVENT_PUBLISHER_PAYLOAD
    )
    assert json.loads(decrypted) == payload


@pytest.mark.unit
def test_partition_key_field_is_guild_id():
    """Per the migration spec §6: per-tenant ordering requires guild_id partitioning."""
    assert event_publisher.PARTITION_KEY_FIELD == "guild_id"

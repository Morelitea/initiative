"""What a guild-app read payload discloses.

Two properties, pulling in opposite directions, and both are load-bearing.

**The pinned definition travels.** A reader — the settings page, and the
automation delegate on its delegated read — has to be able to say what *this*
install is, including the blocks this build assigns no meaning to. Serving the
snapshot the guild pinned rather than whatever the catalog holds today is what
makes that answer true of the install rather than of the listing.

**Stored values never do.** The definition describes the form; what was typed
into it lives in columns this payload does not read. Serializing one alongside
the other would be the single most natural way to leak a credential, so the test
reads the whole payload rather than checking the field somebody remembered.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.schemas.tenant.guild_app import serialize_guild_app

pytestmark = pytest.mark.unit

SECRET_CIPHERTEXT = "gAAAAAB-not-a-real-token"

DEFINITION = {
    "app_kind": "service",
    "service": {"public_id": "tests.shop", "protocol": 1},
    "features": ["events", "automations"],
    "connections": [
        {
            "id": "admin",
            "scope": "static",
            "fields": [{"key": "admin_token", "type": "secret", "required": True}],
        }
    ],
    "events": ["app.tests.shop.order_created"],
    # Opaque to this build by design: it belongs to the automation service,
    # which parses it off this same payload.
    "automation": {"nodes": [{"id": "low_stock"}]},
}


def _app(**overrides) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        **{
            "id": 3,
            "guild_id": 7,
            "listing_uid": "TESTAPP0000001",
            "listing_version": "1.2.0",
            "app_kind": "service",
            "name": "Shop",
            "enabled": True,
            "definition": DEFINITION,
            "config": {},
            "config_secrets": {"admin": {"admin_token": SECRET_CIPHERTEXT}},
            "config_state": "ok",
            "config_state_detail": None,
            "artifacts": [],
            # Every initiative, which is what an install that never narrowed it
            # says and what the serializer reads.
            "placement": {},
            "installed_by_id": 11,
            "created_at": now,
            "updated_at": now,
            **overrides,
        }
    )


def test_the_pinned_definition_is_passed_through_verbatim():
    payload = serialize_guild_app(_app())

    assert payload.definition == DEFINITION
    # Including the block this build never interprets — the delegate reads it
    # here rather than through an endpoint that would have to understand it.
    assert payload.definition["automation"] == {"nodes": [{"id": "low_stock"}]}


def test_the_config_state_the_app_reported_is_carried():
    """Until an app reports, an install has no verdict; once it does, the
    settings page can say whether the app is happy without leaving the app."""
    assert serialize_guild_app(_app()).config_state == "ok"
    assert (
        serialize_guild_app(
            _app(config_state="invalid", config_state_detail="missing_read_orders")
        ).config_state_detail
        == "missing_read_orders"
    )
    assert serialize_guild_app(_app(config_state="unverified")).config_state == (
        "unverified"
    )


def test_no_stored_value_appears_anywhere_in_the_payload():
    payload = serialize_guild_app(
        _app(config={"admin": {"shop_domain": "example.test"}})
    )

    serialized = payload.model_dump_json()
    assert SECRET_CIPHERTEXT not in serialized
    assert "config_secrets" not in serialized
    # The definition describes the field; it carries no value for it.
    assert payload.definition["connections"][0]["fields"][0]["key"] == "admin_token"
    assert "value" not in payload.definition["connections"][0]["fields"][0]


def test_needs_config_still_reads_from_presence():
    """A required guild-wide field with nothing in it is the one thing this
    build can know by itself, and it is unaffected by the passthrough."""
    assert serialize_guild_app(_app(config_secrets={})).needs_config is True
    assert serialize_guild_app(_app()).needs_config is False

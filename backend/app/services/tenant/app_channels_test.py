"""The two pure decisions behind the app channel.

Everything else in this module reaches a database, and the endpoint tests hold
that. What is worth pinning separately is the predicate that decides whether an
install belongs to the calling app — it is the whole of the isolation between
one app's credentials and another's — and the serializer that decides what an
app is told about an install it does own.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.tenant.app_channels import _summarize, owns_install

pytestmark = pytest.mark.unit

SHOP_UID = "TESTAPP0000001"


def _registration(public_id: str = "tests.shop", listing_uid: str | None = SHOP_UID):
    return SimpleNamespace(public_id=public_id, listing_uid=listing_uid)


def _app(
    *,
    listing_uid: str = SHOP_UID,
    service_id: str = "tests.shop",
    app_kind: str = "service",
):
    return SimpleNamespace(
        id=1,
        guild_id=2,
        listing_uid=listing_uid,
        listing_version="1.0.0",
        name="Shop",
        enabled=True,
        app_kind=app_kind,
        definition={
            "app_kind": app_kind,
            "service": {"public_id": service_id},
            "connections": [],
        },
        config={},
        config_secrets={},
        config_state="unverified",
        config_state_detail=None,
        updated_at=datetime.now(timezone.utc),
    )


class TestOwnsInstall:
    def test_a_matching_uid_and_service_id_is_ours(self):
        assert owns_install(_app(), _registration()) is True

    def test_another_listings_install_is_not_ours(self):
        theirs = _app(listing_uid="TESTAPP0000002")

        assert owns_install(theirs, _registration()) is False

    def test_an_install_pinning_another_service_is_not_ours(self):
        """The second condition, on its own. A registration re-pointed at a
        listing still cannot reach installs whose pinned definition names a
        different app."""
        assert owns_install(_app(service_id="tests.other"), _registration()) is False

    def test_a_registration_that_never_verified_owns_nothing(self):
        assert owns_install(_app(), _registration(listing_uid=None)) is False

    def test_a_non_service_install_is_never_ours(self):
        """An embed or a tool instance has no service behind it, so no
        registration speaks for it however its uid lines up."""
        assert owns_install(_app(app_kind="embed"), _registration()) is False

    def test_a_definition_without_a_service_block_is_not_ours(self):
        app = _app()
        app.definition = {"app_kind": "service"}

        assert owns_install(app, _registration()) is False


class TestSummary:
    def test_a_summary_carries_ids_and_state_only(self):
        """What an app reconciles against. Anything about the guild's people
        would be a second channel's answer arriving on this one."""
        summary = _summarize(_app())

        assert set(summary) == {
            "install_id",
            "guild_id",
            "listing_uid",
            "listing_version",
            "name",
            "enabled",
            "config_state",
            "config_state_detail",
            "needs_config",
            "updated_at",
        }
        assert summary["config_state"] == "unverified"

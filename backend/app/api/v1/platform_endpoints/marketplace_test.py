"""The routes that maintain the catalog.

Reading the marketplace is guild-addressed and covered by
``tenant_endpoints/marketplace_test.py``: what a guild is offered depends on
which apps it has installed.

What is left here is the operator's rescan of their own catalog directory —
deployment configuration rather than content, so it sits at the top of the
ladder with everything else that decides what this deployment is.
"""

import json

import pytest

from app.core.config import settings
from app.core.messages import MarketplaceMessages
from app.models.platform.guild import GuildRole


RESCAN_URL = "/api/v1/marketplace/operator-catalog/rescan"


def _manifest(**overrides) -> dict:
    manifest = {
        "uid": "0PRT0R00000001",
        "public_id": "acme.standup",
        "kind": "dashboard",
        "name": "Standup board",
        "publisher": "Acme",
        "description": "What everyone is on today.",
        "avatar_url": "/marketplace/acme-standup.svg",
        "version": "1.0.0",
        "definition": {
            "widgets": [
                {"id": "w1", "type": "stat", "binding": {"source": "task_counts"}}
            ]
        },
    }
    manifest.update(overrides)
    return manifest


@pytest.fixture
def catalog_dir(tmp_path, monkeypatch):
    directory = tmp_path / "marketplace"
    directory.mkdir()
    monkeypatch.setattr(settings, "MARKETPLACE_EXTRA_CATALOG_DIR", str(directory))
    return directory


class TestOperatorRescan:
    """Picking up a file that was dropped in, without a restart.

    The same scan the boot runs, so what an operator sees here is what a
    restart would have given them.
    """

    async def test_a_dropped_file_appears_without_a_restart(
        self, client, acting_user, catalog_dir
    ):
        (catalog_dir / "standup.json").write_text(
            json.dumps(_manifest()), encoding="utf-8"
        )
        # An operator who is also in a guild, so the listing can be read back
        # from the marketplace the way anyone would meet it.
        actor = await acting_user("owner", guild_role=GuildRole.admin)

        response = await client.post(RESCAN_URL, headers=actor.headers)

        assert response.status_code == 200
        assert response.json()["published"] == 1
        assert response.json()["problems"] == []

        page = await client.get(
            actor.g("/marketplace/listings/acme.standup"), headers=actor.headers
        )
        assert page.status_code == 200
        # Provenance travels with the listing: the marketplace shows this as
        # the operator's own addition, never as something shipped from here.
        assert page.json()["source"] == "operator"

    async def test_a_rescan_is_idempotent(self, client, acting_user, catalog_dir):
        (catalog_dir / "standup.json").write_text(
            json.dumps(_manifest()), encoding="utf-8"
        )
        actor = await acting_user("owner")

        first = await client.post(RESCAN_URL, headers=actor.headers)
        second = await client.post(RESCAN_URL, headers=actor.headers)

        assert first.json() == second.json()
        assert second.json()["withdrawn"] == 0

    async def test_a_skipped_file_is_reported_by_name(
        self, client, acting_user, catalog_dir
    ):
        """The operator who just edited the file is the one reading this, so
        the answer names the file rather than sending them to the server log."""
        (catalog_dir / "broken.json").write_text("{ not json", encoding="utf-8")
        actor = await acting_user("owner")

        response = await client.post(RESCAN_URL, headers=actor.headers)

        body = response.json()
        assert body["skipped"] == 1
        assert body["problems"][0]["file"] == "broken.json"
        assert body["problems"][0]["reason"]

    async def test_no_directory_configured_is_a_400(
        self, client, acting_user, monkeypatch
    ):
        monkeypatch.setattr(settings, "MARKETPLACE_EXTRA_CATALOG_DIR", None)
        actor = await acting_user("owner")

        response = await client.post(RESCAN_URL, headers=actor.headers)

        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == MarketplaceMessages.OPERATOR_CATALOG_NOT_CONFIGURED
        )

    async def test_a_directory_that_did_not_mount_is_a_400(
        self, client, acting_user, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            settings, "MARKETPLACE_EXTRA_CATALOG_DIR", str(tmp_path / "absent")
        )
        actor = await acting_user("owner")

        response = await client.post(RESCAN_URL, headers=actor.headers)

        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == MarketplaceMessages.OPERATOR_CATALOG_DIR_MISSING
        )

    @pytest.mark.parametrize("tier", ["member", "support", "moderator", "operator"])
    async def test_only_the_config_capability_may_rescan(
        self, client, acting_user, catalog_dir, tier
    ):
        """Publishing a listing decides what this deployment offers everyone
        on it, so it sits with app-wide configuration rather than with the
        tiers that read or moderate."""
        actor = await acting_user(tier)

        response = await client.post(RESCAN_URL, headers=actor.headers)

        assert response.status_code == 403

    async def test_a_rescan_needs_a_session(self, client, catalog_dir):
        assert (await client.post(RESCAN_URL)).status_code == 401

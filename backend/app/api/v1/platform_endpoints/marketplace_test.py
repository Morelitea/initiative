"""Browsing the catalog over HTTP, and the one route that writes it.

The catalog is platform-addressed and holds catalog metadata only, so any
authenticated session may read it — including a platform `member`, which is the
floor. The shape is structural: no guild column, and nothing about a listing
that a browse route can change.

The exception is the operator's rescan of their own catalog directory, which is
deployment configuration rather than content — so it sits at the top of the
ladder with everything else that decides what this deployment is.
"""

import json

import pytest

from app.core.config import settings
from app.core.messages import MarketplaceMessages
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.testing import (
    create_app_service_registration,
    create_marketplace_listing,
    marketplace_uid,
)


RESCAN_URL = "/api/v1/marketplace/operator-catalog/rescan"


@pytest.fixture
async def listing(session):
    return await create_marketplace_listing(
        session,
        uid="BRWSE000000001",
        public_id="tests.browse",
        name="Sprint health",
        publisher="Tests",
        description="How the sprint is going.",
        long_description="A longer page for the detail view.",
    )


class TestBrowse:
    async def test_any_authenticated_member_may_browse(
        self, client, acting_user, listing
    ):
        # The lowest platform tier: catalog metadata is not privileged.
        actor = await acting_user("member")
        response = await client.get(
            "/api/v1/marketplace/listings", headers=actor.headers
        )
        assert response.status_code == 200
        body = response.json()
        assert "tests.browse" in [item["public_id"] for item in body["items"]]
        assert body["total"] >= 1

    async def test_browsing_requires_a_session(self, client, listing):
        response = await client.get("/api/v1/marketplace/listings")
        assert response.status_code == 401

    async def test_a_card_carries_no_guild_anything(self, client, acting_user, listing):
        actor = await acting_user("member")
        response = await client.get(
            "/api/v1/marketplace/listings", headers=actor.headers
        )
        card = next(
            item
            for item in response.json()["items"]
            if item["public_id"] == "tests.browse"
        )
        # Structural, not incidental: the catalog has no column naming a
        # guild, so no payload built from it carries one.
        assert not any("guild" in key for key in card)
        assert card["installs_count"] == 0

    async def test_search_narrows_the_page(self, client, acting_user, listing):
        actor = await acting_user("member")
        hit = await client.get(
            "/api/v1/marketplace/listings",
            params={"q": "sprint"},
            headers=actor.headers,
        )
        assert [item["public_id"] for item in hit.json()["items"]] == ["tests.browse"]

        miss = await client.get(
            "/api/v1/marketplace/listings",
            params={"q": "nothing-matches"},
            headers=actor.headers,
        )
        assert miss.json()["items"] == []
        assert miss.json()["total"] == 0

    async def test_pages(self, client, acting_user, session):
        for index in range(3):
            await create_marketplace_listing(
                session,
                uid=f"PAGE000000000{index}",
                public_id=f"tests.page{index}",
                name=f"Paged {index}",
            )
        actor = await acting_user("member")
        response = await client.get(
            "/api/v1/marketplace/listings",
            params={"q": "Paged", "page": 2, "page_size": 2},
            headers=actor.headers,
        )
        body = response.json()
        assert body["total"] == 3
        assert len(body["items"]) == 1


class TestDetail:
    async def test_detail_carries_what_would_be_installed(
        self, client, acting_user, listing
    ):
        actor = await acting_user("member")
        response = await client.get(
            "/api/v1/marketplace/listings/tests.browse", headers=actor.headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["long_description"] == "A longer page for the detail view."
        assert body["definition"]["kind"] == "dashboard"
        # One app, one current version. The shelf offers the latest and
        # nothing else; which version an install is running, and upgrading
        # it, belong to guild settings.
        assert body["latest_version"]["version"] == "1.0.0"
        assert "versions" not in body
        assert body["installable"] is True

    async def test_a_uid_resolves_to_its_listing(self, client, acting_user, listing):
        """An installed dashboard stores the uid, not the public id, so this is
        how it finds the listing it came from."""
        actor = await acting_user("member")
        response = await client.get(
            "/api/v1/marketplace/listings/by-uid/BRWSE000000001", headers=actor.headers
        )
        assert response.status_code == 200
        assert response.json()["public_id"] == "tests.browse"
        assert response.json()["latest_version"]["version"] == "1.0.0"

    async def test_an_unknown_uid_is_a_404(self, client, acting_user, listing):
        actor = await acting_user("member")
        response = await client.get(
            "/api/v1/marketplace/listings/by-uid/NTHERE00000001",
            headers=actor.headers,
        )
        assert response.status_code == 404

    async def test_the_uid_route_is_not_read_as_a_public_id(
        self, client, acting_user, listing
    ):
        """`by-uid` is a literal segment, not a listing called 'by-uid'."""
        actor = await acting_user("member")
        response = await client.get(
            "/api/v1/marketplace/listings/by-uid", headers=actor.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == MarketplaceMessages.LISTING_NOT_FOUND

    async def test_an_unknown_listing_is_a_404(self, client, acting_user):
        actor = await acting_user("member")
        response = await client.get(
            "/api/v1/marketplace/listings/tests.nothing", headers=actor.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == MarketplaceMessages.LISTING_NOT_FOUND

    async def test_a_listing_needing_a_newer_app_says_so_rather_than_hiding(
        self, client, acting_user, session
    ):
        await create_marketplace_listing(
            session,
            uid="TNEW0000000001",
            public_id="tests.toonew",
            min_app_version="999.0.0",
        )
        actor = await acting_user("member")
        response = await client.get(
            "/api/v1/marketplace/listings/tests.toonew", headers=actor.headers
        )
        body = response.json()
        # Legible rather than absent: "upgrade the app" is a better answer than
        # a listing that silently isn't there.
        assert body["installable"] is False
        assert body["latest_version"]["compatible"] is False


class TestAnAppNeedsItsServiceRegistered:
    """What this deployment carries is narrower than what its catalog holds.

    A catalog reaches every deployment the same way, but an app is realized by
    a service the operator runs — so the registration is what says this one
    offers it. Until there is one, browse leaves the listing out and its page
    answers 404, which is what a guild admin needs: no shelf full of apps that
    would install into nothing.

    An app that mounts one of this build's own tools is the other half of the
    rule: nothing has to be wired up for it, so nothing gates it.
    """

    SERVICE_UID = marketplace_uid("serviceapp")
    TOOL_UID = marketplace_uid("toolapp")

    @pytest.fixture
    async def service_app(self, session):
        return await create_marketplace_listing(
            session,
            uid=self.SERVICE_UID,
            public_id="tests.shop",
            kind="app",
            name="Shop",
            definition={
                "app_kind": "service",
                "service": {"public_id": "tests.shop", "protocol": 1},
                "features": [],
            },
        )

    async def _shelf(self, client, actor) -> list[str]:
        response = await client.get(
            "/api/v1/marketplace/listings",
            params={"kind": "app"},
            headers=actor.headers,
        )
        assert response.status_code == 200, response.text
        return [item["public_id"] for item in response.json()["items"]]

    async def test_an_unwired_service_app_is_not_on_the_shelf(
        self, client, acting_user, service_app
    ):
        actor = await acting_user("member")
        assert "tests.shop" not in await self._shelf(client, actor)

    async def test_its_page_answers_the_same_as_a_listing_that_is_not_there(
        self, client, acting_user, service_app
    ):
        actor = await acting_user("member")
        for url in (
            "/api/v1/marketplace/listings/tests.shop",
            f"/api/v1/marketplace/listings/by-uid/{self.SERVICE_UID}",
        ):
            response = await client.get(url, headers=actor.headers)
            assert response.status_code == 404, url
            assert response.json()["detail"] == MarketplaceMessages.LISTING_NOT_FOUND

    async def test_wiring_the_service_up_puts_it_on_the_shelf(
        self, client, acting_user, session, service_app
    ):
        await create_app_service_registration(session, public_id="tests.shop")
        actor = await acting_user("member")
        assert "tests.shop" in await self._shelf(client, actor)
        response = await client.get(
            "/api/v1/marketplace/listings/tests.shop", headers=actor.headers
        )
        assert response.status_code == 200
        assert response.json()["installable"] is True

    async def test_the_kill_switch_takes_it_back_off(
        self, client, acting_user, session, service_app
    ):
        """Switched off is switched off everywhere, the shelf included."""
        registration = await create_app_service_registration(
            session, public_id="tests.shop"
        )
        registration.enabled = False
        session.add(registration)
        await session.commit()
        invalidate_registrations()

        actor = await acting_user("member")
        assert "tests.shop" not in await self._shelf(client, actor)
        response = await client.get(
            "/api/v1/marketplace/listings/tests.shop", headers=actor.headers
        )
        assert response.status_code == 404

    async def test_a_service_that_has_not_verified_yet_still_lists(
        self, client, acting_user, session, service_app
    ):
        """The operator's decision is the registration, not the handshake.

        A container that has not answered yet is the ordinary case on a fresh
        deployment, and a shelf that emptied whenever one restarted would be
        reporting something nobody chose. What an unverified service stops is
        what flows through it, which the install itself reports.
        """
        await create_app_service_registration(
            session, public_id="tests.shop", status="unverified"
        )
        actor = await acting_user("member")
        assert "tests.shop" in await self._shelf(client, actor)

    async def test_an_app_that_mounts_a_built_in_tool_needs_no_registration(
        self, client, acting_user, session
    ):
        await create_marketplace_listing(
            session,
            uid=self.TOOL_UID,
            public_id="tests.guild-calendar",
            kind="app",
            name="Guild calendar",
            definition={"app_kind": "tool_instance", "tool": "calendar"},
        )
        actor = await acting_user("member")
        assert "tests.guild-calendar" in await self._shelf(client, actor)


class TestAttribution:
    """Who publishes a listing, served with what bounds the claim.

    The name is what a manifest asserts and ``source`` is how the listing
    actually reached this deployment — which is what lets the client credit a
    shipped listing to this build rather than to whatever its manifest says.
    """

    async def test_a_card_carries_the_publisher_and_its_source(
        self, client, acting_user, session
    ):
        await create_marketplace_listing(
            session,
            # Crockford base32: no I, L, O or U.
            uid="ATTRBT00000001",
            public_id="tests.attributed",
            name="Attributed",
            publisher="Acme Widgets",
        )
        actor = await acting_user("member")
        response = await client.get(
            "/api/v1/marketplace/listings",
            params={"q": "Attributed"},
            headers=actor.headers,
        )
        card = response.json()["items"][0]
        assert card["publisher"] == "Acme Widgets"
        assert card["source"] == "builtin"

    async def test_the_detail_page_carries_them_too(self, client, acting_user, listing):
        # The page where the install decision is made reads the same two
        # fields as the card, so they cannot disagree.
        actor = await acting_user("member")
        response = await client.get(
            "/api/v1/marketplace/listings/tests.browse", headers=actor.headers
        )
        body = response.json()
        assert body["publisher"] == "Tests"
        assert body["source"] == "builtin"

    async def test_no_author_fields_are_served(self, client, acting_user, listing):
        """One required name, not a person and a distributor kept apart."""
        actor = await acting_user("member")
        body = (
            await client.get(
                "/api/v1/marketplace/listings/tests.browse", headers=actor.headers
            )
        ).json()
        assert not [key for key in body if key.startswith("author")]


class TestNoWrites:
    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    async def test_the_catalog_has_no_write_route(
        self, client, acting_user, listing, method
    ):
        actor = await acting_user("owner")
        # httpx's delete() takes no body, so go through request() uniformly.
        response = await client.request(
            method, "/api/v1/marketplace/listings", headers=actor.headers, json={}
        )
        # 405, not 403: there is no write route to authorize. The catalog's
        # only writer is the system engine.
        assert response.status_code == 405


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
        actor = await acting_user("owner")

        response = await client.post(RESCAN_URL, headers=actor.headers)

        assert response.status_code == 200
        assert response.json()["published"] == 1
        assert response.json()["problems"] == []

        browse = await client.get("/api/v1/marketplace/listings", headers=actor.headers)
        card = next(
            item
            for item in browse.json()["items"]
            if item["public_id"] == "acme.standup"
        )
        # Provenance travels with the listing: the marketplace shows this as
        # the operator's own addition, never as something shipped from here.
        assert card["source"] == "operator"

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

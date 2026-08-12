"""Browsing the catalog over HTTP.

The catalog is platform-addressed and holds catalog metadata only, so any
authenticated session may read it — including a platform `member`, which is the
floor. The shape is structural: no guild column, and no write route.
"""

import pytest

from app.core.messages import MarketplaceMessages
from app.testing import create_marketplace_listing

pytestmark = pytest.mark.asyncio


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
        assert [v["version"] for v in body["versions"]] == ["1.0.0"]
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

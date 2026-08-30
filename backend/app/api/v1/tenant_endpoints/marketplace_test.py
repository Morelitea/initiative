"""The marketplace shelf, browsed from inside a guild.

The catalog is platform data — no listing carries a guild — but *which* of it a
guild is offered is a guild question, so the shelf is addressed like every other
guild surface and answered on the guild-routed session.

The case that makes it one is the bundled dashboard: a dashboard an app ships
with itself draws that app's widgets, so it belongs on the shelf only where the
app is installed. Browse and install read the guild's installs the same way, so
a card that appears can be taken and one that does not was never offered.
"""

from typing import Any

import pytest

from app.core.messages import MarketplaceMessages
from app.models.platform.guild import GuildRole
from app.services.marketplace import catalog as catalog_service
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.testing import (
    create_app_service_registration,
    create_guild_app,
    create_marketplace_listing,
    marketplace_uid,
)


APP_UID = "TYG4VVZKAWRMBZ"
BUNDLED_UID = "J9H7S9T7GP7FAG"
STANDALONE_UID = "P3R9WT5HZ2NM6D"

#: The read a bundled tile draws, namespaced under the app's own service id.
OPEN_ITEMS = "app.tests.tracker.open-items"


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


def _tracker_manifest(with_dashboard: bool = True) -> dict:
    """An app that ships one dashboard with itself."""
    definition: dict[str, Any] = {
        "app_kind": "service",
        "service": {"public_id": "tests.tracker", "protocol": 1},
        "features": ["endpoints", "widgets"],
        "endpoints": [{"id": OPEN_ITEMS, "direction": "read"}],
        "widgets": [
            {
                "id": "open-items",
                "meta": {"name": {"en": "Open items"}},
                "module_source": "export default () => ({});",
                "endpoints": [OPEN_ITEMS],
            }
        ],
    }
    if with_dashboard:
        definition["features"] = [*definition["features"], "dashboards"]
        definition["dashboards"] = [
            {
                "uid": BUNDLED_UID,
                "public_id": "tests.tracker-overview",
                "name": "Tracker overview",
                "description": "At a glance.",
                "widgets": [
                    {
                        "type": "open-items",
                        "title": "Open",
                        "binding": {"endpoint_id": OPEN_ITEMS},
                    }
                ],
            }
        ]
    return {
        "uid": APP_UID,
        "public_id": "tests.tracker",
        "kind": "app",
        "name": "Tracker",
        "publisher": "Tests",
        "description": "Track the things.",
        "avatar_url": "/marketplace/tracker.svg",
        "version": "1.0.0",
        "definition": definition,
    }


async def _shelf(client, actor, **params) -> list[str]:
    response = await client.get(
        actor.g("/marketplace/listings"), params=params, headers=actor.headers
    )
    assert response.status_code == 200, response.text
    return [item["public_id"] for item in response.json()["items"]]


class TestBrowse:
    async def test_any_member_of_the_guild_may_browse(
        self, client, acting_user, listing
    ):
        # The lowest tier on both ladders: catalog metadata is not privileged.
        actor = await acting_user(guild_role=GuildRole.member)
        assert "tests.browse" in await _shelf(client, actor)

    async def test_browsing_requires_a_session(self, client, acting_user, listing):
        actor = await acting_user(guild_role=GuildRole.member)
        response = await client.get(actor.g("/marketplace/listings"))
        assert response.status_code == 401

    async def test_a_non_member_gets_nothing(self, client, acting_user, listing):
        """The shelf is reached through the guild, so it is bounded by it."""
        host = await acting_user(guild_role=GuildRole.admin)
        outsider = await acting_user(guild_role=GuildRole.member)
        response = await client.get(
            host.g("/marketplace/listings"), headers=outsider.headers
        )
        assert response.status_code == 403

    async def test_a_card_carries_no_guild_anything(self, client, acting_user, listing):
        actor = await acting_user(guild_role=GuildRole.member)
        response = await client.get(
            actor.g("/marketplace/listings"), headers=actor.headers
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
        actor = await acting_user(guild_role=GuildRole.member)
        response = await client.get(
            actor.g("/marketplace/listings"),
            params={"q": "Attributed"},
            headers=actor.headers,
        )
        card = response.json()["items"][0]
        assert card["publisher"] == "Acme Widgets"
        assert card["source"] == "builtin"

    async def test_search_narrows_the_page(self, client, acting_user, listing):
        actor = await acting_user(guild_role=GuildRole.member)
        assert await _shelf(client, actor, q="sprint") == ["tests.browse"]

        miss = await client.get(
            actor.g("/marketplace/listings"),
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
        actor = await acting_user(guild_role=GuildRole.member)
        response = await client.get(
            actor.g("/marketplace/listings"),
            params={"q": "Paged", "page": 2, "page_size": 2},
            headers=actor.headers,
        )
        body = response.json()
        assert body["total"] == 3
        assert len(body["items"]) == 1

    async def test_a_card_carries_the_version_it_would_install(
        self, client, acting_user, listing
    ):
        """Every card on a page reports its own latest version."""
        actor = await acting_user(guild_role=GuildRole.member)
        response = await client.get(
            actor.g("/marketplace/listings"), headers=actor.headers
        )
        cards = {item["public_id"]: item for item in response.json()["items"]}
        assert cards["tests.browse"]["latest_version"]["version"] == "1.0.0"
        assert cards["tests.browse"]["installable"] is True


class TestNoWrites:
    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    async def test_the_shelf_has_no_write_route(
        self, client, acting_user, listing, method
    ):
        actor = await acting_user(guild_role=GuildRole.admin)
        # httpx's delete() takes no body, so go through request() uniformly.
        response = await client.request(
            method,
            actor.g("/marketplace/listings"),
            headers=actor.headers,
            json={},
        )
        # 405, not 403: there is no write route to authorize. The catalog's
        # only writer is the system engine.
        assert response.status_code == 405


class TestABundledDashboardFollowsItsApp:
    """A dashboard an app ships with is offered where the app is.

    It draws that app's widgets, so anywhere else it would install as a canvas
    of tiles with nothing behind them. The rule is the guild's installs, which
    is why the shelf is addressed by guild at all.
    """

    @pytest.fixture
    async def published(self, session):
        await catalog_service.upsert_listing(
            session, _tracker_manifest(), source="operator"
        )
        await create_app_service_registration(session, public_id="tests.tracker")
        await session.commit()

    async def test_a_guild_without_the_app_is_not_offered_it(
        self, client, acting_user, published
    ):
        actor = await acting_user(guild_role=GuildRole.admin)
        assert "tests.tracker-overview" not in await _shelf(
            client, actor, kind="dashboard"
        )

    async def test_a_guild_with_the_app_is(
        self, client, acting_user, session, published
    ):
        actor = await acting_user(guild_role=GuildRole.admin)
        await create_guild_app(
            session,
            actor.guild,
            actor.user,
            definition={
                "app_kind": "service",
                "service": {"public_id": "tests.tracker"},
            },
            listing_uid=APP_UID,
        )
        assert "tests.tracker-overview" in await _shelf(client, actor, kind="dashboard")

    async def test_one_guild_installing_it_does_not_offer_it_to_another(
        self, client, acting_user, session, published
    ):
        """Two guilds, one catalog: the answer is per guild, not per catalog."""
        haves = await acting_user(guild_role=GuildRole.admin)
        await create_guild_app(
            session,
            haves.guild,
            haves.user,
            definition={
                "app_kind": "service",
                "service": {"public_id": "tests.tracker"},
            },
            listing_uid=APP_UID,
        )
        have_nots = await acting_user(guild_role=GuildRole.admin)

        assert "tests.tracker-overview" in await _shelf(client, haves, kind="dashboard")
        assert "tests.tracker-overview" not in await _shelf(
            client, have_nots, kind="dashboard"
        )

    async def test_switching_the_app_off_takes_it_back_off_the_shelf(
        self, client, acting_user, session, published
    ):
        actor = await acting_user(guild_role=GuildRole.admin)
        app = await create_guild_app(
            session,
            actor.guild,
            actor.user,
            definition={
                "app_kind": "service",
                "service": {"public_id": "tests.tracker"},
            },
            listing_uid=APP_UID,
        )
        assert "tests.tracker-overview" in await _shelf(client, actor, kind="dashboard")

        app.enabled = False
        session.add(app)
        await session.commit()

        assert "tests.tracker-overview" not in await _shelf(
            client, actor, kind="dashboard"
        )

    async def test_a_standalone_dashboard_is_offered_either_way(
        self, client, acting_user, session, published
    ):
        await create_marketplace_listing(
            session,
            uid=STANDALONE_UID,
            public_id="tests.shared-board",
            name="Shared board",
        )
        actor = await acting_user(guild_role=GuildRole.admin)
        assert "tests.shared-board" in await _shelf(client, actor, kind="dashboard")

    async def test_the_shelf_and_the_install_agree(
        self, client, acting_user, session, published
    ):
        """What is not offered cannot be taken by asking for it directly."""
        actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
        actor.initiative.dashboards_enabled = True
        session.add(actor.initiative)
        await session.commit()

        assert "tests.tracker-overview" not in await _shelf(
            client, actor, kind="dashboard"
        )

        response = await client.post(
            actor.g("/dashboards/"),
            json={
                "name": "Tracker overview",
                "initiative_id": actor.initiative.id,
                "listing_uid": BUNDLED_UID,
            },
            headers=actor.headers,
        )
        assert response.status_code == 409
        assert response.json()["detail"] == MarketplaceMessages.LISTING_NEEDS_APP


class TestAnAppNeedsItsServiceRegistered:
    """The shelf half of the rule.

    A catalog reaches every deployment the same way, but an app is realized by
    a service the operator runs — so the registration is what says this one
    offers it. Its listing page answers the same, which
    ``platform_endpoints/marketplace_test.py`` covers.

    An app that mounts one of this build's own tools is the other half: nothing
    has to be wired up for it, so nothing gates it.
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

    async def test_an_unwired_service_app_is_not_on_the_shelf(
        self, client, acting_user, service_app
    ):
        actor = await acting_user(guild_role=GuildRole.member)
        assert "tests.shop" not in await _shelf(client, actor, kind="app")

    async def test_wiring_the_service_up_puts_it_on_the_shelf(
        self, client, acting_user, session, service_app
    ):
        await create_app_service_registration(session, public_id="tests.shop")
        actor = await acting_user(guild_role=GuildRole.member)
        assert "tests.shop" in await _shelf(client, actor, kind="app")

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

        actor = await acting_user(guild_role=GuildRole.member)
        assert "tests.shop" not in await _shelf(client, actor, kind="app")

    async def test_a_service_that_has_not_verified_yet_still_lists(
        self, client, acting_user, session, service_app
    ):
        """The operator's decision is the registration, not the handshake.

        A container that has not answered yet is the ordinary case on a fresh
        deployment, and a shelf that emptied whenever one restarted would be
        reporting something nobody chose.
        """
        await create_app_service_registration(
            session, public_id="tests.shop", status="unverified"
        )
        actor = await acting_user(guild_role=GuildRole.member)
        assert "tests.shop" in await _shelf(client, actor, kind="app")

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
        actor = await acting_user(guild_role=GuildRole.member)
        assert "tests.guild-calendar" in await _shelf(client, actor, kind="app")

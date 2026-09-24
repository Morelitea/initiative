"""The marketplace, read from inside a guild.

The catalog is platform data — no listing carries a guild — but *which* of it a
guild is offered is a guild question, so the shelf and a listing's page are
addressed like every other guild surface and answered on the guild-routed
session.

The case that makes them one is the bundled dashboard: a dashboard an app ships
with itself draws that app's widgets, so it belongs where the app is installed
and nowhere else. All three surfaces read the guild's installs the same way, so
a card that appears opens a page that offers it and an install that takes it —
and one that does not appear is refused the same way at each step.
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

    async def test_its_page_answers_404_where_the_app_is_not_installed(
        self, client, acting_user, published
    ):
        """The page says what the shelf said by leaving it out."""
        actor = await acting_user(guild_role=GuildRole.admin)
        for url in (
            "/marketplace/listings/tests.tracker-overview",
            f"/marketplace/listings/by-uid/{BUNDLED_UID}",
        ):
            response = await client.get(actor.g(url), headers=actor.headers)
            assert response.status_code == 404, url
            assert response.json()["detail"] == MarketplaceMessages.LISTING_NOT_FOUND

    async def test_its_page_opens_where_the_app_is_installed(
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
        response = await client.get(
            actor.g("/marketplace/listings/tests.tracker-overview"),
            headers=actor.headers,
        )
        assert response.status_code == 200
        assert response.json()["installable"] is True

    async def test_removing_the_app_stops_an_update_being_offered(
        self, client, acting_user, session, published
    ):
        """An installed board looks its listing up by uid to see if there is a
        newer version. With the app gone there is nothing it could take, and
        the lookup says so rather than offering an upgrade that is refused."""
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
        by_uid = actor.g(f"/marketplace/listings/by-uid/{BUNDLED_UID}")
        assert (await client.get(by_uid, headers=actor.headers)).status_code == 200

        app.enabled = False
        session.add(app)
        await session.commit()

        assert (await client.get(by_uid, headers=actor.headers)).status_code == 404

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
    """What this deployment carries is narrower than what its catalog holds.

    A catalog reaches every deployment the same way, but an app is realized by
    a service the operator runs — so the registration is what says this one
    offers it. Until there is one the shelf leaves the listing out and its page
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

    async def test_its_page_answers_the_same_as_a_listing_that_is_not_there(
        self, client, acting_user, service_app
    ):
        actor = await acting_user(guild_role=GuildRole.member)
        for url in (
            "/marketplace/listings/tests.shop",
            f"/marketplace/listings/by-uid/{self.SERVICE_UID}",
        ):
            response = await client.get(actor.g(url), headers=actor.headers)
            assert response.status_code == 404, url
            assert response.json()["detail"] == MarketplaceMessages.LISTING_NOT_FOUND

    async def test_wiring_the_service_up_opens_its_page_too(
        self, client, acting_user, session, service_app
    ):
        await create_app_service_registration(session, public_id="tests.shop")
        actor = await acting_user(guild_role=GuildRole.member)
        response = await client.get(
            actor.g("/marketplace/listings/tests.shop"), headers=actor.headers
        )
        assert response.status_code == 200
        assert response.json()["installable"] is True

    async def test_an_app_that_mounts_a_built_in_tool_needs_no_registration(
        self, client, acting_user, session
    ):
        await create_marketplace_listing(
            session,
            uid=self.TOOL_UID,
            public_id="tests.guild-calendar",
            kind="app",
            name="Community calendar",
            definition={"app_kind": "tool_instance", "tool": "calendar"},
        )
        actor = await acting_user(guild_role=GuildRole.member)
        assert "tests.guild-calendar" in await _shelf(client, actor, kind="app")


class TestOneListingsPage:
    async def test_the_page_carries_what_would_be_installed(
        self, client, acting_user, listing
    ):
        actor = await acting_user(guild_role=GuildRole.member)
        response = await client.get(
            actor.g("/marketplace/listings/tests.browse"), headers=actor.headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["long_description"] == "A longer page for the detail view."
        # The dashboard's export envelope, around the canvas it installs.
        assert body["definition"]["type"] == "initiative-dashboard"
        assert body["definition"]["definition"]["kind"] == "dashboard"
        # One app, one current version. The shelf offers the latest and
        # nothing else; which version an install is running, and upgrading
        # it, belong to guild settings.
        assert body["latest_version"]["version"] == "1.0.0"
        assert "versions" not in body
        assert body["installable"] is True

    async def test_the_page_carries_the_publisher_and_its_source(
        self, client, acting_user, listing
    ):
        # The page where the install decision is made reads the same two
        # fields as the card does on the shelf, so they cannot disagree.
        actor = await acting_user(guild_role=GuildRole.member)
        body = (
            await client.get(
                actor.g("/marketplace/listings/tests.browse"), headers=actor.headers
            )
        ).json()
        assert body["publisher"] == "Tests"
        assert body["source"] == "builtin"

    async def test_no_author_fields_are_served(self, client, acting_user, listing):
        """One required name, not a person and a distributor kept apart."""
        actor = await acting_user(guild_role=GuildRole.member)
        body = (
            await client.get(
                actor.g("/marketplace/listings/tests.browse"), headers=actor.headers
            )
        ).json()
        assert not [key for key in body if key.startswith("author")]

    async def test_a_uid_resolves_to_its_listing(self, client, acting_user, listing):
        """An installed dashboard stores the uid, not the public id, so this is
        how it finds the listing it came from."""
        actor = await acting_user(guild_role=GuildRole.member)
        response = await client.get(
            actor.g("/marketplace/listings/by-uid/BRWSE000000001"),
            headers=actor.headers,
        )
        assert response.status_code == 200
        assert response.json()["public_id"] == "tests.browse"
        assert response.json()["latest_version"]["version"] == "1.0.0"

    async def test_an_unknown_uid_is_a_404(self, client, acting_user, listing):
        actor = await acting_user(guild_role=GuildRole.member)
        response = await client.get(
            actor.g("/marketplace/listings/by-uid/NTHERE00000001"),
            headers=actor.headers,
        )
        assert response.status_code == 404

    async def test_the_uid_route_is_not_read_as_a_public_id(
        self, client, acting_user, listing
    ):
        """`by-uid` is a literal segment, not a listing called 'by-uid'."""
        actor = await acting_user(guild_role=GuildRole.member)
        response = await client.get(
            actor.g("/marketplace/listings/by-uid"), headers=actor.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == MarketplaceMessages.LISTING_NOT_FOUND

    async def test_an_unknown_listing_is_a_404(self, client, acting_user):
        actor = await acting_user(guild_role=GuildRole.member)
        response = await client.get(
            actor.g("/marketplace/listings/tests.nothing"), headers=actor.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == MarketplaceMessages.LISTING_NOT_FOUND

    async def test_a_non_member_gets_nothing(self, client, acting_user, listing):
        host = await acting_user(guild_role=GuildRole.admin)
        outsider = await acting_user(guild_role=GuildRole.member)
        response = await client.get(
            host.g("/marketplace/listings/tests.browse"), headers=outsider.headers
        )
        assert response.status_code == 403

    async def test_a_listing_needing_a_newer_app_says_so_rather_than_hiding(
        self, client, acting_user, session
    ):
        await create_marketplace_listing(
            session,
            uid="TNEW0000000001",
            public_id="tests.toonew",
            min_app_version="999.0.0",
        )
        actor = await acting_user(guild_role=GuildRole.member)
        body = (
            await client.get(
                actor.g("/marketplace/listings/tests.toonew"), headers=actor.headers
            )
        ).json()
        # Legible rather than absent: "upgrade the app" is a better answer than
        # a listing that silently isn't there.
        assert body["installable"] is False
        assert body["latest_version"]["compatible"] is False


#: A counter group a publisher shares: the blank template installs empty, the
#: example the way they filled it in.
COUNTERS_UID = "C0VNTERS000001"


def _counter_envelope(*counts: float) -> dict:
    return {
        "type": "initiative-counter-group",
        "name": "Whatever the file called it",
        "description": "Tally of the party's resources.",
        "counters": [
            {"name": name, "count": count}
            for name, count in zip(("Hit points", "Spell slots"), counts)
        ],
    }


async def _counter_listing(session, *, example: bool = True):
    return await create_marketplace_listing(
        session,
        uid=COUNTERS_UID,
        public_id="tests.party-tally",
        kind="counter_group",
        name="Party tally",
        definition=_counter_envelope(0, 0),
        example=_counter_envelope(27, 3) if example else None,
    )


async def _counters_on(session, initiative):
    initiative.counter_groups_enabled = True
    session.add(initiative)
    await session.commit()


async def _read_group(session, guild_id: int, group_id: int):
    from sqlmodel import select

    from app.models.tenant.counter import Counter, CounterGroup
    from app.testing import route_session_to_guild

    await route_session_to_guild(session, guild_id)
    group = (
        await session.exec(select(CounterGroup).where(CounterGroup.id == group_id))
    ).one()
    counts = sorted(
        (
            await session.exec(
                select(Counter.count).where(Counter.counter_group_id == group_id)
            )
        ).all()
    )
    return group, counts


class TestInstallingAToolListing:
    """A tool's listing installs through that tool's importer, as the member."""

    async def test_a_member_who_may_create_it_installs_a_copy(
        self, client, acting_user, session
    ):
        # A guild member, not an admin: what lets them is the initiative
        # role's permission to create counter groups.
        member = await acting_user(guild_role=GuildRole.member, initiative=True)
        await _counters_on(session, member.initiative)
        await _counter_listing(session)

        response = await client.post(
            member.g(f"/marketplace/listings/by-uid/{COUNTERS_UID}/install"),
            json={"initiative_id": member.initiative.id},
            headers=member.headers,
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["kind"] == "counter_group"
        assert body["listing_version"] == "1.0.0"
        group, counts = await _read_group(
            session, member.guild.id, body["result"]["entity_id"]
        )
        # Called what the listing is called, and it remembers where it came from.
        assert group.name == "Party tally"
        assert (group.listing_uid, group.listing_version) == (COUNTERS_UID, "1.0.0")
        assert counts == [0, 0]

    async def test_it_may_start_from_the_example(self, client, acting_user, session):
        actor = await acting_user(guild_role=GuildRole.member, initiative=True)
        await _counters_on(session, actor.initiative)
        await _counter_listing(session)

        response = await client.post(
            actor.g(f"/marketplace/listings/by-uid/{COUNTERS_UID}/install"),
            json={"initiative_id": actor.initiative.id, "start_from": "example"},
            headers=actor.headers,
        )

        assert response.status_code == 201, response.text
        _, counts = await _read_group(
            session, actor.guild.id, response.json()["result"]["entity_id"]
        )
        assert counts == [3, 27]

    async def test_there_is_no_example_to_start_from_unless_it_has_one(
        self, client, acting_user, session
    ):
        actor = await acting_user(guild_role=GuildRole.member, initiative=True)
        await _counters_on(session, actor.initiative)
        await _counter_listing(session, example=False)

        response = await client.post(
            actor.g(f"/marketplace/listings/by-uid/{COUNTERS_UID}/install"),
            json={"initiative_id": actor.initiative.id, "start_from": "example"},
            headers=actor.headers,
        )

        assert response.status_code == 409
        assert response.json()["detail"] == MarketplaceMessages.LISTING_HAS_NO_EXAMPLE

    async def test_the_detail_page_carries_the_example(
        self, client, acting_user, session
    ):
        actor = await acting_user(guild_role=GuildRole.member)
        await _counter_listing(session)

        response = await client.get(
            actor.g(f"/marketplace/listings/by-uid/{COUNTERS_UID}"),
            headers=actor.headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["kind"] == "counter_group"
        assert [c["count"] for c in body["example"]["counters"]] == [27, 3]

    async def test_a_tool_switched_off_takes_no_install(
        self, client, acting_user, session
    ):
        actor = await acting_user(guild_role=GuildRole.member, initiative=True)
        actor.initiative.counter_groups_enabled = False
        session.add(actor.initiative)
        await session.commit()
        await _counter_listing(session)

        response = await client.post(
            actor.g(f"/marketplace/listings/by-uid/{COUNTERS_UID}/install"),
            json={"initiative_id": actor.initiative.id},
            headers=actor.headers,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "IMPORT_TOOL_DISABLED"

    async def test_an_initiative_the_member_is_not_in_takes_no_install(
        self, client, acting_user, session
    ):
        owner = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await _counters_on(session, owner.initiative)
        outsider = await acting_user(guild_role=GuildRole.member, guild=owner.guild)
        await _counter_listing(session)

        response = await client.post(
            outsider.g(f"/marketplace/listings/by-uid/{COUNTERS_UID}/install"),
            json={"initiative_id": owner.initiative.id},
            headers=outsider.headers,
        )

        # The importer's own answer: a guild member may see the initiative,
        # and holds no role in it that creates anything.
        assert response.status_code == 403
        assert response.json()["detail"] == "IMPORT_PERMISSION_REQUIRED"

    async def test_an_app_is_not_installed_here(self, client, acting_user, session):
        actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await catalog_service.upsert_listing(
            session, _tracker_manifest(with_dashboard=False), source="builtin"
        )
        await session.commit()

        response = await client.post(
            actor.g(f"/marketplace/listings/by-uid/{APP_UID}/install"),
            json={"initiative_id": actor.initiative.id},
            headers=actor.headers,
        )

        assert response.status_code == 404
        assert response.json()["detail"] == MarketplaceMessages.LISTING_NOT_FOUND

    async def test_a_dashboard_listing_installs_through_the_same_path(
        self, client, acting_user, session, listing
    ):
        from sqlmodel import select

        from app.models.tenant.dashboard import Dashboard
        from app.testing import route_session_to_guild

        actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
        actor.initiative.dashboards_enabled = True
        session.add(actor.initiative)
        await session.commit()

        response = await client.post(
            actor.g(f"/marketplace/listings/by-uid/{listing.uid}/install"),
            json={"initiative_id": actor.initiative.id},
            headers=actor.headers,
        )

        assert response.status_code == 201, response.text
        await route_session_to_guild(session, actor.guild.id)
        dashboard = (
            await session.exec(
                select(Dashboard).where(
                    Dashboard.id == response.json()["result"]["entity_id"]
                )
            )
        ).one()
        assert dashboard.name == "Sprint health"
        assert dashboard.listing_uid == listing.uid
        assert dashboard.definition["widgets"][0]["type"] == "stat"

"""Installing an app, and what that gives the guild.

Two things carry the weight.

An app mounts an *existing* tool at guild scope — installing the guild calendar
creates an ordinary `calendars` row with no initiative, not a parallel thing. So
the tests assert on the calendar: that it exists, that it belongs to no
initiative, and that a plain member of the guild — who is in no initiative at
all — can actually read it. That last one is the whole point of guild scope, and
it is the assertion that would fail if any layer still assumed a row must name
an initiative.

The other is who may do this. Installing mounts a guild-wide surface, so it is a
guild-admin action; reading the list is not, because the sidebar has to know
what is there.

An embed app is the other shape: it brings no content, so there is nothing to
create, share or trash, and the answer to "who may open this" comes back on the
app itself rather than from grants that do not exist.
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import GuildAppMessages, MarketplaceMessages
from app.models.platform.guild import GuildRole
from app.models.tenant.calendar import Calendar
from app.testing import (
    create_marketplace_listing,
    marketplace_uid,
    route_session_to_guild,
)

pytestmark = pytest.mark.asyncio

CALENDAR_APP_UID = marketplace_uid("guildcalendar")


def _app_definition(tool: str = "calendar") -> dict:
    return {"app_kind": "tool_instance", "tool": tool, "default_name": "Guild calendar"}


@pytest.fixture
async def calendar_app(session):
    return await create_marketplace_listing(
        session,
        uid=CALENDAR_APP_UID,
        public_id="core.guild-calendar",
        kind="app",
        name="Guild calendar",
        definition=_app_definition(),
    )


async def _read_calendar(
    session: AsyncSession,
    guild_id: int,
    calendar_id: int,
    *,
    include_deleted: bool = False,
):
    """Read the calendar the install created, directly.

    Two things a request would do for us: the test session is not routed by
    itself (guild content lives in that guild's schema), and soft-deleted rows
    are filtered out of ordinary queries — so asserting that uninstalling
    *trashed* rather than deleted has to opt back in.
    """
    await route_session_to_guild(session, guild_id)
    statement = select(Calendar).where(Calendar.id == calendar_id)
    if include_deleted:
        statement = statement.execution_options(include_deleted=True)
    return (await session.exec(statement)).first()


async def _install(client: AsyncClient, actor, **body) -> dict:
    response = await client.post(
        actor.g("/apps/"),
        headers=actor.headers,
        json={"listing_uid": CALENDAR_APP_UID, **body},
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestInstall:
    async def test_installing_mounts_a_guild_level_calendar(
        self, client: AsyncClient, acting_user, session: AsyncSession, calendar_app
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(client, a)

        assert app["app_kind"] == "tool_instance"
        assert app["tool"] == "calendar"
        assert app["listing_version"] == "1.0.0"
        assert app["enabled"] is True

        calendar = await _read_calendar(
            session, a.guild.id, app["config"]["calendar_id"]
        )
        assert calendar is not None
        # Belongs to the guild, not to any initiative — which is what an app is.
        assert calendar.initiative_id is None
        assert calendar.guild_id == a.guild.id

    async def test_the_name_can_be_chosen_at_install(
        self, client: AsyncClient, acting_user, session: AsyncSession, calendar_app
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(client, a, name="Club nights")
        assert app["name"] == "Club nights"
        calendar = await _read_calendar(
            session, a.guild.id, app["config"]["calendar_id"]
        )
        assert calendar.name == "Club nights"

    async def test_only_a_guild_admin_may_install(
        self, client: AsyncClient, acting_user, calendar_app
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        response = await client.post(
            member.g("/apps/"),
            headers=member.headers,
            json={"listing_uid": CALENDAR_APP_UID},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == GuildAppMessages.ADMIN_REQUIRED

    async def test_a_listing_that_is_not_an_app_is_a_404(
        self, client: AsyncClient, acting_user, session
    ):
        # A dashboard listing installs through the dashboards endpoint; asking
        # the apps endpoint for one is asking for something that isn't there.
        await create_marketplace_listing(
            session, uid=marketplace_uid("dashnotapp"), public_id="tests.dash"
        )
        a = await acting_user(guild_role=GuildRole.admin)
        response = await client.post(
            a.g("/apps/"),
            headers=a.headers,
            json={"listing_uid": marketplace_uid("dashnotapp")},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == MarketplaceMessages.LISTING_NOT_FOUND

    async def test_installing_twice_is_refused(
        self, client: AsyncClient, acting_user, calendar_app
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        await _install(client, a)
        again = await client.post(
            a.g("/apps/"), headers=a.headers, json={"listing_uid": CALENDAR_APP_UID}
        )
        assert again.status_code == 409
        assert again.json()["detail"] == GuildAppMessages.ALREADY_INSTALLED

    async def test_each_guild_installs_its_own(
        self, client: AsyncClient, acting_user, session: AsyncSession, calendar_app
    ):
        """One install per listing is per *guild* — the catalog is shared, the
        installs are not.

        Not asserted on the ids: each guild has its own schema, so both
        calendars are legitimately id 1. What matters is that each guild has a
        calendar of its own, in its own schema.
        """
        a = await acting_user(guild_role=GuildRole.admin)
        b = await acting_user(guild_role=GuildRole.admin)
        first = await _install(client, a)
        second = await _install(client, b)

        for actor, app in ((a, first), (b, second)):
            calendar = await _read_calendar(
                session, actor.guild.id, app["config"]["calendar_id"]
            )
            assert calendar is not None
            assert calendar.guild_id == actor.guild.id


class TestVisibility:
    async def test_a_member_in_no_initiative_can_read_the_calendar(
        self, client: AsyncClient, acting_user, calendar_app
    ):
        """The point of guild scope: a member who belongs to no initiative still
        reaches the guild's own calendar, because it belongs to no initiative
        either."""
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(client, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        response = await client.get(
            member.g(f"/calendars/{app['config']['calendar_id']}"),
            headers=member.headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["initiative_id"] is None

    async def test_a_member_can_list_the_apps(
        self, client: AsyncClient, acting_user, calendar_app
    ):
        # The sidebar has to know what is installed; that is not privileged.
        a = await acting_user(guild_role=GuildRole.admin)
        await _install(client, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        response = await client.get(member.g("/apps/"), headers=member.headers)
        assert response.status_code == 200
        assert [item["tool"] for item in response.json()["items"]] == ["calendar"]

    async def test_another_guild_sees_nothing(
        self, client: AsyncClient, acting_user, calendar_app
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        await _install(client, a)
        stranger = await acting_user(guild_role=GuildRole.admin)

        response = await client.get(stranger.g("/apps/"), headers=stranger.headers)
        assert response.json()["items"] == []


class TestManage:
    async def test_renaming_and_disabling(
        self, client: AsyncClient, acting_user, calendar_app
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(client, a)

        response = await client.patch(
            a.g(f"/apps/{app['id']}"),
            headers=a.headers,
            json={"name": "Renamed", "enabled": False},
        )
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Renamed"
        assert response.json()["enabled"] is False

    async def test_disabling_leaves_the_content_alone(
        self, client: AsyncClient, acting_user, calendar_app
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(client, a)
        await client.patch(
            a.g(f"/apps/{app['id']}"), headers=a.headers, json={"enabled": False}
        )
        # Turning an app off hides it; it does not throw anything away.
        response = await client.get(
            a.g(f"/calendars/{app['config']['calendar_id']}"), headers=a.headers
        )
        assert response.status_code == 200

    async def test_only_a_guild_admin_may_manage(
        self, client: AsyncClient, acting_user, calendar_app
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(client, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        patched = await client.patch(
            member.g(f"/apps/{app['id']}"), headers=member.headers, json={"name": "no"}
        )
        assert patched.status_code == 403
        removed = await client.delete(
            member.g(f"/apps/{app['id']}"), headers=member.headers
        )
        assert removed.status_code == 403


class TestUninstall:
    async def test_removing_an_app_trashes_what_it_made(
        self, client: AsyncClient, acting_user, session: AsyncSession, calendar_app
    ):
        """Trashed, not deleted: whatever the guild put in that calendar should
        survive an admin removing the app."""
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(client, a)
        calendar_id = app["config"]["calendar_id"]

        response = await client.delete(a.g(f"/apps/{app['id']}"), headers=a.headers)
        assert response.status_code == 204

        assert (await client.get(a.g("/apps/"), headers=a.headers)).json()[
            "items"
        ] == []
        calendar = await _read_calendar(
            session, a.guild.id, calendar_id, include_deleted=True
        )
        assert calendar is not None
        assert calendar.deleted_at is not None
        # And gone from the ordinary view, like anything else in the trash.
        assert await _read_calendar(session, a.guild.id, calendar_id) is None

    async def test_the_listing_can_be_installed_again_afterwards(
        self, client: AsyncClient, acting_user, calendar_app
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(client, a)
        await client.delete(a.g(f"/apps/{app['id']}"), headers=a.headers)
        # The one-install rule is about what is currently mounted, not a
        # permanent claim on the listing.
        again = await _install(client, a)
        assert again["config"]["calendar_id"] != app["config"]["calendar_id"]


EMBED_APP_UID = marketplace_uid("advancedtool")


@pytest.fixture
async def embed_app(session):
    return await create_marketplace_listing(
        session,
        uid=EMBED_APP_UID,
        public_id="core.advanced-tool",
        kind="app",
        name="Automations",
        definition={"app_kind": "embed", "embed_target": "advanced_tool"},
    )


class TestEmbedApp:
    async def test_installing_creates_no_content(
        self, client: AsyncClient, acting_user, session: AsyncSession, embed_app
    ):
        """The surface it opens already exists, wherever the operator pointed
        it. The app row is the whole install."""
        a = await acting_user(guild_role=GuildRole.admin)
        response = await client.post(
            a.g("/apps/"), headers=a.headers, json={"listing_uid": EMBED_APP_UID}
        )
        assert response.status_code == 201, response.text
        app = response.json()

        assert app["app_kind"] == "embed"
        assert app["embed_target"] == "advanced_tool"
        assert app["tool"] is None
        assert app["config"] == {}
        assert app["name"] == "Automations"

        await route_session_to_guild(session, a.guild.id)
        assert (await session.exec(select(Calendar))).all() == []

    async def test_it_reports_itself_as_admin_only(
        self, client: AsyncClient, acting_user, embed_app
    ):
        """A member is told not to bother: the endpoint that mints its handoff
        is admin-only, so an entry offered to everyone would refuse most of
        them. Decided here rather than by the client reading the kind."""
        a = await acting_user(guild_role=GuildRole.admin)
        await client.post(
            a.g("/apps/"), headers=a.headers, json={"listing_uid": EMBED_APP_UID}
        )
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        response = await client.get(member.g("/apps/"), headers=member.headers)
        assert response.status_code == 200
        assert [item["admin_only"] for item in response.json()["items"]] == [True]

    async def test_a_mounted_tool_is_not_admin_only(
        self, client: AsyncClient, acting_user, calendar_app
    ):
        # It has grants of its own, which can say more than a flag can.
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(client, a)
        assert app["admin_only"] is False
        assert app["embed_target"] is None

    async def test_removing_it_takes_only_the_entry(
        self, client: AsyncClient, acting_user, embed_app
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        installed = await client.post(
            a.g("/apps/"), headers=a.headers, json={"listing_uid": EMBED_APP_UID}
        )
        app_id = installed.json()["id"]

        response = await client.delete(a.g(f"/apps/{app_id}"), headers=a.headers)
        assert response.status_code == 204
        assert (await client.get(a.g("/apps/"), headers=a.headers)).json()[
            "items"
        ] == []

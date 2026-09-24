"""Apps the deployment places into every guild.

The behaviour is one sentence — a registration marked ``mandatory`` is installed
everywhere — and the tests are about the edges around it, because those are what
make it usable in production:

* **A new guild gets it as it is created**, through the real creation path, so
  nobody has to remember to run anything.
* **An existing guild gets it at boot**, which is the only way a flag set today
  reaches guilds created last year.
* **Twice is once.** The sweep is idempotent; a guild that already has the app
  is left exactly as it was, configuration and all.
* **Nothing here fails a guild creation.** An app whose listing has not arrived
  is a gap the next boot closes, not a reason a guild cannot exist.
* **The kill switch outranks the flag**, and clearing the flag deletes nothing.
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.tenant.app_placement import AppPlacement
from app.models.tenant.guild_app import GuildApp
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.services.tenant.initiatives import get_moderator_role
from app.services.tenant.mandatory_apps import backfill_mandatory_apps
from app.testing import (
    create_app_service_registration,
    create_guild,
    create_guild_app,
    create_guild_membership,
    create_initiative,
    create_marketplace_listing,
    create_user,
    get_auth_headers,
    marketplace_uid,
    route_session_to_guild,
)


PROVIDED_ID = "platform.provided"
PROVIDED_UID = marketplace_uid("provided")

PROVIDED_DEFINITION = {
    "app_kind": "service",
    "service": {"public_id": PROVIDED_ID, "protocol": 1},
    "features": [],
    "default_name": "Provided app",
}


@pytest.fixture
async def provided_listing(session: AsyncSession):
    return await create_marketplace_listing(
        session,
        uid=PROVIDED_UID,
        public_id=PROVIDED_ID,
        kind="app",
        name="Provided app",
        definition=PROVIDED_DEFINITION,
    )


@pytest.fixture
async def mandatory_registration(session: AsyncSession, provided_listing):
    return await create_app_service_registration(
        session,
        public_id=PROVIDED_ID,
        base_url="https://provided.example.test",
        listing_uid=PROVIDED_UID,
        mandatory=True,
    )


async def _installed_apps(session: AsyncSession, guild_id: int) -> list[GuildApp]:
    await route_session_to_guild(session, guild_id)
    return list(
        (
            await session.exec(
                select(GuildApp).execution_options(populate_existing=True)
            )
        ).all()
    )


class TestAtGuildCreation:
    async def test_a_new_guild_gets_the_app(
        self, client: AsyncClient, session: AsyncSession, mandatory_registration
    ):
        """Through the real creation path: nobody installs it, and nobody was
        offered a choice."""
        user = await create_user(session, email="founder@example.com")
        response = await client.post(
            "/api/v1/guilds/",
            headers=get_auth_headers(user),
            json={"name": "Fresh guild"},
        )
        assert response.status_code == 201, response.text
        guild_id = response.json()["id"]

        apps = await _installed_apps(session, guild_id)
        assert [app.listing_uid for app in apps] == [PROVIDED_UID]
        assert apps[0].name == "Provided app"
        assert apps[0].app_kind == "service"
        # No local content: a service app's install is the row and its pinned
        # definition.
        assert apps[0].artifacts == []

    async def test_a_registration_switched_off_installs_nowhere(
        self, client: AsyncClient, session: AsyncSession, mandatory_registration
    ):
        mandatory_registration.enabled = False
        session.add(mandatory_registration)
        await session.commit()
        invalidate_registrations()

        user = await create_user(session, email="founder2@example.com")
        response = await client.post(
            "/api/v1/guilds/",
            headers=get_auth_headers(user),
            json={"name": "Quiet guild"},
        )
        assert response.status_code == 201, response.text

        assert await _installed_apps(session, response.json()["id"]) == []

    async def test_a_missing_listing_does_not_fail_the_creation(
        self, client: AsyncClient, session: AsyncSession
    ):
        """The install is a local row; an app whose listing this deployment does
        not hold yet is a gap the next boot closes."""
        await create_app_service_registration(
            session,
            public_id="platform.absent",
            base_url="https://absent.example.test",
            listing_uid=marketplace_uid("absent"),
            mandatory=True,
        )
        user = await create_user(session, email="founder3@example.com")

        response = await client.post(
            "/api/v1/guilds/",
            headers=get_auth_headers(user),
            json={"name": "Still created"},
        )
        assert response.status_code == 201, response.text
        assert await _installed_apps(session, response.json()["id"]) == []

    async def test_nothing_mandatory_means_nothing_installed(
        self, client: AsyncClient, session: AsyncSession, provided_listing
    ):
        """A deployment that registered nothing compulsory sees no trace of any
        of this."""
        await create_app_service_registration(
            session,
            public_id=PROVIDED_ID,
            base_url="https://provided.example.test",
            listing_uid=PROVIDED_UID,
            mandatory=False,
        )
        user = await create_user(session, email="founder4@example.com")

        response = await client.post(
            "/api/v1/guilds/",
            headers=get_auth_headers(user),
            json={"name": "Ordinary guild"},
        )
        assert response.status_code == 201, response.text
        assert await _installed_apps(session, response.json()["id"]) == []


class TestBackfill:
    async def test_a_guild_that_predates_the_flag_gets_it(
        self, session: AsyncSession, mandatory_registration
    ):
        """The only way a decision made today reaches a guild made last year."""
        creator = await create_user(session, email="old@example.com")
        guild = await create_guild(session, creator=creator, name="Existing guild")
        await create_guild_membership(
            session, user=creator, guild=guild, role=GuildRole.admin
        )

        result = await backfill_mandatory_apps()
        assert result.installed == 1
        assert result.failed == 0

        apps = await _installed_apps(session, guild.id)
        assert [app.listing_uid for app in apps] == [PROVIDED_UID]
        # Recorded against a guild admin: an app they did not choose is still
        # one they are responsible for.
        assert apps[0].created_by == creator.id

    async def test_several_guilds_each_get_their_own(
        self, session: AsyncSession, mandatory_registration
    ):
        """The sweep walks guild schemas with one session, and ids restart at 1
        in each of them — so the second guild must not be answered with the
        first guild's install still sitting in the identity map."""
        guilds = []
        for index in range(3):
            creator = await create_user(session, email=f"many{index}@example.com")
            guild = await create_guild(session, creator=creator, name=f"Guild {index}")
            await create_guild_membership(
                session, user=creator, guild=guild, role=GuildRole.admin
            )
            guilds.append(guild)

        result = await backfill_mandatory_apps()

        assert (result.installed, result.failed) == (3, 0)
        for guild in guilds:
            apps = await _installed_apps(session, guild.id)
            assert [app.listing_uid for app in apps] == [PROVIDED_UID], (
                f"guild {guild.id} did not get its own install"
            )

    async def test_running_it_twice_installs_once(
        self, session: AsyncSession, mandatory_registration
    ):
        creator = await create_user(session, email="twice@example.com")
        guild = await create_guild(session, creator=creator, name="Twice guild")
        await create_guild_membership(
            session, user=creator, guild=guild, role=GuildRole.admin
        )

        await backfill_mandatory_apps()
        second = await backfill_mandatory_apps()

        assert second.installed == 0
        assert len(await _installed_apps(session, guild.id)) == 1

    async def test_with_nothing_mandatory_it_touches_no_guild(
        self, session: AsyncSession, provided_listing
    ):
        creator = await create_user(session, email="none@example.com")
        guild = await create_guild(session, creator=creator, name="Untouched")
        await create_guild_membership(
            session, user=creator, guild=guild, role=GuildRole.admin
        )

        result = await backfill_mandatory_apps()
        # Not even a pass over the guilds: with nothing marked, there is nothing
        # this could be for.
        assert (result.guilds, result.installed, result.failed) == (0, 0, 0)
        assert await _installed_apps(session, guild.id) == []

    async def test_clearing_the_flag_leaves_the_install_alone(
        self, session: AsyncSession, mandatory_registration
    ):
        """The destructive path is deleting the registration, not clearing a
        flag: an app that stops being compulsory keeps its install."""
        creator = await create_user(session, email="cleared@example.com")
        guild = await create_guild(session, creator=creator, name="Cleared guild")
        await create_guild_membership(
            session, user=creator, guild=guild, role=GuildRole.admin
        )
        await backfill_mandatory_apps()

        mandatory_registration.mandatory = False
        session.add(mandatory_registration)
        await session.commit()
        invalidate_registrations()
        await backfill_mandatory_apps()

        assert len(await _installed_apps(session, guild.id)) == 1


class TestPlacement:
    async def test_it_is_placed_in_every_initiative_and_each_new_one(
        self, session: AsyncSession, mandatory_registration
    ):
        """In every initiative there is when it lands, with the moderator role,
        and in each initiative created afterwards."""
        creator = await create_user(session, email="placed@example.com")
        guild = await create_guild(session, creator=creator, name="Placed guild")
        await create_guild_membership(
            session, user=creator, guild=guild, role=GuildRole.admin
        )
        before = await create_initiative(session, guild, creator, name="Before")

        await backfill_mandatory_apps()
        [app] = await _installed_apps(session, guild.id)
        assert app.follows_new_initiatives is True

        after = await create_initiative(session, guild, creator, name="After")

        await route_session_to_guild(session, guild.id)
        rows = (
            await session.exec(
                select(AppPlacement).where(AppPlacement.install_id == app.id)
            )
        ).all()
        placed = {row.initiative_id: list(row.role_ids) for row in rows}
        expected = {}
        for initiative in (before, after):
            role = await get_moderator_role(session, initiative_id=initiative.id)
            assert role is not None
            expected[initiative.id] = [role.id]
        assert placed == expected

    async def test_an_install_already_there_starts_following(
        self, session: AsyncSession, mandatory_registration
    ):
        """Marked mandatory after it landed: it follows new initiatives from
        then on, and the initiatives already there keep the seat's placement."""
        creator = await create_user(session, email="late@example.com")
        guild = await create_guild(session, creator=creator, name="Late guild")
        await create_guild_membership(
            session, user=creator, guild=guild, role=GuildRole.admin
        )
        await create_initiative(session, guild, creator, name="Existing")
        await create_guild_app(
            session,
            guild,
            creator,
            definition=PROVIDED_DEFINITION,
            listing_uid=PROVIDED_UID,
        )

        await backfill_mandatory_apps()

        [app] = await _installed_apps(session, guild.id)
        assert app.follows_new_initiatives is True
        await route_session_to_guild(session, guild.id)
        assert (
            await session.exec(
                select(AppPlacement).where(AppPlacement.install_id == app.id)
            )
        ).all() == []


class TestScopes:
    async def test_it_is_granted_what_it_asks_for_within_the_ceiling(
        self, session: AsyncSession
    ):
        """The operator's registration is the consent a seat would otherwise
        give, so a mandatory install lands holding the manifest's scopes that
        the registration's ceiling allows — and nothing beyond it."""
        public_id = "platform.scoped"
        uid = marketplace_uid("scoped")
        await create_marketplace_listing(
            session,
            uid=uid,
            public_id=public_id,
            kind="app",
            name="Scoped app",
            definition={
                "app_kind": "service",
                "service": {
                    "public_id": public_id,
                    "protocol": 1,
                    "scopes": ["comments:read", "projects:read", "projects:write"],
                },
                "features": [],
                "default_name": "Scoped app",
            },
        )
        await create_app_service_registration(
            session,
            public_id=public_id,
            base_url="https://scoped.example.test",
            listing_uid=uid,
            mandatory=True,
            scope_ceiling=["projects:read", "projects:write", "tags:read"],
        )
        creator = await create_user(session, email="scoped@example.com")
        guild = await create_guild(session, creator=creator, name="Scoped guild")
        await create_guild_membership(
            session, user=creator, guild=guild, role=GuildRole.admin
        )

        await backfill_mandatory_apps()

        [app] = await _installed_apps(session, guild.id)
        assert app.granted_scopes == ["projects:read", "projects:write"]

    async def test_a_manifest_asking_for_nothing_is_granted_nothing(
        self, session: AsyncSession, mandatory_registration
    ):
        creator = await create_user(session, email="unscoped@example.com")
        guild = await create_guild(session, creator=creator, name="Unscoped guild")
        await create_guild_membership(
            session, user=creator, guild=guild, role=GuildRole.admin
        )

        await backfill_mandatory_apps()

        [app] = await _installed_apps(session, guild.id)
        assert app.granted_scopes == []


class TestScopesOnAnInstallAlreadyThere:
    """The sweep gives an existing mandatory install that holds no grant what a
    new one would get, and leaves a grant the seat set alone."""

    PUBLIC_ID = "platform.scoped-later"
    UID = marketplace_uid("scopedlater")
    DEFINITION = {
        "app_kind": "service",
        "service": {
            "public_id": "platform.scoped-later",
            "protocol": 1,
            "scopes": ["comments:read", "projects:read"],
        },
        "features": [],
        "default_name": "Scoped later",
    }

    async def _guild_with_install(
        self, session: AsyncSession, email: str, *, granted: list[str] | None = None
    ):
        await create_marketplace_listing(
            session,
            uid=self.UID,
            public_id=self.PUBLIC_ID,
            kind="app",
            name="Scoped later",
            definition=self.DEFINITION,
        )
        await create_app_service_registration(
            session,
            public_id=self.PUBLIC_ID,
            base_url="https://scoped-later.example.test",
            listing_uid=self.UID,
            mandatory=True,
            scope_ceiling=["comments:read", "projects:read"],
        )
        creator = await create_user(session, email=email)
        guild = await create_guild(session, creator=creator, name=email)
        await create_guild_membership(
            session, user=creator, guild=guild, role=GuildRole.admin
        )
        app = await create_guild_app(
            session,
            guild,
            creator,
            definition=self.DEFINITION,
            listing_uid=self.UID,
        )
        if granted:
            # Written on the system engine, which the grant guard admits, as a
            # stand-in for the seat having granted it.
            from app.db import session as db_session

            async with db_session.SystemSessionLocal() as system:
                await db_session.set_rls_context(system, guild_id=guild.id)
                row = (
                    await system.exec(select(GuildApp).where(GuildApp.id == app.id))
                ).one()
                row.granted_scopes = granted
                system.add(row)
                await system.commit()
        return guild

    async def test_an_empty_grant_is_filled_in(self, session: AsyncSession):
        guild = await self._guild_with_install(session, "empty-grant@example.com")

        await backfill_mandatory_apps()

        [app] = await _installed_apps(session, guild.id)
        assert app.granted_scopes == ["comments:read", "projects:read"]

    async def test_a_grant_the_seat_set_is_left_alone(self, session: AsyncSession):
        guild = await self._guild_with_install(
            session, "seat-grant@example.com", granted=["comments:read"]
        )

        await backfill_mandatory_apps()

        [app] = await _installed_apps(session, guild.id)
        assert app.granted_scopes == ["comments:read"]

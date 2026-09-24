"""Where an installed app appears: ``app_placements`` rows.

Placement is one row per (install, initiative), carrying the initiative roles
allowed to open the app there. These tests hold the service helpers that read
and write those rows, the trigger that places an app following new
initiatives, and the export that carries them.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.tenant.app_placement import AppPlacement
from app.services.export.guild_sections import SectionContext, _build_apps
from app.services.tenant.guild_apps import (
    PlacementError,
    SurfaceAccess,
    is_placed,
    place_in_every_initiative,
    placed_initiative_ids,
    set_placed_initiatives,
    surface_access,
)
from app.services.tenant.initiatives import get_moderator_role
from app.testing import (
    create_guild,
    create_guild_app,
    create_initiative,
    create_marketplace_listing,
    create_user,
    marketplace_uid,
    route_session_to_guild,
)

pytestmark = pytest.mark.integration

PLACED_ID = "platform.placed"
PLACED_UID = marketplace_uid("placed")

DEFINITION = {
    "app_kind": "service",
    "service": {"public_id": PLACED_ID, "protocol": 1},
    "features": [],
    "default_name": "Placed app",
}


async def _moderator_id(session: AsyncSession, initiative_id: int) -> int:
    role = await get_moderator_role(session, initiative_id=initiative_id)
    assert role is not None and role.id is not None
    return role.id


async def _rows(session: AsyncSession, guild_id: int, install_id: int) -> dict:
    await route_session_to_guild(session, guild_id)
    rows = await session.exec(
        select(AppPlacement).where(AppPlacement.install_id == install_id)
    )
    return {row.initiative_id: list(row.role_ids) for row in rows.all()}


async def _guild_with_two_initiatives(session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    first = await create_initiative(session, guild, user, name="First")
    second = await create_initiative(session, guild, user, name="Second")
    return user, guild, first, second


class TestSetPlacedInitiatives:
    async def test_a_new_placement_starts_with_the_moderator_role(
        self, session: AsyncSession
    ):
        user, guild, first, _ = await _guild_with_two_initiatives(session)
        app = await create_guild_app(session, guild, user, definition=DEFINITION)

        await route_session_to_guild(session, guild.id)
        await set_placed_initiatives(session, app, {first.id})
        await session.commit()

        assert await _rows(session, guild.id, app.id) == {
            first.id: [await _moderator_id(session, first.id)]
        }

    async def test_a_kept_placement_keeps_its_roles_and_a_dropped_one_goes(
        self, session: AsyncSession
    ):
        user, guild, first, second = await _guild_with_two_initiatives(session)
        app = await create_guild_app(session, guild, user, definition=DEFINITION)

        await route_session_to_guild(session, guild.id)
        await set_placed_initiatives(session, app, {first.id})
        row = (
            await session.exec(
                select(AppPlacement).where(AppPlacement.install_id == app.id)
            )
        ).one()
        row.role_ids = [123_456]
        session.add(row)
        await session.commit()

        await route_session_to_guild(session, guild.id)
        await set_placed_initiatives(session, app, {first.id, second.id})
        await session.commit()
        assert await _rows(session, guild.id, app.id) == {
            first.id: [123_456],
            second.id: [await _moderator_id(session, second.id)],
        }

        await route_session_to_guild(session, guild.id)
        await set_placed_initiatives(session, app, {second.id})
        await session.commit()
        assert set(await _rows(session, guild.id, app.id)) == {second.id}

        await route_session_to_guild(session, guild.id)
        await set_placed_initiatives(session, app, set())
        await session.commit()
        assert await _rows(session, guild.id, app.id) == {}

    async def test_it_may_only_name_this_guild_s_initiatives(
        self, session: AsyncSession
    ):
        user, guild, first, _ = await _guild_with_two_initiatives(session)
        app = await create_guild_app(session, guild, user, definition=DEFINITION)

        await route_session_to_guild(session, guild.id)
        with pytest.raises(PlacementError, match="not one of this guild"):
            await set_placed_initiatives(session, app, {first.id + 10_000})


class TestIsPlaced:
    async def test_it_reads_the_rows(self, session: AsyncSession):
        user, guild, first, second = await _guild_with_two_initiatives(session)
        app = await create_guild_app(session, guild, user, definition=DEFINITION)

        await route_session_to_guild(session, guild.id)
        assert await is_placed(session, app.id, first.id) is False
        await set_placed_initiatives(session, app, {first.id})
        await session.commit()

        await route_session_to_guild(session, guild.id)
        assert await is_placed(session, app.id, first.id) is True
        assert await is_placed(session, app.id, second.id) is False
        assert await placed_initiative_ids(session, app.id) == {first.id}

    async def test_the_guild_wide_reading_is_always_placed(self, session: AsyncSession):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        app = await create_guild_app(session, guild, user, definition=DEFINITION)

        await route_session_to_guild(session, guild.id)
        assert await is_placed(session, app.id, None) is True


class TestFollowingNewInitiatives:
    async def test_place_in_every_initiative_covers_the_existing_ones(
        self, session: AsyncSession
    ):
        user, guild, first, second = await _guild_with_two_initiatives(session)
        app = await create_guild_app(session, guild, user, definition=DEFINITION)

        await route_session_to_guild(session, guild.id)
        await place_in_every_initiative(session, app)
        await session.commit()

        assert await _rows(session, guild.id, app.id) == {
            first.id: [await _moderator_id(session, first.id)],
            second.id: [await _moderator_id(session, second.id)],
        }

    async def test_a_new_initiative_places_a_following_install_only(
        self, session: AsyncSession
    ):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        following = await create_guild_app(
            session,
            guild,
            user,
            definition=DEFINITION,
            follows_new_initiatives=True,
        )
        ordinary = await create_guild_app(
            session,
            guild,
            user,
            definition=DEFINITION,
            listing_uid="TESTAPP0000002",
        )

        initiative = await create_initiative(session, guild, user)

        assert await _rows(session, guild.id, following.id) == {
            initiative.id: [await _moderator_id(session, initiative.id)]
        }
        assert await _rows(session, guild.id, ordinary.id) == {}

    async def test_an_initiative_created_through_the_route_is_placed(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        """Created by a guild admin who is not the seat: the row arrives from
        the trigger, under the request's own role."""
        seat = await acting_user(guild_role=GuildRole.superadmin)
        admin = await acting_user(guild_role=GuildRole.admin, guild=seat.guild)
        app = await create_guild_app(
            session,
            seat.guild,
            seat.user,
            definition=DEFINITION,
            follows_new_initiatives=True,
        )

        response = await client.post(
            admin.g("/initiatives/"), headers=admin.headers, json={"name": "Fresh"}
        )
        assert response.status_code in (200, 201), response.text
        initiative_id = response.json()["id"]

        await route_session_to_guild(session, seat.guild.id)
        assert await _rows(session, seat.guild.id, app.id) == {
            initiative_id: [await _moderator_id(session, initiative_id)]
        }


class TestExport:
    async def test_the_apps_section_carries_each_install_s_placements(
        self, session: AsyncSession
    ):
        await create_marketplace_listing(
            session,
            uid=PLACED_UID,
            public_id=PLACED_ID,
            kind="app",
            name="Placed app",
            definition=DEFINITION,
        )
        user, guild, first, _ = await _guild_with_two_initiatives(session)
        app = await create_guild_app(
            session, guild, user, definition=DEFINITION, listing_uid=PLACED_UID
        )
        await route_session_to_guild(session, guild.id)
        await set_placed_initiatives(session, app, {first.id})
        await session.commit()

        await route_session_to_guild(session, guild.id)
        built = await _build_apps(
            SectionContext(session=session, user=user, guild_id=guild.id)
        )
        assert built is not None
        payload, count = built
        assert count == 1
        assert payload["schema_version"] == 2
        [entry] = payload["apps"]
        assert "placement" not in entry
        assert entry["placements"] == [
            {
                "initiative_id": first.id,
                "role_ids": [await _moderator_id(session, first.id)],
            }
        ]


class TestSurfaceAccess:
    """The one decision behind opening a surface, without a database."""

    pytestmark = pytest.mark.unit

    EMBED = {"id": "e", "path": "/e", "scopes": ["guild", "initiative"]}
    ADMIN_ONLY = {**EMBED, "admin_only": True}

    @staticmethod
    def _decide(embed, *, initiative_id=1, roles=(10,), admin=False, held=(10,)):
        return surface_access(
            embed,
            initiative_id=initiative_id,
            placement_role_ids=roles,
            is_guild_admin=admin,
            member_role_ids=held,
        )

    def test_a_role_the_placement_allows_opens_it(self):
        assert self._decide(self.EMBED) is SurfaceAccess.open

    def test_a_role_it_does_not_allow_is_refused(self):
        assert self._decide(self.EMBED, held=(11,)) is SurfaceAccess.refused

    def test_not_placed_is_not_here_even_for_an_admin(self):
        for admin in (False, True):
            assert (
                self._decide(self.EMBED, roles=None, admin=admin)
                is SurfaceAccess.not_here
            )

    def test_the_community_level_is_for_admins(self):
        assert (
            self._decide(self.EMBED, initiative_id=None, roles=None)
            is SurfaceAccess.refused
        )
        assert (
            self._decide(self.EMBED, initiative_id=None, roles=None, admin=True)
            is SurfaceAccess.open
        )

    def test_admin_only_outranks_the_roles(self):
        assert self._decide(self.ADMIN_ONLY) is SurfaceAccess.refused
        assert self._decide(self.ADMIN_ONLY, admin=True) is SurfaceAccess.open

    def test_a_surface_that_does_not_render_here_is_not_here(self):
        inside_only = {**self.EMBED, "scopes": ["initiative"]}
        assert (
            self._decide(inside_only, initiative_id=None, roles=None, admin=True)
            is SurfaceAccess.not_here
        )

    def test_a_surface_pinned_as_admin_only_under_the_earlier_contract(self):
        """``visibility: "guild_admin"`` on a definition pinned before this
        contract means ``admin_only`` until the install moves on."""
        legacy = {**self.EMBED, "visibility": "guild_admin"}
        assert self._decide(legacy) is SurfaceAccess.refused
        assert self._decide(legacy, admin=True) is SurfaceAccess.open

    def test_an_earlier_member_surface_follows_the_placement(self):
        legacy = {**self.EMBED, "visibility": "member"}
        assert self._decide(legacy) is SurfaceAccess.open

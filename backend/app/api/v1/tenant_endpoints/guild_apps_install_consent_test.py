"""The install dialog is the seat's consent.

``POST /apps`` carries what the seat answered: the scopes it grants, where the
app appears, and which built-in roles open it there. All of it lands with the
install in one transaction, under the same checks the separate scope and
placement routes apply, and anything refused leaves no install behind.
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import GuildAppMessages
from app.models.platform.guild import GuildRole
from app.models.tenant.guild_app import GuildApp
from app.services.tenant.initiatives import get_role_by_name
from app.testing import (
    create_app_service_registration,
    create_initiative,
    create_marketplace_listing,
    marketplace_uid,
    route_session_to_guild,
)

SERVICE_ID = "tests.consentco"
SERVICE_UID = marketplace_uid("consentco")
CEILING = ["comments:read", "projects:read", "tags:read"]


def _definition(*, inside: bool = True) -> dict:
    """A service app asking for three scopes, one of them above the ceiling,
    with a surface inside initiatives when ``inside``."""
    embeds = [
        {
            "id": "board",
            "path": "/embed/board",
            "scopes": ["initiative"] if inside else ["guild"],
            "admin_only": False,
            "name": {"en": "Board"},
        }
    ]
    return {
        "app_kind": "service",
        "service": {
            "public_id": SERVICE_ID,
            "protocol": 1,
            "scopes": ["comments:read", "projects:read", "projects:write"],
        },
        "features": ["embeds"],
        "embeds": embeds,
        "default_name": "ConsentCo",
    }


@pytest.fixture
async def listing(session: AsyncSession):
    await create_app_service_registration(
        session,
        public_id=SERVICE_ID,
        base_url="https://consentco.example.test",
        listing_uid=SERVICE_UID,
        scope_ceiling=CEILING,
    )
    return await create_marketplace_listing(
        session,
        uid=SERVICE_UID,
        public_id=SERVICE_ID,
        kind="app",
        name="ConsentCo",
        definition=_definition(),
    )


async def _install(client: AsyncClient, actor, **body):
    return await client.post(
        actor.g("/apps/"),
        headers=actor.headers,
        json={"listing_uid": SERVICE_UID, **body},
    )


async def _role_id(session: AsyncSession, guild_id: int, initiative_id: int, name: str):
    await route_session_to_guild(session, guild_id)
    role = await get_role_by_name(session, initiative_id=initiative_id, role_name=name)
    assert role is not None
    return role.id


async def _installs(session: AsyncSession, guild_id: int) -> list[GuildApp]:
    session.expunge_all()
    await route_session_to_guild(session, guild_id)
    return list((await session.exec(select(GuildApp))).all())


class TestConsentAtInstall:
    async def test_scopes_placements_and_roles_land_with_the_install(
        self, client: AsyncClient, acting_user, session: AsyncSession, listing
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        second = await create_initiative(session, a.guild, a.user, name="Second")

        response = await _install(
            client,
            a,
            granted_scopes=["projects:read", "comments:read"],
            placements="all",
            role_kinds=["moderator", "project_manager"],
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["granted_scopes"] == ["comments:read", "projects:read"]
        expected = []
        for initiative_id in sorted([a.initiative.id, second.id]):
            roles = sorted(
                [
                    await _role_id(session, a.guild.id, initiative_id, "moderator"),
                    await _role_id(
                        session, a.guild.id, initiative_id, "project_manager"
                    ),
                ]
            )
            expected.append({"initiative_id": initiative_id, "role_ids": roles})
        assert body["placements"] == expected

        # "Every current initiative", as the placement panel means it: an
        # initiative created later is the seat's to place.
        (app,) = await _installs(session, a.guild.id)
        assert app.follows_new_initiatives is False

    async def test_picked_initiatives_start_with_their_moderators(
        self, client: AsyncClient, acting_user, session: AsyncSession, listing
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        await create_initiative(session, a.guild, a.user, name="Left out")

        response = await _install(client, a, placements=[a.initiative.id])

        assert response.status_code == 201, response.text
        moderator = await _role_id(session, a.guild.id, a.initiative.id, "moderator")
        assert response.json()["placements"] == [
            {"initiative_id": a.initiative.id, "role_ids": [moderator]}
        ]
        assert response.json()["granted_scopes"] == []

    async def test_an_install_with_no_answers_is_what_it_was(
        self, client: AsyncClient, acting_user, listing
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)

        response = await _install(client, a)

        assert response.status_code == 201, response.text
        assert response.json()["granted_scopes"] == []
        assert response.json()["placements"] == []

    @pytest.mark.parametrize(
        ("body", "code"),
        [
            ({"granted_scopes": ["tags:read"]}, GuildAppMessages.SCOPE_NOT_REQUESTED),
            (
                {"granted_scopes": ["projects:write"]},
                GuildAppMessages.SCOPE_ABOVE_CEILING,
            ),
            ({"placements": [987654]}, GuildAppMessages.PLACEMENT_INVALID),
            (
                {"placements": "all", "role_kinds": ["owner"]},
                GuildAppMessages.PLACEMENT_ROLE_INVALID,
            ),
        ],
    )
    async def test_a_refused_answer_installs_nothing(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        listing,
        body,
        code,
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)

        response = await _install(client, a, **body)

        assert response.status_code == 422, response.text
        assert response.json()["detail"] == code
        assert await _installs(session, a.guild.id) == []

    async def test_only_the_seat_installs(
        self, client: AsyncClient, acting_user, listing
    ):
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)

        response = await _install(client, a, granted_scopes=["projects:read"])

        assert response.status_code == 403
        assert response.json()["detail"] == GuildAppMessages.SUPERADMIN_REQUIRED


class TestTheListingSaysWhatTheDialogAsks:
    async def test_requested_grantable_and_surfaces(
        self, client: AsyncClient, acting_user, listing
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)

        response = await client.get(
            a.g(f"/marketplace/listings/by-uid/{SERVICE_UID}"), headers=a.headers
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["requested_scopes"] == [
            "projects:read",
            "projects:write",
            "comments:read",
        ]
        assert body["grantable_scopes"] == ["projects:read", "comments:read"]
        assert body["has_initiative_surfaces"] is True


def _wider(*, surfaces: bool = False) -> dict:
    """Version 1.1.0: asks for ``tags:read`` too, and a second surface inside
    initiatives when ``surfaces``."""
    definition = _definition()
    definition["service"]["scopes"] = [
        "comments:read",
        "projects:read",
        "projects:write",
        "tags:read",
    ]
    if surfaces:
        definition["embeds"] = [
            *definition["embeds"],
            {
                "id": "planner",
                "path": "/embed/planner",
                "scopes": ["initiative"],
                "admin_only": False,
                "name": {"en": "Planner"},
            },
        ]
    return definition


class TestUpgradeConsent:
    async def _installed_then_widened(
        self, client: AsyncClient, session: AsyncSession, actor, **wider
    ) -> int:
        response = await _install(client, actor, granted_scopes=["projects:read"])
        assert response.status_code == 201, response.text
        await create_marketplace_listing(
            session,
            uid=SERVICE_UID,
            public_id=SERVICE_ID,
            kind="app",
            name="ConsentCo",
            version="1.1.0",
            definition=_wider(**wider),
        )
        return response.json()["id"]

    async def test_the_detail_says_what_the_version_asks_for(
        self, client: AsyncClient, acting_user, session: AsyncSession, listing
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app_id = await self._installed_then_widened(client, session, a, surfaces=True)

        read = (await client.get(a.g(f"/apps/{app_id}"), headers=a.headers)).json()

        assert read["update_version"] == "1.1.0"
        assert read["pending_update"] == {
            "version": "1.1.0",
            "added_scopes": ["tags:read"],
            "added_surfaces": [{"id": "planner", "name": {"en": "Planner"}}],
            "declined": False,
        }

    async def test_without_consent_it_answers_with_what_it_asks(
        self, client: AsyncClient, acting_user, session: AsyncSession, listing
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app_id = await self._installed_then_widened(client, session, a)

        response = await client.post(a.g(f"/apps/{app_id}/upgrade"), headers=a.headers)

        assert response.status_code == 409, response.text
        assert response.json()["detail"] == {
            "code": GuildAppMessages.UPGRADE_NEEDS_CONSENT,
            "version": "1.1.0",
            "added_scopes": ["tags:read"],
            "added_surfaces": [],
            "declined": False,
        }
        (app,) = await _installs(session, a.guild.id)
        assert app.listing_version == "1.0.0"

    async def test_consent_applies_the_version_and_grants(
        self, client: AsyncClient, acting_user, session: AsyncSession, listing
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app_id = await self._installed_then_widened(client, session, a)

        response = await client.post(
            a.g(f"/apps/{app_id}/upgrade"),
            headers=a.headers,
            json={"version": "1.1.0", "add_scopes": ["tags:read"]},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["listing_version"] == "1.1.0"
        assert body["granted_scopes"] == ["projects:read", "tags:read"]
        assert body["pending_update"] is None

    async def test_consent_to_another_version_applies_nothing(
        self, client: AsyncClient, acting_user, session: AsyncSession, listing
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app_id = await self._installed_then_widened(client, session, a)

        response = await client.post(
            a.g(f"/apps/{app_id}/upgrade"),
            headers=a.headers,
            json={"version": "1.0.5", "add_scopes": []},
        )

        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == (
            GuildAppMessages.UPGRADE_VERSION_MOVED
        )

    async def test_consent_is_held_to_the_ceiling(
        self, client: AsyncClient, acting_user, session: AsyncSession, listing
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app_id = await self._installed_then_widened(client, session, a)

        response = await client.post(
            a.g(f"/apps/{app_id}/upgrade"),
            headers=a.headers,
            json={"version": "1.1.0", "add_scopes": ["projects:write"]},
        )

        assert response.status_code == 422, response.text
        assert response.json()["detail"] == GuildAppMessages.SCOPE_ABOVE_CEILING

    async def test_declining_keeps_the_version_and_sticks(
        self, client: AsyncClient, acting_user, session: AsyncSession, listing
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app_id = await self._installed_then_widened(client, session, a)

        response = await client.post(
            a.g(f"/apps/{app_id}/upgrade/decline"),
            headers=a.headers,
            json={"version": "1.1.0"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["listing_version"] == "1.0.0"
        assert body["pending_update"]["declined"] is True
        (app,) = await _installs(session, a.guild.id)
        assert app.declined_version == "1.1.0"

        moved = await client.post(
            a.g(f"/apps/{app_id}/upgrade/decline"),
            headers=a.headers,
            json={"version": "1.0.9"},
        )
        assert moved.status_code == 409
        assert moved.json()["detail"] == GuildAppMessages.UPGRADE_VERSION_MOVED

    async def test_only_the_seat_declines(
        self, client: AsyncClient, acting_user, session: AsyncSession, listing
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app_id = await self._installed_then_widened(client, session, a)
        admin = await acting_user(guild_role=GuildRole.admin, guild=a.guild)

        response = await client.post(
            admin.g(f"/apps/{app_id}/upgrade/decline"),
            headers=admin.headers,
            json={"version": "1.1.0"},
        )

        assert response.status_code == 403

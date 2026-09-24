"""What a registration does to an installed app.

Three statements only an operator can make, and this file is about what each one
does to a guild that never asked.

**Mandatory.** The deployment installs the app into every guild, at creation and
by the boot sweep, and a guild admin can neither remove nor disable it. The
refusal is by name because the affordance is absent in the UI — a request that
arrives anyway is answered, not accepted.

**The kill switch.** Switching a registration off stops the app in every guild:
its surfaces refuse, its vendor flows refuse, and the install reports itself as
unavailable rather than quietly looking fine. It outranks ``mandatory``, because
mandatory constrains guild admins rather than the operator.

**Clearing the flag.** Non-destructive by construction: whether an install is
mandatory is read from the registration every time, so an app that stops being
compulsory becomes an ordinary one with the same row, the same configuration,
and nothing migrated.

The handoff mint is here too, because who may open an app's surface is settled
by where the seat placed the app and which roles it allowed there, under the
caller's real session — before any token exists — and because a deployment with
no signing key must fail closed rather than mint something no app can verify.
So are the seat's own routes for placement and scopes.
"""

from typing import Sequence
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.messages import (
    AppServiceMessages,
    GuildAppMessages,
    InitiativeMessages,
)
from app.models.platform.publisher import Publisher
from app.models.platform.guild import GuildRole
from app.services.marketplace.app_refs import ensure_app_guild_ref, ensure_app_ref
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.services.tenant.guild_apps import set_placed_initiatives, set_placement_roles
from app.services.tenant.initiatives import get_moderator_role, get_role_by_name
from app.testing import (
    create_app_service_registration,
    create_guild_app,
    marketplace_uid,
    route_session_to_guild,
)


SERVICE_ID = "tests.widgetco"
SERVICE_UID = marketplace_uid("widgetco")

# Generated once for this module: the mint needs a real RS256 key, and a
# deployment's own keypair is the one thing it will not improvise.
_SIGNING_KEY_PEM = (
    rsa.generate_private_key(public_exponent=65537, key_size=2048)
    .private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    .decode("ascii")
)


def _service_definition(**overrides) -> dict:
    """A service app declaring one surface for each case the handoff decides."""
    definition = {
        "app_kind": "service",
        "service": {
            "public_id": SERVICE_ID,
            "protocol": 1,
            "scopes": ["comments:read", "projects:read", "projects:write"],
        },
        "features": ["embeds"],
        "embeds": [
            {
                "id": "board",
                "path": "/embed/board",
                "admin_only": False,
                "name": {"en": "Board"},
            },
            {
                "id": "console",
                "path": "/embed/console",
                "admin_only": True,
                "name": {"en": "Console"},
            },
            {
                "id": "runs",
                "path": "/embed/runs",
                "scopes": ["guild", "initiative"],
                "admin_only": False,
                "name": {"en": "Runs"},
            },
            {
                "id": "inside",
                "path": "/embed/inside",
                "scopes": ["initiative"],
                "admin_only": False,
                "name": {"en": "Inside"},
            },
            {
                "id": "settings",
                "path": "/embed/settings",
                "scopes": ["initiative"],
                "admin_only": True,
                "name": {"en": "Settings"},
            },
        ],
        "default_name": "WidgetCo",
    }
    definition.update(overrides)
    return definition


@pytest.fixture
async def registration(session: AsyncSession):
    return await create_app_service_registration(
        session,
        public_id=SERVICE_ID,
        base_url="https://widgetco.example.test",
        allowed_origins=["https://widgetco.example.test"],
        listing_uid=SERVICE_UID,
    )


async def _installed(session: AsyncSession, actor, *, placed: Sequence[int] = ()):
    """The install, placed in ``placed`` the way the seat places it."""
    app = await create_guild_app(
        session,
        actor.guild,
        actor.user,
        definition=_service_definition(),
        listing_uid=SERVICE_UID,
        name="WidgetCo",
    )
    if placed:
        await route_session_to_guild(session, actor.guild.id)
        await set_placed_initiatives(session, app, set(placed))
        await session.commit()
    return app


async def _role_id(session: AsyncSession, actor, initiative_id: int, name: str) -> int:
    """One built-in role of one initiative, by name."""
    await route_session_to_guild(session, actor.guild.id)
    role = await get_role_by_name(session, initiative_id=initiative_id, role_name=name)
    assert role is not None and role.id is not None
    return role.id


async def _allow(session: AsyncSession, actor, app, initiative_id: int, *names: str):
    """Place ``app`` in one initiative, allowing exactly the named roles."""
    role_ids = [await _role_id(session, actor, initiative_id, name) for name in names]
    await route_session_to_guild(session, actor.guild.id)
    await set_placement_roles(session, app, initiative_id, role_ids)
    await session.commit()


async def _mark(session: AsyncSession, row, **fields):
    """Change what the operator declared, and drop the cached snapshot."""
    for key, value in fields.items():
        setattr(row, key, value)
    session.add(row)
    await session.commit()
    invalidate_registrations()


#: Two ways a registration that is switched on is still not live.
NOT_LIVE = ("no key set", "publisher off")


async def _take_out_of_service(session: AsyncSession, registration, how: str):
    """Leave ``registration`` switched on but not live, ``how`` names."""
    if how == "no key set":
        await _mark(session, registration, jwks=None)
        return
    publisher = await session.get(Publisher, registration.publisher_id)
    await _mark(session, publisher, enabled=False)


# ---------------------------------------------------------------------------
# What an install reports about its registration
# ---------------------------------------------------------------------------


class TestInstallState:
    async def test_a_registered_app_is_available(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        await _installed(session, a)

        items = (await client.get(a.g("/apps/"), headers=a.headers)).json()["items"]
        assert [item["available"] for item in items] == [True]
        assert [item["mandatory"] for item in items] == [False]

    async def test_the_kill_switch_makes_it_unavailable(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """Deactivating stops the app in every guild. The install stays — this
        is a stop, not a teardown — and says it is doing nothing."""
        a = await acting_user(guild_role=GuildRole.superadmin)
        await _installed(session, a)
        await _mark(session, registration, enabled=False)

        items = (await client.get(a.g("/apps/"), headers=a.headers)).json()["items"]
        assert [item["available"] for item in items] == [False]

    async def test_an_unregistered_service_app_is_unavailable(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """Installed here, wired up nowhere: nothing it offers can be reached,
        and the read says so rather than showing a working app."""
        a = await acting_user(guild_role=GuildRole.superadmin)
        await _installed(session, a)

        items = (await client.get(a.g("/apps/"), headers=a.headers)).json()["items"]
        assert [item["available"] for item in items] == [False]

    @pytest.mark.parametrize("how", NOT_LIVE)
    async def test_only_a_live_registration_is_available(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        registration,
        how: str,
    ):
        """Availability is the one definition of live: switched on, its
        publisher switched on, and a key set to verify against."""
        a = await acting_user(guild_role=GuildRole.superadmin)
        await _installed(session, a)
        await _take_out_of_service(session, registration, how)

        items = (await client.get(a.g("/apps/"), headers=a.headers)).json()["items"]
        assert [item["available"] for item in items] == [False]


# ---------------------------------------------------------------------------
# Mandatory apps
# ---------------------------------------------------------------------------


class TestMandatory:
    async def test_a_guild_admin_cannot_uninstall_one(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)
        await _mark(session, registration, mandatory=True)

        response = await client.delete(a.g(f"/apps/{app.id}"), headers=a.headers)
        assert response.status_code == 409
        assert response.json()["detail"] == GuildAppMessages.MANDATORY
        # Still there, untouched.
        items = (await client.get(a.g("/apps/"), headers=a.headers)).json()["items"]
        assert [item["id"] for item in items] == [app.id]

    async def test_the_seat_cannot_disable_one(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)
        await _mark(session, registration, mandatory=True)

        response = await client.patch(
            a.g(f"/apps/{app.id}"), headers=a.headers, json={"enabled": False}
        )
        assert response.status_code == 409
        assert response.json()["detail"] == GuildAppMessages.MANDATORY

    async def test_renaming_one_is_still_allowed(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """A guild may call it whatever it likes; what it cannot do is make it
        go away."""
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)
        await _mark(session, registration, mandatory=True)

        response = await client.patch(
            a.g(f"/apps/{app.id}"), headers=a.headers, json={"name": "Ours"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Ours"
        assert response.json()["mandatory"] is True

    async def test_clearing_the_flag_leaves_the_install_and_frees_it(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """Nothing is deleted when an app stops being compulsory: the same
        install becomes an ordinary one a guild admin may now remove."""
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)
        await _mark(session, registration, mandatory=True)
        await _mark(session, registration, mandatory=False)

        read = (await client.get(a.g(f"/apps/{app.id}"), headers=a.headers)).json()
        assert read["mandatory"] is False
        assert read["name"] == "WidgetCo"

        removed = await client.delete(a.g(f"/apps/{app.id}"), headers=a.headers)
        assert removed.status_code == 204

    async def test_the_kill_switch_outranks_the_flag(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """Mandatory constrains guild admins, not the operator: a deactivated
        registration stops a mandatory app exactly like any other."""
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)
        await _mark(session, registration, mandatory=True, enabled=False)

        read = (await client.get(a.g(f"/apps/{app.id}"), headers=a.headers)).json()
        assert read["available"] is False

        opened = await client.post(
            a.g(f"/apps/{app.id}/handoff/board"), headers=a.headers
        )
        assert opened.status_code == 409
        assert opened.json()["detail"] == GuildAppMessages.SERVICE_NOT_REGISTERED


# ---------------------------------------------------------------------------
# The embed handoff
# ---------------------------------------------------------------------------


class TestHandoff:
    @pytest.fixture(autouse=True)
    def signing_key(self, monkeypatch):
        monkeypatch.setattr(
            settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", _SIGNING_KEY_PEM
        )
        monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_KEY_ID", "test-key")

    async def test_a_member_may_not_open_a_community_level_surface(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """At the community level only the guild's admins open a surface,
        whether or not it is marked ``admin_only``."""
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        response = await client.post(
            member.g(f"/apps/{app.id}/handoff/board"), headers=member.headers
        )
        assert response.status_code == 403
        assert response.json()["detail"] == GuildAppMessages.SURFACE_ADMIN_ONLY

    async def test_a_guild_admin_opens_a_community_level_surface(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)

        response = await client.post(
            a.g(f"/apps/{app.id}/handoff/board"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["embed_url"] == "https://widgetco.example.test/embed/board"
        assert body["allowed_origins"] == ["https://widgetco.example.test"]
        assert body["audience"] == f"initiative-app:{SERVICE_ID}"
        assert body["expires_in_seconds"] == 60
        assert body["handoff_token"]

    async def test_the_iframe_opens_at_the_browser_address(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """A deployment may call an app somewhere a browser cannot reach, so the
        iframe is built from the address the operator published, not the one the
        server dials."""
        await _mark(
            session,
            registration,
            base_url="http://widgetco.internal:8200",
            embed_origin="https://widgetco.example.test",
        )
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)

        response = await client.post(
            a.g(f"/apps/{app.id}/handoff/board"), headers=a.headers
        )

        assert response.status_code == 200, response.text
        assert response.json()["embed_url"] == (
            "https://widgetco.example.test/embed/board"
        )

    async def test_the_token_names_the_guild_the_install_and_the_surface(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """And nothing else about the person: an app receives an identity here
        because a human is opening a surface, not a profile it never asked
        for."""
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)

        body = (
            await client.post(a.g(f"/apps/{app.id}/handoff/board"), headers=a.headers)
        ).json()
        claims = jwt.decode(
            body["handoff_token"],
            options={"verify_signature": False},
            audience=body["audience"],
        )
        # The guild by reference for the same reason as the subject below: an
        # index names a row to us, not an entity to somebody else.
        assert claims["guild_ref"] == await ensure_app_guild_ref(
            guild_id=a.guild.id, app_install_id=app.id
        )
        assert "guild_id" not in claims
        assert claims["app_install_id"] == app.id
        assert claims["surface_id"] == "board"
        assert claims["jti"]
        assert "email" not in claims and "guild_role" not in claims

        # The subject is pairwise (OIDC Core §8.1): it names the member to this
        # install and is not the row id, so an app storing `sub` as its key for
        # a person is not storing something another app would recognize.
        assert claims["sub"] != str(a.user.id)
        assert claims["sub"] == await ensure_app_ref(
            guild_id=a.guild.id, app_install_id=app.id, user_id=a.user.id
        )

    async def test_a_member_may_not_open_an_admin_surface(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        response = await client.post(
            member.g(f"/apps/{app.id}/handoff/console"), headers=member.headers
        )
        assert response.status_code == 403
        assert response.json()["detail"] == GuildAppMessages.SURFACE_ADMIN_ONLY

    async def test_a_guild_admin_may_open_an_admin_surface(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)

        response = await client.post(
            a.g(f"/apps/{app.id}/handoff/console"), headers=a.headers
        )
        assert response.status_code == 200, response.text

    async def test_a_surface_that_renders_only_inside_an_initiative_is_not_here(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """The route has to agree with the surface before anyone is measured:
        this route names no initiative, so a surface declared only for one is
        not found here, for everyone."""
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        for actor in (member, a):
            response = await client.post(
                actor.g(f"/apps/{app.id}/handoff/inside"), headers=actor.headers
            )
            assert response.status_code == 404, response.text
            assert response.json()["detail"] == GuildAppMessages.SURFACE_NOT_FOUND

    async def test_managing_an_initiative_does_not_open_the_guild_wide_entry(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """This route names no initiative, so no initiative role reaches it.

        The surface renders in both scopes. Inside an initiative the placement's
        roles decide; out here only admins open it.
        """
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)
        pm = await acting_user(
            guild_role=GuildRole.member, guild=a.guild, initiative=True
        )

        response = await client.post(
            pm.g(f"/apps/{app.id}/handoff/runs"), headers=pm.headers
        )
        assert response.status_code == 403
        assert response.json()["detail"] == GuildAppMessages.SURFACE_ADMIN_ONLY

    async def test_a_guild_admin_opens_it_guild_wide(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)

        response = await client.post(
            a.g(f"/apps/{app.id}/handoff/runs"), headers=a.headers
        )
        assert response.status_code == 200, response.text

    async def test_an_undeclared_surface_is_a_404(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)
        response = await client.post(
            a.g(f"/apps/{app.id}/handoff/nope"), headers=a.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == GuildAppMessages.SURFACE_NOT_FOUND

    async def test_an_unregistered_app_mints_nothing(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)
        response = await client.post(
            a.g(f"/apps/{app.id}/handoff/board"), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == GuildAppMessages.SERVICE_NOT_REGISTERED

    @pytest.mark.parametrize("how", NOT_LIVE)
    async def test_only_a_live_registration_mints(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        registration,
        how: str,
    ):
        """The mint reads the same definition of live as the data plane."""
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)
        await _take_out_of_service(session, registration, how)

        response = await client.post(
            a.g(f"/apps/{app.id}/handoff/board"), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == GuildAppMessages.SERVICE_NOT_REGISTERED


class TestInitiativeHandoff:
    """The same install, opened from inside one initiative.

    The gates stack here, and each is asserted on its own: the initiative has
    to be one the caller can reach, the surface has to have asked to render in
    an initiative, the seat has to have placed the app there, and the caller
    has to hold one of the roles that placement allows — or be a guild admin.
    """

    @pytest.fixture(autouse=True)
    def signing_key(self, monkeypatch):
        monkeypatch.setattr(
            settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", _SIGNING_KEY_PEM
        )
        monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_KEY_ID", "test-key")

    @staticmethod
    def _claims(body: dict) -> dict:
        return jwt.decode(
            body["handoff_token"],
            options={"verify_signature": False},
            audience=body["audience"],
        )

    @staticmethod
    def _path(actor, initiative_id: int, app_id: int, surface: str) -> str:
        return actor.g(f"/initiatives/{initiative_id}/apps/{app_id}/handoff/{surface}")

    async def _member(self, acting_user, a, role: str = "member"):
        return await acting_user(
            guild_role=GuildRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role=role,
        )

    async def test_a_role_the_placement_allows_opens_it(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a)
        await _allow(session, a, app, a.initiative.id, "member")
        member = await self._member(acting_user, a)

        response = await client.post(
            self._path(member, a.initiative.id, app.id, "inside"),
            headers=member.headers,
        )
        assert response.status_code == 200, response.text
        assert self._claims(response.json())["initiative_id"] == a.initiative.id

    async def test_a_role_the_placement_does_not_allow_is_refused(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """Placed with the moderator role only, so a plain member of the same
        initiative is refused — and told it is their role, not the app."""
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a, placed=[a.initiative.id])
        member = await self._member(acting_user, a)

        for surface in ("inside", "runs"):
            response = await client.post(
                self._path(member, a.initiative.id, app.id, surface),
                headers=member.headers,
            )
            assert response.status_code == 403, surface
            assert response.json()["detail"] == (
                GuildAppMessages.SURFACE_ROLE_NOT_ALLOWED
            )

    async def test_a_placement_with_no_role_admits_only_admins(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a)
        await _allow(session, a, app, a.initiative.id)
        moderator = await self._member(acting_user, a, "moderator")

        refused = await client.post(
            self._path(moderator, a.initiative.id, app.id, "inside"),
            headers=moderator.headers,
        )
        assert refused.status_code == 403
        opened = await client.post(
            self._path(a, a.initiative.id, app.id, "inside"), headers=a.headers
        )
        assert opened.status_code == 200, opened.text

    async def test_an_initiative_the_app_is_not_placed_in_has_no_surface(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """Not placed is not found, for the admin as much as for anyone: the
        seat's answer to where the app belongs, not a rule about who."""
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a)
        member = await self._member(acting_user, a)

        for actor in (member, a):
            response = await client.post(
                self._path(actor, a.initiative.id, app.id, "inside"),
                headers=actor.headers,
            )
            assert response.status_code == 404, response.text
            assert response.json()["detail"] == GuildAppMessages.SURFACE_NOT_FOUND

    async def test_an_admin_only_surface_refuses_an_allowed_role(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """``admin_only`` outranks the placement's roles."""
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a)
        await _allow(session, a, app, a.initiative.id, "member", "moderator")
        member = await self._member(acting_user, a)

        response = await client.post(
            self._path(member, a.initiative.id, app.id, "settings"),
            headers=member.headers,
        )
        assert response.status_code == 403
        assert response.json()["detail"] == GuildAppMessages.SURFACE_ADMIN_ONLY

    async def test_an_admin_only_surface_opens_for_an_admin(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a, placed=[a.initiative.id])

        response = await client.post(
            self._path(a, a.initiative.id, app.id, "settings"), headers=a.headers
        )
        assert response.status_code == 200, response.text

    async def test_the_token_names_the_initiative_it_was_opened_in(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """The route's answer, not the caller's — so an app can scope what it
        shows without trusting a parameter or asking a second question."""
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a, placed=[a.initiative.id])

        body = (
            await client.post(
                self._path(a, a.initiative.id, app.id, "runs"), headers=a.headers
            )
        ).json()
        claims = self._claims(body)
        assert claims["initiative_id"] == a.initiative.id
        assert claims["guild_ref"] == await ensure_app_guild_ref(
            guild_id=a.guild.id, app_install_id=app.id
        )
        assert "guild_id" not in claims
        assert claims["app_install_id"] == app.id
        assert claims["surface_id"] == "runs"

    async def test_the_guild_wide_route_names_no_initiative(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """Absent rather than null: "which initiative is this?" has one answer
        guild-wide, not two shapes that both mean none."""
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a, placed=[a.initiative.id])

        body = (
            await client.post(a.g(f"/apps/{app.id}/handoff/runs"), headers=a.headers)
        ).json()
        assert "initiative_id" not in self._claims(body)

    async def test_a_guild_member_in_no_initiative_reaches_none_of_it(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """Opening a surface in an initiative means reaching the initiative,
        under the same scope rule that governs its content."""
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a, placed=[a.initiative.id])
        outsider = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        response = await client.post(
            self._path(outsider, a.initiative.id, app.id, "inside"),
            headers=outsider.headers,
        )
        assert response.status_code == 404
        assert response.json()["detail"] == InitiativeMessages.NOT_FOUND

    async def test_a_role_in_another_initiative_says_nothing_about_this_one(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a, placed=[a.initiative.id])
        elsewhere = await acting_user(
            guild_role=GuildRole.member, guild=a.guild, initiative=True
        )

        response = await client.post(
            self._path(elsewhere, a.initiative.id, app.id, "runs"),
            headers=elsewhere.headers,
        )
        assert response.status_code == 404
        assert response.json()["detail"] == InitiativeMessages.NOT_FOUND

    async def test_a_guild_admin_reaches_an_initiative_they_are_not_in(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """Nothing blocks a guild admin inside their own guild — not initiative
        membership, and not the roles a placement allows."""
        owner = await acting_user(guild_role=GuildRole.member, initiative=True)
        admin = await acting_user(guild_role=GuildRole.superadmin, guild=owner.guild)
        app = await _installed(session, admin, placed=[owner.initiative.id])

        response = await client.post(
            self._path(admin, owner.initiative.id, app.id, "runs"),
            headers=admin.headers,
        )
        assert response.status_code == 200, response.text

    async def test_a_guild_wide_surface_is_not_offered_in_here(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """The mirror of the guild route's refusal. A surface that never asked
        to render in an initiative must not pick one up as a claim."""
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a, placed=[a.initiative.id])

        for surface in ("board", "console"):
            response = await client.post(
                self._path(a, a.initiative.id, app.id, surface), headers=a.headers
            )
            assert response.status_code == 404, response.text
            assert response.json()["detail"] == GuildAppMessages.SURFACE_NOT_FOUND


class TestOpenability:
    """What the app read tells the viewer about where each surface opens.

    Computed by the same decision the handoff makes, so each answer here is
    checked against the handoff for the same viewer.
    """

    @pytest.fixture(autouse=True)
    def signing_key(self, monkeypatch):
        monkeypatch.setattr(
            settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", _SIGNING_KEY_PEM
        )
        monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_KEY_ID", "test-key")

    @staticmethod
    async def _access(client: AsyncClient, actor, app_id: int) -> dict:
        read = (
            await client.get(actor.g(f"/apps/{app_id}"), headers=actor.headers)
        ).json()
        return {one["surface_id"]: one for one in read["surface_access"]}

    async def test_the_read_agrees_with_the_handoff(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a)
        await _allow(session, a, app, a.initiative.id, "member")
        member = await acting_user(
            guild_role=GuildRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        surfaces = ("board", "console", "runs", "inside", "settings")

        for actor in (member, a):
            access = await self._access(client, actor, app.id)
            assert set(access) == set(surfaces)
            for surface in surfaces:
                guild_wide = await client.post(
                    actor.g(f"/apps/{app.id}/handoff/{surface}"), headers=actor.headers
                )
                assert (guild_wide.status_code == 200) is access[surface][
                    "openable_guild_wide"
                ], (surface, guild_wide.text)
                inside = await client.post(
                    actor.g(
                        f"/initiatives/{a.initiative.id}/apps/{app.id}/handoff/{surface}"
                    ),
                    headers=actor.headers,
                )
                assert (inside.status_code == 200) is (
                    a.initiative.id in access[surface]["openable_initiatives"]
                ), (surface, inside.text)

    async def test_a_member_is_offered_only_the_placements_they_hold_a_role_in(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a)
        await _allow(session, a, app, a.initiative.id, "member")
        member = await acting_user(
            guild_role=GuildRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )

        access = await self._access(client, member, app.id)
        assert access["inside"]["openable_initiatives"] == [a.initiative.id]
        assert access["runs"]["openable_initiatives"] == [a.initiative.id]
        assert access["runs"]["openable_guild_wide"] is False
        assert access["settings"]["openable_initiatives"] == []
        assert access["board"]["openable_guild_wide"] is False

        admin_access = await self._access(client, a, app.id)
        assert admin_access["settings"]["openable_initiatives"] == [a.initiative.id]
        assert admin_access["board"]["openable_guild_wide"] is True


class TestPlacement:
    """Which initiatives an app's initiative surfaces appear in.

    Placement is the seat's answer to where an app belongs, not an audience
    rule — so unlike the roles a placement allows, it reads the same for a
    guild admin as for anyone else.
    """

    @pytest.fixture(autouse=True)
    def signing_key(self, monkeypatch):
        monkeypatch.setattr(
            settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", _SIGNING_KEY_PEM
        )
        monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_KEY_ID", "test-key")

    @staticmethod
    def _path(actor, initiative_id: int, app_id: int, surface: str) -> str:
        return actor.g(f"/initiatives/{initiative_id}/apps/{app_id}/handoff/{surface}")

    async def test_an_install_starts_placed_nowhere(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """An ordinary app is never placed on its own: each placement is the
        seat's consent for that initiative."""
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        await _installed(session, a)

        body = (await client.get(a.g("/apps/"), headers=a.headers)).json()
        assert [item["placements"] for item in body["items"]] == [[]]

    async def test_the_seat_places_it_with_the_moderator_role(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a)
        moderator = await get_moderator_role(session, initiative_id=a.initiative.id)
        assert moderator is not None

        response = await client.patch(
            a.g(f"/apps/{app.id}"),
            headers=a.headers,
            json={"placed_initiative_ids": [a.initiative.id]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["placements"] == [
            {"initiative_id": a.initiative.id, "role_ids": [moderator.id]}
        ]

        detail = (await client.get(a.g(f"/apps/{app.id}"), headers=a.headers)).json()
        assert [p["initiative_id"] for p in detail["placements"]] == [a.initiative.id]

    async def test_leaving_placement_out_leaves_it_alone(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a, placed=[a.initiative.id])

        response = await client.patch(
            a.g(f"/apps/{app.id}"), headers=a.headers, json={"name": "Renamed"}
        )
        assert response.status_code == 200, response.text
        assert [p["initiative_id"] for p in response.json()["placements"]] == [
            a.initiative.id
        ]

    async def test_it_may_only_name_an_initiative_this_guild_has(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """Stated as an id this guild has no initiative for, rather than as one
        borrowed from another guild: initiative ids are per-guild, so the two
        guilds' numbering can coincide and a borrowed id would only be refused
        when the numbers happened to differ."""
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a)

        response = await client.patch(
            a.g(f"/apps/{app.id}"),
            headers=a.headers,
            json={"placed_initiative_ids": [a.initiative.id + 10_000]},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == GuildAppMessages.PLACEMENT_INVALID

    async def test_a_member_does_not_place_apps(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        response = await client.patch(
            member.g(f"/apps/{app.id}"),
            headers=member.headers,
            json={"placed_initiative_ids": []},
        )
        assert response.status_code == 403

    async def test_a_surface_placed_elsewhere_is_not_in_this_initiative(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """And not for the admin who placed it either — this is where the app
        goes, which is their own answer rather than a rule about them."""
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        other = await acting_user(
            guild_role=GuildRole.superadmin, guild=a.guild, initiative=True
        )
        app = await _installed(session, a, placed=[a.initiative.id])

        response = await client.patch(
            a.g(f"/apps/{app.id}"),
            headers=a.headers,
            json={"placed_initiative_ids": [other.initiative.id]},
        )
        assert response.status_code == 200, response.text

        placed = await client.post(
            self._path(a, other.initiative.id, app.id, "runs"), headers=a.headers
        )
        assert placed.status_code == 200, placed.text

        elsewhere = await client.post(
            self._path(a, a.initiative.id, app.id, "runs"), headers=a.headers
        )
        assert elsewhere.status_code == 404
        assert elsewhere.json()["detail"] == GuildAppMessages.SURFACE_NOT_FOUND

    async def test_placement_leaves_the_guild_wide_surface_alone(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a, placed=[a.initiative.id])
        await client.patch(
            a.g(f"/apps/{app.id}"),
            headers=a.headers,
            json={"placed_initiative_ids": []},
        )

        response = await client.post(
            a.g(f"/apps/{app.id}/handoff/runs"), headers=a.headers
        )
        assert response.status_code == 200, response.text


class TestPlacementRoutes:
    """The seat's per-initiative placement routes."""

    @staticmethod
    def _path(actor, app_id: int, initiative_id: int | None = None) -> str:
        suffix = "" if initiative_id is None else f"/{initiative_id}"
        return actor.g(f"/apps/{app_id}/placements{suffix}")

    async def test_the_seat_places_an_app_with_chosen_roles(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a)
        member_role = await _role_id(session, a, a.initiative.id, "member")

        response = await client.put(
            self._path(a, app.id, a.initiative.id),
            headers=a.headers,
            json={"role_ids": [member_role]},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "initiative_id": a.initiative.id,
            "role_ids": [member_role],
        }

        listed = await client.get(self._path(a, app.id), headers=a.headers)
        assert listed.status_code == 200
        assert listed.json() == [
            {"initiative_id": a.initiative.id, "role_ids": [member_role]}
        ]

    async def test_putting_again_replaces_the_roles(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a, placed=[a.initiative.id])
        member_role = await _role_id(session, a, a.initiative.id, "member")

        response = await client.put(
            self._path(a, app.id, a.initiative.id),
            headers=a.headers,
            json={"role_ids": [member_role]},
        )
        assert response.status_code == 200, response.text
        listed = (await client.get(self._path(a, app.id), headers=a.headers)).json()
        assert listed == [{"initiative_id": a.initiative.id, "role_ids": [member_role]}]

    async def test_every_member_may_read_the_placements(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """As on the app read itself: placement is where the app belongs."""
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a, placed=[a.initiative.id])
        admin = await acting_user(guild_role=GuildRole.admin, guild=a.guild)

        response = await client.get(self._path(admin, app.id), headers=admin.headers)
        assert response.status_code == 200, response.text
        assert [p["initiative_id"] for p in response.json()] == [a.initiative.id]

    async def test_an_admin_below_the_seat_does_not_place(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a, placed=[a.initiative.id])
        admin = await acting_user(guild_role=GuildRole.admin, guild=a.guild)

        put = await client.put(
            self._path(admin, app.id, a.initiative.id),
            headers=admin.headers,
            json={"role_ids": []},
        )
        assert put.status_code == 403
        assert put.json()["detail"] == GuildAppMessages.SUPERADMIN_REQUIRED

        removed = await client.delete(
            self._path(admin, app.id, a.initiative.id), headers=admin.headers
        )
        assert removed.status_code == 403
        assert removed.json()["detail"] == GuildAppMessages.SUPERADMIN_REQUIRED

    async def test_a_role_of_another_initiative_is_refused(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        other = await acting_user(
            guild_role=GuildRole.superadmin, guild=a.guild, initiative=True
        )
        app = await _installed(session, a)
        foreign = await _role_id(session, a, other.initiative.id, "member")

        response = await client.put(
            self._path(a, app.id, a.initiative.id),
            headers=a.headers,
            json={"role_ids": [foreign]},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == GuildAppMessages.PLACEMENT_ROLE_INVALID

    async def test_an_initiative_this_guild_does_not_have_is_refused(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a)

        response = await client.put(
            self._path(a, app.id, a.initiative.id + 10_000),
            headers=a.headers,
            json={"role_ids": []},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == GuildAppMessages.PLACEMENT_INVALID

    async def test_the_seat_removes_a_placement(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a, placed=[a.initiative.id])

        response = await client.delete(
            self._path(a, app.id, a.initiative.id), headers=a.headers
        )
        assert response.status_code == 204
        listed = (await client.get(self._path(a, app.id), headers=a.headers)).json()
        assert listed == []

    async def test_a_mandatory_app_may_be_removed_from_one_initiative(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """The deployment decides that the app exists; the seat still decides
        where it appears."""
        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a, placed=[a.initiative.id])
        await _mark(session, registration, mandatory=True)

        response = await client.delete(
            self._path(a, app.id, a.initiative.id), headers=a.headers
        )
        assert response.status_code == 204
        read = (await client.get(a.g(f"/apps/{app.id}"), headers=a.headers)).json()
        assert read["mandatory"] is True
        assert read["placements"] == []


class TestScopesRoute:
    """The seat grants an install a subset of what it asks for, within what the
    deployment allows it."""

    CEILING = ["comments:read", "projects:read", "tags:read"]

    @staticmethod
    def _path(actor, app_id: int) -> str:
        return actor.g(f"/apps/{app_id}/scopes")

    async def test_the_seat_grants_what_is_requested_and_allowed(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)
        await _mark(session, registration, scope_ceiling=self.CEILING)

        response = await client.put(
            self._path(a, app.id),
            headers=a.headers,
            json={"granted": ["projects:read", "comments:read"]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["granted_scopes"] == ["comments:read", "projects:read"]

        withdrawn = await client.put(
            self._path(a, app.id), headers=a.headers, json={"granted": []}
        )
        assert withdrawn.status_code == 200, withdrawn.text
        assert withdrawn.json()["granted_scopes"] == []

    async def test_a_scope_the_manifest_does_not_request_is_refused(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """``tags:read`` is within the ceiling but the app never asked."""
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)
        await _mark(session, registration, scope_ceiling=self.CEILING)

        response = await client.put(
            self._path(a, app.id), headers=a.headers, json={"granted": ["tags:read"]}
        )
        assert response.status_code == 422
        assert response.json()["detail"] == GuildAppMessages.SCOPE_NOT_REQUESTED

    async def test_a_scope_above_the_ceiling_is_refused(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """``projects:write`` is requested, but the deployment does not allow
        it."""
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)
        await _mark(session, registration, scope_ceiling=self.CEILING)

        response = await client.put(
            self._path(a, app.id),
            headers=a.headers,
            json={"granted": ["projects:write"]},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == GuildAppMessages.SCOPE_ABOVE_CEILING

    async def test_the_detail_says_what_is_requested_and_grantable(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """``projects:write`` is requested and above the ceiling, so it is
        requested but not grantable; ``tags:read`` is allowed but never asked
        for, so it is neither."""
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)
        await _mark(session, registration, scope_ceiling=self.CEILING)

        read = (await client.get(a.g(f"/apps/{app.id}"), headers=a.headers)).json()
        assert read["requested_scopes"] == [
            "projects:read",
            "projects:write",
            "comments:read",
        ]
        assert read["grantable_scopes"] == ["projects:read", "comments:read"]

        # The list read stays without them.
        listed = (await client.get(a.g("/apps/"), headers=a.headers)).json()
        assert "requested_scopes" not in listed["items"][0]

    async def test_nothing_is_grantable_without_a_registration(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)

        read = (await client.get(a.g(f"/apps/{app.id}"), headers=a.headers)).json()
        assert read["requested_scopes"] == [
            "projects:read",
            "projects:write",
            "comments:read",
        ]
        assert read["grantable_scopes"] == []

    async def test_only_the_seat_grants(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)
        await _mark(session, registration, scope_ceiling=self.CEILING)

        for role in (GuildRole.admin, GuildRole.member):
            actor = await acting_user(guild_role=role, guild=a.guild)
            response = await client.put(
                self._path(actor, app.id),
                headers=actor.headers,
                json={"granted": ["projects:read"]},
            )
            assert response.status_code == 403, role
            assert response.json()["detail"] == GuildAppMessages.SUPERADMIN_REQUIRED


class TestHandoffWithoutASigningKey:
    async def test_it_fails_closed(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        registration,
        monkeypatch,
    ):
        """The app platform's keypair has no fallback: an unconfigured
        deployment refuses rather than minting a token no app can verify."""
        monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", None)
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _installed(session, a)

        response = await client.post(
            a.g(f"/apps/{app.id}/handoff/board"), headers=a.headers
        )
        assert response.status_code == 503
        assert response.json()["detail"] == AppServiceMessages.SIGNING_NOT_CONFIGURED


# ---------------------------------------------------------------------------
# Starting a member's vendor flow
# ---------------------------------------------------------------------------


class TestConnectLaunch:
    @pytest.fixture(autouse=True)
    def signing_key(self, monkeypatch):
        monkeypatch.setattr(
            settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", _SIGNING_KEY_PEM
        )
        monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_KEY_ID", "test-key")

    CONNECT_DEFINITION = {
        "app_kind": "service",
        "service": {"public_id": SERVICE_ID, "protocol": 1},
        "features": [],
        "connections": [
            {
                "id": "github",
                "scope": "interactive",
                "label": {"en": "GitHub"},
                "connect_path": "/connect/github",
                "fields": [
                    {
                        "key": "access_token",
                        "type": "secret",
                        "label": {"en": "Token"},
                        "managed": True,
                    }
                ],
            }
        ],
    }

    async def _install(self, session: AsyncSession, actor):
        return await create_guild_app(
            session,
            actor.guild,
            actor.user,
            definition=self.CONNECT_DEFINITION,
            listing_uid=SERVICE_UID,
        )

    async def test_the_url_is_the_registration_plus_the_manifest_path(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await self._install(session, a)

        response = await client.post(
            a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["connect_url"].startswith(
            "https://widgetco.example.test/connect/github?"
        )
        query = parse_qs(urlsplit(body["connect_url"]).query)
        assert query["connection_ref"] == [body["connection_ref"]]
        assert query["guild_ref"] == [
            await ensure_app_guild_ref(guild_id=a.guild.id, app_install_id=app.id)
        ]

    async def test_the_url_uses_the_browser_address(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """The member's own browser follows this one, so it is built from the
        published address rather than the one the server dials."""
        await _mark(
            session,
            registration,
            base_url="http://widgetco.internal:8200",
            embed_origin="https://widgetco.example.test",
        )
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await self._install(session, a)

        body = (
            await client.post(
                a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
            )
        ).json()

        assert body["connect_url"].startswith(
            "https://widgetco.example.test/connect/github"
        )

    async def test_only_the_handle_the_guild_and_the_return_travel(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """The query string carries the opaque handle, the guild to write back
        under, and the signed return. No credential of any kind: the app writes
        its result back with its own installation token."""
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await self._install(session, a)

        body = (
            await client.post(
                a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
            )
        ).json()
        query = parse_qs(urlsplit(body["connect_url"]).query)
        # Pinned exactly, so anything added to this URL is added deliberately.
        assert set(query) == {"connection_ref", "guild_ref", "return_token"}
        for smell in ("secret", "Bearer", "iat_"):
            assert smell not in body["connect_url"]

    def _return_claims(self, token: str) -> dict:
        public_key = serialization.load_pem_private_key(
            _SIGNING_KEY_PEM.encode("ascii"), password=None
        ).public_key()
        return jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=f"initiative-app:{SERVICE_ID}",
            issuer="initiative",
        )

    async def test_the_return_is_signed_by_the_app_platform_key(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """The browser carries this, so the app checks it against the key set
        Initiative publishes before following it — the same key as every other
        token Initiative signs for the app. It lives five minutes, names the
        flow it ends, and carries a ``jti``."""
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await self._install(session, a)

        body = (
            await client.post(
                a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
            )
        ).json()
        query = parse_qs(urlsplit(body["connect_url"]).query)
        token = query["return_token"][0]

        assert jwt.get_unverified_header(token)["kid"] == "test-key"
        claims = self._return_claims(token)
        assert claims["scope"] == "connect_return"
        assert claims["exp"] - claims["iat"] == 300
        assert claims["jti"]
        assert claims["guild_ref"] == query["guild_ref"][0]
        assert claims["app_install_id"] == app.id
        assert claims["connection_id"] == "github"
        assert claims["connection_ref"] == body["connection_ref"]

    async def test_the_app_is_told_where_to_send_them_back(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """An app knows a handle and a guild reference, and has never been told
        what language this person reads. So it does not write the ending: it
        hands them back here with one word, and Initiative renders the
        sentence.

        The address is Initiative's own, built from the frontend entry the
        deployment publishes rather than from anything the app said."""
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await self._install(session, a)

        body = (
            await client.post(
                a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
            )
        ).json()
        query = parse_qs(urlsplit(body["connect_url"]).query)

        home = self._return_claims(query["return_token"][0])["return_url"]
        assert home.startswith(f"{settings.APP_URL.rstrip('/')}/apps/connected?")
        # Which app and which connection, so the page can say what was being
        # connected without the app having to put it back on the URL.
        assert parse_qs(urlsplit(home).query) == {
            "app": [SERVICE_ID],
            "connection": ["github"],
        }

    async def test_without_the_platform_key_no_return_is_sent(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        registration,
        monkeypatch,
    ):
        """Nothing to sign with, so nothing is offered. The app then says its
        piece on its own page — the same thing it does for somebody who arrived
        by a hand-copied link."""
        monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", None)
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await self._install(session, a)

        body = (
            await client.post(
                a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
            )
        ).json()
        query = parse_qs(urlsplit(body["connect_url"]).query)

        assert "return_token" not in query
        # And the rest of the handoff is untouched: the flow still works, the
        # ending is just the app's own page.
        assert query["connection_ref"] == [body["connection_ref"]]

    async def test_an_unregistered_app_sends_nobody_anywhere(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await self._install(session, a)

        response = await client.post(
            a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == GuildAppMessages.SERVICE_NOT_REGISTERED

    async def test_a_deactivated_registration_sends_nobody_anywhere(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await self._install(session, a)
        await _mark(session, registration, enabled=False)

        response = await client.post(
            a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == GuildAppMessages.SERVICE_NOT_REGISTERED


class TestUninstallStopsDeliveries:
    """An install is what makes an app present in a guild, so removing it ends
    what that app is sent.

    The subscription outlives the install as a record of what was going where,
    and a reinstall registers afresh — but it stops matching events, and it
    stops minting the names its deliveries would have arrived under.
    """

    async def test_uninstalling_switches_off_what_that_install_registered(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        from datetime import datetime, timezone

        from app.models.tenant.webhook_subscription import WebhookSubscription

        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a)

        now = datetime.now(timezone.utc)
        theirs = WebhookSubscription(
            initiative_id=a.initiative.id,
            created_by=a.user.id,
            app_install_id=app.id,
            target_url="https://widgetco.example/in",
            hmac_secret="s" * 40,
            event_types=["tasks.created"],
            active=True,
            created_at=now,
            updated_at=now,
        )
        # A member's own, registered against a URL of their own: nothing to do
        # with this install, and untouched by its removal.
        mine = WebhookSubscription(
            initiative_id=a.initiative.id,
            created_by=a.user.id,
            app_install_id=None,
            target_url="https://mine.example/in",
            hmac_secret="m" * 40,
            event_types=["tasks.created"],
            active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(theirs)
        session.add(mine)
        await session.commit()

        removed = await client.delete(a.g(f"/apps/{app.id}"), headers=a.headers)
        assert removed.status_code in (200, 204), removed.text

        await session.refresh(theirs)
        await session.refresh(mine)
        assert theirs.active is False
        assert mine.active is True

    async def test_switching_them_off_is_staged_with_the_rest_of_the_uninstall(
        self, acting_user, session: AsyncSession
    ):
        """Uninstall removes connections, delegations, these and the install in
        one transaction, and commits once at the end.

        A commit in the middle would make everything staged before it durable
        while the install is still there to fail on — leaving an app installed
        with its credentials and deliveries already gone.
        """
        from datetime import datetime, timezone

        from app.models.tenant.webhook_subscription import WebhookSubscription
        from app.services.tenant import (
            webhook_subscriptions as webhook_subscriptions_service,
        )

        a = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
        app = await _installed(session, a)

        now = datetime.now(timezone.utc)
        sub = WebhookSubscription(
            initiative_id=a.initiative.id,
            created_by=a.user.id,
            app_install_id=app.id,
            target_url="https://widgetco.example/staged",
            hmac_secret="s" * 40,
            event_types=["tasks.created"],
            active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(sub)
        await session.commit()

        switched = await webhook_subscriptions_service.deactivate_for_install(
            session, guild_id=a.guild.id, app_install_id=app.id
        )
        assert switched == 1

        # Nothing committed it, so abandoning the transaction abandons it.
        await session.rollback()
        await session.refresh(sub)
        assert sub.active is True

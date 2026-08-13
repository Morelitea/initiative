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
by the manifest's ``visibility`` under the caller's real session — before any
token exists — and because a deployment with no signing key must fail closed
rather than mint something no app can verify.
"""

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.messages import AppServiceMessages, GuildAppMessages
from app.models.platform.guild import GuildRole
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.testing import (
    create_app_service_registration,
    create_guild_app,
    marketplace_uid,
)

pytestmark = pytest.mark.asyncio

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
    """A service app declaring one member surface and one admin surface."""
    definition = {
        "app_kind": "service",
        "service": {"public_id": SERVICE_ID, "protocol": 1},
        "features": ["embeds"],
        "embeds": [
            {
                "id": "board",
                "path": "/embed/board",
                "visibility": "member",
                "name": {"en": "Board"},
            },
            {
                "id": "console",
                "path": "/embed/console",
                "visibility": "guild_admin",
                "name": {"en": "Console"},
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


async def _installed(session: AsyncSession, actor):
    return await create_guild_app(
        session,
        actor.guild,
        actor.user,
        definition=_service_definition(),
        listing_uid=SERVICE_UID,
        name="WidgetCo",
    )


async def _mark(session: AsyncSession, row, **fields):
    """Change what the operator declared, and drop the cached snapshot."""
    for key, value in fields.items():
        setattr(row, key, value)
    session.add(row)
    await session.commit()
    invalidate_registrations()


# ---------------------------------------------------------------------------
# What an install reports about its registration
# ---------------------------------------------------------------------------


class TestInstallState:
    async def test_a_registered_app_is_available(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        await _installed(session, a)

        items = (await client.get(a.g("/apps/"), headers=a.headers)).json()["items"]
        assert [item["available"] for item in items] == [True]
        assert [item["mandatory"] for item in items] == [False]

    async def test_the_kill_switch_makes_it_unavailable(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """Deactivating stops the app in every guild. The install stays — this
        is a stop, not a teardown — and says it is doing nothing."""
        a = await acting_user(guild_role=GuildRole.admin)
        await _installed(session, a)
        await _mark(session, registration, enabled=False)

        items = (await client.get(a.g("/apps/"), headers=a.headers)).json()["items"]
        assert [item["available"] for item in items] == [False]

    async def test_an_unregistered_service_app_is_unavailable(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """Installed here, wired up nowhere: nothing it offers can be reached,
        and the read says so rather than showing a working app."""
        a = await acting_user(guild_role=GuildRole.admin)
        await _installed(session, a)

        items = (await client.get(a.g("/apps/"), headers=a.headers)).json()["items"]
        assert [item["available"] for item in items] == [False]


# ---------------------------------------------------------------------------
# Mandatory apps
# ---------------------------------------------------------------------------


class TestMandatory:
    async def test_a_guild_admin_cannot_uninstall_one(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _installed(session, a)
        await _mark(session, registration, mandatory=True)

        response = await client.delete(a.g(f"/apps/{app.id}"), headers=a.headers)
        assert response.status_code == 409
        assert response.json()["detail"] == GuildAppMessages.MANDATORY
        # Still there, untouched.
        items = (await client.get(a.g("/apps/"), headers=a.headers)).json()["items"]
        assert [item["id"] for item in items] == [app.id]

    async def test_a_guild_admin_cannot_disable_one(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.admin)
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
        a = await acting_user(guild_role=GuildRole.admin)
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
        a = await acting_user(guild_role=GuildRole.admin)
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
        a = await acting_user(guild_role=GuildRole.admin)
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

    async def test_a_member_may_open_a_member_surface(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _installed(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        response = await client.post(
            member.g(f"/apps/{app.id}/handoff/board"), headers=member.headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["embed_url"] == "https://widgetco.example.test/embed/board"
        assert body["allowed_origins"] == ["https://widgetco.example.test"]
        assert body["audience"] == f"initiative-app:{SERVICE_ID}"
        assert body["expires_in_seconds"] == 60
        assert body["handoff_token"]

    async def test_the_token_names_the_guild_the_install_and_the_surface(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """And nothing else about the person: an app receives an identity here
        because a human is opening a surface, not a profile it never asked
        for."""
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _installed(session, a)

        body = (
            await client.post(a.g(f"/apps/{app.id}/handoff/board"), headers=a.headers)
        ).json()
        claims = jwt.decode(
            body["handoff_token"],
            options={"verify_signature": False},
            audience=body["audience"],
        )
        assert claims["guild_id"] == a.guild.id
        assert claims["app_install_id"] == app.id
        assert claims["surface_id"] == "board"
        assert claims["sub"] == str(a.user.id)
        assert claims["jti"]
        assert "email" not in claims and "guild_role" not in claims

    async def test_a_member_may_not_open_an_admin_surface(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.admin)
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
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _installed(session, a)

        response = await client.post(
            a.g(f"/apps/{app.id}/handoff/console"), headers=a.headers
        )
        assert response.status_code == 200, response.text

    async def test_an_undeclared_surface_is_a_404(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _installed(session, a)
        response = await client.post(
            a.g(f"/apps/{app.id}/handoff/nope"), headers=a.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == GuildAppMessages.SURFACE_NOT_FOUND

    async def test_an_unregistered_app_mints_nothing(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _installed(session, a)
        response = await client.post(
            a.g(f"/apps/{app.id}/handoff/board"), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == GuildAppMessages.SERVICE_NOT_REGISTERED


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
        a = await acting_user(guild_role=GuildRole.admin)
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
        a = await acting_user(guild_role=GuildRole.admin)
        app = await self._install(session, a)

        response = await client.post(
            a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["connect_url"] == (
            "https://widgetco.example.test/connect/github"
            f"?connection_ref={body['connection_ref']}"
        )

    async def test_no_token_travels_in_the_url(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """The only thing in the query string is the opaque handle. It
        authorizes nothing: the app writes its result back over its own
        authenticated channel."""
        a = await acting_user(guild_role=GuildRole.admin)
        app = await self._install(session, a)

        body = (
            await client.post(
                a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
            )
        ).json()
        query = body["connect_url"].split("?", 1)[1]
        assert query == f"connection_ref={body['connection_ref']}"
        for smell in ("token", "jwt", "secret", "Bearer", "eyJ"):
            assert smell not in query

    async def test_an_unregistered_app_sends_nobody_anywhere(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await self._install(session, a)

        response = await client.post(
            a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == GuildAppMessages.SERVICE_NOT_REGISTERED

    async def test_a_deactivated_registration_sends_nobody_anywhere(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await self._install(session, a)
        await _mark(session, registration, enabled=False)

        response = await client.post(
            a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == GuildAppMessages.SERVICE_NOT_REGISTERED

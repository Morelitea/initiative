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

import hashlib
import hmac
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
from app.models.platform.app_service_registration import AppServiceStatus
from app.models.platform.guild import GuildRole
from app.services.marketplace.app_subjects import ensure_subject
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
    """A service app declaring one surface per rung of the visibility ladder."""
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
            {
                "id": "runs",
                "path": "/embed/runs",
                "scopes": ["guild", "initiative"],
                "visibility": "initiative_manager",
                "name": {"en": "Runs"},
            },
            {
                "id": "inside",
                "path": "/embed/inside",
                "scopes": ["initiative"],
                "visibility": "member",
                "name": {"en": "Inside"},
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

    @pytest.mark.parametrize(
        "status",
        [
            AppServiceStatus.UNVERIFIED,
            AppServiceStatus.UNREACHABLE,
            AppServiceStatus.MANIFEST_MISMATCH,
            AppServiceStatus.SIGNATURE_MISMATCH,
        ],
    )
    async def test_only_a_verified_registration_is_available(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        registration,
        status: str,
    ):
        """Availability tracks the last verification as well as the kill switch:
        the app the deployment registered is the one that has to be answering."""
        a = await acting_user(guild_role=GuildRole.admin)
        await _installed(session, a)
        await _mark(session, registration, status=status)

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
        a = await acting_user(guild_role=GuildRole.admin)
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
        assert claims["jti"]
        assert "email" not in claims and "guild_role" not in claims

        # The subject is pairwise (OIDC Core §8.1): it names the member to this
        # install and is not the row id, so an app storing `sub` as its key for
        # a person is not storing something another app would recognize.
        assert claims["sub"] != str(a.user.id)
        assert claims["sub"] == await ensure_subject(
            session, app_install_id=app.id, guild_id=a.guild.id, user_id=a.user.id
        )

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

    async def test_a_surface_that_renders_only_inside_an_initiative_is_not_here(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """``member`` means something different in each place, so the route has
        to agree with the surface before the rung is read at all.

        This route names no initiative, so a surface declared only for one has
        no audience it could be measured against here — and a guild member who
        belongs to no initiative would otherwise clear ``member`` and be handed
        a token for it. Not offered here means not found here, for everyone.
        """
        a = await acting_user(guild_role=GuildRole.admin)
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
        """This route names no initiative, so it cannot admit a manager of one.

        The surface renders in both scopes, and its rung is read against where
        it was opened: guild-wide there is nothing to manage, so the same
        declaration that admits a manager inside their initiative admits only
        admins out here.
        """
        a = await acting_user(guild_role=GuildRole.admin)
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
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _installed(session, a)

        response = await client.post(
            a.g(f"/apps/{app.id}/handoff/runs"), headers=a.headers
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

    @pytest.mark.parametrize(
        "status",
        [
            AppServiceStatus.UNVERIFIED,
            AppServiceStatus.UNREACHABLE,
            AppServiceStatus.MANIFEST_MISMATCH,
            AppServiceStatus.SIGNATURE_MISMATCH,
        ],
    )
    async def test_only_a_verified_registration_mints(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        registration,
        status: str,
    ):
        """A surface is declared by a manifest, so the mint requires the last
        verification to have confirmed which manifest this service serves. The
        data plane already read it this way; this is the same rule."""
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _installed(session, a)
        await _mark(session, registration, status=status)

        response = await client.post(
            a.g(f"/apps/{app.id}/handoff/board"), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == GuildAppMessages.SERVICE_NOT_REGISTERED


class TestInitiativeHandoff:
    """The same install, opened from inside one initiative.

    Three gates stack here, and each is asserted on its own: the initiative has
    to be one the caller can reach, the surface has to have asked to render in
    an initiative, and the rung is then read *here* — where ``member`` means
    this initiative's members rather than the guild's.
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

    async def test_a_manager_opens_the_surface_named_for_them(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        app = await _installed(session, a)
        pm = await acting_user(
            guild_role=GuildRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="project_manager",
        )

        response = await client.post(
            self._path(pm, a.initiative.id, app.id, "runs"), headers=pm.headers
        )
        assert response.status_code == 200, response.text

    async def test_the_token_names_the_initiative_it_was_opened_in(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """The route's answer, not the caller's — so an app can scope what it
        shows without trusting a parameter or asking a second question."""
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        app = await _installed(session, a)

        body = (
            await client.post(
                self._path(a, a.initiative.id, app.id, "runs"), headers=a.headers
            )
        ).json()
        claims = self._claims(body)
        assert claims["initiative_id"] == a.initiative.id
        assert claims["guild_id"] == a.guild.id
        assert claims["app_install_id"] == app.id
        assert claims["surface_id"] == "runs"

    async def test_the_guild_wide_route_names_no_initiative(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """Absent rather than null: "which initiative is this?" has one answer
        guild-wide, not two shapes that both mean none."""
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        app = await _installed(session, a)

        body = (
            await client.post(a.g(f"/apps/{app.id}/handoff/runs"), headers=a.headers)
        ).json()
        assert "initiative_id" not in self._claims(body)

    async def test_a_member_of_the_initiative_is_not_a_manager_of_it(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        app = await _installed(session, a)
        member = await acting_user(
            guild_role=GuildRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )

        response = await client.post(
            self._path(member, a.initiative.id, app.id, "runs"), headers=member.headers
        )
        assert response.status_code == 403
        assert response.json()["detail"] == GuildAppMessages.SURFACE_ADMIN_ONLY

    async def test_a_member_of_the_initiative_opens_a_member_surface(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """The rung that is guild-wide on the other route is this initiative's
        members here — the same word, read where it was opened."""
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        app = await _installed(session, a)
        member = await acting_user(
            guild_role=GuildRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )

        response = await client.post(
            self._path(member, a.initiative.id, app.id, "inside"),
            headers=member.headers,
        )
        assert response.status_code == 200, response.text
        assert self._claims(response.json())["initiative_id"] == a.initiative.id

    async def test_a_guild_member_in_no_initiative_reaches_none_of_it(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """Opening a surface in an initiative means reaching the initiative,
        under the same scope rule that governs its content."""
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        app = await _installed(session, a)
        outsider = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        response = await client.post(
            self._path(outsider, a.initiative.id, app.id, "inside"),
            headers=outsider.headers,
        )
        assert response.status_code == 404
        assert response.json()["detail"] == InitiativeMessages.NOT_FOUND

    async def test_managing_one_initiative_says_nothing_about_another(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        app = await _installed(session, a)
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
        membership, and not a rung named for someone else."""
        owner = await acting_user(guild_role=GuildRole.member, initiative=True)
        admin = await acting_user(guild_role=GuildRole.admin, guild=owner.guild)
        app = await _installed(session, admin)

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
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        app = await _installed(session, a)

        for surface in ("board", "console"):
            response = await client.post(
                self._path(a, a.initiative.id, app.id, surface), headers=a.headers
            )
            assert response.status_code == 404, response.text
            assert response.json()["detail"] == GuildAppMessages.SURFACE_NOT_FOUND


class TestPlacement:
    """Which initiatives an app's initiative surfaces appear in.

    Placement is the guild's own answer to where an app belongs, not an
    audience rule — so unlike ``visibility``, it reads the same for a guild
    admin as for anyone else.
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

    async def test_an_install_starts_placed_everywhere(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        await _installed(session, a)

        body = (await client.get(a.g("/apps/"), headers=a.headers)).json()
        assert [item["placement"] for item in body["items"]] == [{}]

    async def test_an_admin_narrows_it(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        app = await _installed(session, a)

        response = await client.patch(
            a.g(f"/apps/{app.id}"),
            headers=a.headers,
            json={"placement": {"initiatives": [a.initiative.id]}},
        )
        assert response.status_code == 200, response.text
        assert response.json()["placement"] == {"initiatives": [a.initiative.id]}

    async def test_it_may_only_name_an_initiative_this_guild_has(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """Stated as an id this guild has no initiative for, rather than as one
        borrowed from another guild: initiative ids are per-guild, so the two
        guilds' numbering can coincide and a borrowed id would only be refused
        when the numbers happened to differ."""
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        app = await _installed(session, a)

        response = await client.patch(
            a.g(f"/apps/{app.id}"),
            headers=a.headers,
            json={"placement": {"initiatives": [a.initiative.id + 10_000]}},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == GuildAppMessages.PLACEMENT_INVALID

    async def test_a_member_does_not_place_apps(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        app = await _installed(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        response = await client.patch(
            member.g(f"/apps/{app.id}"),
            headers=member.headers,
            json={"placement": {"initiatives": []}},
        )
        assert response.status_code == 403

    async def test_a_surface_placed_elsewhere_is_not_in_this_initiative(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """And not for the admin who placed it either — this is where the app
        goes, which is their own answer rather than a rule about them."""
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        other = await acting_user(
            guild_role=GuildRole.admin, guild=a.guild, initiative=True
        )
        app = await _installed(session, a)

        await client.patch(
            a.g(f"/apps/{app.id}"),
            headers=a.headers,
            json={"placement": {"initiatives": [other.initiative.id]}},
        )

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
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        app = await _installed(session, a)
        await client.patch(
            a.g(f"/apps/{app.id}"),
            headers=a.headers,
            json={"placement": {"initiatives": []}},
        )

        response = await client.post(
            a.g(f"/apps/{app.id}/handoff/runs"), headers=a.headers
        )
        assert response.status_code == 200, response.text


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
        assert body["connect_url"].startswith(
            "https://widgetco.example.test/connect/github?"
        )
        query = parse_qs(urlsplit(body["connect_url"]).query)
        assert query["connection_ref"] == [body["connection_ref"]]
        assert query["guild_id"] == [str(a.guild.id)]

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
        a = await acting_user(guild_role=GuildRole.admin)
        app = await self._install(session, a)

        body = (
            await client.post(
                a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
            )
        ).json()

        assert body["connect_url"].startswith(
            "https://widgetco.example.test/connect/github"
        )

    async def test_no_token_travels_in_the_url(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """The query string carries the opaque handle and the guild to write
        back under, and no credential of any kind: the app writes its result
        over its own authenticated channel."""
        a = await acting_user(guild_role=GuildRole.admin)
        app = await self._install(session, a)

        body = (
            await client.post(
                a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
            )
        ).json()
        query = body["connect_url"].split("?", 1)[1]
        # Pinned exactly, so anything added to this URL is added deliberately.
        # The return address is signed rather than secret — a MAC over a public
        # URL, which is why it travels here and the secret does not.
        assert set(parse_qs(query)) == {
            "connection_ref",
            "guild_id",
            "return_url",
            "return_sig",
        }
        for smell in ("token", "jwt", "secret", "Bearer", "eyJ"):
            assert smell not in query

    async def test_the_app_is_told_where_to_send_them_back(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """An app knows a handle and a guild id, and has never been told what
        language this person reads. So it does not write the ending: it hands
        them back here with one word, and Initiative renders the sentence.

        The address is Initiative's own, built from the frontend entry the
        deployment publishes rather than from anything the app said."""
        a = await acting_user(guild_role=GuildRole.admin)
        app = await self._install(session, a)

        body = (
            await client.post(
                a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
            )
        ).json()
        query = parse_qs(urlsplit(body["connect_url"]).query)

        home = query["return_url"][0]
        assert home.startswith(f"{settings.APP_URL.rstrip('/')}/apps/connected?")
        # Which app and which connection, so the page can say what was being
        # connected without the app having to put it back on the URL.
        assert parse_qs(urlsplit(home).query) == {
            "app": [SERVICE_ID],
            "connection": ["github"],
        }

    async def test_the_return_address_is_signed_with_the_app_s_own_secret(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """The browser carries this, so anybody can propose an address. An app
        that followed one it was merely handed would be a redirector on a
        hostname people trust, reached through a real vendor login — so the app
        checks a MAC, and only Initiative can produce one.

        The secret itself stays where it was: what travels is the MAC."""
        a = await acting_user(guild_role=GuildRole.admin)
        app = await self._install(session, a)

        body = (
            await client.post(
                a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
            )
        ).json()
        query = parse_qs(urlsplit(body["connect_url"]).query)

        expected = hmac.new(
            b"test-secret", query["return_url"][0].encode("utf-8"), hashlib.sha256
        ).hexdigest()
        assert query["return_sig"] == [expected]
        assert "test-secret" not in body["connect_url"]

    async def test_a_registration_with_no_secret_sends_no_address(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """Nothing to sign with, so nothing is offered. The app then says its
        piece on its own page — the same thing it does for somebody who arrived
        by a hand-copied link, and better than an unsigned address it would
        have to take on trust."""
        await _mark(session, registration, secret_encrypted=None)
        a = await acting_user(guild_role=GuildRole.admin)
        app = await self._install(session, a)

        body = (
            await client.post(
                a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
            )
        ).json()
        query = parse_qs(urlsplit(body["connect_url"]).query)

        assert "return_url" not in query
        assert "return_sig" not in query
        # And the rest of the handoff is untouched: the flow still works, the
        # ending is just the app's own page.
        assert query["connection_ref"] == [body["connection_ref"]]

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

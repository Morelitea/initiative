"""Configuring an app, connecting to it, and every way that access ends.

Four things carry the weight here.

**A credential goes in and does not come back.** Every read of an install
reports which fields hold a value and never the value, for the member who typed
it and the guild admin who governs the install alike. The tests read the whole
payload and assert the plaintext is nowhere in it, rather than checking the one
field somebody remembered to hide.

**A personal connection is the member's, and the admin's to govern.** One
member must not see another's row; a guild admin must see every one, because
admins have full authority over their guild. That is a database policy rather
than an endpoint branch, so the tests exercise it through real roles: the
``client`` fixture executes as ``app_user`` under the guild role it routes into.

**Installation never waits on a person.** An app whose credentials are supplied
per member installs with none present and reports itself as needing no
configuration — connecting is something members do afterwards, if they want
what it unlocks.

**Access ends when the relationship does.** Leaving, being removed, being
revoked or blocked, closing an account, uninstalling and deleting the guild each
delete the stored values, and each queues the revocation that tells the app to
let go at the vendor. The teardown tests assert on the rows *and* on the
recorded revocations, because deleting our copy is only half of it.
"""

from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import GuildAppMessages, MarketplaceMessages
from app.models.platform.guild import GuildRole
from app.models.tenant.guild_app_user_connection import GuildAppUserConnection
from app.services.tenant import app_revocation
from app.testing import (
    create_app_service_registration,
    create_guild_app,
    create_guild_membership,
    create_marketplace_listing,
    marketplace_uid,
    route_session_to_guild,
)

pytestmark = pytest.mark.asyncio


def _field(key: str, field_type: str, **extra) -> dict:
    return {"key": key, "type": field_type, "label": {"en": key}, **extra}


ADMIN_CONNECTION = {
    "id": "admin",
    "scope": "static",
    "label": {"en": "Admin API"},
    "access_hint": {"api": "Admin", "scopes": ["read_orders"]},
    "fields": [
        _field("shop_domain", "string", required=True),
        _field("admin_token", "secret", required=True),
    ],
}

GITHUB_CONNECTION = {
    "id": "github",
    "scope": "interactive",
    "label": {"en": "GitHub"},
    "connect_path": "/connect/github",
    "fields": [_field("access_token", "secret", managed=True)],
}

SERVICE_DEFINITION = {
    "app_kind": "service",
    "service": {"public_id": "tests.shop", "protocol": 1},
    "features": [],
    "connections": [ADMIN_CONNECTION, GITHUB_CONNECTION],
}

MEMBER_ONLY_DEFINITION = {
    "app_kind": "service",
    "service": {"public_id": "tests.gh", "protocol": 1},
    "features": [],
    "connections": [GITHUB_CONNECTION],
}

SECRET = "shpat_supersecret"
VALID_ADMIN_VALUES = {"shop_domain": "example.test", "admin_token": SECRET}


async def _install(session: AsyncSession, actor, definition=SERVICE_DEFINITION):
    return await create_guild_app(
        session, actor.guild, actor.user, definition=definition
    )


async def _rows(session: AsyncSession, guild_id: int) -> list:
    """The connection rows as stored, read past RLS via the setup session."""
    await route_session_to_guild(session, guild_id)
    return list((await session.exec(select(GuildAppUserConnection))).all())


@pytest.fixture(autouse=True)
async def wired_app_services(session: AsyncSession):
    """The deployment has both test apps wired up.

    Starting a member's vendor flow sends them to the app's own URL, which
    comes from a registration — so a guild whose app service is not registered
    here has nowhere to send anyone. Every test in this file assumes the
    ordinary case: the operator wired the app up, and it is switched on.
    """
    return [
        await create_app_service_registration(
            session, public_id=public_id, base_url=f"https://{slug}.example.test"
        )
        for public_id, slug in (("tests.shop", "shop"), ("tests.gh", "github"))
    ]


@pytest.fixture
def recorded_revocations(monkeypatch):
    """Capture what each teardown asked the apps to revoke.

    The transport itself belongs to the app protocol; what this phase owes is
    that an intent is raised for every credential it deletes, addressed by the
    handle the app knows it by.
    """
    captured: list = []

    async def _capture(intents):
        captured.extend(intents)

    monkeypatch.setattr(app_revocation, "dispatch_revocations", _capture)
    return captured


# ---------------------------------------------------------------------------
# Installing a service app
# ---------------------------------------------------------------------------


class TestInstallKind:
    async def test_a_service_listing_installs_with_its_connections(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """Installing through the endpoint is what makes this whole file
        reachable in production: the row pins the listing's definition, and the
        form a guild fills in is read straight off it."""
        uid = marketplace_uid("servicelisting")
        await create_marketplace_listing(
            session,
            uid=uid,
            public_id="tests.service",
            kind="app",
            definition=SERVICE_DEFINITION,
        )
        a = await acting_user(guild_role=GuildRole.admin)
        response = await client.post(
            a.g("/apps/"), headers=a.headers, json={"listing_uid": uid}
        )
        assert response.status_code == 201, response.text
        app_id = response.json()["id"]

        detail = (await client.get(a.g(f"/apps/{app_id}"), headers=a.headers)).json()
        assert [c["id"] for c in detail["connections"]] == ["admin", "github"]


class TestInstallIsNotGatedOnAConnection:
    async def test_an_app_with_only_member_connections_needs_no_configuration(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """Nobody has to connect for the install to be valid."""
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a, MEMBER_ONLY_DEFINITION)

        response = await client.get(a.g(f"/apps/{app.id}"), headers=a.headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["needs_config"] is False
        assert body["config_state"] == "unverified"
        assert [c["id"] for c in body["connections"]] == ["github"]
        assert body["connections"][0]["satisfied"] is False

    async def test_a_guild_credential_is_reported_as_outstanding(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        body = (await client.get(a.g(f"/apps/{app.id}"), headers=a.headers)).json()
        assert body["needs_config"] is True


# ---------------------------------------------------------------------------
# Guild-scoped configuration
# ---------------------------------------------------------------------------


class TestConfig:
    async def test_a_secret_is_stored_and_echoed_only_as_presence(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)

        response = await client.put(
            a.g(f"/apps/{app.id}/config"),
            headers=a.headers,
            json={"values": {"admin": VALID_ADMIN_VALUES}},
        )
        assert response.status_code == 200, response.text
        body = response.json()

        admin = next(c for c in body["connections"] if c["id"] == "admin")
        assert admin["has_value"] == {"shop_domain": True, "admin_token": True}
        assert admin["satisfied"] is True
        assert body["needs_config"] is False
        # The whole payload, not just the field somebody remembered to hide.
        assert SECRET not in response.text

    async def test_the_secret_is_not_in_the_list_payload_either(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        await client.put(
            a.g(f"/apps/{app.id}/config"),
            headers=a.headers,
            json={"values": {"admin": VALID_ADMIN_VALUES}},
        )
        listed = await client.get(a.g("/apps/"), headers=a.headers)
        assert SECRET not in listed.text

    async def test_configuring_is_a_guild_admin_action(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        response = await client.put(
            member.g(f"/apps/{app.id}/config"),
            headers=member.headers,
            json={"values": {"admin": VALID_ADMIN_VALUES}},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == GuildAppMessages.ADMIN_REQUIRED

    async def test_values_are_validated_against_the_pinned_schema(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)

        response = await client.put(
            a.g(f"/apps/{app.id}/config"),
            headers=a.headers,
            json={"values": {"admin": {**VALID_ADMIN_VALUES, "nope": "x"}}},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == GuildAppMessages.CONFIG_UNKNOWN_FIELD

    async def test_an_unknown_connection_is_refused(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        response = await client.put(
            a.g(f"/apps/{app.id}/config"),
            headers=a.headers,
            json={"values": {"stripe": {"key": "x"}}},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == GuildAppMessages.CONFIG_UNKNOWN_CONNECTION

    async def test_a_per_member_connection_is_not_set_through_the_form(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """It is that member's to make, and the app writes the result."""
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        response = await client.put(
            a.g(f"/apps/{app.id}/config"),
            headers=a.headers,
            json={"values": {"github": {"access_token": "gho_x"}}},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == GuildAppMessages.CONNECTION_NOT_STATIC

    async def test_a_required_field_left_empty_is_refused(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        response = await client.put(
            a.g(f"/apps/{app.id}/config"),
            headers=a.headers,
            json={"values": {"admin": {"shop_domain": "example.test"}}},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == GuildAppMessages.CONFIG_REQUIRED_FIELD

    async def test_writing_configuration_resets_the_apps_verdict(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """Whatever the app said about the old values is not an answer about
        the new ones."""
        a = await acting_user(guild_role=GuildRole.admin)
        app = await create_guild_app(
            session,
            a.guild,
            a.user,
            definition=SERVICE_DEFINITION,
            config_state="ok",
        )

        body = (
            await client.put(
                a.g(f"/apps/{app.id}/config"),
                headers=a.headers,
                json={"values": {"admin": VALID_ADMIN_VALUES}},
            )
        ).json()
        assert body["config_state"] == "unverified"

    async def test_clearing_a_guild_credential_revokes_it(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        await client.put(
            a.g(f"/apps/{app.id}/config"),
            headers=a.headers,
            json={"values": {"admin": VALID_ADMIN_VALUES}},
        )

        response = await client.delete(
            a.g(f"/apps/{app.id}/connections/admin"), headers=a.headers
        )
        assert response.status_code == 204
        assert [i.connection_id for i in recorded_revocations] == ["admin"]

        body = (await client.get(a.g(f"/apps/{app.id}"), headers=a.headers)).json()
        assert body["needs_config"] is True


# ---------------------------------------------------------------------------
# A member's own connection
# ---------------------------------------------------------------------------


class TestConnect:
    async def test_any_member_may_connect_their_own_account(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """The vendor is going to authorize *them*: what the credential reaches
        is what they already reach, so this is not an admin's decision."""
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        response = await client.post(
            member.g(f"/apps/{app.id}/connections/github/connect"),
            headers=member.headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["connect_path"] == "/connect/github"
        assert body["status"] == "pending"
        assert body["connection_ref"]
        # Where to actually send them: the operator's address, the manifest's
        # path, the handle the app will store its result against, and the guild
        # to write it back under — the app addresses every install by guild and
        # cannot derive one from the ref.
        #
        # Asserted as those four things rather than as one pasted string. The
        # connect URL also carries a signed return address, which has its own
        # tests (``guild_apps_platform_test``) and is not what this one is
        # about: pinning the whole query here made a test about WHO MAY CONNECT
        # fail the day the URL grew a parameter.
        connect = urlparse(body["connect_url"])
        assert f"{connect.scheme}://{connect.netloc}{connect.path}" == (
            "https://shop.example.test/connect/github"
        )
        query = parse_qs(connect.query)
        assert query["connection_ref"] == [body["connection_ref"]]
        assert query["guild_id"] == [str(a.guild.id)]

    async def test_the_handle_is_opaque_and_carries_nothing_about_the_person(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """An app addresses a member by this handle and never learns who they
        are, so the handle must not be derived from them. Checked as
        unrelatedness rather than as a substring search: a random handle
        contains a one-digit id about half the time, which would make a
        substring assertion a coin toss rather than a property."""
        a = await acting_user(guild_role=GuildRole.admin)
        b = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        app = await _install(session, a)

        async def connect(actor):
            return (
                await client.post(
                    a.g(f"/apps/{app.id}/connections/github/connect"),
                    headers=actor.headers,
                )
            ).json()["connection_ref"]

        ref_a = await connect(a)
        ref_b = await connect(b)

        # Nothing about the person survives into it.
        assert a.user.email not in ref_a
        assert a.user.email.split("@")[0] not in ref_a
        # Two members of the same guild connecting to the same app get handles
        # with nothing in common — neither equal nor a shared derivation.
        assert ref_a != ref_b
        assert len(ref_a) == len(ref_b)
        # And it is drawn, not computed: same person, same app, a second
        # connection elsewhere would not reproduce it.
        assert ref_a not in ref_b and ref_b not in ref_a

    async def test_reconnecting_keeps_the_same_handle(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """The app is already holding credentials under that handle; a new one
        would orphan them."""
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)

        first = await client.post(
            a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
        )
        second = await client.post(
            a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
        )
        assert first.json()["connection_ref"] == second.json()["connection_ref"]
        assert len(await _rows(session, a.guild.id)) == 1

    async def test_a_guild_scoped_connection_is_not_connected_to(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        response = await client.post(
            a.g(f"/apps/{app.id}/connections/admin/connect"), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == GuildAppMessages.CONNECTION_NOT_INTERACTIVE

    async def test_an_unknown_connection_is_a_404(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        response = await client.post(
            a.g(f"/apps/{app.id}/connections/nope/connect"), headers=a.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == GuildAppMessages.CONNECTION_NOT_FOUND

    async def test_a_disabled_app_accepts_no_new_connections(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        await client.patch(
            a.g(f"/apps/{app.id}"), headers=a.headers, json={"enabled": False}
        )
        response = await client.post(
            a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == GuildAppMessages.DISABLED

    async def test_a_member_disconnects_their_own(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        await client.post(
            member.g(f"/apps/{app.id}/connections/github/connect"),
            headers=member.headers,
        )

        response = await client.delete(
            member.g(f"/apps/{app.id}/connections/github"), headers=member.headers
        )
        assert response.status_code == 204
        assert await _rows(session, a.guild.id) == []
        assert [i.reason for i in recorded_revocations] == ["disconnected"]


# ---------------------------------------------------------------------------
# Own row, or guild admin — and nothing in between
# ---------------------------------------------------------------------------


class TestConnectionVisibility:
    async def test_a_second_member_does_not_see_the_firsts_connection(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """One member's vendor account is not another member's business. The
        gate is the table's own-row policy, so there is no endpoint branch that
        could be forgotten."""
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        first = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        second = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        await client.post(
            first.g(f"/apps/{app.id}/connections/github/connect"),
            headers=first.headers,
        )

        body = (
            await client.get(second.g(f"/apps/{app.id}"), headers=second.headers)
        ).json()
        github = next(c for c in body["connections"] if c["id"] == "github")
        assert github["status"] is None
        assert github["satisfied"] is False
        assert github["blocked"] is False

    async def test_the_connecting_member_sees_their_own(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        await client.post(
            member.g(f"/apps/{app.id}/connections/github/connect"),
            headers=member.headers,
        )

        body = (
            await client.get(member.g(f"/apps/{app.id}"), headers=member.headers)
        ).json()
        github = next(c for c in body["connections"] if c["id"] == "github")
        assert github["status"] == "pending"

    async def test_a_member_may_not_read_the_members_view(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        response = await client.get(
            member.g(f"/apps/{app.id}/members"), headers=member.headers
        )
        assert response.status_code == 403
        assert response.json()["detail"] == GuildAppMessages.ADMIN_REQUIRED

    async def test_a_guild_admin_sees_every_members_connection(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """Admins have full authority over their guild, and knowing who reaches
        an outside system through it is part of that."""
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        first = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        second = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        for actor in (first, second):
            await client.post(
                actor.g(f"/apps/{app.id}/connections/github/connect"),
                headers=actor.headers,
            )

        body = (
            await client.get(a.g(f"/apps/{app.id}/members"), headers=a.headers)
        ).json()
        assert sorted(item["user_id"] for item in body["items"]) == sorted(
            [first.user.id, second.user.id]
        )
        github = next(s for s in body["summary"] if s["connection_id"] == "github")
        assert github["connected_count"] == 2
        assert github["blocked_count"] == 0
        # Three members in the guild: the admin plus the two who connected.
        assert github["member_count"] == 3

    async def test_the_members_view_carries_no_values_and_no_handles(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """Revoking beats reading: no admin workflow needs the bytes, and the
        handle is between the platform and the app."""
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        started = await client.post(
            member.g(f"/apps/{app.id}/connections/github/connect"),
            headers=member.headers,
        )
        ref = started.json()["connection_ref"]

        response = await client.get(a.g(f"/apps/{app.id}/members"), headers=a.headers)
        assert ref not in response.text
        assert "config_secrets" not in response.text

    async def test_another_guilds_admin_sees_nothing(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        await client.post(
            a.g(f"/apps/{app.id}/connections/github/connect"), headers=a.headers
        )
        stranger = await acting_user(guild_role=GuildRole.admin)

        response = await client.get(
            stranger.g(f"/apps/{app.id}"), headers=stranger.headers
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Admin governance
# ---------------------------------------------------------------------------


class TestGovernance:
    async def test_an_admin_revokes_one_members_connection(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        await client.post(
            member.g(f"/apps/{app.id}/connections/github/connect"),
            headers=member.headers,
        )

        response = await client.delete(
            a.g(f"/apps/{app.id}/members/{member.user.id}/connections/github"),
            headers=a.headers,
        )
        assert response.status_code == 204
        assert await _rows(session, a.guild.id) == []
        assert [i.reason for i in recorded_revocations] == ["admin_revoked"]

    async def test_a_revoked_member_may_connect_again(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        await client.post(
            member.g(f"/apps/{app.id}/connections/github/connect"),
            headers=member.headers,
        )
        await client.delete(
            a.g(f"/apps/{app.id}/members/{member.user.id}/connections/github"),
            headers=a.headers,
        )

        again = await client.post(
            member.g(f"/apps/{app.id}/connections/github/connect"),
            headers=member.headers,
        )
        assert again.status_code == 200

    async def test_blocking_revokes_and_refuses_the_next_attempt(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        await client.post(
            member.g(f"/apps/{app.id}/connections/github/connect"),
            headers=member.headers,
        )

        blocked = await client.post(
            a.g(f"/apps/{app.id}/members/{member.user.id}/connections/github/block"),
            headers=a.headers,
        )
        assert blocked.status_code == 204
        assert [i.reason for i in recorded_revocations] == ["blocked"]

        retry = await client.post(
            member.g(f"/apps/{app.id}/connections/github/connect"),
            headers=member.headers,
        )
        assert retry.status_code == 403
        assert retry.json()["detail"] == GuildAppMessages.CONNECTION_BLOCKED

    async def test_a_block_leaves_a_tombstone_holding_no_values(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        await client.post(
            member.g(f"/apps/{app.id}/connections/github/connect"),
            headers=member.headers,
        )
        await client.post(
            a.g(f"/apps/{app.id}/members/{member.user.id}/connections/github/block"),
            headers=a.headers,
        )

        rows = await _rows(session, a.guild.id)
        assert len(rows) == 1
        assert rows[0].blocked_at is not None
        assert rows[0].blocked_by_id == a.user.id
        assert rows[0].config_secrets == {}
        assert rows[0].status == "blocked"

    async def test_a_member_can_be_blocked_before_ever_connecting(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        response = await client.post(
            a.g(f"/apps/{app.id}/members/{member.user.id}/connections/github/block"),
            headers=a.headers,
        )
        assert response.status_code == 204
        retry = await client.post(
            member.g(f"/apps/{app.id}/connections/github/connect"),
            headers=member.headers,
        )
        assert retry.status_code == 403

    async def test_lifting_a_block_lets_them_connect_again(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        await client.post(
            a.g(f"/apps/{app.id}/members/{member.user.id}/connections/github/block"),
            headers=a.headers,
        )

        lifted = await client.delete(
            a.g(f"/apps/{app.id}/members/{member.user.id}/connections/github/block"),
            headers=a.headers,
        )
        assert lifted.status_code == 204
        retry = await client.post(
            member.g(f"/apps/{app.id}/connections/github/connect"),
            headers=member.headers,
        )
        assert retry.status_code == 200

    async def test_revoke_all_ends_everyones_without_touching_the_install(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        """For a suspected compromise: reacting fast should not cost the guild
        its configuration."""
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        await client.put(
            a.g(f"/apps/{app.id}/config"),
            headers=a.headers,
            json={"values": {"admin": VALID_ADMIN_VALUES}},
        )
        members = [
            await acting_user(guild_role=GuildRole.member, guild=a.guild)
            for _ in range(2)
        ]
        for member in members:
            await client.post(
                member.g(f"/apps/{app.id}/connections/github/connect"),
                headers=member.headers,
            )

        response = await client.post(
            a.g(f"/apps/{app.id}/revoke-all"), headers=a.headers
        )
        assert response.status_code == 204
        assert await _rows(session, a.guild.id) == []
        assert len(recorded_revocations) == 2

        # The install and its guild credential are still standing.
        body = (await client.get(a.g(f"/apps/{app.id}"), headers=a.headers)).json()
        assert body["needs_config"] is False

    async def test_governance_is_admin_only(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        other = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        base = f"/apps/{app.id}/members/{other.user.id}/connections/github"
        assert (
            await client.delete(member.g(base), headers=member.headers)
        ).status_code == 403
        assert (
            await client.post(member.g(f"{base}/block"), headers=member.headers)
        ).status_code == 403
        assert (
            await client.post(
                member.g(f"/apps/{app.id}/revoke-all"), headers=member.headers
            )
        ).status_code == 403


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


UPGRADE_UID = marketplace_uid("upgradeable")


def _tool_definition() -> dict:
    return {"app_kind": "tool_instance", "tool": "calendar", "default_name": "Cal"}


class TestUpgrade:
    async def test_upgrading_re_pins_to_the_current_version(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        await create_marketplace_listing(
            session,
            uid=UPGRADE_UID,
            public_id="tests.upgradeable",
            kind="app",
            version="1.0.0",
            definition=_tool_definition(),
        )
        a = await acting_user(guild_role=GuildRole.admin)
        installed = await client.post(
            a.g("/apps/"), headers=a.headers, json={"listing_uid": UPGRADE_UID}
        )
        app_id = installed.json()["id"]
        assert installed.json()["listing_version"] == "1.0.0"

        await create_marketplace_listing(
            session,
            uid=UPGRADE_UID,
            public_id="tests.upgradeable",
            kind="app",
            version="1.1.0",
            definition={**_tool_definition(), "default_name": "Cal v2"},
        )

        # What the settings page draws its Update button from.
        offered = await client.get(a.g(f"/apps/{app_id}"), headers=a.headers)
        assert offered.json()["update_version"] == "1.1.0"

        response = await client.post(a.g(f"/apps/{app_id}/upgrade"), headers=a.headers)
        assert response.status_code == 200, response.text
        assert response.json()["listing_version"] == "1.1.0"
        # And the button goes away rather than offering the version just taken.
        assert response.json()["update_version"] is None

    async def test_upgrading_to_the_pinned_version_is_refused(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        await create_marketplace_listing(
            session,
            uid=marketplace_uid("alreadylatest"),
            public_id="tests.alreadylatest",
            kind="app",
            definition=_tool_definition(),
        )
        a = await acting_user(guild_role=GuildRole.admin)
        installed = await client.post(
            a.g("/apps/"),
            headers=a.headers,
            json={"listing_uid": marketplace_uid("alreadylatest")},
        )
        response = await client.post(
            a.g(f"/apps/{installed.json()['id']}/upgrade"), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == MarketplaceMessages.ALREADY_LATEST_VERSION

    async def test_upgrading_is_admin_only(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        app = await _install(session, a)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        response = await client.post(
            member.g(f"/apps/{app.id}/upgrade"), headers=member.headers
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Teardown: access ends when the relationship does
# ---------------------------------------------------------------------------


async def _connected_member(client, acting_user, session, admin):
    app = await _install(session, admin)
    member = await acting_user(guild_role=GuildRole.member, guild=admin.guild)
    await client.post(
        member.g(f"/apps/{app.id}/connections/github/connect"), headers=member.headers
    )
    return app, member


class TestUninstallKillsAccess:
    async def test_uninstalling_deletes_every_members_connection(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        """An uninstalled app still receiving a guild's data is the thing this
        prevents — so the values go, and the app is told."""
        a = await acting_user(guild_role=GuildRole.admin)
        app, member = await _connected_member(client, acting_user, session, a)
        await client.put(
            a.g(f"/apps/{app.id}/config"),
            headers=a.headers,
            json={"values": {"admin": VALID_ADMIN_VALUES}},
        )

        response = await client.delete(a.g(f"/apps/{app.id}"), headers=a.headers)
        assert response.status_code == 204
        assert await _rows(session, a.guild.id) == []
        reasons = {i.reason for i in recorded_revocations}
        assert reasons == {"uninstalled"}
        # Both halves: the member's handle, and the guild-scoped credential.
        assert any(i.connection_ref for i in recorded_revocations)
        assert any(i.connection_ref is None for i in recorded_revocations)

    async def test_uninstalling_takes_blocked_tombstones_too(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """A block on an app that is no longer installed constrains nothing."""
        a = await acting_user(guild_role=GuildRole.admin)
        app, member = await _connected_member(client, acting_user, session, a)
        await client.post(
            a.g(f"/apps/{app.id}/members/{member.user.id}/connections/github/block"),
            headers=a.headers,
        )

        await client.delete(a.g(f"/apps/{app.id}"), headers=a.headers)
        assert await _rows(session, a.guild.id) == []


class TestRelationshipCascades:
    async def test_leaving_a_guild_ends_the_connections_made_in_it(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        _, member = await _connected_member(client, acting_user, session, a)

        response = await client.delete(
            f"/api/v1/guilds/{a.guild.id}/leave", headers=member.headers
        )
        assert response.status_code == 204, response.text
        assert await _rows(session, a.guild.id) == []
        assert [i.reason for i in recorded_revocations] == ["left_guild"]

    async def test_being_removed_from_a_guild_ends_them_too(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        _, member = await _connected_member(client, acting_user, session, a)

        response = await client.delete(
            a.g(f"/users/{member.user.id}"), headers=a.headers
        )
        assert response.status_code == 204, response.text
        assert await _rows(session, a.guild.id) == []
        assert [i.reason for i in recorded_revocations] == ["removed_from_guild"]

    async def test_leaving_does_not_touch_another_guild(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """Their access elsewhere is a relationship that has not ended."""
        a = await acting_user(guild_role=GuildRole.admin)
        b = await acting_user(guild_role=GuildRole.admin)
        _, member = await _connected_member(client, acting_user, session, a)
        app_b = await _install(session, b)
        await client.post(
            f"/api/v1/g/{b.guild.id}/apps/{app_b.id}/connections/github/connect",
            headers=b.headers,
        )

        await client.delete(
            f"/api/v1/guilds/{a.guild.id}/leave", headers=member.headers
        )
        assert await _rows(session, a.guild.id) == []
        assert len(await _rows(session, b.guild.id)) == 1

    async def test_a_block_survives_the_member_leaving(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """Somebody removed and later re-invited must not come back with the
        block quietly lifted."""
        a = await acting_user(guild_role=GuildRole.admin)
        app, member = await _connected_member(client, acting_user, session, a)
        await client.post(
            a.g(f"/apps/{app.id}/members/{member.user.id}/connections/github/block"),
            headers=a.headers,
        )

        await client.delete(
            f"/api/v1/guilds/{a.guild.id}/leave", headers=member.headers
        )
        rows = await _rows(session, a.guild.id)
        assert len(rows) == 1
        assert rows[0].blocked_at is not None

    async def test_deleting_a_guild_revokes_before_the_schema_goes(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        """The DROP would take the rows silently, leaving vendor grants
        outliving the guild that authorized them."""
        a = await acting_user(guild_role=GuildRole.admin)
        await _connected_member(client, acting_user, session, a)

        response = await client.request(
            "DELETE",
            f"/api/v1/guilds/{a.guild.id}",
            headers=a.headers,
            json={
                "password": "testpassword123",
                "confirmation_text": f"DELETE GUILD {a.guild.name.upper()}",
            },
        )
        assert response.status_code == 204, response.text
        assert [i.reason for i in recorded_revocations] == ["guild_deleted"]


class TestAccountDeletionSweep:
    async def test_closing_an_account_ends_connections_in_every_guild(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        """One sweep across all their memberships, not a per-guild chore."""
        admin_a = await acting_user(guild_role=GuildRole.admin)
        admin_b = await acting_user(guild_role=GuildRole.admin)
        _, member = await _connected_member(client, acting_user, session, admin_a)

        # The same person, in a second guild, connected there too.
        app_b = await _install(session, admin_b)
        await create_guild_membership(session, user=member.user, guild=admin_b.guild)
        connected = await client.post(
            f"/api/v1/g/{admin_b.guild.id}/apps/{app_b.id}/connections/github/connect",
            headers=member.headers,
        )
        assert connected.status_code == 200, connected.text

        response = await client.post(
            "/api/v1/users/me/delete-account",
            headers=member.headers,
            json={
                "password": "testpassword123",
                "action": "soft_delete",
                "confirmation_text": "DELETE MY ACCOUNT",
            },
        )
        assert response.status_code == 200, response.text

        # Both guilds, in one sweep.
        assert await _rows(session, admin_a.guild.id) == []
        assert await _rows(session, admin_b.guild.id) == []
        assert [i.reason for i in recorded_revocations] == [
            "account_closed",
            "account_closed",
        ]

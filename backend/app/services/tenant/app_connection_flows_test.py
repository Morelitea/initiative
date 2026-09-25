"""Connections Initiative runs, against a fake vendor and a fake app.

The whole trip is exercised through the routes a browser and an app use: a
member starts the flow, the vendor answers the callback with a code, Initiative
exchanges it (with PKCE), asks the app's ``after_connect`` hook, and stores the
result; an app asks for a token by reference and gets a fresh one, refreshed
once under the row's lock however many ask at once; and ending a connection
ends the grant at the vendor.
"""

from __future__ import annotations

import asyncio
import time
from urllib.parse import parse_qs, urlparse

import cryptography.fernet
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.app_access_token import seal_install_token
from app.core.config import settings
from app.core.security import SESSION_COOKIE_NAME
from app.core.encryption import SALT_APP_CONFIG, decrypt_field, encrypt_field
from app.core.messages import AppChannelMessages
from app.db import session as db_session
from app.db.session import set_rls_context
from app.models.platform.guild import GuildMembership, GuildRole
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.guild_app_user_connection import GuildAppUserConnection
from app.services.marketplace.registration_lookup import load_registrations
from app.services.tenant import app_connection_flows, app_revocation
from app.testing import (
    create_app_service_registration,
    create_guild_app,
    route_session_to_guild,
    sealed_vendor_values,
)
from app.testing.fake_vendor import FakeVendor

pytestmark = pytest.mark.integration

PUBLIC_ID = "tests.gh"
LISTING_UID = "TESTAPP0000009"
TOKEN_ROUTE = "/api/v1/app-platform/installation/connections/{ref}/token"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_KEY_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
PUBLIC_KEY_PEM = (
    _KEY.public_key()
    .public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    .decode()
)

VENDOR_VALUES = {
    "client_id": "client-123",
    "client_secret": "client-secret-456",
    "app_slug": "initiative-test",
    "app_id": "4242",
    "private_key": PRIVATE_KEY_PEM,
}


def _field(key: str) -> dict:
    return {"key": key, "type": "string", "label": {"en": key}, "managed": True}


FLOW = {
    "type": "oauth2",
    "authorize_url": "https://github.test/login/oauth/authorize",
    "token_url": "https://github.test/login/oauth/access_token",
    "client_id": "{vendor.client_id}",
    "client_secret": "{vendor.client_secret}",
    "scopes": ["read:user"],
    "pkce": True,
    "after_connect": True,
}

ACCOUNT = {
    "id": "account",
    "scope": "interactive",
    "label": {"en": "Your account"},
    "fields": [_field("login")],
    "flow": {
        **FLOW,
        "revoke": "rfc7009",
        "revoke_url": "https://github.test/revoke",
    },
}

HOOKED = {
    "id": "hooked",
    "scope": "interactive",
    "label": {"en": "Hooked"},
    "fields": [_field("login")],
    "flow": {**FLOW, "revoke": "hook"},
}

WORKSPACE = {
    "id": "workspace",
    "scope": "static",
    "label": {"en": "Organization"},
    "fields": [_field("owner"), _field("installation_id")],
    "flow": {
        **FLOW,
        "install_url": "https://github.test/apps/{vendor.app_slug}/installations/new",
    },
    "token": {
        "type": "jwt_bearer",
        "exchange_url": (
            "https://github.test/app/installations/{installation_id}/access_tokens"
        ),
        "iss": "{vendor.app_id}",
        "key": "{vendor.private_key}",
        "alg": "RS256",
        "lifetime": 540,
    },
}

DEFINITION = {
    "app_kind": "service",
    "service": {"public_id": PUBLIC_ID, "protocol": 1},
    "features": [],
    "connections": [ACCOUNT, HOOKED, WORKSPACE],
}


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    """Initiative signs its hook calls with the app platform's own key."""
    monkeypatch.setattr(
        settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", PRIVATE_KEY_PEM
    )
    monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_KEY_ID", "app-platform-1")


@pytest.fixture
def vendor(monkeypatch) -> FakeVendor:
    fake = FakeVendor()
    fake.install(monkeypatch)
    app_connection_flows.clear_token_cache()
    monkeypatch.setattr(app_revocation, "retry_delays", (0.0, 0.0))
    return fake


@pytest.fixture
async def registration(session: AsyncSession):
    return await create_app_service_registration(
        session,
        public_id=PUBLIC_ID,
        listing_uid=LISTING_UID,
        base_url="https://app.example.test",
        vendor_values=sealed_vendor_values(VENDOR_VALUES),
    )


async def _install(session: AsyncSession, actor, **overrides) -> GuildApp:
    return await create_guild_app(
        session,
        actor.guild,
        actor.user,
        definition=DEFINITION,
        listing_uid=LISTING_UID,
        **overrides,
    )


async def _member_row(
    session: AsyncSession, guild_id: int, app_id: int, connection_id: str = "account"
) -> GuildAppUserConnection | None:
    await route_session_to_guild(session, guild_id)
    session.expunge_all()
    return (
        await session.exec(
            select(GuildAppUserConnection).where(
                GuildAppUserConnection.app_id == app_id,
                GuildAppUserConnection.connection_id == connection_id,
            )
        )
    ).first()


async def _reload(session: AsyncSession, guild_id: int, app_id: int) -> GuildApp:
    await route_session_to_guild(session, guild_id)
    session.expunge_all()
    return (await session.exec(select(GuildApp).where(GuildApp.id == app_id))).one()


async def _start(client: AsyncClient, actor, app: GuildApp, connection: str) -> dict:
    response = await client.post(
        actor.g(f"/apps/{app.id}/connections/{connection}/connect"),
        headers=actor.headers,
    )
    assert response.status_code == 200, response.text
    url = urlparse(response.json()["connect_url"])
    return {key: values[0] for key, values in parse_qs(url.query).items()} | {
        "_url": url
    }


def _cookie(actor) -> dict[str, str]:
    """The session cookie the actor's browser carries."""
    token = actor.headers["Authorization"].removeprefix("Bearer ")
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


async def _callback(client: AsyncClient, actor, **params) -> dict:
    """The vendor's return, in a browser where ``actor`` is signed in (or no
    one is, when ``actor`` is ``None``)."""
    response = await client.get(
        "/api/v1/app-connections/callback",
        params=params,
        headers=_cookie(actor) if actor is not None else {},
    )
    assert response.status_code == 303, response.text
    return _landing(response.headers["location"])


def _landing(location: str) -> dict:
    parsed = urlparse(location)
    return {key: values[0] for key, values in parse_qs(parsed.query).items()} | {
        "_path": parsed.path
    }


def _install_headers(guild, app) -> dict[str, str]:
    token, _ = seal_install_token(
        guild_id=guild.id,
        install_id=app.id,
        client_id=PUBLIC_ID,
        scopes=frozenset(),
        initiative_id=None,
        user_id=None,
        purpose=None,
    )
    return {"Authorization": f"Bearer {token}"}


async def _connected_row(
    session: AsyncSession,
    actor,
    app: GuildApp,
    *,
    expires_in: int,
    connection_id: str = "account",
    ref: str = "cr_account_one",
) -> GuildAppUserConnection:
    """A member connection as a completed flow leaves it."""
    await route_session_to_guild(session, actor.guild.id)
    row = GuildAppUserConnection(
        app_id=app.id,
        connection_id=connection_id,
        user_id=actor.user.id,
        connection_ref=ref,
        config={"login": "alice", "expires_at": int(time.time()) + expires_in},
        config_secrets={
            "access_token": encrypt_field("gho_stored", SALT_APP_CONFIG),
            "refresh_token": encrypt_field("ghr_stored", SALT_APP_CONFIG),
        },
        status="connected",
        account_label="@alice",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


# ---------------------------------------------------------------------------
# The flow
# ---------------------------------------------------------------------------


class TestMemberFlow:
    async def test_authorize_callback_and_exchange(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """The whole trip: the member is sent to the vendor, comes back with a
        code, and Initiative exchanges it, asks the app who connected, and
        keeps the tokens."""
        a = await acting_user(guild_role=GuildRole.member)
        app = await _install(session, a)

        start = await _start(client, a, app, "account")
        assert start["client_id"] == "client-123"
        assert start["scope"] == "read:user"
        assert start["redirect_uri"] == app_connection_flows.callback_url()

        code = vendor.authorize(start["code_challenge"])
        landing = await _callback(client, a, state=start["state"], code=code)

        assert landing["_path"] == "/apps/connected"
        assert landing["outcome"] == "connected"
        assert landing["app"] == PUBLIC_ID
        assert landing["connection"] == "account"

        exchange = vendor.token_requests[0]
        assert exchange["grant_type"] == "authorization_code"
        assert exchange["redirect_uri"] == app_connection_flows.callback_url()
        assert exchange["code_verifier"]

        name, body, authorization = vendor.hooks[0]
        assert name == "after_connect"
        assert body["connection"] == "account"
        assert body["actor"] == "member"
        assert body["access_token"].startswith("gho_access_")
        claims = jwt.decode(
            authorization.removeprefix("Bearer "),
            options={"verify_signature": False},
        )
        assert claims["scope"] == "lifecycle"
        assert claims["hook"] == "after_connect"
        assert claims["app_install_id"] == app.id

        row = await _member_row(session, a.guild.id, app.id)
        assert row is not None
        assert row.status == "connected"
        assert row.account_label == "@alice"
        assert row.config["login"] == "alice"
        assert isinstance(row.config["expires_at"], int)
        assert row.connection_ref
        # Sealed, never stored as it came.
        assert row.config_secrets["access_token"] != body["access_token"]
        assert (
            decrypt_field(row.config_secrets["access_token"], SALT_APP_CONFIG)
            == body["access_token"]
        )

    async def test_reconnecting_keeps_the_handle(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=GuildRole.member)
        app = await _install(session, a)

        refs = []
        for _ in range(2):
            start = await _start(client, a, app, "account")
            code = vendor.authorize(start["code_challenge"])
            await _callback(client, a, state=start["state"], code=code)
            row = await _member_row(session, a.guild.id, app.id)
            assert row is not None
            refs.append(row.connection_ref)
        assert refs[0] == refs[1]

    async def test_pkce_is_verified(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """The code is bound to the challenge the authorization request sent; a
        verifier that does not answer it is refused by the vendor, and nothing
        is stored."""
        a = await acting_user(guild_role=GuildRole.member)
        app = await _install(session, a)
        start = await _start(client, a, app, "account")
        assert start["code_challenge_method"] == "S256"

        code = vendor.authorize("a-challenge-this-flow-never-sent")
        landing = await _callback(client, a, state=start["state"], code=code)

        assert landing["outcome"] == "refused"
        assert await _member_row(session, a.guild.id, app.id) is None

    async def test_a_tampered_state_is_refused(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=GuildRole.member)
        app = await _install(session, a)
        start = await _start(client, a, app, "account")
        code = vendor.authorize(start["code_challenge"])
        state = start["state"]
        tampered = state[:-6] + ("A" if state[-6] != "A" else "B") + state[-5:]

        landing = await _callback(client, a, state=tampered, code=code)

        assert landing["outcome"] == "expired"
        assert vendor.token_requests == []
        assert await _member_row(session, a.guild.id, app.id) is None

    async def test_an_expired_state_is_refused(
        self,
        client: AsyncClient,
        acting_user,
        session,
        vendor,
        registration,
        monkeypatch,
    ):
        a = await acting_user(guild_role=GuildRole.member)
        app = await _install(session, a)
        start = await _start(client, a, app, "account")
        code = vendor.authorize(start["code_challenge"])

        later = time.time() + 11 * 60
        monkeypatch.setattr(cryptography.fernet.time, "time", lambda: later)
        landing = await _callback(client, a, state=start["state"], code=code)

        assert landing["outcome"] == "expired"
        assert vendor.token_requests == []

    async def test_the_vendor_saying_no_reads_as_refused(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=GuildRole.member)
        app = await _install(session, a)
        start = await _start(client, a, app, "account")

        landing = await _callback(
            client, a, state=start["state"], error="access_denied"
        )

        assert landing["outcome"] == "refused"

    async def test_the_app_may_refuse_the_account(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        vendor.after_connect_answer = {"refuse": True}
        a = await acting_user(guild_role=GuildRole.member)
        app = await _install(session, a)
        start = await _start(client, a, app, "account")
        code = vendor.authorize(start["code_challenge"])

        landing = await _callback(client, a, state=start["state"], code=code)

        assert landing["outcome"] == "refused"
        assert await _member_row(session, a.guild.id, app.id) is None

    async def test_a_hook_that_fails_is_not_recorded(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        vendor.hook_status = 500
        a = await acting_user(guild_role=GuildRole.member)
        app = await _install(session, a)
        start = await _start(client, a, app, "account")
        code = vendor.authorize(start["code_challenge"])

        landing = await _callback(client, a, state=start["state"], code=code)

        assert landing["outcome"] == "not_recorded"
        assert await _member_row(session, a.guild.id, app.id) is None

    async def test_another_signed_in_person_cannot_finish_it(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """A flow is finished only by the person who started it; anyone else
        is told to finish it where that person is signed in, and the code is
        never exchanged."""
        a = await acting_user(guild_role=GuildRole.member)
        other = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        app = await _install(session, a)
        start = await _start(client, a, app, "account")
        code = vendor.authorize(start["code_challenge"])

        landing = await _callback(client, other, state=start["state"], code=code)

        assert landing["outcome"] == "sign_in_required"
        assert vendor.token_requests == []
        assert vendor.hooks == []
        assert await _member_row(session, a.guild.id, app.id) is None

    async def test_no_session_cannot_finish_it(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=GuildRole.member)
        app = await _install(session, a)
        start = await _start(client, a, app, "account")
        code = vendor.authorize(start["code_challenge"])

        landing = await _callback(client, None, state=start["state"], code=code)

        assert landing["outcome"] == "sign_in_required"
        assert vendor.token_requests == []
        assert await _member_row(session, a.guild.id, app.id) is None


class TestInstallationStyleFlow:
    async def test_install_page_setup_then_one_authorization(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """The seat installs on the vendor's page, the vendor returns the
        installation's id to the setup address, and one authorization trip lets
        the app check who installed it. The managed values land on the
        community's connection and the person's token is not kept."""
        vendor.after_connect_answer = {
            "values": {"owner": "acme", "installation_id": "42"},
            "account_label": "acme",
        }
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _install(session, a)

        start = await _start(client, a, app, "workspace")
        assert start["_url"].path == "/apps/initiative-test/installations/new"

        setup = await client.get(
            "/api/v1/app-connections/setup",
            headers=_cookie(a),
            params={
                "state": start["state"],
                "installation_id": "42",
                "setup_action": "install",
            },
        )
        assert setup.status_code == 303, setup.text
        authorize = urlparse(setup.headers["location"])
        assert authorize.netloc == "github.test"
        assert authorize.path == "/login/oauth/authorize"
        query = {k: v[0] for k, v in parse_qs(authorize.query).items()}
        # A fresh state for the second leg.
        assert query["state"] != start["state"]

        code = vendor.authorize(query["code_challenge"])
        landing = await _callback(client, a, state=query["state"], code=code)
        assert landing["outcome"] == "connected"

        name, body, _ = vendor.hooks[0]
        assert name == "after_connect"
        assert body["actor"] == "installation"
        assert body["params"] == {"installation_id": "42"}

        stored = await _reload(session, a.guild.id, app.id)
        assert stored.config["workspace"] == {"owner": "acme", "installation_id": "42"}
        assert "workspace" not in (stored.config_secrets or {})
        assert stored.connection_refs.get("workspace")
        assert await _member_row(session, a.guild.id, app.id, "workspace") is None

    async def test_losing_the_seat_mid_flow_refuses_it(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """A community connection is finished only while its starter still
        holds the seat."""
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _install(session, a)
        start = await _start(client, a, app, "workspace")

        membership = (
            await session.exec(
                select(GuildMembership).where(
                    GuildMembership.guild_id == a.guild.id,
                    GuildMembership.user_id == a.user.id,
                )
            )
        ).one()
        membership.role = GuildRole.member
        session.add(membership)
        await session.commit()

        setup = await client.get(
            "/api/v1/app-connections/setup",
            headers=_cookie(a),
            params={"state": start["state"], "installation_id": "42"},
        )

        assert _landing(setup.headers["location"])["outcome"] == "refused"
        assert vendor.token_requests == []
        stored = await _reload(session, a.guild.id, app.id)
        assert "workspace" not in (stored.config or {})

    async def test_an_install_awaiting_approval_says_so(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _install(session, a)
        start = await _start(client, a, app, "workspace")

        setup = await client.get(
            "/api/v1/app-connections/setup",
            headers=_cookie(a),
            params={"state": start["state"], "setup_action": "request"},
        )

        assert setup.status_code == 303
        assert _landing(setup.headers["location"])["outcome"] == "awaiting_approval"
        assert vendor.token_requests == []

    async def test_an_authorize_state_is_not_a_setup_state(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=GuildRole.member)
        app = await _install(session, a)
        start = await _start(client, a, app, "account")

        setup = await client.get(
            "/api/v1/app-connections/setup",
            headers=_cookie(a),
            params={"state": start["state"], "installation_id": "42"},
        )

        assert _landing(setup.headers["location"])["outcome"] == "expired"


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


class TestTokens:
    async def test_a_members_token_by_reference(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=GuildRole.member)
        app = await _install(session, a)
        row = await _connected_row(session, a, app, expires_in=3600)

        response = await client.post(
            TOKEN_ROUTE.format(ref=row.connection_ref),
            headers=_install_headers(a.guild, app),
        )

        assert response.status_code == 200, response.text
        assert response.json()["access_token"] == "gho_stored"
        assert response.json()["expires_at"] == row.config["expires_at"]
        assert vendor.refreshes == 0

    async def test_concurrent_reads_refresh_once(
        self, acting_user, session, vendor, registration
    ):
        """A token about to expire is refreshed under the row's lock: the second
        reader waits and finds the first's fresh token.

        Two sessions of their own, as two requests in two workers would have;
        the test client shares one session per role, so it cannot overlap
        two requests."""
        a = await acting_user(guild_role=GuildRole.member)
        app = await _install(session, a)
        row = await _connected_row(session, a, app, expires_in=30)

        async def read_token():
            async with db_session.SystemSessionLocal() as own:
                await set_rls_context(own, guild_id=a.guild.id)
                install = (
                    await own.exec(select(GuildApp).where(GuildApp.id == app.id))
                ).one()
                return await app_connection_flows.member_token(
                    own,
                    app=install,
                    public_id=PUBLIC_ID,
                    connection_ref=row.connection_ref,
                )

        first, second = await asyncio.gather(read_token(), read_token())

        assert first is not None and second is not None
        assert vendor.refreshes == 1
        assert first.access_token == second.access_token
        assert first.access_token.startswith("gho_access_")
        refreshed = await _member_row(session, a.guild.id, app.id)
        assert refreshed is not None
        assert (
            decrypt_field(refreshed.config_secrets["refresh_token"], SALT_APP_CONFIG)
            != "ghr_stored"
        )

    async def test_a_refused_refresh_expires_the_connection(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        vendor.refuse_refresh = True
        a = await acting_user(guild_role=GuildRole.member)
        app = await _install(session, a)
        row = await _connected_row(session, a, app, expires_in=30)

        response = await client.post(
            TOKEN_ROUTE.format(ref=row.connection_ref),
            headers=_install_headers(a.guild, app),
        )

        assert response.status_code == 409
        assert response.json()["detail"] == AppChannelMessages.CONNECTION_EXPIRED
        expired = await _member_row(session, a.guild.id, app.id)
        assert expired is not None and expired.status == "expired"

        # The member sees it, and is offered to connect again.
        detail = (await client.get(a.g(f"/apps/{app.id}"), headers=a.headers)).json()
        account = next(c for c in detail["connections"] if c["id"] == "account")
        assert account["status"] == "expired"
        assert account["runs_flow"] is True

    async def test_a_minted_token_is_cached(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """A ``jwt_bearer`` connection's token is minted with the vendor key and
        reused until shortly before it expires."""
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _install(
            session,
            a,
            config={"workspace": {"owner": "acme", "installation_id": "42"}},
            connection_refs={"workspace": "gcr_workspace"},
        )
        headers = _install_headers(a.guild, app)

        first = await client.post(
            TOKEN_ROUTE.format(ref="gcr_workspace"), headers=headers
        )
        second = await client.post(
            TOKEN_ROUTE.format(ref="gcr_workspace"), headers=headers
        )

        assert first.status_code == 200, first.text
        assert first.json()["access_token"].startswith("ghs_installation_")
        assert second.json() == first.json()
        assert len(vendor.exchanges) == 1
        claims = jwt.decode(
            vendor.exchanges[0].removeprefix("Bearer "),
            PUBLIC_KEY_PEM,
            algorithms=["RS256"],
        )
        assert claims["iss"] == "4242"
        assert claims["exp"] - claims["iat"] == 540

    async def test_a_ref_of_another_install_is_not_found(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=GuildRole.member)
        app = await _install(session, a)
        row = await _connected_row(session, a, app, expires_in=3600)
        b = await acting_user(guild_role=GuildRole.member)
        other = await _install(session, b)

        response = await client.post(
            TOKEN_ROUTE.format(ref=row.connection_ref),
            headers=_install_headers(b.guild, other),
        )

        assert response.status_code == 404
        assert response.json()["detail"] == AppChannelMessages.CONNECTION_NOT_FOUND

    async def test_a_blocked_member_gets_no_token(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=GuildRole.member)
        app = await _install(session, a)
        row = await _connected_row(session, a, app, expires_in=3600)
        await route_session_to_guild(session, a.guild.id)
        row.status = "blocked"
        row.blocked_at = row.updated_at
        session.add(row)
        await session.commit()

        response = await client.post(
            TOKEN_ROUTE.format(ref=row.connection_ref),
            headers=_install_headers(a.guild, app),
        )

        assert response.status_code == 403
        assert response.json()["detail"] == AppChannelMessages.CONNECTION_BLOCKED

    async def test_the_config_dump_holds_no_flow_secrets(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=GuildRole.member)
        app = await _install(
            session,
            a,
            config={"workspace": {"owner": "acme", "installation_id": "42"}},
            connection_refs={"workspace": "gcr_workspace"},
        )
        await _connected_row(session, a, app, expires_in=3600)

        response = await client.get(
            "/api/v1/app-platform/installation/config",
            headers=_install_headers(a.guild, app),
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["member_connections"][0]["values"] == {"login": "alice"}
        assert body["connections"]["workspace"] == {
            "owner": "acme",
            "installation_id": "42",
        }
        assert body["connection_refs"] == {"workspace": "gcr_workspace"}
        assert "gho_stored" not in response.text
        assert "ghr_stored" not in response.text
        assert "expires_at" not in response.text

    async def test_the_write_back_route_is_gone(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=GuildRole.member)
        app = await _install(session, a)

        response = await client.put(
            "/api/v1/app-platform/installation/connections/cr_x",
            headers=_install_headers(a.guild, app),
            json={"values": {"login": "mallory"}},
        )

        assert response.status_code in (404, 405)


# ---------------------------------------------------------------------------
# Ending a grant
# ---------------------------------------------------------------------------


class TestRevocation:
    async def test_uninstall_calls_the_revoke_url(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=GuildRole.superadmin)
        app = await _install(session, a)
        await _connected_row(session, a, app, expires_in=3600)

        response = await client.delete(a.g(f"/apps/{app.id}"), headers=a.headers)

        assert response.status_code == 204, response.text
        assert vendor.revocations == [
            {
                "token": "ghr_stored",
                "token_type_hint": "refresh_token",
                "client_id": "client-123",
                "client_secret": "client-secret-456",
            }
        ]

    async def test_a_failing_revocation_is_tried_three_times(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        vendor.revoke_status = 503
        a = await acting_user(guild_role=GuildRole.member)
        app = await _install(session, a)
        await _connected_row(session, a, app, expires_in=3600)

        response = await client.delete(
            a.g(f"/apps/{app.id}/connections/account"), headers=a.headers
        )

        assert response.status_code == 204
        assert len(vendor.revocations) == app_revocation.REVOKE_ATTEMPTS

    async def test_a_hook_revocation_hands_the_app_the_tokens(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=GuildRole.member)
        app = await _install(session, a)
        await _connected_row(
            session, a, app, expires_in=3600, connection_id="hooked", ref="cr_hooked"
        )

        response = await client.delete(
            a.g(f"/apps/{app.id}/connections/hooked"), headers=a.headers
        )

        assert response.status_code == 204
        name, body, authorization = vendor.hooks[-1]
        assert name == "revoke"
        assert body == {
            "connection": "hooked",
            "access_token": "gho_stored",
            "refresh_token": "ghr_stored",
        }
        claims = jwt.decode(
            authorization.removeprefix("Bearer "),
            options={"verify_signature": False},
        )
        assert claims["hook"] == "revoke"


# ---------------------------------------------------------------------------
# The vendor values a registration needs
# ---------------------------------------------------------------------------


class TestVendorLiveness:
    async def test_a_registration_missing_a_required_value_is_not_live(
        self, session: AsyncSession
    ):
        await create_app_service_registration(
            session,
            public_id="tests.needs",
            base_url="https://needs.example.test",
            vendor_required=["client_id", "client_secret"],
            vendor_values=sealed_vendor_values({"client_id": "x"}),
        )
        snapshot = (await load_registrations(force=True))["tests.needs"]
        assert snapshot.live is False

    async def test_every_required_value_set_is_live(self, session: AsyncSession):
        await create_app_service_registration(
            session,
            public_id="tests.ready",
            base_url="https://ready.example.test",
            vendor_required=["client_id"],
            vendor_values=sealed_vendor_values({"client_id": "x"}),
        )
        snapshot = (await load_registrations(force=True))["tests.ready"]
        assert snapshot.live is True

"""What an installed app may read and report about its own installation.

Every route here takes an installation token and reaches the install the token
names; no route names a community or an install in its path. Four things carry
the weight.

**The token is the only statement of which install.** A token the install seam
will not stand up — a member token, one whose registration or publisher is
off, one naming an install the guild turned off or another listing's install —
reaches nothing, and the answer is the same 401 however it failed.

**An app sees its own install and nothing else.** An install carrying this
registration's listing but pinning another app's definition is not this
app's, and neither is a connection handle minted in another community.

**Plaintext leaves on two routes.** The config route returns decrypted
values to the app that uses them, and never a flow's tokens; the token route
hands out one access token by reference (``app_connection_flows_test``). The
connections route reports which handles are live and carries no value at all.
Each is asserted against the whole response body.

**The app is the only party that can say whether credentials work.** Nothing
else in this build moves ``config_state`` off ``unverified``.
"""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.app_access_token import seal_install_token
from app.core.body_limit import APP_INSTALLATION_MAX_REQUEST_BYTES, _RULES
from app.core.encryption import SALT_APP_CONFIG, encrypt_field
from app.core.messages import AppChannelMessages
from app.models.platform.app_service_registration import AppServiceRegistration
from app.models.platform.publisher import Publisher
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.guild_app_user_connection import GuildAppUserConnection
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.services.tenant import app_channels as channels_service
from app.testing import (
    create_app_service_registration,
    create_guild,
    create_guild_app,
    create_user,
    route_session_to_guild,
)

pytestmark = pytest.mark.integration

BASE = "/api/v1/app-platform/installation"
SHOP = "tests.shop"
SHOP_UID = "TESTAPP0000001"
OTHER_UID = "TESTAPP0000002"
ORDER_CREATED = "app.tests.shop.order_created"

GUILD_TOKEN = "shpat_the_guilds_own_token"
MEMBER_TOKEN = "gho_one_members_own_token"


def _field(key: str, field_type: str, **extra) -> dict:
    return {"key": key, "type": field_type, "label": {"en": key}, **extra}


ADMIN_CONNECTION = {
    "id": "admin",
    "scope": "static",
    "label": {"en": "Admin API"},
    "fields": [
        _field("shop_domain", "string", required=True),
        _field("admin_token", "secret", required=True),
    ],
}

FLOW = {
    "type": "oauth2",
    "authorize_url": "https://github.test/login/oauth/authorize",
    "token_url": "https://github.test/login/oauth/access_token",
    "client_id": "{vendor.client_id}",
    "after_connect": True,
}

MEMBER_CONNECTION = {
    "id": "github",
    "scope": "interactive",
    "label": {"en": "GitHub"},
    "fields": [_field("login", "string", managed=True)],
    "flow": FLOW,
}


def _definition(public_id: str = SHOP) -> dict:
    return {
        "app_kind": "service",
        "service": {"public_id": public_id, "protocol": 1},
        "features": ["endpoints"],
        "connections": [ADMIN_CONNECTION, MEMBER_CONNECTION],
        "endpoints": [{"id": ORDER_CREATED, "direction": "emit"}],
    }


async def _register(session: AsyncSession, **overrides) -> AppServiceRegistration:
    return await create_app_service_registration(
        session, public_id=SHOP, listing_uid=SHOP_UID, **overrides
    )


async def _install(
    session: AsyncSession,
    *,
    definition: dict | None = None,
    listing_uid: str = SHOP_UID,
    with_values: bool = False,
    **overrides,
):
    """A guild with a service app installed, optionally already configured."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    if with_values:
        overrides.setdefault("config", {"admin": {"shop_domain": "example.test"}})
        overrides.setdefault(
            "config_secrets",
            {"admin": {"admin_token": encrypt_field(GUILD_TOKEN, SALT_APP_CONFIG)}},
        )
    app = await create_guild_app(
        session,
        guild,
        user,
        definition=definition or _definition(),
        listing_uid=listing_uid,
        **overrides,
    )
    return guild, user, app


async def _member_connection(
    session: AsyncSession,
    *,
    guild,
    app,
    user,
    connection_id: str = "github",
    connection_ref: str = "cr_member_one",
    with_secret: bool = True,
    blocked: bool = False,
) -> GuildAppUserConnection:
    await route_session_to_guild(session, guild.id)
    row = GuildAppUserConnection(
        app_id=app.id,
        connection_id=connection_id,
        user_id=user.id,
        connection_ref=connection_ref,
        config={"login": "alice"} if with_secret else {},
        config_secrets=(
            {"access_token": encrypt_field(MEMBER_TOKEN, SALT_APP_CONFIG)}
            if with_secret
            else {}
        ),
        status="connected" if with_secret else "pending",
    )
    if blocked:
        row.blocked_at = datetime.now(timezone.utc)
        row.status = "blocked"
        row.config_secrets = {}
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


def _headers(
    guild,
    app,
    *,
    client_id: str = SHOP,
    initiative_id: int | None = None,
    user_id: int | None = None,
) -> dict[str, str]:
    """An installation token for ``app`` in ``guild``, as the token endpoint
    would issue one."""
    token, _exp = seal_install_token(
        guild_id=guild.id,
        install_id=app.id,
        client_id=client_id,
        scopes=frozenset(),
        initiative_id=initiative_id,
        user_id=user_id,
        purpose=None,
    )
    return {"Authorization": f"Bearer {token}"}


async def _reload(session: AsyncSession, guild_id: int, app_id: int) -> GuildApp:
    await route_session_to_guild(session, guild_id)
    session.expunge_all()
    return (await session.exec(select(GuildApp).where(GuildApp.id == app_id))).one()


async def _switch_off(session: AsyncSession, row) -> None:
    row.enabled = False
    session.add(row)
    await session.commit()
    invalidate_registrations()


# ---------------------------------------------------------------------------
# The token
# ---------------------------------------------------------------------------


class TestTheToken:
    async def test_no_token_reaches_nothing(
        self, client: AsyncClient, session: AsyncSession
    ):
        await _register(session)
        await _install(session, with_values=True)

        response = await client.get(f"{BASE}/config")

        assert response.status_code == 401

    async def test_a_narrowed_token_reaches_its_installation(
        self, client: AsyncClient, session: AsyncSession
    ):
        """These calls are about the install, not an initiative's content, so
        a token narrowed to one initiative reaches them too."""
        await _register(session)
        guild, _, app = await _install(session, with_values=True)

        response = await client.get(
            f"{BASE}/config", headers=_headers(guild, app, initiative_id=12345)
        )

        assert response.status_code == 200, response.text

    async def test_a_member_token_is_refused(
        self, client: AsyncClient, session: AsyncSession
    ):
        """A member token acts for somebody; the install's own configuration is
        not something it reaches."""
        await _register(session)
        guild, user, app = await _install(session, with_values=True)

        response = await client.get(
            f"{BASE}/config", headers=_headers(guild, app, user_id=user.id)
        )

        assert response.status_code == 401
        assert GUILD_TOKEN not in response.text

    @pytest.mark.parametrize("what", ["registration", "publisher", "install"])
    async def test_a_switch_turned_off_stops_every_call(
        self, client: AsyncClient, session: AsyncSession, what: str
    ):
        """The operator's switch, the publisher's and the guild's all end the
        install's calls at the next request, with the same answer."""
        registration = await _register(session)
        guild, _, app = await _install(session, with_values=True)
        if what == "registration":
            await _switch_off(session, registration)
        elif what == "publisher":
            await _switch_off(
                session, await session.get(Publisher, registration.publisher_id)
            )
        else:
            await route_session_to_guild(session, guild.id)
            await _switch_off(session, app)

        for method, path in (
            ("GET", "/config"),
            ("GET", "/connections"),
            ("POST", "/config-status"),
        ):
            response = await client.request(
                method,
                f"{BASE}{path}",
                headers=_headers(guild, app),
                json={"state": "ok"} if method == "POST" else None,
            )
            assert response.status_code == 401, (path, response.text)
            assert GUILD_TOKEN not in response.text

    async def test_a_registration_with_no_keys_reaches_nothing(
        self, client: AsyncClient, session: AsyncSession
    ):
        await _register(session, jwks={})
        guild, _, app = await _install(session, with_values=True)

        response = await client.get(f"{BASE}/config", headers=_headers(guild, app))

        assert response.status_code == 401

    async def test_a_token_naming_another_listings_install_reaches_nothing(
        self, client: AsyncClient, session: AsyncSession
    ):
        """One app's credentials are not reachable by another's token, and the
        refusal says nothing about what is there."""
        await _register(session)
        theirs, _, theirs_app = await _install(
            session,
            definition=_definition("tests.other"),
            listing_uid=OTHER_UID,
            with_values=True,
        )

        response = await client.get(
            f"{BASE}/config", headers=_headers(theirs, theirs_app)
        )

        assert response.status_code == 401
        assert GUILD_TOKEN not in response.text


# ---------------------------------------------------------------------------
# The custody route
# ---------------------------------------------------------------------------


class TestConfig:
    async def test_config_returns_the_decrypted_values(
        self, client: AsyncClient, session: AsyncSession
    ):
        await _register(session)
        guild, user, app = await _install(session, with_values=True)
        await _member_connection(session, guild=guild, app=app, user=user)

        response = await client.get(f"{BASE}/config", headers=_headers(guild, app))

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["connections"]["admin"] == {
            "shop_domain": "example.test",
            "admin_token": GUILD_TOKEN,
        }
        member = body["member_connections"][0]
        assert member["connection_ref"] == "cr_member_one"
        # A flow's token is asked for by reference, never handed over here.
        assert member["values"] == {"login": "alice"}
        assert MEMBER_TOKEN not in response.text
        # The app is told which member by handle, and by nothing else.
        assert "user_id" not in member
        assert user.seeded_address not in response.text

    async def test_a_blocked_members_values_are_not_served(
        self, client: AsyncClient, session: AsyncSession
    ):
        """A block ends that member's access; the tombstone it leaves must not
        keep handing the app a credential to act with."""
        await _register(session)
        guild, user, app = await _install(session, with_values=True)
        await _member_connection(session, guild=guild, app=app, user=user, blocked=True)

        response = await client.get(f"{BASE}/config", headers=_headers(guild, app))

        assert response.status_code == 200, response.text
        assert response.json()["member_connections"] == []

    async def test_an_install_pinning_another_apps_definition_is_not_ours(
        self, client: AsyncClient, session: AsyncSession
    ):
        """Both statements have to agree. A row carrying this registration's
        catalog uid but pinning a definition that names a different service is
        not an install this caller may reach."""
        await _register(session)
        guild, _, app = await _install(
            session, definition=_definition("tests.someone-else"), with_values=True
        )

        response = await client.get(f"{BASE}/config", headers=_headers(guild, app))

        assert response.status_code == 404
        assert response.json()["detail"] == AppChannelMessages.INSTALL_NOT_FOUND
        assert GUILD_TOKEN not in response.text

    async def test_an_install_that_needed_configuring_says_so(
        self, client: AsyncClient, session: AsyncSession
    ):
        await _register(session)
        guild, _, app = await _install(session)

        response = await client.get(f"{BASE}/config", headers=_headers(guild, app))

        assert response.status_code == 200, response.text
        assert response.json()["needs_config"] is True


# ---------------------------------------------------------------------------
# Who connected — status, never values
# ---------------------------------------------------------------------------


class TestConnections:
    async def test_connections_report_state_and_never_a_value(
        self, client: AsyncClient, session: AsyncSession
    ):
        await _register(session)
        guild, user, app = await _install(session, with_values=True)
        await _member_connection(session, guild=guild, app=app, user=user)

        response = await client.get(f"{BASE}/connections", headers=_headers(guild, app))

        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["connection_ref"] == "cr_member_one"
        assert items[0]["connection_id"] == "github"
        assert items[0]["status"] == "connected"
        assert items[0]["blocked"] is False
        assert MEMBER_TOKEN not in response.text
        assert GUILD_TOKEN not in response.text
        assert "values" not in items[0]

    async def test_connections_never_name_the_member(
        self, client: AsyncClient, session: AsyncSession
    ):
        await _register(session)
        guild, user, app = await _install(session)
        await _member_connection(session, guild=guild, app=app, user=user)

        response = await client.get(f"{BASE}/connections", headers=_headers(guild, app))

        assert response.status_code == 200, response.text
        assert "user_id" not in response.text
        assert user.seeded_address not in response.text

    async def test_a_blocked_connection_is_reported_as_blocked(
        self, client: AsyncClient, session: AsyncSession
    ):
        await _register(session)
        guild, user, app = await _install(session)
        await _member_connection(session, guild=guild, app=app, user=user, blocked=True)

        response = await client.get(f"{BASE}/connections", headers=_headers(guild, app))

        assert response.status_code == 200, response.text
        assert response.json()["items"][0]["blocked"] is True


# ---------------------------------------------------------------------------
# The app's own verdict
# ---------------------------------------------------------------------------


class TestConfigStatus:
    async def test_reporting_invalid_carries_the_reason(
        self, client: AsyncClient, session: AsyncSession
    ):
        await _register(session)
        guild, _, app = await _install(session, with_values=True)
        assert app.config_state == "unverified"

        response = await client.post(
            f"{BASE}/config-status",
            headers=_headers(guild, app),
            json={"state": "invalid", "detail": "missing_read_orders"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["config_state"] == "invalid"
        stored = await _reload(session, guild.id, app.id)
        assert stored.config_state == "invalid"
        assert stored.config_state_detail == "missing_read_orders"

    async def test_a_state_outside_the_vocabulary_is_refused(
        self, client: AsyncClient, session: AsyncSession
    ):
        await _register(session)
        guild, _, app = await _install(session)

        response = await client.post(
            f"{BASE}/config-status",
            headers=_headers(guild, app),
            json={"state": "wonderful"},
        )

        assert response.status_code == 422
        stored = await _reload(session, guild.id, app.id)
        assert stored.config_state == "unverified"


# ---------------------------------------------------------------------------
# Third-party events
# ---------------------------------------------------------------------------


@pytest.fixture
def dispatched(monkeypatch):
    """What reached the dispatcher, without delivering anything."""
    calls: list[dict] = []

    async def _capture(session, *, event_type, guild_id, payload, initiative_id=None):
        calls.append(
            {
                "event_type": event_type,
                "guild_id": guild_id,
                "payload": payload,
                "initiative_id": initiative_id,
            }
        )

    monkeypatch.setattr(channels_service, "dispatch_event", _capture)
    return calls


class TestEvents:
    async def test_a_declared_event_reaches_the_dispatcher(
        self, client: AsyncClient, session: AsyncSession, dispatched
    ):
        await _register(session)
        guild, _, app = await _install(session)

        response = await client.post(
            f"{BASE}/events",
            headers=_headers(guild, app),
            json={"event_type": ORDER_CREATED, "payload": {"order_id": "1001"}},
        )

        assert response.status_code == 202, response.text
        assert dispatched == [
            {
                "event_type": ORDER_CREATED,
                "guild_id": guild.id,
                "payload": {"order_id": "1001"},
                "initiative_id": None,
            }
        ]

    @pytest.mark.parametrize(
        ("case", "event", "status", "detail"),
        [
            (
                "an event type the app never declared",
                {"event_type": "app.tests.shop.never_declared", "payload": {}},
                400,
                AppChannelMessages.UNKNOWN_EVENT_TYPE,
            ),
            (
                "a payload over the event cap",
                {
                    "event_type": ORDER_CREATED,
                    "payload": {
                        "note": "x" * (channels_service.MAX_EVENT_PAYLOAD_BYTES + 1_000)
                    },
                },
                413,
                AppChannelMessages.EVENT_TOO_LARGE,
            ),
            (
                "a body over the request bound",
                {"event_type": ORDER_CREATED, "payload": {"note": "x" * (128 * 1024)}},
                413,
                AppChannelMessages.EVENT_TOO_LARGE,
            ),
        ],
        ids=lambda v: v if isinstance(v, str) and " " in v else "",
    )
    async def test_an_event_the_route_will_not_carry_is_refused(
        self,
        client: AsyncClient,
        session: AsyncSession,
        dispatched,
        case: str,
        event: dict,
        status: int,
        detail: str,
    ):
        await _register(session)
        guild, _, app = await _install(session)

        response = await client.post(
            f"{BASE}/events", headers=_headers(guild, app), json=event
        )

        assert response.status_code == status, response.text
        assert response.json()["detail"] == detail
        assert dispatched == []

    async def test_another_apps_namespace_is_refused(
        self, client: AsyncClient, session: AsyncSession, dispatched
    ):
        await _register(session)
        definition = _definition()
        definition["endpoints"] = [
            {"id": "app.tests.other.order_created", "direction": "emit"}
        ]
        guild, _, app = await _install(session, definition=definition)

        response = await client.post(
            f"{BASE}/events",
            headers=_headers(guild, app),
            json={"event_type": "app.tests.other.order_created", "payload": {}},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == AppChannelMessages.UNKNOWN_EVENT_TYPE
        assert dispatched == []

    def test_the_transport_bounds_every_installation_call(self):
        """An event is the largest body these routes take, so the transport's
        ceiling is an event and its envelope."""
        assert APP_INSTALLATION_MAX_REQUEST_BYTES == (
            channels_service.MAX_EVENT_PAYLOAD_BYTES + 8 * 1024
        )
        assert any(pattern.match(f"{BASE}/events") for pattern, _, _ in _RULES)

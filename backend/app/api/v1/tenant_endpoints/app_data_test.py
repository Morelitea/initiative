"""External data reaching a widget, and everything that has to be true first.

Five things carry the weight here.

**The gates run before anything else.** A member of the guild who is not in the
dashboard's initiative gets nothing — not a filtered answer, not an empty one.
That is the hard isolation boundary, and it is enforced by loading the dashboard
through the ordinary resource path rather than by a check in the proxy.

**A dashboard is not a skeleton key.** Holding one dashboard lets you fetch the
sources *it displays*. Naming a different source of the same app is refused, so
the surface a viewer can reach is the surface they can see.

**Both kill switches are real.** The guild's install and the operator's
registration each stop the call on their own, and each is re-read per request —
neither is something a cached body can outlive.

**The cache key contains every credential the response depended on.** Two members
who connected different vendor accounts must never see each other's rows. That is
the assertion the whole cache exists to survive, so it is tested end to end
through two real sessions rather than by inspecting a key.

**An app that misbehaves costs one tile.** Unreachable, slow, oversized, or
answering in a shape we will not pass on — all of it comes back as a named code
with a 4xx/502, never a server fault.

The seam these tests stub is `_read_answer`: the single point where the decision
ends and the network begins. Everything above it — gates, kill switches,
parameters, credentials, the cache, the in-flight cap, the minted token — runs
for real.
"""

from datetime import datetime, timezone

import json
import httpx
import jwt
import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.encryption import SALT_APP_CONFIG, encrypt_field
from app.core.messages import AppDataMessages, GuildAppMessages
from app.models.platform.app_service_registration import (
    AppServiceRegistration,
    AppServiceStatus,
)
from app.models.platform.guild import GuildRole
from app.models.tenant.guild_app_user_connection import GuildAppUserConnection
from app.services.marketplace import app_data as app_data_service
from app.services.marketplace.context_jwt_test import _PRIVATE_PEM
from app.services.tenant.dashboard_definition import normalize_dashboard_definition
from app.testing import create_dashboard, create_guild_app, route_session_to_guild

pytestmark = pytest.mark.integration

APP_UID = "SHPAPP00000001"
PUBLIC_ID = "acme.shop"

#: What the fixture app declares. Namespaced under its own service id, which is
#: what every endpoint id has to be.
ORDERS_SUMMARY = f"app.{PUBLIC_ID}.orders-summary"
REVENUE = f"app.{PUBLIC_ID}.revenue"
MY_PRS = f"app.{PUBLIC_ID}.my-prs"
REFUND = f"app.{PUBLIC_ID}.refund"
#: The two reads that exist to fill a menu rather than a tile. Which shops
#: there are is a fact about one install, so it cannot be written into a
#: manifest — the manifest names these instead.
LIST_SHOPS = f"app.{PUBLIC_ID}.list-shops"
LIST_AISLES = f"app.{PUBLIC_ID}.list-aisles"
BASE_URL = "http://127.0.0.1:9100"

#: A widget module with the characters a plain-text sanitizer would mangle.
MODULE_SOURCE = (
    "export const render = (d) => (d.rows.length < 5 && d.rows[0] ? {} : {});"
)


def _field(key: str, field_type: str, **extra) -> dict:
    return {"key": key, "type": field_type, "label": {"en": key}, **extra}


ADMIN_CONNECTION = {
    "id": "admin",
    "scope": "static",
    "label": {"en": "Admin API"},
    "fields": [_field("admin_token", "secret", required=True)],
}

GITHUB_CONNECTION = {
    "id": "github",
    "scope": "interactive",
    "label": {"en": "GitHub"},
    "connect_path": "/connect/github",
    "fields": [_field("access_token", "secret", managed=True)],
}


def _definition() -> dict:
    """A service app offering three sources: one open, one for guild admins, one
    that runs on the caller's own vendor account."""
    return {
        "app_kind": "service",
        "service": {"public_id": PUBLIC_ID, "protocol": 1},
        "features": ["endpoints", "widgets"],
        "connections": [ADMIN_CONNECTION, GITHUB_CONNECTION],
        "endpoints": [
            {
                "id": ORDERS_SUMMARY,
                "direction": "read",
                "visibility": "member",
                "cache_ttl_seconds": 60,
                "params": [
                    _field("range", "select", options=["7d", "30d"]),
                    _field("limit", "int"),
                    # A menu the app fills, and a second that cannot be filled
                    # until the first has been: an aisle belongs to a shop.
                    _field(
                        "shop",
                        "string",
                        options_from={"endpoint": LIST_SHOPS, "key": "names"},
                    ),
                    _field(
                        "aisle",
                        "string",
                        options_from={
                            "endpoint": LIST_AISLES,
                            "key": "codes",
                            "label_key": "names",
                            "needs": {"shop": "shop"},
                        },
                    ),
                    # Sourced from the guild-admin read, so a member asking for
                    # its values is a case rather than a hypothetical.
                    _field(
                        "tier",
                        "string",
                        options_from={"endpoint": REVENUE, "key": "tiers"},
                    ),
                    # Several values rather than one, which is a fact about the
                    # value and the only thing that says so.
                    _field(
                        "tags",
                        "string",
                        list=True,
                        options_from={"endpoint": LIST_SHOPS, "key": "names"},
                    ),
                ],
                "returns": [
                    {"key": "days", "type": "string", "list": True},
                    {"key": "totals", "type": "int", "list": True},
                    {"key": "total", "type": "int"},
                ],
            },
            {
                "id": REVENUE,
                "direction": "read",
                "visibility": "guild_admin",
                "cache_ttl_seconds": 0,
                "returns": [{"key": "tiers", "type": "string", "list": True}],
            },
            {
                "id": LIST_SHOPS,
                "direction": "read",
                "visibility": "member",
                "cache_ttl_seconds": 300,
                "returns": [{"key": "names", "type": "string", "list": True}],
            },
            {
                "id": LIST_AISLES,
                "direction": "read",
                "visibility": "member",
                "cache_ttl_seconds": 300,
                "params": [_field("shop", "string")],
                "returns": [
                    {"key": "codes", "type": "string", "list": True},
                    {"key": "names", "type": "string", "list": True},
                ],
            },
            {
                "id": MY_PRS,
                "direction": "read",
                "visibility": "member",
                "cache_ttl_seconds": 60,
                "requires": {"all_of": ["github"]},
            },
            # A write, so a case can prove a tile cannot reach one.
            {"id": REFUND, "direction": "write", "actors": ["member"]},
        ],
        "widgets": [
            {
                "id": "summary",
                "meta": {"name": {"en": "Summary"}},
                # Carries ``<`` and ``&`` deliberately: a widget module is
                # JavaScript, and a plain-text sanitizer on the way out would
                # rewrite these into something that no longer parses.
                "module_source": MODULE_SOURCE,
                "endpoints": [ORDERS_SUMMARY],
                # What the endpoint would answer with, in its own declared
                # returns — the catalog reads it the way the proxy reads a live
                # answer.
                "sample_data": {
                    ORDERS_SUMMARY: {"days": ["mon"], "totals": [4], "total": 4}
                },
            }
        ],
    }


def _dashboard_definition(*endpoint_ids: str) -> dict:
    return normalize_dashboard_definition(
        {
            "widgets": [
                {
                    "id": f"w{index + 1}",
                    "type": f"app:{APP_UID}:summary",
                    "binding": {
                        "source": "app",
                        "app_uid": APP_UID,
                        "endpoint_id": endpoint_id,
                    },
                }
                for index, endpoint_id in enumerate(endpoint_ids)
            ]
        }
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    """The app platform needs its own keypair; these tests are about the proxy
    rather than the fail-closed path, so give it a real one."""
    monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", _PRIVATE_PEM)
    monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_KEY_ID", "app-platform-1")


@pytest.fixture(autouse=True)
def _clean_cache():
    """Per test, both directions: an entry left behind would let one test's
    answer satisfy another's request."""
    app_data_service.clear_app_data_cache()
    app_data_service._inflight.clear()
    yield
    app_data_service.clear_app_data_cache()
    app_data_service._inflight.clear()


@pytest.fixture
def upstream(monkeypatch):
    """Stand in for the app service, recording every call it receives.

    Returns a recorder whose ``calls`` holds the outgoing `httpx.Request`s — so a
    test can assert on the minted token and the URL — and whose ``rows`` and
    ``values`` are what the app answers with next.
    """

    class Recorder:
        def __init__(self) -> None:
            self.calls: list[httpx.Request] = []
            self.rows: list = [{"id": 1}]
            self.values: dict = {}
            self.error: Exception | None = None

        @property
        def count(self) -> int:
            return len(self.calls)

    recorder = Recorder()

    async def _fake_read_answer(request, *, endpoint, transport=None):
        recorder.calls.append(request)
        if recorder.error is not None:
            raise recorder.error
        return list(recorder.rows), dict(recorder.values)

    monkeypatch.setattr(app_data_service, "_read_answer", _fake_read_answer)
    return recorder


async def _register(
    session: AsyncSession,
    *,
    enabled: bool = True,
    status: str = AppServiceStatus.OK,
) -> AppServiceRegistration:
    row = AppServiceRegistration(
        public_id=PUBLIC_ID,
        listing_uid=APP_UID,
        base_url=BASE_URL,
        allowed_origins=[BASE_URL],
        enabled=enabled,
        status=status,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def _install(session: AsyncSession, actor, **overrides):
    return await create_guild_app(
        session,
        actor.guild,
        actor.user,
        definition=_definition(),
        listing_uid=APP_UID,
        name="Shop",
        **overrides,
    )


async def _workspace(session: AsyncSession, acting_user, *sources: str):
    """A guild admin with a dashboards-enabled initiative, an installed app, a
    live registration, and a dashboard binding the given sources."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    a.initiative.dashboards_enabled = True
    session.add(a.initiative)
    await session.commit()

    await _register(session)
    app = await _install(session, a)
    dashboard = await create_dashboard(
        session,
        a.initiative,
        a.user,
        definition=_dashboard_definition(*(sources or (ORDERS_SUMMARY,))),
    )
    return a, app, dashboard


def _url(actor, app, endpoint_id: str, dashboard, **params) -> str:
    query = f"dashboard_id={dashboard.id}"
    for key, value in params.items():
        query = f"{query}&{key}={value}"
    return actor.g(f"/apps/{app.id}/endpoints/{endpoint_id}?{query}")


# ---------------------------------------------------------------------------
# The gates run first
# ---------------------------------------------------------------------------


class TestGates:
    async def test_a_member_reads_a_source_their_dashboard_displays(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user)

        response = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["rows"] == [{"id": 1}]
        assert body["cached"] is False
        assert datetime.fromisoformat(body["fetched_at"]).tzinfo is not None

    async def test_both_halves_of_an_answer_reach_the_viewer(
        self, client, acting_user, session, upstream
    ):
        """An endpoint's ``list`` returns become rows and its single ones stay
        whole, and the route carries both."""
        a, app, dashboard = await _workspace(session, acting_user)
        upstream.rows = [{"days": "mon", "totals": 4}]
        upstream.values = {"total": 4}

        response = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["rows"] == [{"days": "mon", "totals": 4}]
        assert body["values"] == {"total": 4}

    async def test_a_guild_member_outside_the_initiative_reaches_nothing(
        self, client, acting_user, session, upstream
    ):
        """The hard isolation boundary. The app is installed guild-wide and this
        person is a member of the guild — but the dashboard belongs to an
        initiative they are not in, so RLS hides the row and the read is a 404
        before the app is ever contacted."""
        a, app, dashboard = await _workspace(session, acting_user)
        outsider = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        response = await client.get(
            _url(outsider, app, ORDERS_SUMMARY, dashboard), headers=outsider.headers
        )
        assert response.status_code == 404
        assert upstream.count == 0

    async def test_a_dashboard_is_not_a_key_to_every_source(
        self, client, acting_user, session, upstream
    ):
        """The dashboard names which sources it displays; anything else is not
        reachable through it, even though the same app offers it."""
        a, app, dashboard = await _workspace(session, acting_user, ORDERS_SUMMARY)

        response = await client.get(_url(a, app, REVENUE, dashboard), headers=a.headers)
        assert response.status_code == 404
        assert response.json()["detail"] == AppDataMessages.ENDPOINT_NOT_FOUND
        assert upstream.count == 0

    async def test_a_source_the_app_does_not_declare_is_refused(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user, "made_up")

        response = await client.get(
            _url(a, app, "made_up", dashboard), headers=a.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == AppDataMessages.ENDPOINT_NOT_FOUND
        assert upstream.count == 0


class TestVisibility:
    async def test_a_guild_admin_source_is_open_to_an_admin(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user, REVENUE)

        response = await client.get(_url(a, app, REVENUE, dashboard), headers=a.headers)
        assert response.status_code == 200, response.text

    async def test_a_guild_admin_source_is_refused_to_a_member(
        self, client, acting_user, session, upstream
    ):
        """Checked against the caller's real guild role, on the pinned
        definition — not against anything the request supplied."""
        a, app, dashboard = await _workspace(session, acting_user, REVENUE)
        member = await acting_user(
            guild_role=GuildRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )

        response = await client.get(
            _url(member, app, REVENUE, dashboard), headers=member.headers
        )
        assert response.status_code == 403
        assert response.json()["detail"] == AppDataMessages.ADMIN_ONLY
        assert upstream.count == 0


class TestKillSwitches:
    async def test_a_disabled_install_stops_the_call(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user)
        await route_session_to_guild(session, a.guild.id)
        app.enabled = False
        session.add(app)
        await session.commit()

        response = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == AppDataMessages.APP_DISABLED
        assert upstream.count == 0

    async def test_the_operators_kill_switch_stops_the_call(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user)
        registration = (await session.exec(select(AppServiceRegistration))).first()
        registration.enabled = False
        session.add(registration)
        await session.commit()

        response = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == AppDataMessages.SERVICE_DISABLED
        assert upstream.count == 0

    async def test_a_kill_is_not_outlived_by_a_cached_body(
        self, client, acting_user, session, upstream
    ):
        """The registration is re-read on every request, so an entry cached a
        moment earlier is not served after the switch flips."""
        a, app, dashboard = await _workspace(session, acting_user)
        first = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert first.status_code == 200

        registration = (await session.exec(select(AppServiceRegistration))).first()
        registration.enabled = False
        session.add(registration)
        await session.commit()

        second = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert second.status_code == 409

    async def test_an_unregistered_app_is_named_rather_than_guessed_at(
        self, client, acting_user, session, upstream
    ):
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        a.initiative.dashboards_enabled = True
        session.add(a.initiative)
        await session.commit()
        app = await _install(session, a)
        dashboard = await create_dashboard(
            session,
            a.initiative,
            a.user,
            definition=_dashboard_definition(ORDERS_SUMMARY),
        )

        response = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == AppDataMessages.SERVICE_NOT_REGISTERED


class TestParams:
    async def test_declared_parameters_reach_the_app(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user)

        response = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard, params='{"range":"30d"}'),
            headers=a.headers,
        )
        assert response.status_code == 200, response.text
        # In the body now, not the query string: one path serves every endpoint,
        # so which one is being called travels with the parameters.
        body = json.loads(upstream.calls[0].content)
        assert body["endpoint"] == ORDERS_SUMMARY
        assert body["params"]["range"] == "30d"

    @pytest.mark.parametrize(
        "params",
        [
            '{"nope":"1"}',  # not declared
            '{"range":"90d"}',  # outside the declared options
            '{"limit":"ten"}',  # wrong type for an int
            '{"limit":true}',  # a bool is not an int
            "not json",
            "[1,2]",  # not an object
        ],
    )
    async def test_anything_the_source_did_not_declare_is_refused(
        self, client, acting_user, session, upstream, params
    ):
        a, app, dashboard = await _workspace(session, acting_user)

        response = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard, params=params),
            headers=a.headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"] == AppDataMessages.INVALID_PARAMS
        assert upstream.count == 0


class TestContextToken:
    async def test_the_call_carries_a_guild_pinned_token_with_no_user(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user)
        await client.get(_url(a, app, ORDERS_SUMMARY, dashboard), headers=a.headers)

        header = upstream.calls[0].headers["Authorization"]
        assert header.startswith("Bearer ")
        claims = jwt.decode(
            header.removeprefix("Bearer "),
            options={"verify_signature": False},
            algorithms=["RS256"],
        )
        assert claims["guild_id"] == a.guild.id
        assert claims["app_install_id"] == app.id
        assert claims["scope"] == "endpoint"
        assert claims["endpoint_id"] == ORDERS_SUMMARY
        assert claims["aud"] == f"initiative-app:{PUBLIC_ID}"
        assert claims["exp"] - claims["iat"] == 60
        assert "sub" not in claims
        # A guild-scoped source needs no per-member credential, so the token
        # carries no user-derived claim at all.
        assert "connection_refs" not in claims


# ---------------------------------------------------------------------------
# Credentials, and the cache key that follows them
# ---------------------------------------------------------------------------


async def _connect(session: AsyncSession, *, app, user_id: int, ref: str) -> None:
    """Give one member a completed per-member connection."""
    await route_session_to_guild(session, app.guild_id)
    session.add(
        GuildAppUserConnection(
            guild_id=app.guild_id,
            app_id=app.id,
            connection_id="github",
            user_id=user_id,
            connection_ref=ref,
            config_secrets={"access_token": encrypt_field("tok", SALT_APP_CONFIG)},
            status="connected",
        )
    )
    await session.commit()


class TestConnections:
    async def test_a_member_who_has_not_connected_is_told_to(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user, MY_PRS)

        response = await client.get(_url(a, app, MY_PRS, dashboard), headers=a.headers)
        assert response.status_code == 409
        assert response.json()["detail"] == AppDataMessages.CONNECTION_REQUIRED
        assert upstream.count == 0

    async def test_a_blocked_member_is_refused_by_name(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user, MY_PRS)
        await route_session_to_guild(session, a.guild.id)
        session.add(
            GuildAppUserConnection(
                guild_id=app.guild_id,
                app_id=app.id,
                connection_id="github",
                user_id=a.user.id,
                connection_ref="cr_blocked",
                status="blocked",
                blocked_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

        response = await client.get(_url(a, app, MY_PRS, dashboard), headers=a.headers)
        assert response.status_code == 403
        assert response.json()["detail"] == GuildAppMessages.CONNECTION_BLOCKED
        assert upstream.count == 0

    async def test_the_token_carries_the_opaque_handle_not_the_person(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user, MY_PRS)
        await _connect(session, app=app, user_id=a.user.id, ref="cr_alice")

        response = await client.get(_url(a, app, MY_PRS, dashboard), headers=a.headers)
        assert response.status_code == 200, response.text

        claims = jwt.decode(
            upstream.calls[0].headers["Authorization"].removeprefix("Bearer "),
            options={"verify_signature": False},
            algorithms=["RS256"],
        )
        assert claims["connection_refs"] == {"github": "cr_alice"}
        assert str(a.user.id) not in str(claims.get("connection_refs"))
        assert "sub" not in claims

    async def test_an_unconfigured_guild_credential_is_named(
        self, client, acting_user, session, upstream
    ):
        """A source needing the guild's own credential says so rather than
        calling an app that would fail."""
        definition = _definition()
        definition["endpoints"][0]["requires"] = {"all_of": ["admin"]}

        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        a.initiative.dashboards_enabled = True
        session.add(a.initiative)
        await session.commit()
        await _register(session)
        app = await create_guild_app(
            session, a.guild, a.user, definition=definition, listing_uid=APP_UID
        )
        dashboard = await create_dashboard(
            session,
            a.initiative,
            a.user,
            definition=_dashboard_definition(ORDERS_SUMMARY),
        )

        response = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == AppDataMessages.NEEDS_CONFIGURATION
        assert upstream.count == 0


class TestCache:
    async def test_repeat_reads_of_guild_data_cost_one_upstream_call(
        self, client, acting_user, session, upstream
    ):
        """Twenty viewers of a dashboard are one call to the app, which is what
        keeps a single-replica community container comfortable."""
        a, app, dashboard = await _workspace(session, acting_user)
        member = await acting_user(
            guild_role=GuildRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )

        first = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        second = await client.get(
            _url(member, app, ORDERS_SUMMARY, dashboard), headers=member.headers
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["rows"] == first.json()["rows"]
        assert second.json()["cached"] is True
        assert upstream.count == 1

    async def test_different_parameters_are_different_entries(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user)

        await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard, params='{"range":"7d"}'),
            headers=a.headers,
        )
        await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard, params='{"range":"30d"}'),
            headers=a.headers,
        )
        assert upstream.count == 2

    async def test_two_members_with_different_connections_never_share_an_entry(
        self, client, acting_user, session, upstream
    ):
        """The assertion the cache exists to survive.

        Both members read the same source of the same install on the same
        dashboard. Their vendor accounts differ, so their rows differ, and a
        shared entry would show one person the other's data.
        """
        a, app, dashboard = await _workspace(session, acting_user, MY_PRS)
        b = await acting_user(
            guild_role=GuildRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        await _connect(session, app=app, user_id=a.user.id, ref="cr_alice")
        await _connect(session, app=app, user_id=b.user.id, ref="cr_bob")

        upstream.rows = [{"pr": "alice"}]
        alice = await client.get(_url(a, app, MY_PRS, dashboard), headers=a.headers)
        upstream.rows = [{"pr": "bob"}]
        bob = await client.get(_url(b, app, MY_PRS, dashboard), headers=b.headers)

        assert alice.status_code == 200, alice.text
        assert bob.status_code == 200, bob.text
        assert alice.json()["rows"] == [{"pr": "alice"}]
        assert bob.json()["rows"] == [{"pr": "bob"}]
        # Two calls, because two credentials.
        assert upstream.count == 2
        assert bob.json()["cached"] is False

    async def test_one_members_repeated_reads_still_collapse(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user, MY_PRS)
        await _connect(session, app=app, user_id=a.user.id, ref="cr_alice")

        await client.get(_url(a, app, MY_PRS, dashboard), headers=a.headers)
        again = await client.get(_url(a, app, MY_PRS, dashboard), headers=a.headers)

        assert again.json()["cached"] is True
        assert upstream.count == 1

    async def test_a_rotated_credential_retires_the_answers_it_produced(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user)
        await client.get(_url(a, app, ORDERS_SUMMARY, dashboard), headers=a.headers)
        assert upstream.count == 1

        await route_session_to_guild(session, a.guild.id)
        app.config = {"admin": {"shop_domain": "rotated.example"}}
        session.add(app)
        await session.commit()

        response = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.json()["cached"] is False
        assert upstream.count == 2

    async def test_a_source_asking_for_no_cache_is_not_cached(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user, REVENUE)

        await client.get(_url(a, app, REVENUE, dashboard), headers=a.headers)
        await client.get(_url(a, app, REVENUE, dashboard), headers=a.headers)
        assert upstream.count == 2


class TestFailureIsOneTile:
    async def test_an_unreachable_app_is_a_named_code_not_a_server_fault(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user)
        upstream.error = app_data_service.AppDataError(
            AppDataMessages.SERVICE_UNAVAILABLE, 502, "down"
        )

        response = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.status_code == 502
        assert response.json()["detail"] == AppDataMessages.SERVICE_UNAVAILABLE

    async def test_a_failed_call_is_not_cached(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user)
        upstream.error = app_data_service.AppDataError(
            AppDataMessages.SERVICE_UNAVAILABLE, 502, "down"
        )
        await client.get(_url(a, app, ORDERS_SUMMARY, dashboard), headers=a.headers)

        upstream.error = None
        upstream.rows = [{"id": 2}]
        response = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.status_code == 200
        assert response.json()["rows"] == [{"id": 2}]

    async def test_one_slow_app_cannot_exhaust_the_worker(
        self, client, acting_user, session, upstream, monkeypatch
    ):
        """The in-flight cap is refused rather than queued: waiting behind a
        stalled app is the same outage with a longer fuse."""
        a, app, dashboard = await _workspace(session, acting_user)
        monkeypatch.setitem(
            app_data_service._inflight,
            PUBLIC_ID,
            app_data_service.MAX_INFLIGHT_PER_APP,
        )

        response = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.status_code == 503
        assert response.json()["detail"] == AppDataMessages.BUSY
        assert upstream.count == 0


class TestWidgetCatalog:
    async def test_it_serves_the_pinned_module_and_samples(
        self, client, acting_user, session
    ):
        a, app, _ = await _workspace(session, acting_user)

        response = await client.get(a.g("/apps/widget-catalog"), headers=a.headers)
        assert response.status_code == 200, response.text

        entry = response.json()["items"][0]
        assert entry["app_uid"] == APP_UID
        assert entry["app_id"] == app.id

        widget = entry["widgets"][0]
        assert widget["type"] == f"app:{APP_UID}:summary"
        # Byte-for-byte: the module is JavaScript, and anything that rewrote a
        # ``<`` or an ``&`` on the way out would ship a module that cannot parse.
        assert widget["module_source"] == MODULE_SOURCE
        # Projected through the endpoint's returns, so what a preview draws is
        # what a bound tile draws.
        assert widget["sample_data"] == {
            ORDERS_SUMMARY: {
                "rows": [{"days": "mon", "totals": 4}],
                "values": {"total": 4},
            }
        }

        sources = {source["id"]: source for source in entry["endpoints"]}
        assert sources[REVENUE]["visibility"] == "guild_admin"
        assert sources[ORDERS_SUMMARY]["cache_ttl_seconds"] == 60

    async def test_a_disabled_install_offers_no_widgets(
        self, client, acting_user, session
    ):
        a, app, _ = await _workspace(session, acting_user)
        await route_session_to_guild(session, a.guild.id)
        app.enabled = False
        session.add(app)
        await session.commit()

        response = await client.get(a.g("/apps/widget-catalog"), headers=a.headers)
        assert response.status_code == 200
        assert response.json()["items"] == []


# ---------------------------------------------------------------------------
# Filling a menu
# ---------------------------------------------------------------------------


def _options_url(actor, app, endpoint_id: str, param: str, **query) -> str:
    parts = [f"param={param}"]
    for key, value in query.items():
        parts.append(f"{key}={value}")
    return actor.g(f"/apps/{app.id}/endpoints/{endpoint_id}/options?{'&'.join(parts)}")


class TestParamOptions:
    """The read that turns a declared ``options_from`` into a menu.

    It is the one here with no dashboard on it, and the reason is the whole
    point of it: a form is filled in *before* a widget is placed, so there is no
    dashboard row whose gates could decide it. What stands in for that is that
    the caller never names what gets called — the source is read out of the
    app's own declaration — and that the source's own visibility is enforced on
    the caller's own credentials.
    """

    async def test_a_member_gets_the_values_the_app_answers_with(
        self, client, acting_user, session, upstream
    ):
        a, app, _ = await _workspace(session, acting_user)
        upstream.rows = [{"names": "north"}, {"names": "south"}]

        response = await client.get(
            _options_url(a, app, ORDERS_SUMMARY, "shop"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["unavailable"] is None
        assert [option["value"] for option in body["options"]] == ["north", "south"]
        # The source the manifest named, never one the caller did.
        assert json.loads(upstream.calls[0].content)["endpoint"] == LIST_SHOPS

    async def test_no_dashboard_is_named_or_needed(
        self, client, acting_user, session, upstream
    ):
        """The case the route exists for: a widget nobody has placed yet."""
        a, app, _ = await _workspace(session, acting_user)
        upstream.rows = [{"names": "north"}]

        url = _options_url(a, app, ORDERS_SUMMARY, "shop")
        assert "dashboard" not in url
        assert (await client.get(url, headers=a.headers)).status_code == 200

    async def test_an_opaque_value_carries_what_a_person_reads(
        self, client, acting_user, session, upstream
    ):
        a, app, _ = await _workspace(session, acting_user)
        upstream.rows = [{"codes": "A1", "names": "Baking"}]

        response = await client.get(
            _options_url(a, app, ORDERS_SUMMARY, "aisle", params='{"shop":"north"}'),
            headers=a.headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["options"] == [{"value": "A1", "label": "Baking"}]

    async def test_a_sibling_the_form_has_not_answered_calls_nothing(
        self, client, acting_user, session, upstream
    ):
        """An aisle belongs to a shop, and no shop has been chosen.

        Not an error, and not an empty menu either: the parameter stays typeable
        and the caller asks again once the sibling has a value. Asking the
        source anyway would offer every shop's aisles, which is not a menu
        anybody can use.
        """
        a, app, _ = await _workspace(session, acting_user)

        response = await client.get(
            _options_url(a, app, ORDERS_SUMMARY, "aisle"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"options": [], "unavailable": "needs-sibling"}
        assert upstream.count == 0

    async def test_a_sibling_answered_is_what_the_source_is_told(
        self, client, acting_user, session, upstream
    ):
        a, app, _ = await _workspace(session, acting_user)
        upstream.rows = [{"codes": "A1"}]

        await client.get(
            _options_url(a, app, ORDERS_SUMMARY, "aisle", params='{"shop":"north"}'),
            headers=a.headers,
        )
        assert json.loads(upstream.calls[0].content)["params"] == {"shop": "north"}

    async def test_only_what_the_source_asked_for_is_forwarded(
        self, client, acting_user, session, upstream
    ):
        """The form holds more answers than the source needs, and the source is
        told exactly the ones its ``needs`` names."""
        a, app, _ = await _workspace(session, acting_user)
        upstream.rows = [{"codes": "A1"}]

        await client.get(
            _options_url(
                a,
                app,
                ORDERS_SUMMARY,
                "aisle",
                params='{"shop":"north","range":"30d","limit":5}',
            ),
            headers=a.headers,
        )
        assert json.loads(upstream.calls[0].content)["params"] == {"shop": "north"}

    async def test_a_parameter_naming_no_source_says_so(
        self, client, acting_user, session, upstream
    ):
        a, app, _ = await _workspace(session, acting_user)

        response = await client.get(
            _options_url(a, app, ORDERS_SUMMARY, "limit"), headers=a.headers
        )
        assert response.status_code == 200
        assert response.json() == {"options": [], "unavailable": "no-source"}
        assert upstream.count == 0

    async def test_a_parameter_the_endpoint_does_not_declare_is_a_404(
        self, client, acting_user, session, upstream
    ):
        a, app, _ = await _workspace(session, acting_user)

        response = await client.get(
            _options_url(a, app, ORDERS_SUMMARY, "nonesuch"), headers=a.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == AppDataMessages.PARAM_NOT_FOUND

    async def test_a_source_that_will_not_answer_leaves_the_field_typeable(
        self, client, acting_user, session, upstream
    ):
        """A vendor outage must not become a value nobody can enter.

        The alternative — a disabled control — makes a configuration that would
        have worked unreachable for as long as the app is down.
        """
        a, app, _ = await _workspace(session, acting_user)
        # The same seam every other failure case uses: `_read_answer` is where
        # the network is, and it is what turns an unreachable host into this.
        upstream.error = app_data_service.AppDataError(
            AppDataMessages.SERVICE_UNAVAILABLE, 502, "down"
        )

        response = await client.get(
            _options_url(a, app, ORDERS_SUMMARY, "shop"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"options": [], "unavailable": "unresolved"}

    async def test_a_member_is_told_nothing_by_a_guild_admin_source(
        self, client, acting_user, session, upstream
    ):
        """The source's own visibility decides, exactly as it does for a tile.

        A member asking for the values of a parameter sourced from a guild-admin
        read gets the same answer as one whose app is down — no options and no
        indication of which of the two it was.
        """
        a, app, _ = await _workspace(session, acting_user)
        member = await acting_user(guild=a.guild, guild_role=GuildRole.member)

        response = await client.get(
            _options_url(member, app, ORDERS_SUMMARY, "tier"), headers=member.headers
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"options": [], "unavailable": "unresolved"}
        assert upstream.count == 0

    async def test_a_guild_admin_reads_that_same_source(
        self, client, acting_user, session, upstream
    ):
        a, app, _ = await _workspace(session, acting_user)
        upstream.rows = [{"tiers": "gold"}]

        response = await client.get(
            _options_url(a, app, ORDERS_SUMMARY, "tier"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        assert [o["value"] for o in response.json()["options"]] == ["gold"]

    async def test_a_repeated_value_is_offered_once_in_the_order_given(
        self, client, acting_user, session, upstream
    ):
        a, app, _ = await _workspace(session, acting_user)
        upstream.rows = [
            {"names": "south"},
            {"names": "north"},
            {"names": "south"},
            {"names": None},
        ]

        response = await client.get(
            _options_url(a, app, ORDERS_SUMMARY, "shop"), headers=a.headers
        )
        assert [o["value"] for o in response.json()["options"]] == ["south", "north"]

    async def test_a_disabled_install_fills_no_menu(
        self, client, acting_user, session, upstream
    ):
        a, app, _ = await _workspace(session, acting_user)
        await route_session_to_guild(session, a.guild.id)
        app.enabled = False
        session.add(app)
        await session.commit()

        response = await client.get(
            _options_url(a, app, ORDERS_SUMMARY, "shop"), headers=a.headers
        )
        assert response.status_code == 200
        assert response.json()["unavailable"] == "unresolved"

    async def test_a_write_cannot_be_configured_through_this(
        self, client, acting_user, session, upstream
    ):
        """Reads only, the same rule the fetch path keeps: filling in a form
        must not be a way to make an app act."""
        a, app, _ = await _workspace(session, acting_user)

        response = await client.get(
            _options_url(a, app, REFUND, "shop"), headers=a.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == AppDataMessages.ENDPOINT_NOT_FOUND


class TestListParams:
    """A parameter declaring several values.

    ``list`` exists so an app does not have to declare a string and document a
    comma — a convention nothing on this side could validate or complete. That
    only holds if an array is what actually travels, so these pin the shape
    rather than the convention.
    """

    async def test_several_values_reach_the_app_as_several(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user)

        response = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard, params='{"tags":["red","blue"]}'),
            headers=a.headers,
        )
        assert response.status_code == 200, response.text
        assert json.loads(upstream.calls[0].content)["params"] == {
            "tags": ["red", "blue"]
        }

    async def test_one_value_for_a_list_parameter_is_still_an_array(
        self, client, acting_user, session, upstream
    ):
        """Cardinality is the declaration's, not the caller's. A single value
        sent bare would be a second encoding of the same thing."""
        a, app, dashboard = await _workspace(session, acting_user)

        response = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard, params='{"tags":"red"}'),
            headers=a.headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"] == AppDataMessages.INVALID_PARAMS

    async def test_an_array_for_a_single_parameter_is_refused(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user)

        response = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard, params='{"shop":["north"]}'),
            headers=a.headers,
        )
        assert response.status_code == 400
        assert upstream.count == 0

    async def test_an_empty_array_is_refused_rather_than_sent(
        self, client, acting_user, session, upstream
    ):
        """ "None of them" is a parameter that is absent. An array with nothing
        in it is a request nobody meant to make."""
        a, app, dashboard = await _workspace(session, acting_user)

        response = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard, params='{"tags":[]}'),
            headers=a.headers,
        )
        assert response.status_code == 400
        assert upstream.count == 0

    async def test_every_entry_is_held_to_the_declared_type(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user)

        response = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard, params='{"tags":["red",7]}'),
            headers=a.headers,
        )
        assert response.status_code == 400
        assert upstream.count == 0

    async def test_more_values_than_a_request_may_carry_are_refused(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user)
        many = json.dumps(
            {
                "tags": [
                    str(index) for index in range(app_data_service.MAX_PARAM_VALUES + 1)
                ]
            }
        )

        response = await client.get(
            _url(a, app, ORDERS_SUMMARY, dashboard, params=many), headers=a.headers
        )
        assert response.status_code == 400
        assert upstream.count == 0

    async def test_a_list_parameter_fills_its_menu_the_same_way(
        self, client, acting_user, session, upstream
    ):
        """Where the values come from does not change with how many are wanted:
        one source answers both."""
        a, app, _ = await _workspace(session, acting_user)
        upstream.rows = [{"names": "north"}, {"names": "south"}]

        response = await client.get(
            _options_url(a, app, ORDERS_SUMMARY, "tags"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        assert [o["value"] for o in response.json()["options"]] == ["north", "south"]

    async def test_a_sibling_answered_with_nothing_is_unanswered(
        self, client, acting_user, session, upstream
    ):
        a, app, _ = await _workspace(session, acting_user)

        response = await client.get(
            _options_url(a, app, ORDERS_SUMMARY, "aisle", params='{"shop":""}'),
            headers=a.headers,
        )
        assert response.json()["unavailable"] == "needs-sibling"
        assert upstream.count == 0

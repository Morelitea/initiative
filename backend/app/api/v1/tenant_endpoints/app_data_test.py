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

The seam these tests stub is `_read_rows`: the single point where the decision
ends and the network begins. Everything above it — gates, kill switches,
parameters, credentials, the cache, the in-flight cap, the minted token — runs
for real.
"""

from datetime import datetime, timezone

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

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

APP_UID = "SHPAPP00000001"
PUBLIC_ID = "acme.shop"
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
        "features": ["data", "widgets"],
        "connections": [ADMIN_CONNECTION, GITHUB_CONNECTION],
        "data_sources": [
            {
                "id": "orders_summary",
                "path": "/v1/data/orders_summary",
                "visibility": "member",
                "cache_ttl_seconds": 60,
                "params_schema": [
                    _field("range", "select", options=["7d", "30d"]),
                    _field("limit", "int"),
                ],
            },
            {
                "id": "revenue",
                "path": "/v1/data/revenue",
                "visibility": "guild_admin",
                "cache_ttl_seconds": 0,
            },
            {
                "id": "my_prs",
                "path": "/v1/data/my_prs",
                "visibility": "member",
                "cache_ttl_seconds": 60,
                "requires": {"all_of": ["github"]},
            },
        ],
        "widgets": [
            {
                "id": "summary",
                "meta": {"name": {"en": "Summary"}},
                # Carries ``<`` and ``&`` deliberately: a widget module is
                # JavaScript, and a plain-text sanitizer on the way out would
                # rewrite these into something that no longer parses.
                "module_source": MODULE_SOURCE,
                "sources": ["orders_summary"],
                "sample_data": {"orders_summary": [{"day": "mon", "total": 4}]},
            }
        ],
    }


def _dashboard_definition(*source_ids: str) -> dict:
    return normalize_dashboard_definition(
        {
            "widgets": [
                {
                    "id": f"w{index + 1}",
                    "type": f"app:{APP_UID}:summary",
                    "binding": {
                        "source": "app",
                        "app_uid": APP_UID,
                        "source_id": source_id,
                    },
                }
                for index, source_id in enumerate(source_ids)
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
    test can assert on the minted token and the URL — and whose ``rows`` is what
    the app answers with next.
    """

    class Recorder:
        def __init__(self) -> None:
            self.calls: list[httpx.Request] = []
            self.rows: list = [{"id": 1}]
            self.error: Exception | None = None

        @property
        def count(self) -> int:
            return len(self.calls)

    recorder = Recorder()

    async def _fake_read_rows(request, *, transport=None):
        recorder.calls.append(request)
        if recorder.error is not None:
            raise recorder.error
        return list(recorder.rows)

    monkeypatch.setattr(app_data_service, "_read_rows", _fake_read_rows)
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
        definition=_dashboard_definition(*(sources or ("orders_summary",))),
    )
    return a, app, dashboard


def _url(actor, app, source_id: str, dashboard, **params) -> str:
    query = f"dashboard_id={dashboard.id}"
    for key, value in params.items():
        query = f"{query}&{key}={value}"
    return actor.g(f"/apps/{app.id}/data/{source_id}?{query}")


# ---------------------------------------------------------------------------
# The gates run first
# ---------------------------------------------------------------------------


class TestGates:
    async def test_a_member_reads_a_source_their_dashboard_displays(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user)

        response = await client.get(
            _url(a, app, "orders_summary", dashboard), headers=a.headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["rows"] == [{"id": 1}]
        assert body["cached"] is False
        assert datetime.fromisoformat(body["fetched_at"]).tzinfo is not None

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
            _url(outsider, app, "orders_summary", dashboard), headers=outsider.headers
        )
        assert response.status_code == 404
        assert upstream.count == 0

    async def test_a_dashboard_is_not_a_key_to_every_source(
        self, client, acting_user, session, upstream
    ):
        """The dashboard names which sources it displays; anything else is not
        reachable through it, even though the same app offers it."""
        a, app, dashboard = await _workspace(session, acting_user, "orders_summary")

        response = await client.get(
            _url(a, app, "revenue", dashboard), headers=a.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == AppDataMessages.SOURCE_NOT_FOUND
        assert upstream.count == 0

    async def test_a_source_the_app_does_not_declare_is_refused(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user, "made_up")

        response = await client.get(
            _url(a, app, "made_up", dashboard), headers=a.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == AppDataMessages.SOURCE_NOT_FOUND
        assert upstream.count == 0


class TestVisibility:
    async def test_a_guild_admin_source_is_open_to_an_admin(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user, "revenue")

        response = await client.get(
            _url(a, app, "revenue", dashboard), headers=a.headers
        )
        assert response.status_code == 200, response.text

    async def test_a_guild_admin_source_is_refused_to_a_member(
        self, client, acting_user, session, upstream
    ):
        """Checked against the caller's real guild role, on the pinned
        definition — not against anything the request supplied."""
        a, app, dashboard = await _workspace(session, acting_user, "revenue")
        member = await acting_user(
            guild_role=GuildRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )

        response = await client.get(
            _url(member, app, "revenue", dashboard), headers=member.headers
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
            _url(a, app, "orders_summary", dashboard), headers=a.headers
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
            _url(a, app, "orders_summary", dashboard), headers=a.headers
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
            _url(a, app, "orders_summary", dashboard), headers=a.headers
        )
        assert first.status_code == 200

        registration = (await session.exec(select(AppServiceRegistration))).first()
        registration.enabled = False
        session.add(registration)
        await session.commit()

        second = await client.get(
            _url(a, app, "orders_summary", dashboard), headers=a.headers
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
            definition=_dashboard_definition("orders_summary"),
        )

        response = await client.get(
            _url(a, app, "orders_summary", dashboard), headers=a.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == AppDataMessages.SERVICE_NOT_REGISTERED


class TestParams:
    async def test_declared_parameters_reach_the_app(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user)

        response = await client.get(
            _url(a, app, "orders_summary", dashboard, params='{"range":"30d"}'),
            headers=a.headers,
        )
        assert response.status_code == 200, response.text
        assert upstream.calls[0].url.params["range"] == "30d"

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
            _url(a, app, "orders_summary", dashboard, params=params),
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
        await client.get(_url(a, app, "orders_summary", dashboard), headers=a.headers)

        header = upstream.calls[0].headers["Authorization"]
        assert header.startswith("Bearer ")
        claims = jwt.decode(
            header.removeprefix("Bearer "),
            options={"verify_signature": False},
            algorithms=["RS256"],
        )
        assert claims["guild_id"] == a.guild.id
        assert claims["app_install_id"] == app.id
        assert claims["scope"] == "data"
        assert claims["source_id"] == "orders_summary"
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
        a, app, dashboard = await _workspace(session, acting_user, "my_prs")

        response = await client.get(
            _url(a, app, "my_prs", dashboard), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == AppDataMessages.CONNECTION_REQUIRED
        assert upstream.count == 0

    async def test_a_blocked_member_is_refused_by_name(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user, "my_prs")
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

        response = await client.get(
            _url(a, app, "my_prs", dashboard), headers=a.headers
        )
        assert response.status_code == 403
        assert response.json()["detail"] == GuildAppMessages.CONNECTION_BLOCKED
        assert upstream.count == 0

    async def test_the_token_carries_the_opaque_handle_not_the_person(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user, "my_prs")
        await _connect(session, app=app, user_id=a.user.id, ref="cr_alice")

        response = await client.get(
            _url(a, app, "my_prs", dashboard), headers=a.headers
        )
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
        definition["data_sources"][0]["requires"] = {"all_of": ["admin"]}

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
            definition=_dashboard_definition("orders_summary"),
        )

        response = await client.get(
            _url(a, app, "orders_summary", dashboard), headers=a.headers
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
            _url(a, app, "orders_summary", dashboard), headers=a.headers
        )
        second = await client.get(
            _url(member, app, "orders_summary", dashboard), headers=member.headers
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
            _url(a, app, "orders_summary", dashboard, params='{"range":"7d"}'),
            headers=a.headers,
        )
        await client.get(
            _url(a, app, "orders_summary", dashboard, params='{"range":"30d"}'),
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
        a, app, dashboard = await _workspace(session, acting_user, "my_prs")
        b = await acting_user(
            guild_role=GuildRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        await _connect(session, app=app, user_id=a.user.id, ref="cr_alice")
        await _connect(session, app=app, user_id=b.user.id, ref="cr_bob")

        upstream.rows = [{"pr": "alice"}]
        alice = await client.get(_url(a, app, "my_prs", dashboard), headers=a.headers)
        upstream.rows = [{"pr": "bob"}]
        bob = await client.get(_url(b, app, "my_prs", dashboard), headers=b.headers)

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
        a, app, dashboard = await _workspace(session, acting_user, "my_prs")
        await _connect(session, app=app, user_id=a.user.id, ref="cr_alice")

        await client.get(_url(a, app, "my_prs", dashboard), headers=a.headers)
        again = await client.get(_url(a, app, "my_prs", dashboard), headers=a.headers)

        assert again.json()["cached"] is True
        assert upstream.count == 1

    async def test_a_rotated_credential_retires_the_answers_it_produced(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user)
        await client.get(_url(a, app, "orders_summary", dashboard), headers=a.headers)
        assert upstream.count == 1

        await route_session_to_guild(session, a.guild.id)
        app.config = {"admin": {"shop_domain": "rotated.example"}}
        session.add(app)
        await session.commit()

        response = await client.get(
            _url(a, app, "orders_summary", dashboard), headers=a.headers
        )
        assert response.json()["cached"] is False
        assert upstream.count == 2

    async def test_a_source_asking_for_no_cache_is_not_cached(
        self, client, acting_user, session, upstream
    ):
        a, app, dashboard = await _workspace(session, acting_user, "revenue")

        await client.get(_url(a, app, "revenue", dashboard), headers=a.headers)
        await client.get(_url(a, app, "revenue", dashboard), headers=a.headers)
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
            _url(a, app, "orders_summary", dashboard), headers=a.headers
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
        await client.get(_url(a, app, "orders_summary", dashboard), headers=a.headers)

        upstream.error = None
        upstream.rows = [{"id": 2}]
        response = await client.get(
            _url(a, app, "orders_summary", dashboard), headers=a.headers
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
            _url(a, app, "orders_summary", dashboard), headers=a.headers
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
        assert widget["sample_data"] == {"orders_summary": [{"day": "mon", "total": 4}]}

        sources = {source["id"]: source for source in entry["data_sources"]}
        assert sources["revenue"]["visibility"] == "guild_admin"
        assert sources["orders_summary"]["cache_ttl_seconds"] == 60

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

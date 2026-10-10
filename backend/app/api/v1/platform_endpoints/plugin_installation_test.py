"""What an installed plug-in may read and report about its own installation.

Every route here takes an installation token and reaches the install the token
names; no route names a community or an install in its path. Four things carry
the weight.

**The token is the only statement of which install.** A token the install seam
will not stand up — a member token, one whose registration or publisher is
off, one naming an install the guild turned off or another listing's install —
reaches nothing, and the answer is the same 401 however it failed.

**A plug-in sees its own install and nothing else.** An install carrying this
registration's listing but pinning another plug-in's definition is not this
plug-in's, and neither is a connection handle minted in another community.

**Plaintext leaves on two routes.** The config route returns decrypted
values to the plug-in that uses them, and never a flow's tokens; the token route
hands out one access token by reference (``plugin_connection_flows_test``). The
connections route reports which handles are live and carries no value at all.
Each is asserted against the whole response body.

**The plug-in is the only party that can say whether credentials work.** Nothing
else in this build moves ``config_state`` off ``unverified``.
"""

import json
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.plugin_access_token import seal_install_token
from app.core.encryption import SALT_PLUGIN_CONFIG, encrypt_field
from app.core.messages import PluginChannelMessages, PluginMessages
from app.models.platform.plugin_service_registration import PluginServiceRegistration
from app.models.platform.guild import CommunityRole
from app.models.platform.publisher import Publisher
from app.models.tenant.event_outbox import EventOutbox
from app.models.tenant.initiative import InitiativeMember
from app.models.tenant.plugin_event_outbox import PluginEventOutbox
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.guild_plugin_user_connection import GuildPluginUserConnection
from app.models.tenant.plugin_metadata import PluginMetadata
from app.models.tenant.plugin_placement import PluginPlacement
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.services.tenant import plugin_channels as channels_service
from app.services.tenant import plugin_metadata as metadata_service
from app.testing import (
    create_plugin_service_registration,
    create_guild,
    create_guild_plugin,
    create_project,
    create_resource_grant,
    create_task,
    create_user,
    guild_url,
    route_as,
    route_as_install,
    route_session_to_guild,
)
from app.testing.plugin_clients import CLIENT, install_headers, install_plugin


BASE = "/api/v1/plugin-platform/installation"
SHOP = "tests.shop"
SHOP_UID = "TESTAPP0000001"
OTHER_UID = "TESTAPP0000002"
ORDER_CREATED = "plugin.tests.shop.order_created"

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
        "plugin_kind": "service",
        "service": {"public_id": public_id, "protocol": 1},
        "features": ["endpoints"],
        "connections": [ADMIN_CONNECTION, MEMBER_CONNECTION],
        "endpoints": [{"id": ORDER_CREATED, "direction": "emit"}],
    }


async def _register(session: AsyncSession, **overrides) -> PluginServiceRegistration:
    return await create_plugin_service_registration(
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
    """A guild with a service plug-in installed, optionally already configured."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    if with_values:
        overrides.setdefault("config", {"admin": {"shop_domain": "example.test"}})
        overrides.setdefault(
            "secrets",
            {"admin": {"admin_token": encrypt_field(GUILD_TOKEN, SALT_PLUGIN_CONFIG)}},
        )
    plugin = await create_guild_plugin(
        session,
        guild,
        user,
        definition=definition or _definition(),
        listing_uid=listing_uid,
        **overrides,
    )
    return guild, user, plugin


async def _member_connection(
    session: AsyncSession,
    *,
    guild,
    plugin,
    user,
    connection_id: str = "github",
    connection_ref: str = "cr_member_one",
    with_secret: bool = True,
    blocked: bool = False,
) -> GuildPluginUserConnection:
    await route_session_to_guild(session, guild.id)
    row = GuildPluginUserConnection(
        plugin_id=plugin.id,
        connection_id=connection_id,
        user_id=user.id,
        connection_ref=connection_ref,
        config={"login": "alice"} if with_secret else {},
        config_secrets=(
            {"access_token": encrypt_field(MEMBER_TOKEN, SALT_PLUGIN_CONFIG)}
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
    plugin,
    *,
    client_id: str = SHOP,
    initiative_id: int | None = None,
    user_id: int | None = None,
) -> dict[str, str]:
    """An installation token for ``plug-in`` in ``guild``, as the token endpoint
    would issue one."""
    token, _exp = seal_install_token(
        guild_id=guild.id,
        install_id=plugin.id,
        client_id=client_id,
        scopes=frozenset(),
        initiative_id=initiative_id,
        user_id=user_id,
        purpose=None,
    )
    return {"Authorization": f"Bearer {token}"}


async def _reload(session: AsyncSession, guild_id: int, plugin_id: int) -> GuildPlugin:
    await route_session_to_guild(session, guild_id)
    session.expunge_all()
    return (
        await session.exec(select(GuildPlugin).where(GuildPlugin.id == plugin_id))
    ).one()


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
        guild, _, plugin = await _install(session, with_values=True)

        response = await client.get(
            f"{BASE}/config", headers=_headers(guild, plugin, initiative_id=12345)
        )

        assert response.status_code == 200, response.text

    async def test_a_member_token_is_refused(
        self, client: AsyncClient, session: AsyncSession
    ):
        """A member token acts for somebody; the install's own configuration is
        not something it reaches."""
        await _register(session)
        guild, user, plugin = await _install(session, with_values=True)

        response = await client.get(
            f"{BASE}/config", headers=_headers(guild, plugin, user_id=user.id)
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
        guild, _, plugin = await _install(session, with_values=True)
        if what == "registration":
            await _switch_off(session, registration)
        elif what == "publisher":
            await _switch_off(
                session, await session.get(Publisher, registration.publisher_id)
            )
        else:
            await route_session_to_guild(session, guild.id)
            await _switch_off(session, plugin)

        for method, path in (
            ("GET", "/config"),
            ("GET", "/connections"),
            ("POST", "/config-status"),
        ):
            response = await client.request(
                method,
                f"{BASE}{path}",
                headers=_headers(guild, plugin),
                json={"state": "ok"} if method == "POST" else None,
            )
            assert response.status_code == 401, (path, response.text)
            assert GUILD_TOKEN not in response.text

    async def test_a_registration_with_no_keys_reaches_nothing(
        self, client: AsyncClient, session: AsyncSession
    ):
        await _register(session, jwks={})
        guild, _, plugin = await _install(session, with_values=True)

        response = await client.get(f"{BASE}/config", headers=_headers(guild, plugin))

        assert response.status_code == 401

    async def test_a_token_naming_another_listings_install_reaches_nothing(
        self, client: AsyncClient, session: AsyncSession
    ):
        """One plug-in's credentials are not reachable by another's token, and the
        refusal says nothing about what is there."""
        await _register(session)
        theirs, _, theirs_plugin = await _install(
            session,
            definition=_definition("tests.other"),
            listing_uid=OTHER_UID,
            with_values=True,
        )

        response = await client.get(
            f"{BASE}/config", headers=_headers(theirs, theirs_plugin)
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
        guild, user, plugin = await _install(session, with_values=True)
        await _member_connection(session, guild=guild, plugin=plugin, user=user)

        response = await client.get(f"{BASE}/config", headers=_headers(guild, plugin))

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
        # The plug-in is told which member by handle, and by nothing else.
        assert "user_id" not in member
        assert user.seeded_address not in response.text

    async def test_a_blocked_members_values_are_not_served(
        self, client: AsyncClient, session: AsyncSession
    ):
        """A block ends that member's access; the tombstone it leaves must not
        keep handing the plug-in a credential to act with."""
        await _register(session)
        guild, user, plugin = await _install(session, with_values=True)
        await _member_connection(
            session, guild=guild, plugin=plugin, user=user, blocked=True
        )

        response = await client.get(f"{BASE}/config", headers=_headers(guild, plugin))

        assert response.status_code == 200, response.text
        assert response.json()["member_connections"] == []

    async def test_an_install_pinning_another_plugins_definition_is_not_ours(
        self, client: AsyncClient, session: AsyncSession
    ):
        """Both statements have to agree. A row carrying this registration's
        catalog uid but pinning a definition that names a different service is
        not an install this caller may reach."""
        await _register(session)
        guild, _, plugin = await _install(
            session, definition=_definition("tests.someone-else"), with_values=True
        )

        response = await client.get(f"{BASE}/config", headers=_headers(guild, plugin))

        assert response.status_code == 404
        assert response.json()["detail"] == PluginChannelMessages.INSTALL_NOT_FOUND
        assert GUILD_TOKEN not in response.text

    async def test_an_install_that_needed_configuring_says_so(
        self, client: AsyncClient, session: AsyncSession
    ):
        await _register(session)
        guild, _, plugin = await _install(session)

        response = await client.get(f"{BASE}/config", headers=_headers(guild, plugin))

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
        guild, user, plugin = await _install(session, with_values=True)
        await _member_connection(session, guild=guild, plugin=plugin, user=user)

        response = await client.get(
            f"{BASE}/connections", headers=_headers(guild, plugin)
        )

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
        guild, user, plugin = await _install(session)
        await _member_connection(session, guild=guild, plugin=plugin, user=user)

        response = await client.get(
            f"{BASE}/connections", headers=_headers(guild, plugin)
        )

        assert response.status_code == 200, response.text
        assert "user_id" not in response.text
        assert user.seeded_address not in response.text

    async def test_a_blocked_connection_is_reported_as_blocked(
        self, client: AsyncClient, session: AsyncSession
    ):
        await _register(session)
        guild, user, plugin = await _install(session)
        await _member_connection(
            session, guild=guild, plugin=plugin, user=user, blocked=True
        )

        response = await client.get(
            f"{BASE}/connections", headers=_headers(guild, plugin)
        )

        assert response.status_code == 200, response.text
        assert response.json()["items"][0]["blocked"] is True


# ---------------------------------------------------------------------------
# The plug-in's own verdict
# ---------------------------------------------------------------------------


class TestConfigStatus:
    async def test_reporting_invalid_carries_the_reason(
        self, client: AsyncClient, session: AsyncSession
    ):
        await _register(session)
        guild, _, plugin = await _install(session, with_values=True)
        assert plugin.config_state == "unverified"

        response = await client.post(
            f"{BASE}/config-status",
            headers=_headers(guild, plugin),
            json={"state": "invalid", "detail": "missing_read_orders"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["config_state"] == "invalid"
        stored = await _reload(session, guild.id, plugin.id)
        assert stored.config_state == "invalid"
        assert stored.config_state_detail == "missing_read_orders"

    async def test_a_state_outside_the_vocabulary_is_refused(
        self, client: AsyncClient, session: AsyncSession
    ):
        await _register(session)
        guild, _, plugin = await _install(session)

        response = await client.post(
            f"{BASE}/config-status",
            headers=_headers(guild, plugin),
            json={"state": "wonderful"},
        )

        assert response.status_code == 422
        stored = await _reload(session, guild.id, plugin.id)
        assert stored.config_state == "unverified"


# ---------------------------------------------------------------------------
# Events a plug-in emits
# ---------------------------------------------------------------------------


async def _kept(session: AsyncSession, guild_id: int) -> list[dict]:
    """The events kept in the community for the poller to deliver."""
    await route_session_to_guild(session, guild_id)
    session.expunge_all()
    rows = (await session.exec(select(PluginEventOutbox))).all()
    return [
        {
            "install_id": row.install_id,
            "event_type": row.event_type,
            "initiative_id": row.initiative_id,
            "payload": row.payload,
        }
        for row in rows
    ]


class TestEvents:
    async def test_a_declared_event_is_kept_for_delivery(
        self, client: AsyncClient, session: AsyncSession
    ):
        await _register(session)
        guild, _, plugin = await _install(session)

        response = await client.post(
            f"{BASE}/events",
            headers=_headers(guild, plugin),
            json={"event_type": ORDER_CREATED, "payload": {"order_id": "1001"}},
        )

        assert response.status_code == 202, response.text
        assert await _kept(session, guild.id) == [
            {
                "install_id": plugin.id,
                "event_type": ORDER_CREATED,
                "initiative_id": None,
                "payload": {"order_id": "1001"},
            }
        ]

    @pytest.mark.parametrize(
        ("case", "event", "status", "detail"),
        [
            (
                "an event type the plug-in never declared",
                {"event_type": "plugin.tests.shop.never_declared", "payload": {}},
                400,
                PluginChannelMessages.UNKNOWN_EVENT_TYPE,
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
                PluginChannelMessages.EVENT_TOO_LARGE,
            ),
            (
                "a body over the request bound",
                {"event_type": ORDER_CREATED, "payload": {"note": "x" * (128 * 1024)}},
                413,
                PluginChannelMessages.EVENT_TOO_LARGE,
            ),
            (
                "an initiative the plug-in is not placed in",
                {"event_type": ORDER_CREATED, "payload": {}, "initiative_id": 999},
                403,
                PluginChannelMessages.INITIATIVE_NOT_PLACED,
            ),
        ],
        ids=lambda v: v if isinstance(v, str) and " " in v else "",
    )
    async def test_an_event_the_route_will_not_carry_is_refused(
        self,
        client: AsyncClient,
        session: AsyncSession,
        case: str,
        event: dict,
        status: int,
        detail: str,
    ):
        await _register(session)
        guild, _, plugin = await _install(session)

        response = await client.post(
            f"{BASE}/events", headers=_headers(guild, plugin), json=event
        )

        assert response.status_code == status, response.text
        assert response.json()["detail"] == detail
        assert await _kept(session, guild.id) == []

    async def test_another_plugins_namespace_is_refused(
        self, client: AsyncClient, session: AsyncSession
    ):
        await _register(session)
        definition = _definition()
        definition["endpoints"] = [
            {"id": "plugin.tests.other.order_created", "direction": "emit"}
        ]
        guild, _, plugin = await _install(session, definition=definition)

        response = await client.post(
            f"{BASE}/events",
            headers=_headers(guild, plugin),
            json={"event_type": "plugin.tests.other.order_created", "payload": {}},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == PluginChannelMessages.UNKNOWN_EVENT_TYPE
        assert await _kept(session, guild.id) == []


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

PROJECTS = ["projects:read", "projects:write"]


async def _with_task(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """An install placed in one initiative, holding the projects scopes, and a
    task it made there."""
    installed = await install_plugin(
        session, acting_user, role_session, granted=PROJECTS
    )
    headers = install_headers(installed, PROJECTS)
    project = await client.post(
        guild_url(installed.guild.id, "/projects/"),
        headers=headers,
        json={"name": "The plug-in's", "initiative_id": installed.placed.id},
    )
    assert project.status_code == 201, project.text
    task = await client.post(
        guild_url(installed.guild.id, "/tasks/"),
        headers=headers,
        json={"project_id": project.json()["id"], "title": "The plug-in's"},
    )
    assert task.status_code == 201, task.text
    return installed, task.json()["id"]


async def _stored(session: AsyncSession, guild_id: int) -> list[PluginMetadata]:
    await route_session_to_guild(session, guild_id)
    session.expunge_all()
    return list(await session.exec(select(PluginMetadata)))


class TestMetadata:
    async def test_values_are_written_read_and_removed_with_the_read_scope(
        self, client: AsyncClient, session: AsyncSession, acting_user, role_session
    ):
        """Keeping values changes nothing on the item, so the tool's read
        scope is enough to write them."""
        installed, task_id = await _with_task(
            client, session, acting_user, role_session
        )
        headers = install_headers(installed, ["projects:read"])

        written = await client.put(
            f"{BASE}/metadata",
            headers=headers,
            json={
                "entity_type": "task",
                "entity_id": task_id,
                "values": {"github.issue": 123, "state": {"open": True}},
            },
        )
        assert written.status_code == 200, written.text
        assert written.json() == {
            "values": {"github.issue": 123, "state": {"open": True}}
        }

        removed = await client.put(
            f"{BASE}/metadata",
            headers=headers,
            json={
                "entity_type": "task",
                "entity_id": task_id,
                "values": {"state": None},
            },
        )
        assert removed.json() == {"values": {"github.issue": 123}}

        read = await client.get(
            f"{BASE}/metadata",
            headers=headers,
            params={"entity_type": "task", "entity_ids": [task_id, 987654]},
        )
        assert read.status_code == 200, read.text
        assert read.json() == {
            "items": [
                {
                    "entity_type": "task",
                    "entity_id": task_id,
                    "values": {"github.issue": 123},
                }
            ]
        }

    async def test_an_item_is_found_by_a_value(
        self, client: AsyncClient, session: AsyncSession, acting_user, role_session
    ):
        installed, task_id = await _with_task(
            client, session, acting_user, role_session
        )
        headers = install_headers(installed, ["projects:read"])
        await client.put(
            f"{BASE}/metadata",
            headers=headers,
            json={
                "entity_type": "task",
                "entity_id": task_id,
                "values": {"github.issue": 123, "repo": "acme/web"},
            },
        )

        async def find(key: str, value: str) -> list:
            response = await client.get(
                f"{BASE}/metadata/lookup",
                headers=headers,
                params={"key": key, "value": value},
            )
            assert response.status_code == 200, response.text
            return response.json()["items"]

        assert await find("github.issue", "123") == [
            {
                "entity_type": "task",
                "entity_id": task_id,
                "values": {"github.issue": 123, "repo": "acme/web"},
            }
        ]
        assert [i["entity_id"] for i in await find("repo", "acme/web")] == [task_id]
        assert await find("github.issue", "124") == []

    @pytest.mark.parametrize(
        ("values", "status", "detail"),
        [
            ({"Github": 1}, 400, PluginChannelMessages.METADATA_KEY_INVALID),
            ({"1st": 1}, 400, PluginChannelMessages.METADATA_KEY_INVALID),
            ({"a-b": 1}, 400, PluginChannelMessages.METADATA_KEY_INVALID),
            ({"a" * 65: 1}, 400, PluginChannelMessages.METADATA_KEY_INVALID),
            ({"note": "x" * 8200}, 413, PluginChannelMessages.METADATA_VALUE_TOO_LARGE),
            (
                {f"k{i}": i for i in range(33)},
                409,
                PluginChannelMessages.METADATA_LIMIT_REACHED,
            ),
            (
                {f"k{i}": "x" * 8000 for i in range(9)},
                409,
                PluginChannelMessages.METADATA_LIMIT_REACHED,
            ),
        ],
        ids=[
            "uppercase",
            "leading-digit",
            "dash",
            "long-key",
            "large-value",
            "too-many-keys",
            "too-many-bytes",
        ],
    )
    async def test_a_write_past_the_caps_is_refused(
        self,
        client: AsyncClient,
        session: AsyncSession,
        acting_user,
        role_session,
        values: dict,
        status: int,
        detail: str,
    ):
        installed, task_id = await _with_task(
            client, session, acting_user, role_session
        )

        response = await client.put(
            f"{BASE}/metadata",
            headers=install_headers(installed, ["projects:read"]),
            json={"entity_type": "task", "entity_id": task_id, "values": values},
        )

        assert response.status_code == status, response.text
        assert response.json()["detail"] == detail
        assert await _stored(session, installed.guild.id) == []

    async def test_a_write_that_replaces_a_full_item_is_measured_after(
        self, client: AsyncClient, session: AsyncSession, acting_user, role_session
    ):
        installed, task_id = await _with_task(
            client, session, acting_user, role_session
        )
        headers = install_headers(installed, ["projects:read"])
        full = {f"k{i}": i for i in range(32)}

        async def put(values: dict):
            return await client.put(
                f"{BASE}/metadata",
                headers=headers,
                json={"entity_type": "task", "entity_id": task_id, "values": values},
            )

        assert (await put(full)).status_code == 200
        replaced = await put({**dict.fromkeys(full), "fresh": 1})

        assert replaced.status_code == 200, replaced.text
        assert replaced.json()["values"] == {"fresh": 1}

    async def test_an_item_out_of_reach_is_refused_and_left_out(
        self, client: AsyncClient, session: AsyncSession, acting_user, role_session
    ):
        """An item in an initiative the install is not placed in, and an item
        of a tool whose scope the token does not carry."""
        installed, task_id = await _with_task(
            client, session, acting_user, role_session
        )
        project = await create_project(session, installed.unplaced, installed.seat.user)
        elsewhere = await create_task(session, project)

        async def put(task: int, scopes: list[str]):
            return await client.put(
                f"{BASE}/metadata",
                headers=install_headers(installed, scopes),
                json={"entity_type": "task", "entity_id": task, "values": {"k": 1}},
            )

        unplaced = await put(elsewhere.id, ["projects:read"])
        assert unplaced.status_code == 404, unplaced.text
        assert (
            unplaced.json()["detail"] == PluginChannelMessages.METADATA_ITEM_NOT_FOUND
        )
        unscoped = await put(task_id, [])
        assert unscoped.status_code == 403, unscoped.text
        assert unscoped.json()["detail"] == PluginMessages.SCOPE_REQUIRED
        assert await _stored(session, installed.guild.id) == []

        # Kept while the scope was held, and out of sight without it.
        assert (await put(task_id, ["projects:read"])).status_code == 200
        read = await client.get(
            f"{BASE}/metadata",
            headers=install_headers(installed, []),
            params={"entity_type": "task", "entity_ids": [task_id]},
        )
        assert read.json() == {"items": []}

    async def test_another_install_neither_reads_nor_writes_the_rows(
        self, client: AsyncClient, session: AsyncSession, acting_user, role_session
    ):
        """Held by the table's policies, not by the routes: routed as one
        install, another install's rows on the same item are out of reach."""
        installed, task_id = await _with_task(
            client, session, acting_user, role_session
        )
        other = await create_guild_plugin(
            session,
            installed.guild,
            installed.seat.user,
            definition={
                "plugin_kind": "service",
                "service": {"public_id": "tests.other"},
            },
            listing_uid="OTHERLISTING01",
        )
        await route_session_to_guild(session, installed.guild.id)
        session.add_all(
            PluginMetadata(
                install_id=install_id,
                entity_type="task",
                entity_id=task_id,
                key="k",
                value=1,
            )
            for install_id in (installed.plugin.id, other.id)
        )
        await session.commit()

        s = await role_session("app_user")
        await route_as_install(
            s,
            guild_id=installed.guild.id,
            install_id=installed.plugin.id,
            client_id=CLIENT,
            scopes=["projects:read"],
        )
        seen = await s.exec(select(PluginMetadata.install_id))
        assert seen.all() == [installed.plugin.id]
        moved = await s.exec(
            update(PluginMetadata)
            .where(PluginMetadata.install_id == other.id)
            .values(value=2)
        )
        assert moved.rowcount == 0
        s.add(
            PluginMetadata(
                install_id=other.id,
                entity_type="task",
                entity_id=task_id,
                key="j",
                value=1,
            )
        )
        with pytest.raises(DBAPIError, match="row-level security"):
            await s.commit()
        await s.rollback()

        theirs = [
            (row.key, row.value)
            for row in await _stored(session, installed.guild.id)
            if row.install_id == other.id
        ]
        assert theirs == [("k", 1)]

    async def test_the_install_keeps_values_of_its_own(
        self, client: AsyncClient, session: AsyncSession, acting_user, role_session
    ):
        """On the install itself, with no scope, on a token narrowed to an
        initiative too; and gone with the install."""
        installed = await install_plugin(session, acting_user, role_session, granted=[])
        headers = install_headers(installed, [], initiative_id=installed.placed.id)

        written = await client.put(
            f"{BASE}/metadata",
            headers=headers,
            json={"entity_type": "plugin", "values": {"sync.cursor": "abc"}},
        )
        assert written.status_code == 200, written.text
        read = await client.get(
            f"{BASE}/metadata", headers=headers, params={"entity_type": "plugin"}
        )
        assert read.json() == {
            "items": [
                {
                    "entity_type": "plugin",
                    "entity_id": installed.plugin.id,
                    "values": {"sync.cursor": "abc"},
                }
            ]
        }

        await route_session_to_guild(session, installed.guild.id)
        await session.delete(await session.get(GuildPlugin, installed.plugin.id))
        await session.commit()
        assert await _stored(session, installed.guild.id) == []

    async def test_purging_an_item_takes_its_values(
        self, client: AsyncClient, session: AsyncSession, acting_user, role_session
    ):
        installed, task_id = await _with_task(
            client, session, acting_user, role_session
        )
        await client.put(
            f"{BASE}/metadata",
            headers=install_headers(installed, ["projects:read"]),
            json={"entity_type": "task", "entity_id": task_id, "values": {"k": 1}},
        )
        seat = installed.seat

        trashed = await client.delete(seat.g(f"/tasks/{task_id}"), headers=seat.headers)
        assert trashed.status_code == 204, trashed.text
        assert len(await _stored(session, installed.guild.id)) == 1
        purged = await client.delete(
            seat.g(f"/trash/task/{task_id}/purge"), headers=seat.headers
        )
        assert purged.status_code == 204, purged.text
        assert await _stored(session, installed.guild.id) == []


#: A field on tasks, and one on queue items only.
_FIELDS = {
    "fields": [
        {
            "key": "github.issue",
            "name": {"en": "Issue"},
            "kind": "number",
            "on": ["task"],
        },
        {"key": "lane", "name": {"en": "Lane"}, "kind": "text", "on": ["queue_item"]},
    ]
}


async def _shown_board(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """An install declaring :data:`_FIELDS`, placed for its initiative's
    ``member`` role, a task its members and the install read, a member there,
    and the install's values on the task: a declared key and private ones."""
    installed = await install_plugin(
        session, acting_user, role_session, granted=["projects:read"], declares=_FIELDS
    )
    project = await create_project(session, installed.placed, installed.seat.user)
    await create_resource_grant(session, project, all_initiative_members=True)
    task = await create_task(session, project)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=installed.guild,
        initiative=installed.placed,
        initiative_role="member",
    )
    await route_session_to_guild(session, installed.guild.id)
    role_id = (
        await session.exec(
            select(InitiativeMember.role_id).where(
                InitiativeMember.initiative_id == installed.placed.id,
                InitiativeMember.user_id == member.user.id,
            )
        )
    ).one()
    await session.exec(
        update(PluginPlacement)
        .where(PluginPlacement.install_id == installed.plugin.id)
        .values(role_ids=[role_id])
    )
    await session.commit()
    written = await client.put(
        f"{BASE}/metadata",
        headers=install_headers(installed, ["projects:read"]),
        json={
            "entity_type": "task",
            "entity_id": task.id,
            "values": {"github.issue": 123, "lane": "a", "sync.etag": "x"},
        },
    )
    assert written.status_code == 200, written.text
    return installed, member, task


def _shown(rows: list[PluginMetadata]) -> dict[str, bool]:
    return {row.key: row.shown for row in rows}


class TestShownValues:
    async def test_a_value_is_shown_where_its_key_is_a_field_on_the_kind(
        self, client: AsyncClient, session: AsyncSession, acting_user, role_session
    ):
        """On every write, and again when the install moves to a version that
        declares other fields; the install's own values never."""
        installed, _member, task = await _shown_board(
            client, session, acting_user, role_session
        )
        await client.put(
            f"{BASE}/metadata",
            headers=install_headers(installed, []),
            json={"entity_type": "plugin", "values": {"github.issue": 1}},
        )
        stored = await _stored(session, installed.guild.id)
        assert _shown([r for r in stored if r.entity_type == "task"]) == {
            "github.issue": True,
            "lane": False,
            "sync.etag": False,
        }
        assert _shown([r for r in stored if r.entity_type == "plugin"]) == {
            "github.issue": False
        }

        # The new version is read from the install, as it stands when no
        # write is between reading the old one and committing.
        await route_session_to_guild(session, installed.guild.id)
        await session.exec(
            update(GuildPlugin)
            .where(GuildPlugin.id == installed.plugin.id)
            .values(
                definition={
                    **installed.plugin.definition,
                    "fields": [
                        {**_FIELDS["fields"][0], "key": "sync.etag"},
                        {**_FIELDS["fields"][1], "on": ["queue_item", "task"]},
                    ],
                }
            )
        )
        await session.commit()
        await metadata_service.reconcile_shown(installed.guild.id, installed.plugin.id)
        stored = await _stored(session, installed.guild.id)
        assert _shown([r for r in stored if r.entity_type == "task"]) == {
            "github.issue": False,
            "lane": True,
            "sync.etag": True,
        }
        assert _shown([r for r in stored if r.entity_type == "plugin"]) == {
            "github.issue": False
        }

    async def test_whoever_reads_the_task_reads_its_shown_values(
        self, client: AsyncClient, session: AsyncSession, acting_user, role_session
    ):
        """Through the task's read and its list, and through the table's
        policies: a member reads the shown row alone, and a member of another
        initiative reads none."""
        installed, member, task = await _shown_board(
            client, session, acting_user, role_session
        )
        shown = [
            {"plugin_id": installed.plugin.id, "key": "github.issue", "value": 123}
        ]

        read = await client.get(member.g(f"/tasks/{task.id}"), headers=member.headers)
        assert read.status_code == 200, read.text
        assert read.json()["plugin_values"] == shown
        conditions = json.dumps(
            [{"field": "project_id", "op": "eq", "value": task.project_id}]
        )
        listed = await client.get(
            member.g(f"/tasks/?conditions={conditions}"), headers=member.headers
        )
        assert [row["plugin_values"] for row in listed.json()["items"]] == [shown]

        outsider = await acting_user(
            guild_role=CommunityRole.member,
            guild=installed.guild,
            initiative=installed.unplaced,
            initiative_role="member",
        )
        for actor, keys in ((member, ["github.issue"]), (outsider, [])):
            s = await role_session("app_user")
            await route_as(s, user_id=actor.user.id, guild_id=installed.guild.id)
            seen = await s.exec(select(PluginMetadata.key))
            assert seen.all() == keys
            await s.rollback()

    async def test_values_reach_whom_the_plugins_actions_would(
        self, client: AsyncClient, session: AsyncSession, acting_user, role_session
    ):
        """The install on, placed in the task's initiative with a role the
        reader holds (or the reader its admin), and the reader old enough."""
        installed, member, task = await _shown_board(
            client, session, acting_user, role_session
        )
        manager = await acting_user(
            guild_role=CommunityRole.member,
            guild=installed.guild,
            initiative=installed.placed,
            initiative_role="project_manager",
        )
        shown = [
            {"plugin_id": installed.plugin.id, "key": "github.issue", "value": 123}
        ]

        async def drawn(actor=member) -> list:
            read = await client.get(actor.g(f"/tasks/{task.id}"), headers=actor.headers)
            assert read.status_code == 200, read.text
            return read.json()["plugin_values"]

        async def change(**values) -> None:
            await route_session_to_guild(session, installed.guild.id)
            await session.exec(
                update(GuildPlugin)
                .where(GuildPlugin.id == installed.plugin.id)
                .values(**values)
            )
            await session.commit()

        assert await drawn() == shown
        assert await drawn(installed.seat) == shown
        assert await drawn(manager) == [], "a role the placement does not allow"

        await change(
            definition={**installed.plugin.definition, "minimum_age": {"default": 16}}
        )
        assert await drawn() == [], "a reader too young for the plug-in"
        await change(definition=installed.plugin.definition)

        await change(enabled=False)
        assert await drawn() == [], "an install turned off"
        await change(enabled=True)

        await route_session_to_guild(session, installed.guild.id)
        await session.exec(
            delete(PluginPlacement).where(
                PluginPlacement.install_id == installed.plugin.id
            )
        )
        await session.commit()
        assert await drawn() == [], "an install not placed there"

    async def test_only_a_shown_value_is_heard_as_a_change_to_the_task(
        self, client: AsyncClient, session: AsyncSession, acting_user, role_session
    ):
        installed, _member, task = await _shown_board(
            client, session, acting_user, role_session
        )

        async def heard() -> list:
            await route_session_to_guild(session, installed.guild.id)
            session.expunge_all()
            rows = await session.exec(
                select(EventOutbox).where(EventOutbox.changed.any("plugin_values"))
            )
            return [
                (e.resource_type, e.resource_id, e.action, e.actor_install_id)
                for e in rows
            ]

        async def write(values: dict) -> None:
            response = await client.put(
                f"{BASE}/metadata",
                headers=install_headers(installed, ["projects:read"]),
                json={"entity_type": "task", "entity_id": task.id, "values": values},
            )
            assert response.status_code == 200, response.text

        event = ("tasks", task.id, "updated", installed.plugin.id)
        # Of the board's three keys, one is shown.
        assert await heard() == [event]
        await write({"sync.etag": "y", "lane": None})
        assert await heard() == [event]
        await write({"github.issue": 124})
        assert await heard() == [event, event]

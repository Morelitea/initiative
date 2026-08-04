"""Integration tests for the mode-based AI config surface.

Proves the security properties of the refactor end-to-end:
- A connection's key is never returned by the API (only ``has_api_key``).
- A member can attach a key + pick a connection, but has NO way to set a
  destination (no member connection-create endpoint; attaching to an unknown
  connection 404s) — the inherited-key + attacker-base_url exfil is impossible.
- A member sees only their OWN key state (own-row).
- A guild admin can never persist a private/internal base_url.
"""

import pytest

from app.models.platform.guild import GuildRole
from app.services import ai_settings as ai_settings_service

pytestmark = pytest.mark.database

PLATFORM_MODE = "/api/v1/settings/ai/platform/mode"
PLATFORM_CONNS = "/api/v1/settings/ai/platform/connections"


@pytest.fixture(autouse=True)
def _reset_ai_cache():
    """The platform config is cached in-process; drop it around each test so a
    mode/connection change in one test never leaks into the next."""
    ai_settings_service.invalidate_platform_ai_cache()
    yield
    ai_settings_service.invalidate_platform_ai_cache()


async def _set_mode(client, owner, mode: str):
    r = await client.put(PLATFORM_MODE, headers=owner.headers, json={"mode": mode})
    assert r.status_code == 200, r.text


async def test_platform_connection_key_never_returned(client, acting_user):
    owner = await acting_user()  # platform owner (config.manage)
    await _set_mode(client, owner, "platform")

    r = await client.post(
        PLATFORM_CONNS,
        headers=owner.headers,
        json={
            "label": "Company OpenAI",
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "sk-super-secret",
            "enabled": True,
            "is_default": True,
            "allow_member_keys": False,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_api_key"] is True
    assert body["scope"] == "platform"
    # The ciphertext / plaintext key is never serialized.
    assert "api_key" not in body
    assert "api_key_encrypted" not in body

    # Listing likewise never exposes the key.
    r = await client.get(PLATFORM_CONNS, headers=owner.headers)
    assert r.status_code == 200
    for conn in r.json():
        assert "api_key" not in conn
        assert "api_key_encrypted" not in conn


async def test_member_sees_platform_connection_without_key(client, acting_user):
    owner = await acting_user()
    await _set_mode(client, owner, "platform")
    await client.post(
        PLATFORM_CONNS,
        headers=owner.headers,
        json={
            "label": "Shared",
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "sk-secret",
            "is_default": True,
            "allow_member_keys": False,
        },
    )

    member = await acting_user(guild_role=GuildRole.member, initiative=True)
    r = await client.get(member.g("/settings/ai/me"), headers=member.headers)
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["mode"] == "platform"
    platform_conns = [c for c in view["connections"] if c["scope"] == "platform"]
    assert platform_conns, "member should see the operator's connection"
    for c in platform_conns:
        assert "api_key" not in c
        # operator set a shared key, so the member is not required to bring one
        assert c["requires_member_key"] is False


async def test_member_cannot_set_a_destination(client, acting_user):
    """Exfil-impossible: a member has no endpoint to create a connection, and
    attaching a key to an unknown connection id 404s — they can never point a
    key at a destination they chose."""
    owner = await acting_user()
    await _set_mode(client, owner, "platform")
    member = await acting_user(guild_role=GuildRole.member, initiative=True)

    # There is no member connection-create route.
    r = await client.post(
        member.g("/settings/ai/connections"),
        headers=member.headers,
        json={"label": "evil", "provider": "custom", "base_url": "http://evil"},
    )
    assert r.status_code == 403  # guild-admin only

    # Attaching a key to a connection that doesn't exist is refused.
    r = await client.put(
        member.g("/settings/ai/me/key"),
        headers=member.headers,
        json={"scope": "platform", "connection_id": 999999, "api_key": "sk-x"},
    )
    assert r.status_code == 404


async def test_member_attach_key_is_own_row(client, acting_user):
    owner = await acting_user()
    await _set_mode(client, owner, "platform")
    r = await client.post(
        PLATFORM_CONNS,
        headers=owner.headers,
        json={"label": "Shared", "provider": "openai", "is_default": True},
    )
    conn_id = r.json()["id"]

    m1 = await acting_user(guild_role=GuildRole.member, initiative=True)
    m2 = await acting_user(guild_role=GuildRole.member, guild=m1.guild)

    # m1 attaches their own key.
    r = await client.put(
        m1.g("/settings/ai/me/key"),
        headers=m1.headers,
        json={"scope": "platform", "connection_id": conn_id, "api_key": "sk-m1"},
    )
    assert r.status_code == 200, r.text
    conn_view = next(
        c
        for c in r.json()["connections"]
        if c["id"] == conn_id and c["scope"] == "platform"
    )
    assert conn_view["has_member_key"] is True

    # m2 (same guild) sees the connection but NOT m1's key.
    r = await client.get(m2.g("/settings/ai/me"), headers=m2.headers)
    assert r.status_code == 200
    conn_view = next(
        c
        for c in r.json()["connections"]
        if c["id"] == conn_id and c["scope"] == "platform"
    )
    assert conn_view["has_member_key"] is False


async def test_guild_admin_cannot_save_private_base_url(client, acting_user):
    owner = await acting_user()
    await _set_mode(client, owner, "guild")

    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)

    # A public custom endpoint is fine.
    r = await client.post(
        admin.g("/settings/ai/connections"),
        headers=admin.headers,
        json={"label": "ok", "provider": "openai", "model": "gpt-4o", "api_key": "k"},
    )
    assert r.status_code == 200, r.text

    # A private/internal base_url is rejected for a guild connection.
    r = await client.post(
        admin.g("/settings/ai/connections"),
        headers=admin.headers,
        json={
            "label": "evil",
            "provider": "ollama",
            "base_url": "http://169.254.169.254",
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "AI_INVALID_BASE_URL"


async def test_connection_that_disallows_member_keys(client, acting_user):
    """A connection with allow_member_keys=False uses its own shared key only —
    a member cannot attach their own key to it."""
    owner = await acting_user()
    await _set_mode(client, owner, "platform")
    r = await client.post(
        PLATFORM_CONNS,
        headers=owner.headers,
        json={
            "label": "Company-only",
            "provider": "openai",
            "api_key": "sk-shared",
            "is_default": True,
            "allow_member_keys": False,
        },
    )
    assert r.status_code == 200, r.text
    conn = r.json()
    assert conn["allow_member_keys"] is False
    conn_id = conn["id"]

    member = await acting_user(guild_role=GuildRole.member, initiative=True)
    view = (
        await client.get(member.g("/settings/ai/me"), headers=member.headers)
    ).json()
    conn_view = next(c for c in view["connections"] if c["id"] == conn_id)
    assert conn_view["allow_member_keys"] is False
    # Has a shared key, so no member key is required.
    assert conn_view["requires_member_key"] is False

    # Attaching a member key is refused.
    r = await client.put(
        member.g("/settings/ai/me/key"),
        headers=member.headers,
        json={"scope": "platform", "connection_id": conn_id, "api_key": "sk-mine"},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "AI_MEMBER_KEYS_DISABLED"


async def test_shared_key_and_member_keys_are_mutually_exclusive(client, acting_user):
    """A connection's key is EITHER shared OR member-supplied, never both. If a
    key is sent together with allow_member_keys=True, the toggle wins and the
    shared key is dropped."""
    owner = await acting_user()
    await _set_mode(client, owner, "platform")
    r = await client.post(
        PLATFORM_CONNS,
        headers=owner.headers,
        json={
            "label": "Conflicted",
            "provider": "openai",
            "api_key": "sk-should-be-ignored",
            "allow_member_keys": True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["allow_member_keys"] is True
    assert body["has_api_key"] is False  # shared key dropped in favor of BYO


async def test_my_ai_aggregate_lists_connections_across_guilds(client, acting_user):
    """GET /me/ai flattens the member's available connections across guilds,
    carrying guild context so the client can address per-guild writes."""
    owner = await acting_user()
    await _set_mode(client, owner, "platform")
    r = await client.post(
        PLATFORM_CONNS,
        headers=owner.headers,
        json={
            "label": "Shared",
            "provider": "openai",
            "api_key": "k",
            "is_default": True,
        },
    )
    conn_id = r.json()["id"]

    member = await acting_user(guild_role=GuildRole.member, initiative=True)
    r = await client.get("/api/v1/me/ai", headers=member.headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["guild_id"] == member.guild.id
    assert row["guild_name"] == member.guild.name
    assert row["scope"] == "platform"
    assert row["connection_id"] == conn_id
    assert row["label"] == "Shared"
    # Never leaks the key itself.
    assert "api_key" not in row


async def _member_key_rows(session, guild_id, connection_id):
    from sqlmodel import select

    from app.models.tenant.ai_member_key import GuildAIMemberKey
    from app.testing.schema_harness import route_session_to_guild

    await route_session_to_guild(session, guild_id)
    return (
        await session.exec(
            select(GuildAIMemberKey).where(
                GuildAIMemberKey.connection_id == connection_id
            )
        )
    ).all()


async def test_deleting_platform_connection_purges_member_keys(
    client, acting_user, session
):
    """Deleting a connection must not leave orphaned member secrets — the
    per-guild member key rows are purged across every guild."""
    owner = await acting_user()
    await _set_mode(client, owner, "platform")
    r = await client.post(
        PLATFORM_CONNS,
        headers=owner.headers,
        json={"label": "BYO", "provider": "openai", "is_default": True},
    )
    conn_id = r.json()["id"]

    member = await acting_user(guild_role=GuildRole.member, initiative=True)
    r = await client.put(
        member.g("/settings/ai/me/key"),
        headers=member.headers,
        json={"scope": "platform", "connection_id": conn_id, "api_key": "sk-mine"},
    )
    assert r.status_code == 200, r.text
    assert len(await _member_key_rows(session, member.guild.id, conn_id)) == 1

    r = await client.delete(f"{PLATFORM_CONNS}/{conn_id}", headers=owner.headers)
    assert r.status_code == 204
    assert await _member_key_rows(session, member.guild.id, conn_id) == []


async def test_deleting_guild_connection_purges_member_keys(
    client, acting_user, session
):
    owner = await acting_user()
    await _set_mode(client, owner, "guild")
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    r = await client.post(
        admin.g("/settings/ai/connections"),
        headers=admin.headers,
        json={"label": "Team", "provider": "openai"},
    )
    conn_id = r.json()["id"]
    r = await client.put(
        admin.g("/settings/ai/me/key"),
        headers=admin.headers,
        json={"scope": "guild", "connection_id": conn_id, "api_key": "sk-admin"},
    )
    assert r.status_code == 200, r.text
    assert len(await _member_key_rows(session, admin.guild.id, conn_id)) == 1

    r = await client.delete(
        admin.g(f"/settings/ai/connections/{conn_id}"), headers=admin.headers
    )
    assert r.status_code == 204
    assert await _member_key_rows(session, admin.guild.id, conn_id) == []


async def test_disabled_mode_hides_ai(client, acting_user):
    owner = await acting_user()
    await _set_mode(client, owner, "disabled")
    member = await acting_user(guild_role=GuildRole.member, initiative=True)

    r = await client.get(member.g("/settings/ai/me"), headers=member.headers)
    assert r.status_code == 200
    view = r.json()
    assert view["mode"] == "disabled"
    assert view["enabled"] is False

    r = await client.get(member.g("/settings/ai/resolved"), headers=member.headers)
    assert r.status_code == 200
    assert r.json()["enabled"] is False

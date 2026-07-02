"""Tests for the settings endpoints.

Currently focused on the SMTP test-email error path (pentest SEC-16): a failed
delivery must return a generic machine-readable code, never the raw SMTP
exception (which can carry the mail host, port, or server banner).
"""

from __future__ import annotations

import logging

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.platform.user import UserRole
from app.services import email as email_service
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_user,
    get_auth_headers,
)


@pytest.mark.integration
async def test_email_test_runtime_error_returns_generic_code(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = await create_user(
        session, email="owner-smtp@example.com", role=UserRole.owner
    )

    sensitive = "SMTPConnectError to smtp.internal.example.com:587 (banner leak)"

    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(sensitive)

    monkeypatch.setattr(email_service, "send_test_email", _boom)

    resp = await client.post(
        "/api/v1/settings/email/test",
        json={"recipient": "dest@example.com"},
        headers=get_auth_headers(owner),
    )

    assert resp.status_code == 502
    # The client gets only the generic machine-readable code...
    assert resp.json()["detail"] == "SETTINGS_EMAIL_SEND_FAILED"
    # ...and never the raw SMTP host / banner.
    assert sensitive not in resp.text
    assert "smtp.internal.example.com" not in resp.text


@pytest.mark.integration
async def test_email_test_runtime_error_logs_details_server_side(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner = await create_user(
        session, email="owner-smtp-log@example.com", role=UserRole.owner
    )

    sensitive = "535 auth failed for relay user at mail.corp.example.net"

    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(sensitive)

    monkeypatch.setattr(email_service, "send_test_email", _boom)

    with caplog.at_level(
        logging.WARNING, logger="app.api.v1.platform_endpoints.settings"
    ):
        resp = await client.post(
            "/api/v1/settings/email/test",
            json={"recipient": "dest@example.com"},
            headers=get_auth_headers(owner),
        )

    assert resp.status_code == 502
    # The real cause is preserved for the operator in the server logs only.
    assert sensitive in caplog.text


@pytest.mark.integration
async def test_oidc_mapping_options_includes_guild_scoped_initiatives(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Regression: initiatives/roles are guild-scoped content (rows live in each
    guild's schema, not the empty public copies). The options endpoint must route
    into every guild schema, otherwise the form's initiative dropdown is empty."""
    owner = await create_user(
        session, email="owner-oidc-opts@example.com", role=UserRole.owner
    )
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(
        session, user=owner, guild=guild, role=GuildRole.admin
    )
    initiative = await create_initiative(session, guild=guild, creator=owner)

    resp = await client.get(
        "/api/v1/settings/oidc-mappings/options", headers=get_auth_headers(owner)
    )
    assert resp.status_code == 200
    data = resp.json()

    matched = next((i for i in data["initiatives"] if i["id"] == initiative.id), None)
    assert matched is not None, "guild-scoped initiative missing from options"
    assert matched["guild_id"] == guild.id

    # Roles carry guild_id so the client can disambiguate initiative ids that
    # collide across guild schemas.
    roles = [
        r
        for r in data["initiative_roles"]
        if r["initiative_id"] == initiative.id and r["guild_id"] == guild.id
    ]
    assert roles, "initiative roles missing from options"
    assert all("guild_id" in r for r in data["initiative_roles"])


@pytest.mark.integration
async def test_create_initiative_oidc_mapping_resolves_guild_scoped_data(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Regression: creating an initiative-target mapping must validate the
    initiative/role inside the guild schema (previously it queried the empty
    public copy and always 400'd INITIATIVE_NOT_FOUND)."""
    owner = await create_user(
        session, email="owner-oidc-create@example.com", role=UserRole.owner
    )
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(
        session, user=owner, guild=guild, role=GuildRole.admin
    )
    initiative = await create_initiative(session, guild=guild, creator=owner)

    headers = get_auth_headers(owner)
    options = (
        await client.get("/api/v1/settings/oidc-mappings/options", headers=headers)
    ).json()
    role = next(
        r
        for r in options["initiative_roles"]
        if r["initiative_id"] == initiative.id and r["guild_id"] == guild.id
    )

    resp = await client.post(
        "/api/v1/settings/oidc-mappings",
        json={
            "claim_value": "eng-team",
            "target_type": "initiative",
            "guild_id": guild.id,
            "guild_role": "member",
            "initiative_id": initiative.id,
            "initiative_role_id": role["id"],
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Denormalized names are resolved from the guild schema for display.
    assert body["initiative_name"] == initiative.name
    assert body["initiative_role_name"] == role["name"]


# The whole OIDC claim-mapping surface reads/writes guild-scoped data through the
# system admin engine, so the ONLY thing standing between a caller and every
# guild's data is the owner-only ``config.manage`` capability gate. These tests
# hard-pin that gate per endpoint so a future edit can't silently drop it and let
# a non-owner (even a platform admin) through.
_NON_OWNER_ROLES = [
    UserRole.member,
    UserRole.support,
    UserRole.moderator,
    UserRole.admin,
]


@pytest.mark.integration
@pytest.mark.parametrize("role", _NON_OWNER_ROLES)
async def test_oidc_mapping_endpoints_reject_non_owner(
    client: AsyncClient,
    session: AsyncSession,
    role: UserRole,
) -> None:
    """Every OIDC claim-mapping endpoint is owner-only (config.manage). No other
    platform tier — not even ``admin`` — may read or write them."""
    user = await create_user(
        session, email=f"oidc-deny-{role.value}@example.com", role=role
    )
    headers = get_auth_headers(user)

    # Every route on the surface, covering each HTTP method/verb.
    requests = [
        ("get", "/api/v1/settings/oidc-mappings", None),
        ("get", "/api/v1/settings/oidc-mappings/options", None),
        (
            "post",
            "/api/v1/settings/oidc-mappings",
            {
                "claim_value": "x",
                "target_type": "guild",
                "guild_id": 1,
                "guild_role": "member",
            },
        ),
        ("put", "/api/v1/settings/oidc-mappings/claim-path", {"claim_path": "groups"}),
        ("put", "/api/v1/settings/oidc-mappings/1", {"claim_value": "x"}),
        ("delete", "/api/v1/settings/oidc-mappings/1", None),
    ]
    for method, url, json_body in requests:
        resp = await getattr(client, method)(
            url, headers=headers, **({"json": json_body} if json_body else {})
        )
        # 403 (capability denied) before any handler logic runs — never 200/201/204,
        # and never a 400/404 that would imply the request reached the handler.
        assert resp.status_code == 403, (
            f"{method.upper()} {url} as {role.value}: {resp.status_code}"
        )
        assert resp.json()["detail"] == "INSUFFICIENT_PRIVILEGES"


@pytest.mark.integration
async def test_oidc_mapping_endpoints_require_authentication(
    client: AsyncClient,
) -> None:
    """Unauthenticated callers are rejected outright (401), never reaching the
    admin-engine handlers."""
    for method, url in [
        ("get", "/api/v1/settings/oidc-mappings"),
        ("get", "/api/v1/settings/oidc-mappings/options"),
        ("delete", "/api/v1/settings/oidc-mappings/1"),
    ]:
        resp = await getattr(client, method)(url)
        assert resp.status_code == 401, f"{method.upper()} {url}: {resp.status_code}"


# --- Guild storage limits (platform settings → Guilds tab) -----------------


@pytest.mark.integration
async def test_list_guild_storage_returns_all_guilds(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """The Guilds tab lists every guild (not just the operator's own) with its
    member count and current storage cap."""
    owner = await create_user(
        session, email="owner-gstor-list@example.com", role=UserRole.owner
    )
    capped = await create_guild(
        session, creator=owner, name="Capped Guild", max_storage_bytes=1024
    )
    await create_guild_membership(
        session, user=owner, guild=capped, role=GuildRole.admin
    )
    uncapped = await create_guild(session, creator=owner, name="Uncapped Guild")

    resp = await client.get("/api/v1/settings/guilds", headers=get_auth_headers(owner))
    assert resp.status_code == 200
    rows = {row["name"]: row for row in resp.json()}

    assert rows["Capped Guild"]["id"] == capped.id
    assert rows["Capped Guild"]["max_storage_bytes"] == 1024
    assert rows["Capped Guild"]["member_count"] == 1
    # An unlimited guild reports null, and no membership rows -> 0 members.
    assert rows["Uncapped Guild"]["id"] == uncapped.id
    assert rows["Uncapped Guild"]["max_storage_bytes"] is None
    assert rows["Uncapped Guild"]["member_count"] == 0


@pytest.mark.integration
async def test_update_guild_storage_sets_and_clears_limit(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """An operator can cap a guild and later switch it back to unlimited (null)."""
    owner = await create_user(
        session, email="owner-gstor-upd@example.com", role=UserRole.owner
    )
    guild = await create_guild(session, creator=owner)
    headers = get_auth_headers(owner)

    set_resp = await client.patch(
        f"/api/v1/settings/guilds/{guild.id}",
        json={"max_storage_bytes": 5_000_000},
        headers=headers,
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["max_storage_bytes"] == 5_000_000

    clear_resp = await client.patch(
        f"/api/v1/settings/guilds/{guild.id}",
        json={"max_storage_bytes": None},
        headers=headers,
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json()["max_storage_bytes"] is None


@pytest.mark.integration
async def test_update_guild_storage_rejects_negative_limit(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    owner = await create_user(
        session, email="owner-gstor-neg@example.com", role=UserRole.owner
    )
    guild = await create_guild(session, creator=owner)

    resp = await client.patch(
        f"/api/v1/settings/guilds/{guild.id}",
        json={"max_storage_bytes": -1},
        headers=get_auth_headers(owner),
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_update_guild_storage_unknown_guild_returns_404(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    owner = await create_user(
        session, email="owner-gstor-404@example.com", role=UserRole.owner
    )
    resp = await client.patch(
        "/api/v1/settings/guilds/999999",
        json={"max_storage_bytes": 1024},
        headers=get_auth_headers(owner),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "SETTINGS_GUILD_NOT_FOUND"


# The Guilds tab moved from Platform settings (owner-only) to the Admin
# dashboard, so it now gates on ``guilds.manage`` — held by admin *and* owner.
_BELOW_ADMIN_ROLES = [UserRole.member, UserRole.support, UserRole.moderator]


@pytest.mark.integration
async def test_guild_storage_endpoints_allow_admin(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """A platform ``admin`` (guilds.manage) can list guilds and set a storage
    cap from the Admin dashboard Guilds tab."""
    admin = await create_user(
        session, email="gstor-admin@example.com", role=UserRole.admin
    )
    guild = await create_guild(session, creator=admin)
    headers = get_auth_headers(admin)

    list_resp = await client.get("/api/v1/settings/guilds", headers=headers)
    assert list_resp.status_code == 200

    patch_resp = await client.patch(
        f"/api/v1/settings/guilds/{guild.id}",
        json={"max_storage_bytes": 1024},
        headers=headers,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["max_storage_bytes"] == 1024


@pytest.mark.integration
@pytest.mark.parametrize("role", _BELOW_ADMIN_ROLES)
async def test_guild_storage_endpoints_reject_below_admin(
    client: AsyncClient,
    session: AsyncSession,
    role: UserRole,
) -> None:
    """The Guilds tab gates on ``guilds.manage``. No tier below ``admin`` —
    member, support, or moderator — may list guilds or change a storage cap."""
    user = await create_user(
        session, email=f"gstor-deny-{role.value}@example.com", role=role
    )
    guild = await create_guild(session, creator=user)
    headers = get_auth_headers(user)

    for method, url, json_body in [
        ("get", "/api/v1/settings/guilds", None),
        ("patch", f"/api/v1/settings/guilds/{guild.id}", {"max_storage_bytes": 1024}),
    ]:
        resp = await getattr(client, method)(
            url, headers=headers, **({"json": json_body} if json_body else {})
        )
        assert resp.status_code == 403, (
            f"{method.upper()} {url} as {role.value}: {resp.status_code}"
        )
        assert resp.json()["detail"] == "INSUFFICIENT_PRIVILEGES"

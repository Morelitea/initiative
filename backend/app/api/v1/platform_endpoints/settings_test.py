"""Tests for the settings endpoints.

Currently focused on the SMTP test-email error path (pentest SEC-16): a failed
delivery must return a generic machine-readable code, never the raw SMTP
exception (which can carry the mail host, port, or server banner).
"""

from __future__ import annotations

import logging

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole, GuildStatus
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
async def test_list_guild_storage_returns_max_users(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """The Guilds tab reports each guild's user cap (null = unlimited) alongside
    its member count, for the ``3/unlimited`` display."""
    owner = await create_user(
        session, email="owner-gusers-list@example.com", role=UserRole.owner
    )
    capped = await create_guild(
        session, creator=owner, name="Seat-Capped Guild", max_users=10
    )
    await create_guild_membership(
        session, user=owner, guild=capped, role=GuildRole.admin
    )
    await create_guild(session, creator=owner, name="Open Guild")

    resp = await client.get("/api/v1/settings/guilds", headers=get_auth_headers(owner))
    assert resp.status_code == 200
    rows = {row["name"]: row for row in resp.json()}

    assert rows["Seat-Capped Guild"]["max_users"] == 10
    assert rows["Seat-Capped Guild"]["member_count"] == 1
    assert rows["Open Guild"]["max_users"] is None
    assert rows["Open Guild"]["member_count"] == 0


@pytest.mark.integration
async def test_update_guild_users_sets_and_clears_limit(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """An operator can cap a guild's users and later switch it back to unlimited."""
    owner = await create_user(
        session, email="owner-gusers-upd@example.com", role=UserRole.owner
    )
    guild = await create_guild(session, creator=owner)
    headers = get_auth_headers(owner)

    set_resp = await client.patch(
        f"/api/v1/settings/guilds/{guild.id}",
        json={"max_users": 25},
        headers=headers,
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["max_users"] == 25

    clear_resp = await client.patch(
        f"/api/v1/settings/guilds/{guild.id}",
        json={"max_users": None},
        headers=headers,
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json()["max_users"] is None


@pytest.mark.integration
async def test_update_guild_caps_are_independent(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """A PATCH touching only one cap leaves the other untouched (the endpoint
    keys off ``model_fields_set``)."""
    owner = await create_user(
        session, email="owner-gcaps-indep@example.com", role=UserRole.owner
    )
    guild = await create_guild(
        session, creator=owner, max_storage_bytes=2048, max_users=5
    )
    headers = get_auth_headers(owner)

    # Update only the user cap: storage must survive.
    resp = await client.patch(
        f"/api/v1/settings/guilds/{guild.id}",
        json={"max_users": 9},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["max_users"] == 9
    assert resp.json()["max_storage_bytes"] == 2048

    # Update only storage: the user cap must survive.
    resp = await client.patch(
        f"/api/v1/settings/guilds/{guild.id}",
        json={"max_storage_bytes": 4096},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["max_storage_bytes"] == 4096
    assert resp.json()["max_users"] == 9


# --- Guild lifecycle status (platform settings → Guilds tab) ---------------


@pytest.mark.integration
async def test_list_guild_storage_includes_status(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """The Guilds tab surfaces each guild's lifecycle status (default active)."""
    owner = await create_user(
        session, email="owner-gstatus-list@example.com", role=UserRole.owner
    )
    guild = await create_guild(session, creator=owner, name="Status Guild")

    resp = await client.get("/api/v1/settings/guilds", headers=get_auth_headers(owner))
    assert resp.status_code == 200
    row = {r["name"]: r for r in resp.json()}["Status Guild"]
    assert row["id"] == guild.id
    assert row["status"] == GuildStatus.active.value
    assert row["status_changed_at"] is None


@pytest.mark.integration
async def test_operator_sets_and_clears_guild_status(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """An operator can suspend a guild and reactivate it; a real transition
    stamps status_changed_at."""
    owner = await create_user(
        session, email="owner-gstatus-upd@example.com", role=UserRole.owner
    )
    guild = await create_guild(session, creator=owner)
    headers = get_auth_headers(owner)

    resp = await client.patch(
        f"/api/v1/settings/guilds/{guild.id}",
        json={"status": "suspended"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "suspended"
    assert resp.json()["status_changed_at"] is not None

    resp = await client.patch(
        f"/api/v1/settings/guilds/{guild.id}",
        json={"status": "read_only"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "read_only"

    resp = await client.patch(
        f"/api/v1/settings/guilds/{guild.id}",
        json={"status": "active"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


@pytest.mark.integration
async def test_guild_status_rejects_unknown_value(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """An unknown status value is a 422 (validated against GuildStatus)."""
    owner = await create_user(
        session, email="owner-gstatus-bad@example.com", role=UserRole.owner
    )
    guild = await create_guild(session, creator=owner)

    resp = await client.patch(
        f"/api/v1/settings/guilds/{guild.id}",
        json={"status": "deleted"},
        headers=get_auth_headers(owner),
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_status_and_caps_are_independent(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Status and caps use omit-to-skip: touching one leaves the other alone."""
    owner = await create_user(
        session, email="owner-gstatus-indep@example.com", role=UserRole.owner
    )
    guild = await create_guild(session, creator=owner, max_users=5)
    headers = get_auth_headers(owner)

    # Set only status: the cap survives.
    resp = await client.patch(
        f"/api/v1/settings/guilds/{guild.id}",
        json={"status": "read_only"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "read_only"
    assert resp.json()["max_users"] == 5

    # Set only a cap: the status survives.
    resp = await client.patch(
        f"/api/v1/settings/guilds/{guild.id}",
        json={"max_users": 9},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["max_users"] == 9
    assert resp.json()["status"] == "read_only"


@pytest.mark.integration
async def test_non_privileged_user_cannot_set_guild_status(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Setting status requires guilds.manage (admin/owner) — a plain member 403s."""
    member = await create_user(
        session, email="member-gstatus@example.com", role=UserRole.member
    )
    owner = await create_user(
        session, email="owner-gstatus-gate@example.com", role=UserRole.owner
    )
    guild = await create_guild(session, creator=owner)

    resp = await client.patch(
        f"/api/v1/settings/guilds/{guild.id}",
        json={"status": "suspended"},
        headers=get_auth_headers(member),
    )
    assert resp.status_code == 403


@pytest.mark.integration
async def test_update_guild_users_rejects_zero(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """A cap of 0 is nonsensical (a guild always has at least its creator) and is
    rejected by validation (``ge=1``)."""
    owner = await create_user(
        session, email="owner-gusers-zero@example.com", role=UserRole.owner
    )
    guild = await create_guild(session, creator=owner)

    resp = await client.patch(
        f"/api/v1/settings/guilds/{guild.id}",
        json={"max_users": 0},
        headers=get_auth_headers(owner),
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_lowering_cap_below_count_keeps_members_and_blocks_join(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Lowering the cap under the current headcount is allowed: it never removes
    existing members, it only blocks the next join. End-to-end across the
    settings PATCH and invite-accept endpoints."""
    from app.services.platform import guilds as guild_service

    owner = await create_user(
        session, email="owner-lower@example.com", role=UserRole.owner
    )
    guild = await create_guild(session, creator=owner)
    other = await create_user(session, email="lower-other@example.com")
    await guild_service.ensure_membership(
        session, guild_id=guild.id, user_id=owner.id, role=GuildRole.admin
    )
    await guild_service.ensure_membership(
        session, guild_id=guild.id, user_id=other.id, role=GuildRole.member
    )
    invitee = await create_user(session, email="lower-invitee@example.com")
    invite = await guild_service.create_guild_invite(
        session, guild_id=guild.id, created_by_user_id=owner.id, max_uses=5
    )
    await session.commit()
    headers = get_auth_headers(owner)

    # Cap 1 is below the current 2 members — accepted, and both members stay.
    patch = await client.patch(
        f"/api/v1/settings/guilds/{guild.id}",
        json={"max_users": 1},
        headers=headers,
    )
    assert patch.status_code == 200
    assert patch.json()["max_users"] == 1
    assert patch.json()["member_count"] == 2

    # But the guild is now over its cap, so a new join is refused.
    accept = await client.post(
        "/api/v1/guilds/invite/accept",
        headers=get_auth_headers(invitee),
        json={"code": invite.code},
    )
    assert accept.status_code == 403
    assert accept.json()["detail"] == "GUILD_USER_LIMIT_REACHED"


@pytest.mark.integration
async def test_raising_cap_reopens_joins(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """A full guild blocks joins; raising the cap lets the same invite through."""
    from app.services.platform import guilds as guild_service

    owner = await create_user(
        session, email="owner-raise@example.com", role=UserRole.owner
    )
    guild = await create_guild(session, creator=owner, max_users=1)
    await guild_service.ensure_membership(
        session, guild_id=guild.id, user_id=owner.id, role=GuildRole.admin
    )
    invitee = await create_user(session, email="raise-invitee@example.com")
    invite = await guild_service.create_guild_invite(
        session, guild_id=guild.id, created_by_user_id=owner.id, max_uses=5
    )
    await session.commit()
    headers = get_auth_headers(owner)

    # Full (1/1) — the invite is refused, and it is NOT consumed (the cap check
    # runs before the invite's use count is incremented).
    blocked = await client.post(
        "/api/v1/guilds/invite/accept",
        headers=get_auth_headers(invitee),
        json={"code": invite.code},
    )
    assert blocked.status_code == 403

    # Raise the cap, then the very same invite succeeds.
    patch = await client.patch(
        f"/api/v1/settings/guilds/{guild.id}",
        json={"max_users": 5},
        headers=headers,
    )
    assert patch.status_code == 200

    accepted = await client.post(
        "/api/v1/guilds/invite/accept",
        headers=get_auth_headers(invitee),
        json={"code": invite.code},
    )
    assert accepted.status_code == 200
    assert accepted.json()["max_users"] == 5


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


# --- Object storage (platform settings → Storage tab) ----------------------


@pytest.fixture
def reset_storage_cache():
    """Keep the process-wide storage-config snapshot from leaking across tests:
    a test that saves an ``s3`` backend would otherwise route a later upload
    test's writes at a non-existent bucket."""
    from app.services import storage_config

    storage_config.reset_for_tests()
    yield
    storage_config.reset_for_tests()


_S3_PAYLOAD = {
    "backend": "s3",
    "s3_bucket": "my-bucket",
    "s3_region": "eu-west-1",
    "s3_endpoint_url": "https://s3.example.com",
    "s3_access_key_id": "AKIAEXAMPLE",
    "s3_secret_access_key": "super-secret-value",
    "s3_use_path_style": True,
    "s3_kms_key_id": None,
    "s3_local_fallback": True,
}


@pytest.mark.integration
async def test_storage_settings_round_trip_never_returns_secret(
    client: AsyncClient,
    session: AsyncSession,
    reset_storage_cache: None,
) -> None:
    """PUT saves S3 config; GET reflects it but never echoes the secret (only a
    ``has_secret_access_key`` flag). The secret is persisted encrypted."""
    owner = await create_user(
        session, email="owner-storage-rt@example.com", role=UserRole.owner
    )
    headers = get_auth_headers(owner)

    put = await client.put(
        "/api/v1/settings/storage", json=_S3_PAYLOAD, headers=headers
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["backend"] == "s3"
    assert body["s3_bucket"] == "my-bucket"
    assert body["s3_region"] == "eu-west-1"
    assert body["s3_use_path_style"] is True
    assert body["s3_local_fallback"] is True
    assert body["has_secret_access_key"] is True
    # The plaintext secret must never appear in any response.
    assert "super-secret-value" not in put.text
    assert "s3_secret_access_key" not in body

    get = await client.get("/api/v1/settings/storage", headers=headers)
    assert get.status_code == 200
    assert get.json()["s3_bucket"] == "my-bucket"
    assert get.json()["has_secret_access_key"] is True
    assert "super-secret-value" not in get.text

    # Stored encrypted, and decrypts back to the original.
    from app.core.encryption import SALT_S3_SECRET_KEY, decrypt_field
    from app.services.platform.app_settings import get_app_settings

    row = await get_app_settings(session, force_refresh=True)
    assert row.s3_secret_access_key_encrypted
    assert row.s3_secret_access_key_encrypted != "super-secret-value"
    assert (
        decrypt_field(row.s3_secret_access_key_encrypted, SALT_S3_SECRET_KEY)
        == "super-secret-value"
    )


@pytest.mark.integration
async def test_storage_update_keeps_secret_when_omitted(
    client: AsyncClient,
    session: AsyncSession,
    reset_storage_cache: None,
) -> None:
    """Re-saving without ``s3_secret_access_key`` keeps the stored key (the SMTP
    password pattern), so an admin can tweak the bucket without re-typing it."""
    owner = await create_user(
        session, email="owner-storage-keep@example.com", role=UserRole.owner
    )
    headers = get_auth_headers(owner)

    assert (
        await client.put("/api/v1/settings/storage", json=_S3_PAYLOAD, headers=headers)
    ).status_code == 200

    no_secret = {k: v for k, v in _S3_PAYLOAD.items() if k != "s3_secret_access_key"}
    no_secret["s3_bucket"] = "renamed-bucket"
    resp = await client.put("/api/v1/settings/storage", json=no_secret, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["s3_bucket"] == "renamed-bucket"
    assert resp.json()["has_secret_access_key"] is True

    from app.core.encryption import SALT_S3_SECRET_KEY, decrypt_field
    from app.services.platform.app_settings import get_app_settings

    row = await get_app_settings(session, force_refresh=True)
    assert (
        decrypt_field(row.s3_secret_access_key_encrypted, SALT_S3_SECRET_KEY)
        == "super-secret-value"
    )


@pytest.mark.integration
async def test_storage_clearing_a_field_does_not_revert_to_env(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    reset_storage_cache: None,
) -> None:
    """An owner clearing an S3 field must stay cleared even when the matching
    ``S3_*`` env var is still set — the DB is authoritative once saved (env only
    seeds the first-run/migrated row, never re-seeds on read)."""
    from app.core.config import settings as app_config

    monkeypatch.setattr(app_config, "S3_BUCKET", "env-bucket", raising=False)
    owner = await create_user(
        session, email="owner-storage-clear@example.com", role=UserRole.owner
    )
    headers = get_auth_headers(owner)

    assert (
        await client.put("/api/v1/settings/storage", json=_S3_PAYLOAD, headers=headers)
    ).status_code == 200

    cleared = {**_S3_PAYLOAD, "s3_bucket": None}
    resp = await client.put("/api/v1/settings/storage", json=cleared, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["s3_bucket"] is None  # NOT re-seeded to "env-bucket"

    get = await client.get("/api/v1/settings/storage", headers=headers)
    assert get.json()["s3_bucket"] is None


@pytest.mark.integration
async def test_storage_update_refreshes_process_config(
    client: AsyncClient,
    session: AsyncSession,
    reset_storage_cache: None,
) -> None:
    """Saving updates the live process snapshot so the request path uses the new
    backend without a restart."""
    owner = await create_user(
        session, email="owner-storage-cache@example.com", role=UserRole.owner
    )
    resp = await client.put(
        "/api/v1/settings/storage", json=_S3_PAYLOAD, headers=get_auth_headers(owner)
    )
    assert resp.status_code == 200

    from app.services import storage_config

    cfg = storage_config.current_storage_config()
    assert cfg.backend == "s3"
    assert cfg.bucket == "my-bucket"
    assert cfg.secret_access_key == "super-secret-value"
    assert cfg.use_path_style is True


@pytest.mark.integration
async def test_storage_backfill_requires_bucket(
    client: AsyncClient,
    session: AsyncSession,
    reset_storage_cache: None,
) -> None:
    """The backfill writes to S3, so it needs a bucket configured first."""
    owner = await create_user(
        session, email="owner-storage-bf@example.com", role=UserRole.owner
    )
    resp = await client.post(
        "/api/v1/settings/storage/backfill", headers=get_auth_headers(owner)
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "SETTINGS_STORAGE_BACKFILL_NOT_CONFIGURED"


@pytest.mark.integration
async def test_storage_backfill_status_reads_shared_row(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """GET status returns the shared UNLOGGED-table row (idle by default), so
    every worker reports the same thing rather than its own in-memory guess."""
    from app.services import storage_backfill

    # The UNLOGGED status row persists across tests within a worker; clear it so a
    # prior test's terminal status doesn't bleed into this fresh-state assertion.
    await storage_backfill._ensure_table()
    await session.exec(text("DELETE FROM storage_backfill_state"))
    await session.commit()

    owner = await create_user(
        session, email="owner-storage-bfstatus@example.com", role=UserRole.owner
    )
    resp = await client.get(
        "/api/v1/settings/storage/backfill", headers=get_auth_headers(owner)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "idle"
    assert body["copied"] == 0


@pytest.mark.integration
@pytest.mark.parametrize("role", _NON_OWNER_ROLES)
async def test_storage_endpoints_reject_non_owner(
    client: AsyncClient,
    session: AsyncSession,
    role: UserRole,
    reset_storage_cache: None,
) -> None:
    """Every storage endpoint is owner-only (config.manage)."""
    user = await create_user(
        session, email=f"storage-deny-{role.value}@example.com", role=role
    )
    headers = get_auth_headers(user)

    requests = [
        ("get", "/api/v1/settings/storage", None),
        ("put", "/api/v1/settings/storage", {"backend": "local"}),
        ("post", "/api/v1/settings/storage/test", {"backend": "local"}),
        ("post", "/api/v1/settings/storage/backfill", None),
        ("get", "/api/v1/settings/storage/backfill", None),
    ]
    for method, url, json_body in requests:
        resp = await getattr(client, method)(
            url, headers=headers, **({"json": json_body} if json_body else {})
        )
        assert resp.status_code == 403, (
            f"{method.upper()} {url} as {role.value}: {resp.status_code}"
        )
        assert resp.json()["detail"] == "INSUFFICIENT_PRIVILEGES"


# --- auth scope (platform-wide vs guild-scoped login) -------------------------


async def _configure_platform_oidc(client: AsyncClient, headers: dict) -> None:
    resp = await client.put(
        "/api/v1/settings/auth",
        json={
            "enabled": True,
            "issuer": "https://idp.example.com",
            "client_id": "client-123",
            "client_secret": "s3cret",
            "provider_name": "Okta",
            "scopes": ["openid", "email"],
        },
        headers=headers,
    )
    assert resp.status_code == 200


@pytest.mark.integration
async def test_auth_scope_defaults_to_platform(
    client: AsyncClient, session: AsyncSession
) -> None:
    owner = await create_user(session, role=UserRole.owner)

    resp = await client.get("/api/v1/settings/auth", headers=get_auth_headers(owner))
    assert resp.status_code == 200
    assert resp.json()["auth_scope"] == "platform"

    # Non-secret posture info is readable without config.manage (login page,
    # guild settings) via the interface settings.
    resp = await client.get("/api/v1/settings/interface")
    assert resp.status_code == 200
    assert resp.json()["auth_scope"] == "platform"


@pytest.mark.integration
async def test_auth_scope_switch_is_non_destructive(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Switching postures never touches the dormant side's configuration —
    switching back restores platform OIDC exactly."""
    owner = await create_user(session, role=UserRole.owner)
    headers = get_auth_headers(owner)
    await _configure_platform_oidc(client, headers)

    status_resp = await client.get("/api/v1/auth/oidc/status")
    assert status_resp.json()["enabled"] is True

    # Switch to guild scope: OIDC config is retained but the login goes dormant.
    resp = await client.put(
        "/api/v1/settings/auth-scope", json={"scope": "guild"}, headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_scope"] == "guild"
    assert body["enabled"] is True  # stored config untouched...
    assert body["issuer"] == "https://idp.example.com"
    status_resp = await client.get("/api/v1/auth/oidc/status")
    assert status_resp.json()["enabled"] is False  # ...but not offered

    # Switch back: everything as before.
    resp = await client.put(
        "/api/v1/settings/auth-scope", json={"scope": "platform"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["auth_scope"] == "platform"
    status_resp = await client.get("/api/v1/auth/oidc/status")
    assert status_resp.json()["enabled"] is True


@pytest.mark.integration
async def test_guild_scope_refuses_platform_oidc_login(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Server-side enforcement: in guild scope the dormant platform provider
    must not authenticate anyone, regardless of what a client requests."""
    owner = await create_user(session, role=UserRole.owner)
    headers = get_auth_headers(owner)
    await _configure_platform_oidc(client, headers)
    resp = await client.put(
        "/api/v1/settings/auth-scope", json={"scope": "guild"}, headers=headers
    )
    assert resp.status_code == 200

    login_resp = await client.get("/api/v1/auth/oidc/login")
    assert login_resp.status_code == 404
    assert login_resp.json()["detail"] == "OIDC_NOT_ENABLED"


@pytest.mark.integration
async def test_auth_scope_rejects_unknown_value(
    client: AsyncClient, session: AsyncSession
) -> None:
    owner = await create_user(session, role=UserRole.owner)
    resp = await client.put(
        "/api/v1/settings/auth-scope",
        json={"scope": "both"},
        headers=get_auth_headers(owner),
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_auth_scope_requires_config_manage(
    client: AsyncClient, session: AsyncSession
) -> None:
    member = await create_user(session, role=UserRole.member)
    resp = await client.put(
        "/api/v1/settings/auth-scope",
        json={"scope": "guild"},
        headers=get_auth_headers(member),
    )
    assert resp.status_code == 403


@pytest.mark.integration
async def test_auth_scope_check_constraint_rejects_garbage(
    session: AsyncSession,
) -> None:
    """The posture gate compares literally, so an out-of-vocabulary value would
    silently disable login — the DB CHECK refuses it even for a privileged
    writer that bypasses the API schema. (INSERT, not UPDATE: the settings
    singleton may not exist yet, and a zero-row UPDATE never fires the check.)"""
    with pytest.raises(DBAPIError):
        async with session.begin_nested():
            await session.exec(
                text(
                    "INSERT INTO app_settings (id, oidc_enabled, auth_scope) "
                    "VALUES (999, false, 'both')"
                )
            )

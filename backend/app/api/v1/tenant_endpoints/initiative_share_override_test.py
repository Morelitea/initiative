"""Tests for the initiative "Full access" share-override (PM-only).

A guild admin can set ``override_share_restrictions`` on the built-in
``project_manager`` role; members with that role then view/edit ALL content in
the initiative regardless of per-item sharing, and may manage sharing — the
gate-4 (DAC) override, scoped to one initiative (the initiative-scoped sibling of
the guild-admin override). Only a guild admin may set it, and only on the PM
role. See history/initiative-admin-override-design.md.
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.pam_context import set_active_grant
from app.core.role_context import (
    set_active_role,
    set_override_sharing_initiatives,
)
from app.models.platform.guild import GuildRole
from app.models.tenant.initiative import InitiativeRoleModel
from app.services.permissions import (
    DAC_RESOURCES,
    compute_permission,
    request_bypasses_dac,
)


async def _role_by_name(session: AsyncSession, initiative, name: str):
    return (
        await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == initiative.id,
                InitiativeRoleModel.name == name,
            )
        )
    ).one()


async def _setup(session: AsyncSession, acting_user):
    """admin = guild admin + initiative creator (PM); owner = a PM who owns a
    restricted project; pm = a PM whose access we toggle via the override."""
    admin = await acting_user(
        guild_role=GuildRole.admin, initiative=True, email="admin@example.com"
    )
    initiative = admin.initiative  # admin -> PM
    owner = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=initiative,
        initiative_role="project_manager",
        email="owner@example.com",
    )
    pm = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=initiative,
        initiative_role="project_manager",
        email="pm@example.com",
    )
    return admin, owner, pm, admin.guild, initiative


# ── Enforcement: the gate-4 override leg (unit) ──────────────────────────────


def test_request_overrides_sharing_bypasses_dac():
    """A "Full access" initiative bypasses DAC (incl. owner-only ops), scoped to
    that initiative; compute_permission reports owner there and nothing extra
    elsewhere."""
    set_active_role(None, None)
    set_active_grant(None, None)
    set_override_sharing_initiatives(frozenset({42}))

    class _Row:
        def __init__(self, guild_id, initiative_id):
            self.guild_id = guild_id
            self.initiative_id = initiative_id
            self.grants = []
            self.initiative = None

    try:
        assert request_bypasses_dac(1, initiative_id=42, access="write") is True
        # Ignores require_owner — a full-access PM may manage sharing.
        assert (
            request_bypasses_dac(
                1, initiative_id=42, access="write", require_owner=True
            )
            is True
        )
        # Scope-bound: a different initiative is not covered.
        assert request_bypasses_dac(1, initiative_id=99, access="write") is False
        assert (
            compute_permission(DAC_RESOURCES["project"], _Row(1, 42), user_id=7)
            == "owner"
        )
        assert (
            compute_permission(DAC_RESOURCES["project"], _Row(1, 99), user_id=7)
            != "owner"
        )
    finally:
        set_override_sharing_initiatives(None)


# ── Enforcement: end-to-end through the API (integration) ────────────────────


@pytest.mark.integration
async def test_full_access_pm_reaches_restricted_content(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin, owner, pm, guild, initiative = await _setup(session, acting_user)
    admin_headers = admin.headers
    owner_headers = owner.headers
    pm_headers = pm.headers

    # owner (a PM/manager) creates a RESTRICTED project: grants=[] drops the
    # default all-members Viewer grant, so only the owner can reach it.
    resp = await client.post(
        f"/api/v1/g/{guild.id}/projects/",
        headers=owner_headers,
        json={"name": "Secret", "initiative_id": initiative.id, "grants": []},
    )
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["id"]

    # Before the override: pm holds the PM role (a manager) but has no grant on
    # this project — manager status is gate-3, not a DAC bypass — so 403.
    resp = await client.get(
        f"/api/v1/g/{guild.id}/projects/{project_id}", headers=pm_headers
    )
    assert resp.status_code == 403

    # Guild admin grants the PM role "Full access".
    pm_role = await _role_by_name(session, initiative, "project_manager")
    resp = await client.patch(
        f"/api/v1/g/{guild.id}/initiatives/{initiative.id}/roles/{pm_role.id}",
        headers=admin_headers,
        json={"override_share_restrictions": True},
    )
    assert resp.status_code == 200
    assert resp.json()["override_share_restrictions"] is True

    # After the override: pm can read, edit content, and manage sharing.
    resp = await client.get(
        f"/api/v1/g/{guild.id}/projects/{project_id}", headers=pm_headers
    )
    assert resp.status_code == 200

    resp = await client.patch(
        f"/api/v1/g/{guild.id}/projects/{project_id}",
        headers=pm_headers,
        json={"name": "Renamed by full-access PM"},
    )
    assert resp.status_code == 200

    resp = await client.put(
        f"/api/v1/g/{guild.id}/projects/{project_id}/grants",
        headers=pm_headers,
        json=[{"all_initiative_members": True, "level": "read"}],
    )
    assert resp.status_code == 200

    # my-permissions reflects the capability for the client.
    resp = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/{initiative.id}/my-permissions",
        headers=pm_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["override_share_restrictions"] is True


# ── Setting the flag: guild-admin-only + PM-only (no self-escalation) ─────────


@pytest.mark.integration
async def test_only_guild_admin_can_grant_full_access(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin, owner, pm, guild, initiative = await _setup(session, acting_user)
    pm_headers = pm.headers
    pm_role = await _role_by_name(session, initiative, "project_manager")

    # pm is an initiative manager (can edit roles) but NOT a guild admin — it must
    # not be able to flip the override on its own role (self-escalation).
    resp = await client.patch(
        f"/api/v1/g/{guild.id}/initiatives/{initiative.id}/roles/{pm_role.id}",
        headers=pm_headers,
        json={"override_share_restrictions": True},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "INITIATIVE_OVERRIDE_REQUIRES_GUILD_ADMIN"


@pytest.mark.integration
async def test_full_access_only_on_pm_role(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin, owner, pm, guild, initiative = await _setup(session, acting_user)
    admin_headers = admin.headers

    # The built-in "member" role is ineligible — 422.
    member_role = await _role_by_name(session, initiative, "member")
    resp = await client.patch(
        f"/api/v1/g/{guild.id}/initiatives/{initiative.id}/roles/{member_role.id}",
        headers=admin_headers,
        json={"override_share_restrictions": True},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "INITIATIVE_OVERRIDE_PM_ONLY"

    # A custom manager role is also ineligible — Full access is PM-only.
    resp = await client.post(
        f"/api/v1/g/{guild.id}/initiatives/{initiative.id}/roles",
        headers=admin_headers,
        json={"name": "leads", "display_name": "Leads", "is_manager": True},
    )
    assert resp.status_code == 201, resp.text
    custom_role_id = resp.json()["id"]
    resp = await client.patch(
        f"/api/v1/g/{guild.id}/initiatives/{initiative.id}/roles/{custom_role_id}",
        headers=admin_headers,
        json={"override_share_restrictions": True},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "INITIATIVE_OVERRIDE_PM_ONLY"

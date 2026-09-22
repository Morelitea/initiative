"""Tests for the initiative "Full access" share-override (the moderator role).

Every initiative has a built-in ``moderator`` role carrying
``override_share_restrictions``: members holding it view/edit ALL content in the
initiative regardless of per-item sharing, and may manage sharing — the gate-4
(DAC) override, scoped to one initiative (the initiative-scoped sibling of the
guild-admin override). A guild admin is the one who puts somebody on it, and a
guild admin joining an initiative lands on it. See
history/initiative-admin-override-design.md.
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.guild_standing import GuildContext
from app.models.platform.guild import Guild, GuildRole
from app.models.tenant.initiative import (
    Initiative,
    InitiativeMember,
    InitiativeRoleModel,
)
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


async def _role_of(session: AsyncSession, initiative, user) -> InitiativeRoleModel:
    membership = (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == initiative.id,
                InitiativeMember.user_id == user.id,
            )
        )
    ).one()
    role = await session.get(InitiativeRoleModel, membership.role_id)
    assert role is not None
    return role


async def _setup(session: AsyncSession, acting_user):
    """admin = guild admin + initiative creator; owner = a PM who owns a
    restricted project; pm = a second PM, the one moved onto moderator."""
    admin = await acting_user(
        guild_role=GuildRole.admin, initiative=True, email="admin@example.com"
    )
    initiative = admin.initiative
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
    context = GuildContext(
        guild=Guild(id=1, name="g"),
        user_id=7,
        guild_id=1,
        guild_role=GuildRole.member.value,
        standing_guild_id=1,
        override_initiatives=(42,),
    )

    class _Row:
        def __init__(self, guild_id, initiative_id):
            self.guild_id = guild_id
            self.initiative_id = initiative_id
            self.grants = []
            self.initiative = None

    assert request_bypasses_dac(context, initiative_id=42, access="write") is True
    # Ignores require_owner — a moderator may manage sharing.
    assert (
        request_bypasses_dac(
            context, initiative_id=42, access="write", require_owner=True
        )
        is True
    )
    # Scope-bound: a different initiative is not covered.
    assert request_bypasses_dac(context, initiative_id=99, access="write") is False
    assert (
        compute_permission(
            DAC_RESOURCES["project"], _Row(1, 42), user_id=7, context=context
        )
        == "owner"
    )
    assert (
        compute_permission(
            DAC_RESOURCES["project"], _Row(1, 99), user_id=7, context=context
        )
        != "owner"
    )


# ── The built-in roles as created ────────────────────────────────────────────


@pytest.mark.integration
async def test_moderator_holds_full_access_and_project_manager_does_not(
    session: AsyncSession, acting_user
):
    admin, _owner, _pm, _guild, initiative = await _setup(session, acting_user)

    moderator = await _role_by_name(session, initiative, "moderator")
    assert moderator.is_builtin is True
    assert moderator.is_manager is True
    assert moderator.override_share_restrictions is True
    assert moderator.position == 0

    pm_role = await _role_by_name(session, initiative, "project_manager")
    assert pm_role.is_manager is True
    assert pm_role.override_share_restrictions is False


@pytest.mark.integration
async def test_guild_admin_joins_an_initiative_as_moderator(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Every route into an initiative puts a community admin on the moderator
    role — here, the row they write creating one, and the row a project manager
    writes adding them to an existing one."""
    admin, _owner, pm, guild, initiative = await _setup(session, acting_user)

    resp = await client.post(
        f"/api/v1/g/{guild.id}/initiatives/",
        headers=admin.headers,
        json={"name": "Founded by an admin"},
    )
    assert resp.status_code == 201, resp.text
    founded = await session.get(Initiative, resp.json()["id"])
    assert (await _role_of(session, founded, admin.user)).name == "moderator"

    other_admin = await acting_user(
        guild_role=GuildRole.admin, guild=guild, email="other-admin@example.com"
    )
    member_role = await _role_by_name(session, initiative, "member")
    resp = await client.post(
        f"/api/v1/g/{guild.id}/initiatives/{initiative.id}/members",
        headers=pm.headers,
        json={"user_id": other_admin.user.id, "role_id": member_role.id},
    )
    assert resp.status_code == 200, resp.text

    assert (await _role_of(session, initiative, other_admin.user)).name == "moderator"


# ── Enforcement: end-to-end through the API (integration) ────────────────────


@pytest.mark.integration
async def test_moderator_reaches_restricted_content(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin, owner, pm, guild, initiative = await _setup(session, acting_user)

    # owner (a PM/manager) creates a RESTRICTED project: grants=[] drops the
    # default all-members Viewer grant, so only the owner can reach it.
    resp = await client.post(
        f"/api/v1/g/{guild.id}/projects/",
        headers=owner.headers,
        json={"name": "Secret", "initiative_id": initiative.id, "grants": []},
    )
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["id"]

    # As a project manager, pm has no grant on this project — manager status is
    # gate-3, and gate 4 is per item — so 403.
    resp = await client.get(
        f"/api/v1/g/{guild.id}/projects/{project_id}", headers=pm.headers
    )
    assert resp.status_code == 403

    # The guild admin moves pm onto the moderator role.
    moderator = await _role_by_name(session, initiative, "moderator")
    resp = await client.patch(
        f"/api/v1/g/{guild.id}/initiatives/{initiative.id}/members/{pm.user.id}",
        headers=admin.headers,
        json={"role_id": moderator.id},
    )
    assert resp.status_code == 200, resp.text

    # As a moderator: read, edit content, and manage sharing.
    resp = await client.get(
        f"/api/v1/g/{guild.id}/projects/{project_id}", headers=pm.headers
    )
    assert resp.status_code == 200

    resp = await client.patch(
        f"/api/v1/g/{guild.id}/projects/{project_id}",
        headers=pm.headers,
        json={"name": "Renamed by a moderator"},
    )
    assert resp.status_code == 200

    resp = await client.put(
        f"/api/v1/g/{guild.id}/projects/{project_id}/grants",
        headers=pm.headers,
        json=[{"all_initiative_members": True, "level": "read"}],
    )
    assert resp.status_code == 200

    # my-permissions reflects the capability for the client.
    resp = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/{initiative.id}/my-permissions",
        headers=pm.headers,
    )
    assert resp.status_code == 200
    assert resp.json()["override_share_restrictions"] is True


# ── Who may hand out the role ────────────────────────────────────────────────


@pytest.mark.integration
async def test_only_a_guild_admin_puts_a_member_on_the_moderator_role(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A project manager may edit roles and staff the initiative; the one role
    a community admin keeps for themselves is the one carrying Full access."""
    admin, owner, pm, guild, initiative = await _setup(session, acting_user)
    moderator = await _role_by_name(session, initiative, "moderator")

    resp = await client.patch(
        f"/api/v1/g/{guild.id}/initiatives/{initiative.id}/members/{pm.user.id}",
        headers=pm.headers,
        json={"role_id": moderator.id},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "INITIATIVE_OVERRIDE_REQUIRES_GUILD_ADMIN"

    joiner = await acting_user(
        guild_role=GuildRole.member, guild=guild, email="joiner@example.com"
    )
    resp = await client.post(
        f"/api/v1/g/{guild.id}/initiatives/{initiative.id}/members",
        headers=pm.headers,
        json={"user_id": joiner.user.id, "role_id": moderator.id},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "INITIATIVE_OVERRIDE_REQUIRES_GUILD_ADMIN"

    # The same call from a community admin goes through.
    resp = await client.post(
        f"/api/v1/g/{guild.id}/initiatives/{initiative.id}/members",
        headers=admin.headers,
        json={"user_id": joiner.user.id, "role_id": moderator.id},
    )
    assert resp.status_code == 200, resp.text
    assert (await _role_of(session, initiative, joiner.user)).name == "moderator"


@pytest.mark.integration
async def test_moderator_permissions_are_not_editable(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin, _owner, _pm, guild, initiative = await _setup(session, acting_user)
    moderator = await _role_by_name(session, initiative, "moderator")

    resp = await client.patch(
        f"/api/v1/g/{guild.id}/initiatives/{initiative.id}/roles/{moderator.id}",
        headers=admin.headers,
        json={"permissions": {"projects_enabled": False}},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "INITIATIVE_CANNOT_MODIFY_BUILTIN_PERMISSIONS"

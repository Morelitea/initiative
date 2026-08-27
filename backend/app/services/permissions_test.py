"""Tests for Discretionary Access Control (DAC) — the final privilege gate.

Every case here runs against real rows: a real guild schema, a real initiative,
real ``resource_grants``, loaded through the same ``RESOURCE_ACCESS`` loader the
endpoints use. The engine is one registry-driven function, so the cases are
parametrized over ``DAC_RESOURCES`` rather than written once per tool — a tool
added later inherits the coverage by registering.
"""

import pathlib

import pytest
from fastapi import HTTPException
from sqlalchemy import ColumnElement
from sqlmodel import delete, select

from app.api import resource_access
from app.core.pam_context import set_active_grant
from app.core.role_context import (
    set_active_role,
    set_content_read_only_guild,
    set_override_sharing_initiatives,
)
from app.core.tools import Tool
from app.models.platform.guild import GuildRole
from app.models.platform.user import UserRole
from app.models.tenant.document import Document
from app.models.tenant.initiative import InitiativeMember
from app.models.tenant.project import Project
from app.models.tenant.project import ProjectPermissionLevel as PL
from app.models.tenant.queue import Queue
from app.models.tenant.resource_grant import ResourceGrant
from app.services.permissions import (
    DAC_RESOURCES,
    PROJECT_LEVEL_ORDER,
    compute_permission,
    dac_scope_clause,
    effective_permission_level,
    has_project_write_access,
    require_access,
)
from app.testing import factories

# The tools whose rows are gated on initiative membership as well as on grants
# (``scope_gate``); the rest are guild-level and skip that leg.
SCOPE_GATED = [t for t, r in DAC_RESOURCES.items() if r.scope_gate]
ALL_TOOLS = list(DAC_RESOURCES)

_TOOL_FACTORIES = {
    Tool.project: "create_project",
    Tool.document: "create_document",
    Tool.queue: "create_queue",
    Tool.counter_group: "create_counter_group",
    Tool.calendar: "create_calendar",
    Tool.dashboard: "create_dashboard",
}


# ── Building a real world ────────────────────────────────────────────────────


class World:
    """One guild, one initiative, one resource of ``tool``, and four actors."""

    def __init__(self, session, tool, guild, initiative, row, owner, co_member, admin):
        self.session = session
        self.tool = tool
        self.resource = DAC_RESOURCES[tool]
        self.guild = guild
        self.initiative = initiative
        self.row = row
        # Captured once: the tests expire the identity map to force a real
        # re-read, and an expired instance cannot answer for its own id.
        self.row_id = row.id
        self.initiative_id = getattr(row, "initiative_id", None)
        self.owner = owner
        self.co_member = co_member
        self.admin = admin

    async def load(self):
        """Re-read the resource through the loader the endpoints use, so the
        eager-loaded shape under test is production's."""
        loader = resource_access.RESOURCE_ACCESS[self.tool].loader
        assert loader is not None, f"{self.tool.value} has no loader"
        # Expire just the resource: the loader re-reads it with its grants
        # eagerly loaded, and the actors stay usable (expiring them would make
        # every later attribute read a lazy load from sync code).
        self.session.expire(self.row)
        return await loader(self.session, self.row_id)

    async def grant(self, level, *, user=None, role_id=None, everyone=False):
        """Replace the resource's grants with exactly the ones named."""
        await self.session.exec(
            delete(ResourceGrant).where(
                ResourceGrant.resource_type == self.tool.value,
                ResourceGrant.resource_id == self.row_id,
            )
        )
        if level is not None:
            self.session.add(
                ResourceGrant(
                    guild_id=self.guild.id,
                    initiative_id=self.initiative_id,
                    resource_type=self.tool,
                    resource_id=self.row_id,
                    user_id=user.id if user is not None else None,
                    role_id=role_id,
                    all_initiative_members=everyone,
                    level=level,
                )
            )
        await self.session.commit()
        return await self.load()


async def build_world(session, acting_user, tool: Tool) -> World:
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    initiative, guild = owner.initiative, owner.guild
    for t in Tool:
        if hasattr(initiative, t.view_permission):
            setattr(initiative, t.view_permission, True)
    session.add(initiative)
    await session.commit()

    co_member = await acting_user(
        guild_role=GuildRole.member,
        guild=guild,
        initiative=initiative,
        initiative_role="member",
    )
    admin = await acting_user(guild_role=GuildRole.admin, guild=guild)

    factory = getattr(factories, _TOOL_FACTORIES[tool])
    row = await factory(session, initiative, owner.user)
    return World(session, tool, guild, initiative, row, owner, co_member, admin)


@pytest.fixture
def clean_context():
    """Every DAC decision reads request context; start and leave it empty."""
    set_active_role(None, None)
    set_active_grant(None, None)
    set_override_sharing_initiatives(None)
    set_content_read_only_guild(None)
    yield
    set_active_role(None, None)
    set_active_grant(None, None)
    set_override_sharing_initiatives(None)
    set_content_read_only_guild(None)


def refused(resource, row, user, **kwargs) -> HTTPException:
    with pytest.raises(HTTPException) as exc:
        require_access(resource, row, user, **kwargs)
    assert exc.value.status_code == 403
    return exc.value


async def _role_id_of(session, initiative, user) -> int:
    row = (
        await session.exec(
            select(InitiativeMember.role_id).where(
                InitiativeMember.initiative_id == initiative.id,
                InitiativeMember.user_id == user.id,
            )
        )
    ).one()
    role_id = row[0] if isinstance(row, tuple) else row
    assert role_id is not None
    return role_id


async def _remove_from_initiative(session, initiative, user) -> None:
    await session.exec(
        delete(InitiativeMember).where(
            InitiativeMember.initiative_id == initiative.id,
            InitiativeMember.user_id == user.id,
        )
    )
    await session.commit()


# ── effective_permission_level (pure helper) ─────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("user_level", "role_level", "expected"),
    [
        (None, None, None),
        (PL.read, None, PL.read),
        (None, PL.write, PL.write),
        (PL.read, PL.owner, PL.owner),
        (PL.owner, PL.read, PL.owner),
    ],
)
def test_effective_permission_level_takes_the_higher_of_the_two(
    user_level, role_level, expected
):
    """The user's own grant and their role's grant combine by taking the higher,
    in either order."""
    assert (
        effective_permission_level(user_level, role_level, PROJECT_LEVEL_ORDER)
        == expected
    )


# ── Every tool resolves sharing through the same engine ──────────────────────


@pytest.mark.integration
@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.value)
async def test_every_tool_resolves_sharing_through_one_engine(
    session, acting_user, clean_context, tool: Tool
):
    """Each tool answers the same questions the same way, with the refusal
    messages its registry entry names.

    A tool reaches the engine through its ``DAC_RESOURCES`` entry and its
    ``RESOURCE_ACCESS`` loader, so a tool added later inherits this behaviour by
    registering rather than by re-implementing it.
    """
    w = await build_world(session, acting_user, tool)
    resource = w.resource

    # The holder of the owner grant.
    loaded = await w.grant("owner", user=w.owner.user)
    set_active_role(w.guild.id, GuildRole.member.value)
    require_access(resource, loaded, w.owner.user, access="write")
    assert compute_permission(resource, loaded, w.owner.user.id) == "owner"

    # An initiative co-member with no grant on this resource.
    assert compute_permission(resource, loaded, w.co_member.user.id) is None
    assert (
        refused(resource, loaded, w.co_member.user, access="read").detail
        == resource.denied_msg
    )

    # A guild admin needs no grant at all.
    set_active_role(w.guild.id, GuildRole.admin.value)
    require_access(resource, loaded, w.admin.user, access="write")
    require_access(resource, loaded, w.admin.user, require_owner=True)
    assert compute_permission(resource, loaded, w.admin.user.id) == "owner"

    # A PAM read grant opens the guild for reading only. The grantee holds no
    # grant row, so the write stops at the same "nothing shared with you" answer
    # a stranger gets rather than at the level check.
    set_active_role(None, None)
    set_active_grant(w.guild.id, "read")
    require_access(resource, loaded, w.co_member.user, access="read")
    assert (
        refused(resource, loaded, w.co_member.user, access="write").detail
        == resource.denied_msg
    )

    # Holding a read grant of their own is where the level check answers, and it
    # names the tool's own write message.
    set_active_grant(None, None)
    set_active_role(w.guild.id, GuildRole.member.value)
    loaded = await w.grant("read", user=w.co_member.user)
    require_access(resource, loaded, w.co_member.user, access="read")
    assert (
        refused(resource, loaded, w.co_member.user, access="write").detail
        == resource.write_msg
    )
    assert (
        refused(resource, loaded, w.co_member.user, require_owner=True).detail
        == resource.owner_msg
    )


# ── How a grant resolves ─────────────────────────────────────────────────────


@pytest.mark.integration
async def test_a_role_grant_elevates_over_a_users_own(
    session, acting_user, clean_context
):
    """A grant to an initiative role the user holds outranks their own lower
    grant — the two combine by taking the higher."""
    w = await build_world(session, acting_user, Tool.project)
    set_active_role(w.guild.id, GuildRole.member.value)

    role_id = await _role_id_of(session, w.initiative, w.co_member.user)
    loaded = await w.grant("read", user=w.co_member.user)
    assert compute_permission(w.resource, loaded, w.co_member.user.id) == "read"

    session.add(
        ResourceGrant(
            guild_id=w.guild.id,
            initiative_id=w.initiative_id,
            resource_type=Tool.project,
            resource_id=w.row_id,
            role_id=role_id,
            level="write",
        )
    )
    await session.commit()
    loaded = await w.load()
    assert compute_permission(w.resource, loaded, w.co_member.user.id) == "write"


@pytest.mark.integration
async def test_general_access_covers_the_initiatives_members_only(
    session, acting_user, clean_context
):
    """An all-initiative-members grant reaches every member without naming them,
    and stops at the initiative boundary."""
    w = await build_world(session, acting_user, Tool.project)
    outsider = await acting_user(guild_role=GuildRole.member, guild=w.guild)
    set_active_role(w.guild.id, GuildRole.member.value)

    loaded = await w.grant("write", everyone=True)
    assert compute_permission(w.resource, loaded, w.co_member.user.id) == "write"
    require_access(w.resource, loaded, w.co_member.user, access="write")

    assert compute_permission(w.resource, loaded, outsider.user.id) is None
    refused(w.resource, loaded, outsider.user, access="read")


@pytest.mark.integration
async def test_membership_alone_grants_nothing(session, acting_user, clean_context):
    """The gate is an AND-layer: being in the initiative is not access to its
    resources."""
    w = await build_world(session, acting_user, Tool.project)
    set_active_role(w.guild.id, GuildRole.member.value)
    loaded = await w.grant(None)
    assert compute_permission(w.resource, loaded, w.co_member.user.id) is None
    refused(w.resource, loaded, w.co_member.user, access="read")


@pytest.mark.integration
@pytest.mark.parametrize("tool", SCOPE_GATED, ids=lambda t: t.value)
async def test_a_grant_left_behind_after_removal_is_denied(
    session, acting_user, clean_context, tool: Tool
):
    """A grant row outliving the user's initiative membership must not carry
    access — the scope gate is checked before the grant is read."""
    w = await build_world(session, acting_user, tool)
    set_active_role(w.guild.id, GuildRole.member.value)
    loaded = await w.grant("owner", user=w.co_member.user)
    require_access(w.resource, loaded, w.co_member.user, access="read")

    await _remove_from_initiative(session, w.initiative, w.co_member.user)
    loaded = await w.load()
    assert refused(w.resource, loaded, w.co_member.user, access="read").detail == (
        w.resource.denied_msg
    )


@pytest.mark.integration
async def test_has_project_write_access_tracks_the_level(
    session, acting_user, clean_context
):
    """The synchronous filter helper agrees with the engine about who may write."""
    w = await build_world(session, acting_user, Tool.project)
    set_active_role(w.guild.id, GuildRole.member.value)
    for level, expected in (("owner", True), ("write", True), ("read", False)):
        loaded = await w.grant(level, user=w.co_member.user)
        assert has_project_write_access(loaded, w.co_member.user) is expected
    loaded = await w.grant(None)
    assert has_project_write_access(loaded, w.co_member.user) is False


# ── The overrides that sit above sharing ─────────────────────────────────────


@pytest.mark.integration
async def test_a_guild_admin_bypasses_the_scope_gate(
    session, acting_user, clean_context
):
    """Guild admin is full authority over the guild, by role context or by the
    explicit parameter, membership or not."""
    w = await build_world(session, acting_user, Tool.project)
    loaded = await w.grant(None)
    await _remove_from_initiative(session, w.initiative, w.co_member.user)
    loaded = await w.load()

    require_access(
        w.resource, loaded, w.co_member.user, access="write", guild_role="admin"
    )

    set_active_role(w.guild.id, GuildRole.admin.value)
    require_access(w.resource, loaded, w.co_member.user, require_owner=True)


@pytest.mark.integration
async def test_admin_of_another_guild_unlocks_nothing_here(
    session, acting_user, clean_context
):
    """Role context is keyed by guild, so admin of guild A grants nothing in B."""
    w = await build_world(session, acting_user, Tool.project)
    loaded = await w.grant(None)
    set_active_role(w.guild.id + 1000, GuildRole.admin.value)
    refused(w.resource, loaded, w.co_member.user, access="read")


@pytest.mark.integration
async def test_a_platform_owner_holds_no_standing_bypass(
    session, acting_user, clean_context
):
    """``data.bypass`` is the right to break glass, not an ambient reach — a
    platform owner with no membership and no live grant is refused."""
    w = await build_world(session, acting_user, Tool.project)
    loaded = await w.grant(None)
    w.co_member.user.role = UserRole.owner
    session.add(w.co_member.user)
    await session.commit()
    refused(w.resource, loaded, w.co_member.user, access="read")


@pytest.mark.integration
async def test_a_pam_grant_lifts_the_level_and_never_bleeds(
    session, acting_user, clean_context
):
    """A grantee holds no grant row, so the level the client sees has to come
    from the PAM grant — at the level it was issued, in its guild only, and
    never as owner.

    One tool stands for all of them: the lift reads the guild off the row and
    never consults the resource, and the per-tool sweep above already covers
    each tool reaching the engine.
    """
    w = await build_world(session, acting_user, Tool.project)
    loaded = await w.grant(None)
    stranger_id = w.co_member.user.id

    assert compute_permission(w.resource, loaded, stranger_id) is None

    set_active_grant(w.guild.id, "read")
    assert compute_permission(w.resource, loaded, stranger_id) == "read"

    set_active_grant(w.guild.id, "read_write")
    assert compute_permission(w.resource, loaded, stranger_id) == "write"

    set_active_grant(w.guild.id + 1000, "read_write")
    assert compute_permission(w.resource, loaded, stranger_id) is None


@pytest.mark.integration
async def test_a_pam_grant_never_downgrades_an_owner(
    session, acting_user, clean_context
):
    """An explicit owner grant outranks the write a read_write grant implies."""
    w = await build_world(session, acting_user, Tool.project)
    loaded = await w.grant("owner", user=w.co_member.user)
    set_active_grant(w.guild.id, "read_write")
    assert compute_permission(w.resource, loaded, w.co_member.user.id) == "owner"


@pytest.mark.integration
async def test_a_frozen_guild_caps_everyone_at_read(
    session, acting_user, clean_context
):
    """A read_only guild caps the level the client sees and refuses every write
    — checked before the admin leg, so full authority does not clear the hold.

    ``guild_suspension_test`` covers the same hold end-to-end through an
    endpoint; this pins where in the engine the cap sits.
    """
    w = await build_world(session, acting_user, Tool.project)
    loaded = await w.grant("owner", user=w.owner.user)

    set_active_role(w.guild.id, GuildRole.member.value)
    set_content_read_only_guild(w.guild.id)

    assert compute_permission(w.resource, loaded, w.owner.user.id) == "read"
    require_access(w.resource, loaded, w.owner.user, access="read")
    assert (
        refused(w.resource, loaded, w.owner.user, access="write").detail
        == w.resource.write_msg
    )
    refused(w.resource, loaded, w.owner.user, require_owner=True)

    set_active_role(w.guild.id, GuildRole.admin.value)
    assert compute_permission(w.resource, loaded, w.admin.user.id) == "read"
    refused(w.resource, loaded, w.admin.user, access="write")


# ── dac_scope_clause: the query-shaped half of the DAC decision ──────────────


def _compiled(clause: ColumnElement[bool]) -> str:
    return str(clause.compile(compile_kwargs={"literal_binds": True}))


def test_dac_scope_clause_is_a_no_op_for_a_guild_wide_request():
    """A guild admin, or a live PAM grant, reaches the whole guild — so the
    clause adds nothing and the caller needs no branch around it."""
    set_active_grant(None, None)
    set_override_sharing_initiatives(None)
    try:
        set_active_role(7, GuildRole.admin.value)
        assert _compiled(dac_scope_clause(Tool.project, Project.id, 1, guild_id=7)) == (
            "true"
        )

        set_active_role(None, None)
        set_active_grant(7, "read")
        assert (
            _compiled(dac_scope_clause(Tool.document, Document.id, 1, guild_id=7))
            == "true"
        )
    finally:
        set_active_role(None, None)
        set_active_grant(None, None)


def test_dac_scope_clause_respects_the_grant_level():
    """A grant opens the guild only at the level it was issued at, so a read
    grant is a no-op for a read but not for a write."""
    set_active_role(None, None)
    set_override_sharing_initiatives(None)
    set_active_grant(7, "read")
    try:
        assert (
            _compiled(dac_scope_clause(Tool.project, Project.id, 1, guild_id=7))
            == "true"
        )
        assert (
            _compiled(
                dac_scope_clause(
                    Tool.project, Project.id, 1, guild_id=7, access="write"
                )
            )
            != "true"
        )
        set_active_grant(7, "read_write")
        assert (
            _compiled(
                dac_scope_clause(
                    Tool.project, Project.id, 1, guild_id=7, access="write"
                )
            )
            == "true"
        )
    finally:
        set_active_grant(None, None)


def test_dac_scope_clause_narrows_an_ordinary_member():
    """A member is scoped to the resources granted to them, and the clause names
    the tool it was asked about."""
    set_active_grant(None, None)
    set_override_sharing_initiatives(None)
    set_active_role(7, GuildRole.member.value)
    try:
        sql = _compiled(dac_scope_clause(Tool.queue, Queue.id, 1, guild_id=7))
        assert "resource_grants" in sql
        assert "queue" in sql
        assert sql != "true"
    finally:
        set_active_role(None, None)


def test_dac_scope_clause_narrows_when_the_role_is_for_another_guild():
    """Role context is keyed by guild, so being an admin of guild 8 grants
    nothing in guild 7."""
    set_active_grant(None, None)
    set_override_sharing_initiatives(None)
    set_active_role(8, GuildRole.admin.value)
    try:
        assert (
            _compiled(dac_scope_clause(Tool.project, Project.id, 1, guild_id=7))
            != "true"
        )
        # ...and no guild at all narrows too, rather than opening up.
        assert (
            _compiled(dac_scope_clause(Tool.project, Project.id, 1, guild_id=None))
            != "true"
        )
    finally:
        set_active_role(None, None)


@pytest.mark.parametrize("tool", list(Tool))
def test_every_tool_can_be_scoped(tool):
    """Every tool in the registry resolves through the clause, so a tool added
    later inherits the same listing rule."""
    set_active_role(None, None)
    set_active_grant(None, None)
    set_override_sharing_initiatives(None)
    sql = _compiled(dac_scope_clause(tool, Project.id, 1, guild_id=7))
    assert "resource_grants" in sql
    assert tool.value in sql


def test_the_grants_subquery_has_one_caller():
    """``dac_scope_clause`` is the single entry point for narrowing a listing.

    ``_granted_resource_ids`` is one part of what it composes, and is private so
    that composition happens in one place.
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if path.name not in {"permissions.py", "permissions_test.py"}
        and "_granted_resource_ids" in path.read_text()
    ]
    assert offenders == [], (
        "these modules reach for the grants subquery directly instead of "
        f"permissions.dac_scope_clause: {offenders}"
    )

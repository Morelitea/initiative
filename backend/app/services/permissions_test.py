"""Tests for Discretionary Access Control (DAC) — project and document permissions.

Tests cover:
- Generic helpers (effective_permission_level)
- Project permission computation and enforcement
- Document permission computation and enforcement

Uses SimpleNamespace mocks to simulate eagerly-loaded ORM objects.
"""

import pathlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.messages import DocumentMessages, ProjectMessages
from app.models.tenant.document import DocumentPermissionLevel
from app.models.tenant.project import ProjectPermissionLevel
from app.models.platform.user import UserRole
from sqlalchemy import ColumnElement

from app.core.pam_context import set_active_grant
from app.core.role_context import set_active_role, set_override_sharing_initiatives
from app.core.tools import Tool
from app.models.platform.guild import GuildRole
from app.models.tenant.document import Document
from app.models.tenant.project import Project
from app.models.tenant.queue import Queue
from app.services.permissions import (
    DAC_RESOURCES,
    PROJECT_LEVEL_ORDER,
    compute_permission,
    dac_scope_clause,
    require_access,
    compute_document_permission,
    compute_project_permission,
    effective_permission_level,
    has_project_write_access,
    require_document_access,
    require_project_access,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(user_id: int = 1, role: UserRole = UserRole.member) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, role=role)


def _make_project(
    *,
    user_id: int | None = None,
    user_level: ProjectPermissionLevel | None = None,
    role_permissions: list | None = None,
    memberships: list | None = None,
    guild_id: int = 1,
    member: bool = True,
) -> SimpleNamespace:
    """Build a mock project with eagerly-loaded relationships.

    By default the permission-holding user is also an initiative member
    (the normal production state); pass ``member=False`` to model a stale
    permission row left behind after removal from the initiative.
    """
    grants = []
    all_memberships = list(memberships or [])
    if user_id is not None and user_level is not None:
        grants.append(SimpleNamespace(user_id=user_id, role_id=None, level=user_level))
        if member:
            all_memberships.append(SimpleNamespace(user_id=user_id, role_id=None))
    for rp in role_permissions or []:
        grants.append(
            SimpleNamespace(
                user_id=None,
                role_id=getattr(rp, "initiative_role_id", getattr(rp, "role_id", None)),
                level=rp.level,
            )
        )
    return SimpleNamespace(
        guild_id=guild_id,
        grants=grants,
        initiative=SimpleNamespace(memberships=all_memberships),
    )


def _make_document(
    *,
    user_id: int | None = None,
    user_level: DocumentPermissionLevel | None = None,
    role_permissions: list | None = None,
    memberships: list | None = None,
    guild_id: int = 1,
    member: bool = True,
) -> SimpleNamespace:
    """Build a mock document with eagerly-loaded relationships.

    By default the permission-holding user is also an initiative member
    (the normal production state); pass ``member=False`` to model a stale
    permission row left behind after removal from the initiative.
    """
    grants = []
    all_memberships = list(memberships or [])
    if user_id is not None and user_level is not None:
        grants.append(SimpleNamespace(user_id=user_id, role_id=None, level=user_level))
        if member:
            all_memberships.append(SimpleNamespace(user_id=user_id, role_id=None))
    for rp in role_permissions or []:
        grants.append(
            SimpleNamespace(
                user_id=None,
                role_id=getattr(rp, "initiative_role_id", getattr(rp, "role_id", None)),
                level=rp.level,
            )
        )
    return SimpleNamespace(
        guild_id=guild_id,
        grants=grants,
        initiative=SimpleNamespace(memberships=all_memberships),
    )


# ---------------------------------------------------------------------------
# effective_permission_level (generic helper)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_effective_permission_level_both_none():
    result = effective_permission_level(None, None, PROJECT_LEVEL_ORDER)
    assert result is None


@pytest.mark.unit
def test_effective_permission_level_user_only():
    result = effective_permission_level(
        ProjectPermissionLevel.read,
        None,
        PROJECT_LEVEL_ORDER,
    )
    assert result == ProjectPermissionLevel.read


@pytest.mark.unit
def test_effective_permission_level_role_only():
    result = effective_permission_level(
        None,
        ProjectPermissionLevel.write,
        PROJECT_LEVEL_ORDER,
    )
    assert result == ProjectPermissionLevel.write


@pytest.mark.unit
def test_effective_permission_level_takes_higher():
    result = effective_permission_level(
        ProjectPermissionLevel.read,
        ProjectPermissionLevel.owner,
        PROJECT_LEVEL_ORDER,
    )
    assert result == ProjectPermissionLevel.owner

    # Also verify the reverse: user > role
    result2 = effective_permission_level(
        ProjectPermissionLevel.owner,
        ProjectPermissionLevel.read,
        PROJECT_LEVEL_ORDER,
    )
    assert result2 == ProjectPermissionLevel.owner


# ---------------------------------------------------------------------------
# compute_project_permission
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_compute_project_permission_guild_admin_gets_owner():
    """A guild admin has full access to all of their guild's data regardless of
    DAC, so ``my_permission_level`` reports ``owner`` — otherwise the UI would
    hide edit/delete affordances the API actually honors."""
    from app.core.role_context import set_active_role

    project = _make_project()  # no DAC permission for user_id=1
    try:
        set_active_role(1, "admin")
        result = compute_project_permission(project, user_id=1)
    finally:
        set_active_role(None, None)
    assert result == "owner"


@pytest.mark.unit
def test_compute_project_permission_user_read():
    project = _make_project(user_id=1, user_level=ProjectPermissionLevel.read)
    result = compute_project_permission(project, user_id=1)
    assert result == "read"


@pytest.mark.unit
def test_compute_project_permission_no_access():
    project = _make_project()
    result = compute_project_permission(project, user_id=1)
    assert result is None


@pytest.mark.unit
def test_compute_project_permission_role_elevates():
    """Role-based permission higher than user permission should take effect."""
    role_id = 10
    project = _make_project(
        user_id=1,
        user_level=ProjectPermissionLevel.read,
        role_permissions=[
            SimpleNamespace(
                initiative_role_id=role_id, level=ProjectPermissionLevel.write
            ),
        ],
        memberships=[
            SimpleNamespace(user_id=1, role_id=role_id),
        ],
    )
    result = compute_project_permission(project, user_id=1)
    assert result == "write"


# ---------------------------------------------------------------------------
# require_project_access
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_require_project_access_read_allowed():
    project = _make_project(user_id=1, user_level=ProjectPermissionLevel.read)
    user = _make_user(user_id=1)
    require_project_access(project, user, access="read")  # should not raise


@pytest.mark.unit
def test_require_project_access_write_denied_for_reader():
    project = _make_project(user_id=1, user_level=ProjectPermissionLevel.read)
    user = _make_user(user_id=1)
    with pytest.raises(HTTPException) as exc_info:
        require_project_access(project, user, access="write")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == ProjectMessages.WRITE_ACCESS_REQUIRED


@pytest.mark.unit
def test_require_project_access_no_access():
    project = _make_project()  # no permissions for user_id=1
    user = _make_user(user_id=1)
    with pytest.raises(HTTPException) as exc_info:
        require_project_access(project, user, access="read")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == ProjectMessages.NO_ACCESS


@pytest.mark.unit
def test_require_project_access_owner_required():
    project = _make_project(user_id=1, user_level=ProjectPermissionLevel.write)
    user = _make_user(user_id=1)
    with pytest.raises(HTTPException) as exc_info:
        require_project_access(project, user, require_owner=True)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == ProjectMessages.OWNER_REQUIRED


@pytest.mark.unit
def test_require_project_access_owner_passes():
    project = _make_project(user_id=1, user_level=ProjectPermissionLevel.owner)
    user = _make_user(user_id=1)
    require_project_access(project, user, require_owner=True)  # should not raise


@pytest.mark.unit
def test_require_project_access_guild_admin_no_dac_full_access():
    """A guild admin gets read/write/owner access to any project in their guild
    without a permission row or initiative membership."""
    from app.core.role_context import set_active_role

    project = _make_project()  # no permissions, no membership for user_id=1
    user = _make_user(user_id=1)
    try:
        set_active_role(1, "admin")
        require_project_access(project, user, access="read")
        require_project_access(project, user, access="write")
        require_project_access(project, user, require_owner=True)  # none should raise
    finally:
        set_active_role(None, None)


@pytest.mark.unit
def test_require_project_access_guild_member_no_dac_denied():
    """A plain guild member (non-admin) still needs DAC — the admin bypass is
    strictly guild-admin-scoped."""
    from app.core.role_context import set_active_role

    project = _make_project()  # no permissions for user_id=1
    user = _make_user(user_id=1)
    try:
        set_active_role(1, "member")
        with pytest.raises(HTTPException) as exc_info:
            require_project_access(project, user, access="read")
    finally:
        set_active_role(None, None)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# has_project_write_access
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_has_project_write_access_true_for_write():
    project = _make_project(user_id=1, user_level=ProjectPermissionLevel.write)
    user = _make_user(user_id=1)
    assert has_project_write_access(project, user) is True


@pytest.mark.unit
def test_has_project_write_access_true_for_owner():
    project = _make_project(user_id=1, user_level=ProjectPermissionLevel.owner)
    user = _make_user(user_id=1)
    assert has_project_write_access(project, user) is True


@pytest.mark.unit
def test_has_project_write_access_false_for_read():
    project = _make_project(user_id=1, user_level=ProjectPermissionLevel.read)
    user = _make_user(user_id=1)
    assert has_project_write_access(project, user) is False


@pytest.mark.unit
def test_has_project_write_access_false_for_none():
    project = _make_project()  # no permissions
    user = _make_user(user_id=1)
    assert has_project_write_access(project, user) is False


# ---------------------------------------------------------------------------
# compute_document_permission
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_compute_document_permission_guild_admin_gets_owner():
    """A guild admin has full access to all of their guild's data regardless of
    DAC, so ``my_permission_level`` reports ``owner``."""
    from app.core.role_context import set_active_role

    doc = _make_document()  # no DAC permission for user_id=1
    try:
        set_active_role(1, "admin")
        result = compute_document_permission(doc, user_id=1)
    finally:
        set_active_role(None, None)
    assert result == "owner"


@pytest.mark.unit
def test_compute_document_permission_user_write():
    doc = _make_document(user_id=1, user_level=DocumentPermissionLevel.write)
    result = compute_document_permission(doc, user_id=1)
    assert result == "write"


@pytest.mark.unit
def test_compute_document_permission_no_access():
    doc = _make_document()
    result = compute_document_permission(doc, user_id=1)
    assert result is None


# ---------------------------------------------------------------------------
# require_document_access
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_require_document_access_read_allowed():
    doc = _make_document(user_id=1, user_level=DocumentPermissionLevel.read)
    user = _make_user(user_id=1)
    require_document_access(doc, user, access="read")  # should not raise


@pytest.mark.unit
def test_require_document_access_write_denied():
    doc = _make_document(user_id=1, user_level=DocumentPermissionLevel.read)
    user = _make_user(user_id=1)
    with pytest.raises(HTTPException) as exc_info:
        require_document_access(doc, user, access="write")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == DocumentMessages.WRITE_ACCESS_REQUIRED


@pytest.mark.unit
def test_require_document_access_no_access():
    doc = _make_document()  # no permissions for user
    user = _make_user(user_id=1)
    with pytest.raises(HTTPException) as exc_info:
        require_document_access(doc, user, access="read")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == DocumentMessages.NO_ACCESS


@pytest.mark.unit
def test_require_document_access_owner_required():
    doc = _make_document(user_id=1, user_level=DocumentPermissionLevel.write)
    user = _make_user(user_id=1)
    with pytest.raises(HTTPException) as exc_info:
        require_document_access(doc, user, require_owner=True)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == DocumentMessages.OWNER_REQUIRED


@pytest.mark.unit
def test_require_document_access_owner_passes():
    doc = _make_document(user_id=1, user_level=DocumentPermissionLevel.owner)
    user = _make_user(user_id=1)
    require_document_access(doc, user, require_owner=True)  # should not raise


# ---------------------------------------------------------------------------
# my_permission_level reflects an active PAM grant (drives edit affordances)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_compute_project_permission_lifts_to_grant():
    """A grantee has no permission row; ``my_permission_level`` must reflect the
    grant so the UI shows edit affordances for a read_write grant."""
    from app.core.pam_context import set_active_grant

    project = _make_project()  # no DAC permission rows
    project.guild_id = 7
    try:
        set_active_grant(None, None)
        assert compute_project_permission(project, 99) is None

        set_active_grant(7, "read")
        assert compute_project_permission(project, 99) == "read"

        set_active_grant(7, "read_write")
        assert compute_project_permission(project, 99) == "write"

        # A grant never confers owner, and never bleeds across guilds.
        set_active_grant(8, "read_write")
        assert compute_project_permission(project, 99) is None
    finally:
        set_active_grant(None, None)


@pytest.mark.unit
def test_compute_document_permission_lifts_to_grant():
    from app.core.pam_context import set_active_grant

    doc = _make_document()
    doc.guild_id = 7
    try:
        set_active_grant(7, "read_write")
        assert compute_document_permission(doc, 99) == "write"
        set_active_grant(7, "read")
        assert compute_document_permission(doc, 99) == "read"
    finally:
        set_active_grant(None, None)


@pytest.mark.unit
def test_compute_project_permission_grant_does_not_downgrade_dac():
    """An explicit owner permission outranks the grant (no downgrade to write)."""
    from app.core.pam_context import set_active_grant

    project = _make_project(user_id=99, user_level=ProjectPermissionLevel.owner)
    project.guild_id = 7
    try:
        set_active_grant(7, "read_write")
        assert compute_project_permission(project, 99) == "owner"
    finally:
        set_active_grant(None, None)


# ---------------------------------------------------------------------------
# Initiative-scope gate (replacement for the dropped RESTRICTIVE RLS layer)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_stale_document_permission_denied_without_membership():
    """An explicit permission row left behind after initiative removal must
    not grant access (the old DB RESTRICTIVE policy enforced this)."""
    doc = _make_document(
        user_id=1, user_level=DocumentPermissionLevel.write, member=False
    )
    user = _make_user(user_id=1)
    with pytest.raises(HTTPException) as exc_info:
        require_document_access(doc, user, access="read")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == DocumentMessages.NO_ACCESS


@pytest.mark.unit
def test_stale_project_permission_denied_without_membership():
    project = _make_project(
        user_id=1, user_level=ProjectPermissionLevel.owner, member=False
    )
    user = _make_user(user_id=1)
    with pytest.raises(HTTPException) as exc_info:
        require_project_access(project, user, access="read")
    assert exc_info.value.status_code == 403


@pytest.mark.unit
def test_guild_admin_bypasses_initiative_scope_via_param():
    """A guild admin holding an explicit permission keeps access without
    membership (mirrors the old policy's IS_ADMIN leg)."""
    doc = _make_document(
        user_id=1, user_level=DocumentPermissionLevel.read, member=False
    )
    user = _make_user(user_id=1)
    require_document_access(
        doc, user, access="read", guild_role="admin"
    )  # should not raise


@pytest.mark.unit
def test_guild_admin_bypasses_initiative_scope_via_role_context():
    from app.core.role_context import set_active_role

    doc = _make_document(
        user_id=1, user_level=DocumentPermissionLevel.read, member=False, guild_id=7
    )
    user = _make_user(user_id=1)
    try:
        set_active_role(7, "admin")
        require_document_access(doc, user, access="read")  # should not raise
    finally:
        set_active_role(None, None)


@pytest.mark.unit
def test_require_document_access_guild_admin_no_dac_full_access():
    """A guild admin gets read/write/owner access to any document in their guild
    without a permission row or initiative membership."""
    from app.core.role_context import set_active_role

    doc = _make_document(guild_id=7)  # no permissions, no membership for user_id=1
    user = _make_user(user_id=1)
    try:
        set_active_role(7, "admin")
        require_document_access(doc, user, access="read")
        require_document_access(doc, user, access="write")
        require_document_access(doc, user, require_owner=True)  # none should raise
    finally:
        set_active_role(None, None)


@pytest.mark.unit
def test_role_context_for_other_guild_does_not_bypass():
    """An admin role recorded for guild A must not unlock guild B's entities
    (cross-guild gathers)."""
    from app.core.role_context import set_active_role

    doc = _make_document(
        user_id=1, user_level=DocumentPermissionLevel.read, member=False, guild_id=8
    )
    user = _make_user(user_id=1)
    try:
        set_active_role(7, "admin")
        with pytest.raises(HTTPException):
            require_document_access(doc, user, access="read")
    finally:
        set_active_role(None, None)


@pytest.mark.unit
def test_data_bypass_no_longer_bypasses_initiative_scope():
    """Phase 3: ``data.bypass`` is no longer a standing all-guild bypass. An
    owner/admin who isn't a member and holds no live grant is DENIED — they must
    break-glass into a grant first (covered by
    ``test_pam_grant_bypasses_initiative_scope``)."""
    doc = _make_document(user_id=1, member=False)
    user = _make_user(user_id=1, role=UserRole.owner)
    with pytest.raises(HTTPException) as exc_info:
        require_document_access(doc, user, access="read")
    assert exc_info.value.status_code == 403


@pytest.mark.unit
def test_pam_grant_bypasses_initiative_scope():
    """A live grant acts as membership of every initiative in the guild."""
    from app.core.pam_context import set_active_grant

    doc = _make_document(guild_id=7)
    user = _make_user(user_id=99)
    try:
        set_active_grant(7, "read")
        require_document_access(doc, user, access="read")  # should not raise
    finally:
        set_active_grant(None, None)


@pytest.mark.unit
def test_membership_without_permission_row_still_denied():
    """The gate is an AND-layer: membership alone grants nothing."""
    doc = _make_document(memberships=[SimpleNamespace(user_id=1, role_id=None)])
    user = _make_user(user_id=1)
    with pytest.raises(HTTPException) as exc_info:
        require_document_access(doc, user, access="read")
    assert exc_info.value.status_code == 403


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


# ── Every tool resolves sharing through the same engine ─────────────────────

_TOOL_FACTORIES = {
    Tool.project: "create_project",
    Tool.document: "create_document",
    Tool.queue: "create_queue",
    Tool.counter_group: "create_counter_group",
    Tool.calendar: "create_calendar",
    Tool.dashboard: "create_dashboard",
}


async def _only_the_owner_holds_a_grant(session, tool: Tool, resource_id: int) -> None:
    """Drop the factory's default all-initiative-members grant."""
    from sqlmodel import delete

    from app.models.tenant.resource_grant import ResourceGrant

    await session.exec(
        delete(ResourceGrant).where(
            ResourceGrant.resource_type == tool.value,
            ResourceGrant.resource_id == resource_id,
            ResourceGrant.level != "owner",
        )
    )
    await session.commit()


@pytest.mark.integration
@pytest.mark.parametrize("tool", list(Tool), ids=lambda t: t.value)
async def test_every_tool_resolves_sharing_through_one_engine(
    session, acting_user, tool: Tool
):
    """Each tool answers the same four questions the same way.

    A tool reaches the engine through its ``DAC_RESOURCES`` entry and its
    ``RESOURCE_ACCESS`` loader, so a tool added later inherits this behaviour by
    registering rather than by re-implementing it.
    """
    from app.api import resource_access
    from app.testing import factories

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
    await _only_the_owner_holds_a_grant(session, tool, row.id)

    loader = resource_access.RESOURCE_ACCESS[tool].loader
    assert loader is not None, f"{tool.value} has no loader"
    resource = DAC_RESOURCES[tool]

    def _refused(user):
        with pytest.raises(HTTPException) as exc:
            require_access(resource, loaded, user, access="read")
        assert exc.value.status_code == 403

    set_override_sharing_initiatives(None)
    try:
        # The holder of the owner grant.
        set_active_role(guild.id, GuildRole.member.value)
        set_active_grant(None, None)
        loaded = await loader(session, row.id)
        require_access(resource, loaded, owner.user, access="write")
        assert compute_permission(resource, loaded, owner.user.id) == "owner"

        # An initiative co-member with no grant on this resource.
        _refused(co_member.user)
        assert compute_permission(resource, loaded, co_member.user.id) is None

        # A guild admin.
        set_active_role(guild.id, GuildRole.admin.value)
        require_access(resource, loaded, admin.user, access="write")
        assert compute_permission(resource, loaded, admin.user.id) == "owner"

        # A read grant: reads, not writes.
        set_active_role(None, None)
        set_active_grant(guild.id, "read")
        require_access(resource, loaded, co_member.user, access="read")
        with pytest.raises(HTTPException):
            require_access(resource, loaded, co_member.user, access="write")
    finally:
        set_active_role(None, None)
        set_active_grant(None, None)

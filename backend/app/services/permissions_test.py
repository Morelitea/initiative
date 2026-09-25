"""The DAC engine, asked the way a request asks it.

The rung a request holds on a row is the database's answer — the schema's
``resource_level``, mapped on every shareable model as ``access_level`` — so
every case here loads the row on the request login, routed through the seam
as the reader, through the loader the endpoints use. ``resource_level_test``
holds that function to the sharing gate, standing by standing. What this
file holds is what the app layer still decides on top of the level: the
named refusal, the frozen caps, the clauses a list spanning initiatives
adds, and the audience a notice reaches.
"""

from __future__ import annotations

import pathlib
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import ColumnElement, delete
from sqlmodel import select

from app.api import resource_access
from app.core.tools import Tool
from app.db import session as db_session
from app.db.guild_standing import GuildContext
from app.db.session import _RLS_PARAMS_INFO_KEY
from app.models.platform.guild import Guild, GuildRole, GuildStatus
from app.models.platform.user import UserRole
from app.models.tenant.document import Document
from app.models.tenant.initiative import InitiativeMember
from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.services.permissions import (
    DAC_RESOURCES,
    audience_user_ids,
    Action,
    client_access,
    granted_scope_clause,
    level_of,
    listing_scope_clause,
    require_access,
    writable_scope_clause,
)
from app.services.tenant import posts as posts_service
from app.services.tenant import project_grants
from app.testing import (
    create_access_grant,
    create_resource_grant,
    create_user,
    route_as,
)
from app.testing.factories import TOOL_FACTORIES

ALL_TOOLS = list(DAC_RESOURCES)

# The canonical per-tool factory registry rather than a copy of it: that one
# is checked against the Tool enum at import time, so a new tool cannot reach
# these parametrized cases without a factory behind it.
_TOOL_FACTORIES = TOOL_FACTORIES


# ── Building a real world ────────────────────────────────────────────────────


class World:
    """One guild, one initiative, one resource of ``tool``, and three actors."""

    def __init__(
        self,
        session,
        role_session,
        tool,
        guild,
        initiative,
        row,
        owner,
        co_member,
        admin,
    ):
        self.session = session
        self.role_session = role_session
        self.tool = tool
        self.resource = DAC_RESOURCES[tool]
        self.guild = guild
        self.initiative = initiative
        self.model = type(row)
        self.row = row
        self.row_id = row.id
        self.owner = owner
        self.co_member = co_member
        self.admin = admin

    async def as_reader(self, user):
        """The resource as ``user`` reads it, and the standing it was read
        under: on the request login, routed through the seam, through the
        loader the endpoints use. ``None`` where the policy admits nothing."""
        s = await self.role_session("app_user")
        context = await route_as(s, user_id=user.id, guild_id=self.guild.id)
        loader = resource_access.RESOURCE_ACCESS[self.tool].loader
        assert loader is not None, f"{self.tool.value} has no loader"
        return await loader(s, self.row_id), context

    async def grant(self, level, *, user=None, role_id=None, everyone=False) -> None:
        """Replace the resource's grants with exactly the ones named."""
        await self.session.exec(
            delete(ResourceGrant).where(
                ResourceGrant.resource_type == self.tool.value,
                ResourceGrant.resource_id == self.row_id,
            )
        )
        if level is not None:
            await create_resource_grant(
                self.session,
                self.row,
                user=user,
                role_id=role_id,
                all_initiative_members=everyone,
                level=ResourceAccessLevel(level),
                commit=False,
            )
        await self.session.commit()


async def build_world(session, role_session, acting_user, tool: Tool) -> World:
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

    factory = _TOOL_FACTORIES[tool]
    row = await factory(session, initiative, owner.user)
    return World(
        session, role_session, tool, guild, initiative, row, owner, co_member, admin
    )


def standing(
    guild=None,
    *,
    admin: bool = False,
    grant: str | None = None,
    read_only: bool = False,
    overrides: tuple[int, ...] = (),
) -> GuildContext | None:
    """A reader's standing in one community, shaped as the seam computes it,
    for the clause builders — which read the standing and no row.

    ``None`` is a request with no standing anywhere.
    """
    if guild is None:
        return None
    guild_id = guild if isinstance(guild, int) else guild.id
    return GuildContext(
        guild=guild if not isinstance(guild, int) else Guild(id=guild_id, name="g"),
        user_id=0,
        guild_id=guild_id,
        guild_role=GuildRole.admin.value if admin else GuildRole.member.value,
        standing_guild_id=guild_id,
        admin=admin,
        pam_read=grant is not None,
        pam_write=grant == "read_write",
        content_read_only=read_only,
        override_initiatives=overrides,
    )


def refused(resource, row, **kwargs) -> HTTPException:
    with pytest.raises(HTTPException) as exc:
        require_access(resource, row, **kwargs)
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


async def _freeze(session, guild) -> None:
    guild.status = GuildStatus.read_only.value
    guild.status_changed_at = datetime.now(timezone.utc)
    session.add(guild)
    await session.commit()


# ── Every tool resolves sharing through the same engine ──────────────────────


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.value)
async def test_every_tool_resolves_sharing_through_one_engine(
    session, role_session, acting_user, tool: Tool
):
    """Each tool answers the same questions the same way, with the refusal
    messages its registry entry names.

    A tool reaches the engine through its ``DAC_RESOURCES`` entry and its
    ``RESOURCE_ACCESS`` loader, so a tool added later inherits this behaviour by
    registering rather than by re-implementing it.
    """
    w = await build_world(session, role_session, acting_user, tool)
    resource = w.resource

    # The holder of the owner grant.
    await w.grant("owner", user=w.owner.user)
    row, context = await w.as_reader(w.owner.user)
    require_access(resource, row, context=context, access="write")
    assert client_access(row, context.user_id, context=context) == {
        **{action.value: True for action in Action},
        "unarchive": False,
    }

    # An initiative co-member with no grant on this resource: the table's own
    # policy admits nothing, so there is no row to refuse.
    row, _ = await w.as_reader(w.co_member.user)
    assert row is None

    # A guild admin needs no grant at all.
    row, context = await w.as_reader(w.admin.user)
    require_access(resource, row, context=context, access="write")
    require_access(resource, row, context=context, require_owner=True)
    assert client_access(row, context.user_id, context=context) == {
        **{action.value: True for action in Action},
        "unarchive": False,
    }

    # A PAM read grant opens the guild for reading only. The grantee holds the
    # rung the grant lends, so the write stops at the level check and names
    # the tool's own write message.
    grantee = await create_user(session, role=UserRole.support)
    await create_access_grant(session, user=grantee, guild=w.guild)
    row, context = await w.as_reader(grantee)
    require_access(resource, row, context=context, access="read")
    assert (
        refused(resource, row, context=context, access="write").detail
        == resource.write_msg
    )

    # Holding a read grant of their own is where the level check answers.
    await w.grant("read", user=w.co_member.user)
    row, context = await w.as_reader(w.co_member.user)
    require_access(resource, row, context=context, access="read")
    assert (
        refused(resource, row, context=context, access="write").detail
        == resource.write_msg
    )
    assert (
        refused(resource, row, context=context, require_owner=True).detail
        == resource.owner_msg
    )

    # A writer edits it; deleting it and changing who it is shared with are
    # the owner's.
    await w.grant("write", user=w.co_member.user)
    row, context = await w.as_reader(w.co_member.user)
    assert client_access(row, context.user_id, context=context) == {
        "edit": True,
        "delete": False,
        "share": False,
        "export": False,
        "unarchive": False,
    }


# ── How a grant resolves ─────────────────────────────────────────────────────


async def test_a_role_grant_elevates_over_a_users_own(
    session, role_session, acting_user
):
    """A grant to an initiative role the user holds outranks their own lower
    grant — the two combine by taking the higher."""
    w = await build_world(session, role_session, acting_user, Tool.project)

    role_id = await _role_id_of(session, w.initiative, w.co_member.user)
    await w.grant("read", user=w.co_member.user)
    row, context = await w.as_reader(w.co_member.user)
    assert level_of(row) == "read"

    await create_resource_grant(
        session, w.row, role_id=role_id, level=ResourceAccessLevel.write
    )
    row, _ = await w.as_reader(w.co_member.user)
    assert level_of(row) == "write"


async def test_general_access_covers_the_initiatives_members_only(
    session, role_session, acting_user
):
    """An all-initiative-members grant reaches every member without naming them,
    and stops at the initiative boundary."""
    w = await build_world(session, role_session, acting_user, Tool.project)
    outsider = await acting_user(guild_role=GuildRole.member, guild=w.guild)

    await w.grant("write", everyone=True)
    row, context = await w.as_reader(w.co_member.user)
    assert level_of(row) == "write"
    require_access(w.resource, row, context=context, access="write")

    row, _ = await w.as_reader(outsider.user)
    assert row is None


async def test_membership_alone_grants_nothing(session, role_session, acting_user):
    """The gate is an AND-layer: being in the initiative is not access to its
    resources."""
    w = await build_world(session, role_session, acting_user, Tool.project)
    await w.grant(None)
    row, _ = await w.as_reader(w.co_member.user)
    assert row is None


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.value)
async def test_a_grant_left_behind_after_removal_reaches_nothing(
    session, role_session, acting_user, reading_as, tool: Tool
):
    """A grant row outliving the user's initiative membership carries no access.

    Leaving an initiative does not sweep the grants written for you, so the row
    is still there naming you at owner. What answers it is the table's own
    policy: every content table ANDs ``initiative_access`` onto its
    sharing leg, so the resource stops being visible the moment the membership
    goes — asserted against the database on the request login, because that is
    where the answer comes from.
    """
    w = await build_world(session, role_session, acting_user, tool)
    await w.grant("owner", user=w.co_member.user)

    async def visible() -> bool:
        reader = await reading_as(w.co_member.user.id, w.guild.id)
        rows = (
            await reader.exec(select(w.model.id).where(w.model.id == w.row_id))
        ).all()
        await reader.rollback()
        return bool(rows)

    assert await visible(), "the grant should reach it while the membership stands"

    await _remove_from_initiative(session, w.initiative, w.co_member.user)
    assert not await visible(), (
        "a grant that outlived the membership must reach nothing"
    )


async def test_write_holders_follow_the_level(session, role_session, acting_user):
    """Who may be assigned a project's tasks is who holds write on it, asked of
    the roster and the grant rows together."""
    w = await build_world(session, role_session, acting_user, Tool.project)
    s = await role_session("app_user")
    await route_as(s, user_id=w.owner.user.id, guild_id=w.guild.id)
    project = await project_grants.get_project(s, w.row_id)
    assert project is not None

    co = w.co_member.user.id
    for level, expected in (("owner", {co}), ("write", {co}), ("read", set())):
        await w.grant(level, user=w.co_member.user)
        assert await project_grants.write_holder_ids(s, project) == expected
    await w.grant(None)
    assert await project_grants.write_holder_ids(s, project) == set()

    role_id = await _role_id_of(session, w.initiative, w.co_member.user)
    await w.grant("write", role_id=role_id)
    assert await project_grants.write_holder_ids(s, project) == {co}

    await w.grant("write", everyone=True)
    assert await project_grants.write_holder_ids(s, project) == {co, w.owner.user.id}


# ── The overrides that sit above sharing ─────────────────────────────────────


async def test_a_guild_admin_bypasses_the_scope_gate(
    session, role_session, acting_user
):
    """Guild admin is full authority over the guild, membership of the
    initiative or not."""
    w = await build_world(session, role_session, acting_user, Tool.project)
    await w.grant(None)
    row, context = await w.as_reader(w.admin.user)
    require_access(w.resource, row, context=context, access="write")
    require_access(w.resource, row, context=context, require_owner=True)


def test_a_standing_for_another_community_is_never_read_back():
    """A standing means nothing outside the community it was computed in.

    The binding is where the context is read off the session: one routed into
    guild B is handed no standing computed for guild A, so an admin of A
    reaches nothing here by carrying theirs along.
    """

    class _Session:
        def __init__(self, params):
            self.info = {_RLS_PARAMS_INFO_KEY: params}

    held = standing(7, admin=True)
    assert db_session.guild_context(_Session({"guild_id": 7, "context": held})) is held
    assert db_session.guild_context(_Session({"guild_id": 9, "context": held})) is None


async def test_a_platform_owner_holds_no_standing_bypass(
    session, role_session, acting_user
):
    """``data.bypass`` is the right to break glass, not an ambient reach — a
    platform owner with no grant on the row is admitted nothing."""
    w = await build_world(session, role_session, acting_user, Tool.project)
    await w.grant(None)
    w.co_member.user.role = UserRole.owner
    session.add(w.co_member.user)
    await session.commit()
    row, _ = await w.as_reader(w.co_member.user)
    assert row is None


async def test_a_frozen_guild_caps_everyone_at_read(session, role_session, acting_user):
    """A read_only guild refuses every change — before the level is read, so
    full authority does not clear the hold — and still lets its owner export,
    which changes nothing.

    ``guild_suspension_test`` covers the same hold end-to-end through an
    endpoint; this pins where in the engine the cap sits.
    """
    w = await build_world(session, role_session, acting_user, Tool.project)
    await w.grant("owner", user=w.owner.user)
    await _freeze(session, w.guild)

    row, context = await w.as_reader(w.owner.user)
    assert context.content_read_only
    assert client_access(row, context.user_id, context=context) == {
        "edit": False,
        "delete": False,
        "share": False,
        "export": True,
        "unarchive": False,
    }
    require_access(w.resource, row, context=context, access="read")
    assert (
        refused(w.resource, row, context=context, access="write").detail
        == w.resource.write_msg
    )
    refused(w.resource, row, context=context, require_owner=True)

    row, context = await w.as_reader(w.admin.user)
    assert not client_access(row, context.user_id, context=context)["edit"]
    refused(w.resource, row, context=context, access="write")


# ── The clauses that survive the policies ───────────────────────────────────
#
# A statement confined to one initiative asks nothing: the table's own policy
# already applied the sharing gate. What is left here is the listing rule for a
# statement that SPANS initiatives, which is narrower than the policy on
# purpose, and the writable rule, which is narrower than any read policy.


def _compiled(clause: ColumnElement[bool]) -> str:
    return str(clause.compile(compile_kwargs={"literal_binds": True}))


def test_a_confined_listing_adds_nothing():
    """Named an initiative, the clause is a no-op whoever is asking.

    The rows come from a table whose policy has already asked gate 4, so a
    second copy of the question could only cost a query.
    """
    for context in (None, standing(7), standing(7, admin=True)):
        assert (
            _compiled(
                listing_scope_clause(
                    Tool.project, Project.id, 1, context=context, initiative_id=3
                )
            )
            == "true"
        )


def test_a_listing_across_initiatives_still_narrows_a_guild_admin():
    """Spanning initiatives, the question is what reaches the reader.

    A guild admin's authority is not a leg here — their sidebar lists what was
    shared with them, and they reach the rest by naming an initiative.
    """
    sql = _compiled(
        listing_scope_clause(
            Tool.project, Project.id, 1, context=standing(7, admin=True)
        )
    )
    assert sql != "true"
    assert "resource_grants" in sql


def test_a_pam_window_is_a_no_op_across_initiatives():
    """A grantee holds no membership and no grant row, so the grant legs would
    answer nothing at all — the window is what they navigate by."""
    assert (
        _compiled(
            granted_scope_clause(
                Tool.document, Document.id, 1, context=standing(7, grant="read")
            )
        )
        == "true"
    )


def test_the_window_opens_only_at_the_level_it_was_issued_at():
    """A read grant is a no-op for a read and not for a write."""
    read = standing(7, grant="read")
    assert (
        _compiled(granted_scope_clause(Tool.project, Project.id, 1, context=read))
        == "true"
    )
    assert (
        _compiled(
            granted_scope_clause(
                Tool.project, Project.id, 1, context=read, access="write"
            )
        )
        != "true"
    )
    assert (
        _compiled(
            granted_scope_clause(
                Tool.project,
                Project.id,
                1,
                context=standing(7, grant="read_write"),
                access="write",
            )
        )
        == "true"
    )


def test_no_standing_at_all_narrows_rather_than_opens():
    """A request with nothing behind it asks the grant rows, like a stranger."""
    assert (
        _compiled(granted_scope_clause(Tool.project, Project.id, 1, context=None))
        != "true"
    )


def test_the_writable_clause_asks_the_gate_when_confined():
    """Unlike the read listing, this one still has something to ask.

    A read policy admits a row shared at any level, so "which of these may I
    change" is a narrower question than the one already answered. Confined to
    one initiative it is the table's own gate, asked at write.
    """
    sql = _compiled(
        writable_scope_clause(
            Tool.project, Project.id, 1, context=standing(7), initiative_id=3
        )
    )
    assert sql != "true"
    assert "resource_access(" in sql
    assert ", true, (SELECT current_standing()" in sql


def test_the_writable_clause_spanning_initiatives_filters_the_grant_rows():
    sql = _compiled(writable_scope_clause(Tool.project, Project.id, 1, context=None))
    assert "resource_grants" in sql
    assert "'write'" in sql and "'owner'" in sql


@pytest.mark.parametrize("tool", list(Tool))
def test_every_tool_can_be_scoped(tool):
    """Every tool in the registry resolves through the clause, so a tool added
    later inherits the same listing rule."""
    sql = _compiled(granted_scope_clause(tool, Project.id, 1, context=standing(7)))
    assert "resource_grants" in sql
    assert tool.value in sql


def test_the_grants_subquery_has_one_home():
    """``_granted_resource_ids`` is private so the composition happens in one
    place — the clause builders in ``permissions.py`` and nowhere else."""
    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if path.name not in {"permissions.py", "permissions_test.py"}
        and "_granted_resource_ids" in path.read_text()
    ]
    assert offenders == [], (
        "these modules reach for the grants subquery directly instead of the "
        f"clause builders in permissions.py: {offenders}"
    )


# ---------------------------------------------------------------------------
# The audience — who a resource's sharing reaches
# ---------------------------------------------------------------------------


class _Grant:
    def __init__(self, *, level="read", user_id=None, role_id=None, all_members=False):
        self.level = level
        self.user_id = user_id
        self.role_id = role_id
        self.all_initiative_members = all_members


class _Membership:
    def __init__(self, user_id, role_id=None):
        self.user_id = user_id
        self.role_id = role_id


class _Initiative:
    def __init__(self, memberships):
        self.memberships = memberships


class _Row:
    """The two collections the audience reads."""

    def __init__(self, grants, memberships, initiative_id=1):
        self.grants = grants
        self.initiative = _Initiative(memberships)
        self.initiative_id = initiative_id


async def test_the_audience_is_exactly_who_the_database_admits(
    session, role_session, acting_user
):
    """The invariant the post notifier hangs on.

    ``audience_user_ids`` reads the roster and the grant rows; the database
    reads the same rows when a member asks for the notice. A notifier built
    on the first must not address anyone the second would turn away, and must
    not miss anyone it would admit.
    """
    w = await build_world(session, role_session, acting_user, Tool.post)
    named = w.co_member
    by_role = w.owner  # the creator holds the manager role
    unnamed = await acting_user(
        guild_role=GuildRole.member,
        guild=w.guild,
        initiative=w.initiative,
        initiative_role="member",
    )
    departed = await acting_user(guild_role=GuildRole.member, guild=w.guild)

    await w.grant("owner", user=named.user)
    await create_resource_grant(
        session,
        w.row,
        role_id=await _role_id_of(session, w.initiative, by_role.user),
        level=ResourceAccessLevel.write,
    )
    # Named, but not a member of the initiative.
    await create_resource_grant(session, w.row, user=departed.user)

    post = await posts_service.get_post(session, w.row_id)
    assert post is not None
    audience = audience_user_ids(post)
    assert audience == {named.user.id, by_role.user.id}

    for actor in (named, by_role, unnamed, departed):
        row, _ = await w.as_reader(actor.user)
        assert (row is not None) is (actor.user.id in audience), actor.user.id


def test_an_all_members_grant_reaches_every_member():
    everyone = [_Membership(1), _Membership(2), _Membership(3)]
    row = _Row(grants=[_Grant(all_members=True)], memberships=everyone)
    assert audience_user_ids(row) == {1, 2, 3}


def test_a_resource_shared_with_nobody_has_no_audience():
    """Posting to a board nobody can read interrupts nobody, rather than
    falling back to the roster."""
    row = _Row(grants=[], memberships=[_Membership(1), _Membership(2)])
    assert audience_user_ids(row) == set()


def test_a_named_grant_does_not_outlive_the_membership():
    """A grant survives the membership it was written for — leaving an
    initiative sweeps no grants — and RLS answers the leftover with 404. An
    audience built on the grant alone would carry a headline and an excerpt to
    somebody who can no longer open the thing they name.
    """
    row = _Row(
        grants=[_Grant(user_id=1), _Grant(user_id=2)],
        memberships=[_Membership(1)],
    )

    assert audience_user_ids(row) == {1}


def test_an_all_members_grant_names_the_roster_as_it_is_now():
    row = _Row(grants=[_Grant(all_members=True)], memberships=[_Membership(4)])
    assert audience_user_ids(row) == {4}

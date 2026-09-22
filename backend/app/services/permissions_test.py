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
from app.core.tools import Tool
from app.db import session as db_session
from app.db.guild_standing import GuildContext
from app.db.session import _RLS_PARAMS_INFO_KEY
from app.models.platform.guild import Guild, GuildRole
from app.models.platform.user import UserRole
from app.models.tenant.document import Document
from app.models.tenant.initiative import InitiativeMember
from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceGrant
from app.services.permissions import (
    DAC_RESOURCES,
    audience_user_ids,
    compute_permission,
    effective_level,
    granted_scope_clause,
    has_project_write_access,
    listing_scope_clause,
    require_access,
    writable_scope_clause,
)
from app.testing.factories import TOOL_FACTORIES

ALL_TOOLS = list(DAC_RESOURCES)

# The canonical per-tool factory registry rather than a copy of it: that one
# is checked against the Tool enum at import time, so a new tool cannot reach
# these parametrized cases without a factory behind it.
_TOOL_FACTORIES = TOOL_FACTORIES


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

    factory = _TOOL_FACTORIES[tool]
    row = await factory(session, initiative, owner.user)
    return World(session, tool, guild, initiative, row, owner, co_member, admin)


def standing(
    guild=None,
    *,
    admin: bool = False,
    grant: str | None = None,
    read_only: bool = False,
    overrides: tuple[int, ...] = (),
) -> GuildContext | None:
    """A reader's standing in one community, shaped as the seam computes it.

    ``None`` is a request with no standing anywhere — the shape every leg of a
    DAC decision answers no to. Each case builds the one it is about and hands
    the same object to every check it makes, the way an endpoint hands down the
    context its session was routed with.
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


# ── Every tool resolves sharing through the same engine ──────────────────────


@pytest.mark.integration
@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.value)
async def test_every_tool_resolves_sharing_through_one_engine(
    session, acting_user, tool: Tool
):
    """Each tool answers the same questions the same way, with the refusal
    messages its registry entry names.

    A tool reaches the engine through its ``DAC_RESOURCES`` entry and its
    ``RESOURCE_ACCESS`` loader, so a tool added later inherits this behaviour by
    registering rather than by re-implementing it.
    """
    w = await build_world(session, acting_user, tool)
    resource = w.resource

    member = standing(w.guild)

    # The holder of the owner grant.
    loaded = await w.grant("owner", user=w.owner.user)
    require_access(resource, loaded, w.owner.user, context=member, access="write")
    assert compute_permission(resource, loaded, w.owner.user.id, context=member) == (
        "owner"
    )

    # An initiative co-member with no grant on this resource.
    assert compute_permission(
        resource, loaded, w.co_member.user.id, context=member
    ) is (None)
    assert (
        refused(
            resource, loaded, w.co_member.user, context=member, access="read"
        ).detail
        == resource.denied_msg
    )

    # A guild admin needs no grant at all.
    as_admin = standing(w.guild, admin=True)
    require_access(resource, loaded, w.admin.user, context=as_admin, access="write")
    require_access(resource, loaded, w.admin.user, context=as_admin, require_owner=True)
    assert compute_permission(resource, loaded, w.admin.user.id, context=as_admin) == (
        "owner"
    )

    # A PAM read grant opens the guild for reading only. The grantee holds no
    # grant row, so the write stops at the same "nothing shared with you" answer
    # a stranger gets rather than at the level check.
    grantee = standing(w.guild, grant="read")
    require_access(resource, loaded, w.co_member.user, context=grantee, access="read")
    assert (
        refused(
            resource, loaded, w.co_member.user, context=grantee, access="write"
        ).detail
        == resource.denied_msg
    )

    # Holding a read grant of their own is where the level check answers, and it
    # names the tool's own write message.
    loaded = await w.grant("read", user=w.co_member.user)
    require_access(resource, loaded, w.co_member.user, context=member, access="read")
    assert (
        refused(
            resource, loaded, w.co_member.user, context=member, access="write"
        ).detail
        == resource.write_msg
    )
    assert (
        refused(
            resource, loaded, w.co_member.user, context=member, require_owner=True
        ).detail
        == resource.owner_msg
    )


# ── How a grant resolves ─────────────────────────────────────────────────────


@pytest.mark.integration
async def test_a_role_grant_elevates_over_a_users_own(session, acting_user):
    """A grant to an initiative role the user holds outranks their own lower
    grant — the two combine by taking the higher."""
    w = await build_world(session, acting_user, Tool.project)
    member = standing(w.guild)

    role_id = await _role_id_of(session, w.initiative, w.co_member.user)
    loaded = await w.grant("read", user=w.co_member.user)
    assert compute_permission(
        w.resource, loaded, w.co_member.user.id, context=member
    ) == ("read")

    session.add(
        ResourceGrant(
            initiative_id=w.initiative_id,
            resource_type=Tool.project,
            resource_id=w.row_id,
            role_id=role_id,
            level="write",
        )
    )
    await session.commit()
    loaded = await w.load()
    assert compute_permission(
        w.resource, loaded, w.co_member.user.id, context=member
    ) == ("write")


@pytest.mark.integration
async def test_general_access_covers_the_initiatives_members_only(session, acting_user):
    """An all-initiative-members grant reaches every member without naming them,
    and stops at the initiative boundary."""
    w = await build_world(session, acting_user, Tool.project)
    outsider = await acting_user(guild_role=GuildRole.member, guild=w.guild)
    member = standing(w.guild)

    loaded = await w.grant("write", everyone=True)
    assert compute_permission(
        w.resource, loaded, w.co_member.user.id, context=member
    ) == ("write")
    require_access(w.resource, loaded, w.co_member.user, context=member, access="write")

    assert (
        compute_permission(w.resource, loaded, outsider.user.id, context=member) is None
    )
    refused(w.resource, loaded, outsider.user, context=member, access="read")


@pytest.mark.integration
async def test_membership_alone_grants_nothing(session, acting_user):
    """The gate is an AND-layer: being in the initiative is not access to its
    resources."""
    w = await build_world(session, acting_user, Tool.project)
    member = standing(w.guild)
    loaded = await w.grant(None)
    assert (
        compute_permission(w.resource, loaded, w.co_member.user.id, context=member)
        is None
    )
    refused(w.resource, loaded, w.co_member.user, context=member, access="read")


@pytest.mark.integration
@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.value)
async def test_a_grant_left_behind_after_removal_reaches_nothing(
    session, acting_user, reading_as, tool: Tool
):
    """A grant row outliving the user's initiative membership carries no access.

    Leaving an initiative does not sweep the grants written for you, so the row
    is still there naming you at owner. What answers it is the table's own
    policy: every content table ANDs ``initiative_access`` onto its
    sharing leg, so the resource stops being visible the moment the membership
    goes — asserted against the database on the request login, because that is
    where the answer comes from.
    """
    w = await build_world(session, acting_user, tool)
    await w.grant("owner", user=w.co_member.user)
    model = type(w.row)

    async def visible() -> bool:
        reader = await reading_as(w.co_member.user.id, w.guild.id)
        rows = (await reader.exec(select(model.id).where(model.id == w.row.id))).all()
        await reader.rollback()
        return bool(rows)

    assert await visible(), "the grant should reach it while the membership stands"

    await _remove_from_initiative(session, w.initiative, w.co_member.user)
    assert not await visible(), (
        "a grant that outlived the membership must reach nothing"
    )


@pytest.mark.integration
async def test_has_project_write_access_tracks_the_level(session, acting_user):
    """The synchronous filter helper agrees with the engine about who may write."""
    w = await build_world(session, acting_user, Tool.project)
    member = standing(w.guild)
    for level, expected in (("owner", True), ("write", True), ("read", False)):
        loaded = await w.grant(level, user=w.co_member.user)
        assert (
            has_project_write_access(loaded, w.co_member.user, context=member)
            is expected
        )
    loaded = await w.grant(None)
    assert has_project_write_access(loaded, w.co_member.user, context=member) is False


# ── The overrides that sit above sharing ─────────────────────────────────────


@pytest.mark.integration
async def test_a_guild_admin_bypasses_the_scope_gate(session, acting_user):
    """Guild admin is full authority over the guild, membership of the
    initiative or not."""
    w = await build_world(session, acting_user, Tool.project)
    loaded = await w.grant(None)
    await _remove_from_initiative(session, w.initiative, w.co_member.user)
    loaded = await w.load()

    as_admin = standing(w.guild, admin=True)
    require_access(
        w.resource, loaded, w.co_member.user, context=as_admin, access="write"
    )
    require_access(
        w.resource, loaded, w.co_member.user, context=as_admin, require_owner=True
    )


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


@pytest.mark.integration
async def test_a_platform_owner_holds_no_standing_bypass(session, acting_user):
    """``data.bypass`` is the right to break glass, not an ambient reach — a
    platform owner with no membership and no live grant is refused."""
    w = await build_world(session, acting_user, Tool.project)
    loaded = await w.grant(None)
    w.co_member.user.role = UserRole.owner
    session.add(w.co_member.user)
    await session.commit()
    refused(
        w.resource, loaded, w.co_member.user, context=standing(w.guild), access="read"
    )


@pytest.mark.integration
async def test_a_pam_grant_lifts_the_level_and_never_bleeds(session, acting_user):
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

    assert compute_permission(w.resource, loaded, stranger_id, context=None) is None
    assert (
        compute_permission(
            w.resource, loaded, stranger_id, context=standing(w.guild, grant="read")
        )
        == "read"
    )
    assert (
        compute_permission(
            w.resource,
            loaded,
            stranger_id,
            context=standing(w.guild, grant="read_write"),
        )
        == "write"
    )


@pytest.mark.integration
async def test_a_pam_grant_never_downgrades_an_owner(session, acting_user):
    """An explicit owner grant outranks the write a read_write grant implies."""
    w = await build_world(session, acting_user, Tool.project)
    loaded = await w.grant("owner", user=w.co_member.user)
    assert (
        compute_permission(
            w.resource,
            loaded,
            w.co_member.user.id,
            context=standing(w.guild, grant="read_write"),
        )
        == "owner"
    )


@pytest.mark.integration
async def test_a_frozen_guild_caps_everyone_at_read(session, acting_user):
    """A read_only guild caps the level the client sees and refuses every write
    — checked before the admin leg, so full authority does not clear the hold.

    ``guild_suspension_test`` covers the same hold end-to-end through an
    endpoint; this pins where in the engine the cap sits.
    """
    w = await build_world(session, acting_user, Tool.project)
    loaded = await w.grant("owner", user=w.owner.user)

    frozen = standing(w.guild, read_only=True)

    assert compute_permission(w.resource, loaded, w.owner.user.id, context=frozen) == (
        "read"
    )
    require_access(w.resource, loaded, w.owner.user, context=frozen, access="read")
    assert (
        refused(w.resource, loaded, w.owner.user, context=frozen, access="write").detail
        == w.resource.write_msg
    )
    refused(w.resource, loaded, w.owner.user, context=frozen, require_owner=True)

    frozen_admin = standing(w.guild, admin=True, read_only=True)
    assert (
        compute_permission(w.resource, loaded, w.admin.user.id, context=frozen_admin)
        == "read"
    )
    refused(w.resource, loaded, w.admin.user, context=frozen_admin, access="write")


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


def test_the_writable_clause_does_not_collapse_when_confined():
    """Unlike the read listing, this one still has something to ask.

    A read policy admits a row shared at any level, so "which of these may I
    change" is a narrower question than the one already answered — the grant
    rows have to be filtered by level whatever the scope.
    """
    sql = _compiled(
        writable_scope_clause(
            Tool.project, Project.id, 1, context=standing(7), initiative_id=3
        )
    )
    assert sql != "true"
    assert "resource_grants" in sql


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
    """The two collections both the audience and the access check read."""

    def __init__(self, grants, memberships, initiative_id=1):
        self.grants = grants
        self.initiative = _Initiative(memberships)
        self.initiative_id = initiative_id


def test_the_audience_is_exactly_who_the_access_check_would_admit():
    """The invariant the post notifier hangs on.

    ``audience_user_ids`` and ``effective_level`` read the same rows and must
    not drift: a notifier built on the first must not address anyone the second
    would turn away, and must not miss anyone it would admit.
    """
    everyone = [_Membership(1, role_id=10), _Membership(2, role_id=20), _Membership(3)]
    row = _Row(
        grants=[
            _Grant(user_id=1, level="owner"),
            _Grant(role_id=20, level="write"),
            _Grant(user_id=99),  # named, but not a member of the initiative
        ],
        memberships=everyone,
    )

    audience = audience_user_ids(row)
    resource = DAC_RESOURCES[Tool.post]
    # Everyone the audience names can in fact reach it...
    for user_id in audience:
        assert effective_level(resource, row, user_id) is not None
    # ...and every MEMBER it leaves out cannot. (A grant naming somebody who is
    # no longer in the initiative passes this check and still fails RLS, which
    # is why the audience is narrowed to the roster — see the case below.)
    for member in everyone:
        if member.user_id not in audience:
            assert effective_level(resource, row, member.user_id) is None
    assert audience == {1, 2}


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

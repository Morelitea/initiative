"""Content ownership — who administers a tool, and what happens when they leave.

Ownership and authorship are different things, and this module only deals with
the first:

- **Author** — who wrote it: ``created_by``, one column on every guild table
  that records one (:class:`CreatedByMixin`). A historical fact. Nothing here
  ever changes one.
- **Owner** — who administers it: the ``resource_grants`` row at
  ``level='owner'``. A live permission, and the only thing this module moves.

Comments, tasks and uploads have an author and no owner at all; they are
administered through the tool that holds them. The members of :class:`Tool` are
exactly the things that have an owner, so :data:`OWNABLE` derives from that enum
and ``ownership_test.py`` fails if a tool is ever missing from it.

**Ownership is optional.** There is no "ownerless" grant row — the
``resource_grants_one_grantee`` constraint requires every row to name a user, a
role, or all members — so having no owner is the *absence* of an owner grant,
which is also the honest way to say it. Two rules follow:

    An owner is always a current member of the guild, or there is no owner.

Leaving a guild drops the person's owner grants rather than handing them to
someone else: nobody inherits privilege they did not ask for, which matters most
in a guild with heavy turnover. Guild admins still administer unowned content
through their guild-admin authority, and can claim it whenever they choose.
"""

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select as sa_select
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.guild import GuildMembership
from app.models.tenant.calendar import Calendar
from app.models.tenant.counter import CounterGroup
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.post import Post
from app.models.tenant.document import Document
from app.models.tenant.project import Project
from app.models.tenant.queue import Queue
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant


@dataclass(frozen=True)
class OwnableSpec:
    """Where one tool's rows live.

    That is the whole per-tool variation: no model carries an owner column, so
    finding who owns a row is the same query for every tool. The label shown for
    a row comes from ``SoftDeleteMixin.display_field()``, which already names it
    for the trash can and the recents bar.
    """

    model: Any

    @property
    def display_column(self) -> str:
        return self.model.display_field()


OWNABLE: dict[Tool, OwnableSpec] = {
    Tool.project: OwnableSpec(Project),
    Tool.document: OwnableSpec(Document),
    Tool.queue: OwnableSpec(Queue),
    Tool.counter_group: OwnableSpec(CounterGroup),
    Tool.calendar: OwnableSpec(Calendar),
    Tool.dashboard: OwnableSpec(Dashboard),
    Tool.post: OwnableSpec(Post),
}


# Reverse of OWNABLE, so a row can name its own tool.
TOOL_BY_MODEL: dict[Any, Tool] = {spec.model: tool for tool, spec in OWNABLE.items()}


def tool_for_row(row: Any) -> Optional[Tool]:
    """The :class:`Tool` this row is an instance of, or None if it is not one.

    Tasks, comments and uploads land here as None — they have an author and no
    owner, and are administered through the tool that holds them.
    """
    return TOOL_BY_MODEL.get(type(row))


@dataclass(frozen=True)
class OwnedItem:
    tool: Tool
    id: int
    name: str


def owner_id_of(row: Any) -> Optional[int]:
    """The user holding this resource's owner grant, or None if nobody does.

    Reads ``row.grants``, which the caller must have eagerly loaded — this is
    deliberately a function rather than a model property so that requirement is
    visible at the call site instead of turning into a lazy load that fails
    under async.
    """
    for grant in row.grants or []:
        if grant.user_id is not None and grant.level == ResourceAccessLevel.owner:
            return grant.user_id
    return None


# ── Reading what is owned ────────────────────────────────────────────────────


def _owner_grant_resource_ids(tool: Tool, user_id: Optional[int] = None):
    stmt = sa_select(ResourceGrant.resource_id).where(
        ResourceGrant.resource_type == tool.value,
        ResourceGrant.level == ResourceAccessLevel.owner,
    )
    if user_id is not None:
        stmt = stmt.where(ResourceGrant.user_id == user_id)
    else:
        stmt = stmt.where(ResourceGrant.user_id.is_not(None))
    return stmt


async def _owned_rows(session: AsyncSession, tool: Tool, user_id: int) -> list[Any]:
    """Rows of ``tool`` whose owner grant names this user."""
    model = OWNABLE[tool].model
    stmt = select(model).where(model.id.in_(_owner_grant_resource_ids(tool, user_id)))
    return list((await session.exec(stmt)).unique().all())


async def _unowned_rows(
    session: AsyncSession, tool: Tool, *, guild_id: int
) -> list[Any]:
    """Rows of ``tool`` that no current member of the guild owns.

    Two situations, one condition, because they are the same problem: the
    resource has no owner grant at all (a member left and released it), or its
    owner grant names someone who is no longer in the guild (content orphaned
    before ownership was released on departure). Either way nobody who can act
    on it owns it, and an admin claiming it is the same click.
    """
    member_ids = sa_select(GuildMembership.user_id).where(
        GuildMembership.guild_id == guild_id
    )
    owned_by_member = sa_select(ResourceGrant.resource_id).where(
        ResourceGrant.resource_type == tool.value,
        ResourceGrant.level == ResourceAccessLevel.owner,
        ResourceGrant.user_id.in_(member_ids),
    )
    stmt = select(OWNABLE[tool].model).where(
        OWNABLE[tool].model.id.not_in(owned_by_member)
    )
    return list((await session.exec(stmt)).unique().all())


def _as_items(tool: Tool, rows: list[Any]) -> list[OwnedItem]:
    column = OWNABLE[tool].display_column
    return [
        OwnedItem(tool=tool, id=row.id, name=getattr(row, column, None) or "")
        for row in rows
    ]


async def summarize_owned_content(
    session: AsyncSession, user_id: int
) -> list[OwnedItem]:
    """Everything this user owns in the routed guild, tool by tool. The session
    must already be routed into the guild's schema."""
    items: list[OwnedItem] = []
    for tool in OWNABLE:
        items.extend(_as_items(tool, await _owned_rows(session, tool, user_id)))
    return items


async def summarize_unowned_content(
    session: AsyncSession, *, guild_id: int
) -> list[OwnedItem]:
    """Everything in the guild that no current member owns — what a guild admin
    watches accumulate as people leave, and can claim in one go."""
    items: list[OwnedItem] = []
    for tool in OWNABLE:
        items.extend(
            _as_items(tool, await _unowned_rows(session, tool, guild_id=guild_id))
        )
    return items


# ── Changing it ──────────────────────────────────────────────────────────────


async def _clear_owner_grants(session: AsyncSession, *, tool: Tool, row: Any) -> None:
    """Drop every user-held owner grant on one resource.

    Every one, not just the one the owner column names: the re-homing paths this
    replaced could leave several rows at owner level on a single resource, and
    "the owner" has to mean one person or nobody.
    """
    grants = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == tool.value,
                ResourceGrant.resource_id == row.id,
                ResourceGrant.user_id.is_not(None),
                ResourceGrant.level == ResourceAccessLevel.owner,
            )
        )
    ).all()
    for grant in grants:
        await session.delete(grant)
    # Flush the deletes before any new owner row is added. The unit of work
    # orders INSERTs ahead of DELETEs, so without this the incoming owner
    # collides with the outgoing one on the single-owner index.
    if grants:
        await session.flush()


async def set_resource_owner(
    session: AsyncSession, *, tool: Tool, row: Any, new_owner_id: Optional[int]
) -> None:
    """Make ``new_owner_id`` the resource's owner, or leave it unowned when None.
    Caller commits.

    Clears any existing owner grant, then gives the recipient one at ``owner`` —
    upgrading a lower grant they already hold rather than colliding with the
    ``resource_grants_unique_grantee`` constraint. Author columns are not
    touched: who wrote the thing does not change when who administers it does.
    """
    await _clear_owner_grants(session, tool=tool, row=row)

    if new_owner_id is None:
        await session.flush()
        return

    existing = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == tool.value,
                ResourceGrant.resource_id == row.id,
                ResourceGrant.user_id == new_owner_id,
            )
        )
    ).one_or_none()
    if existing is not None:
        existing.level = ResourceAccessLevel.owner
        session.add(existing)
    else:
        session.add(
            ResourceGrant(
                resource_type=tool.value,
                resource_id=row.id,
                user_id=new_owner_id,
                role_id=None,
                level=ResourceAccessLevel.owner,
                guild_id=row.guild_id,
                initiative_id=row.initiative_id,
            )
        )
    await session.flush()


async def current_owner_id(
    session: AsyncSession, *, tool: Tool, resource_id: int
) -> Optional[int]:
    """Who owns this resource right now, straight from the grants.

    Unlike :func:`owner_id_of` this issues a query, for callers holding a row
    whose grants were never loaded.
    """
    return (
        await session.exec(
            select(ResourceGrant.user_id).where(
                ResourceGrant.resource_type == tool.value,
                ResourceGrant.resource_id == resource_id,
                ResourceGrant.level == ResourceAccessLevel.owner,
            )
        )
    ).one_or_none()


async def restore_ownership_to_author(
    session: AsyncSession, *, row: Any, guild_id: int
) -> bool:
    """Give an unowned resource back to whoever wrote it, if they are still here.

    A convenience for restoring from the trash: content trashed before its owner
    left the guild comes back unowned, and the author is the one non-arbitrary
    person to hand it to. Does nothing when the row already has an owner, when
    the row records no author, or when that author has since left — there is no
    second-guess, the content simply stays unowned.

    Returns whether an owner was set. Caller commits.
    """
    tool = tool_for_row(row)
    if tool is None:
        return False

    # Every tool carries CreatedByMixin, so once tool_for_row has answered there
    # is a created_by to read (ownership_test pins that).
    author_id = row.created_by
    if author_id is None:
        return False

    if await current_owner_id(session, tool=tool, resource_id=row.id) is not None:
        return False

    still_a_member = (
        await session.exec(
            select(GuildMembership.user_id).where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.user_id == author_id,
            )
        )
    ).one_or_none()
    if still_a_member is None:
        return False

    await set_resource_owner(session, tool=tool, row=row, new_owner_id=author_id)
    return True


async def transfer_content_ownership(
    session: AsyncSession, *, from_user_id: int, to_user_id: int
) -> dict[Tool, int]:
    """Move everything ``from_user_id`` owns in the routed guild to
    ``to_user_id``. Returns a per-tool count of what moved. Caller commits."""
    moved: dict[Tool, int] = {}
    for tool in OWNABLE:
        rows = await _owned_rows(session, tool, from_user_id)
        for row in rows:
            await set_resource_owner(
                session, tool=tool, row=row, new_owner_id=to_user_id
            )
        if rows:
            moved[tool] = len(rows)
    return moved


async def claim_unowned_content(
    session: AsyncSession, *, guild_id: int, to_user_id: int
) -> dict[Tool, int]:
    """Give every resource no current member owns to ``to_user_id``.
    Returns a per-tool count. Caller commits."""
    claimed: dict[Tool, int] = {}
    for tool in OWNABLE:
        rows = await _unowned_rows(session, tool, guild_id=guild_id)
        for row in rows:
            await set_resource_owner(
                session, tool=tool, row=row, new_owner_id=to_user_id
            )
        if rows:
            claimed[tool] = len(rows)
    return claimed


async def release_owned_content(
    session: AsyncSession, *, user_id: int
) -> dict[Tool, int]:
    """Leave everything this user owns in the routed guild unowned.

    The departure hook, called from ``remove_user_from_guild_initiatives`` — the
    choke point every guild-departure path funnels through — so leaving, being
    removed, being deactivated, anonymized, hard-deleted or revoked by OIDC sync
    all land the same way.

    Being removed from a single *initiative* is not a departure in this sense:
    the person is still in the guild, their content simply stops being reachable
    by them, and nothing here runs.
    """
    released: dict[Tool, int] = {}
    for tool in OWNABLE:
        rows = await _owned_rows(session, tool, user_id)
        for row in rows:
            await set_resource_owner(session, tool=tool, row=row, new_owner_id=None)
        if rows:
            released[tool] = len(rows)
    return released


__all__ = [
    "OWNABLE",
    "current_owner_id",
    "owner_id_of",
    "restore_ownership_to_author",
    "tool_for_row",
    "OwnableSpec",
    "OwnedItem",
    "claim_unowned_content",
    "release_owned_content",
    "set_resource_owner",
    "summarize_owned_content",
    "summarize_unowned_content",
    "transfer_content_ownership",
]

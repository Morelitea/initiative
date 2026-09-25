"""Who may be told about a thing.

A notice names what it is about — a task's title, a document's name, the
thread somebody wrote in — so it goes to people who can open that thing now.
Every content notifier asks here before it resolves a recipient, so the people
a notice reaches are the people its sharing reaches.

Two answers, for two kinds of notice:

* :func:`audience` is who the thing was shared *with*, checked against the
  roster as it stands. It is the audience for news nobody asked for — a project
  was shared with you, a notice went up on a board — and it is
  :func:`app.services.permissions.audience_user_ids` over a freshly loaded row,
  so the fan-out and the per-row check read one rule.
* :func:`readers` adds the community's admins, who reach everything in it. It is
  the check for a notice addressed to a person — a mention, a reply, a comment
  on something of theirs — which goes to anybody who can open the thing.

Both read through the caller's session, routed into the community the thing
lives in.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.db.session import routed_guild_id
from app.models.platform.guild import GUILD_ADMIN_ROLES, GuildMembership
from app.models.tenant._mixins import tool_models
from app.models.tenant.initiative import Initiative
from app.services import permissions as permissions_service

#: What a notice is about, for the purpose of who may hear of it: the tool row
#: whose sharing answers for it. A task answers through its project, an event
#: through its calendar, a wiki page through its wiki.
Anchor = tuple[Tool, int]


async def _guild_member_ids(session: AsyncSession, *, admins_only: bool) -> set[int]:
    guild_id = routed_guild_id(session)
    if guild_id is None:
        return set()
    stmt = select(GuildMembership.user_id).where(GuildMembership.guild_id == guild_id)
    if admins_only:
        stmt = stmt.where(GuildMembership.role.in_(tuple(GUILD_ADMIN_ROLES)))
    return set((await session.exec(stmt)).all())


async def audience(session: AsyncSession, tool: Tool, resource_id: int) -> set[int]:
    """The people the thing is shared with, as of now.

    Empty when the row is gone or the session cannot reach it. A guild-level
    row (a community calendar) has no roster, so its sharing is read against
    the community's members instead: a grant to everyone there reaches them
    all, a grant to one person reaches that person while they still belong.
    """
    model = tool_models()[tool.plural]
    row = (
        await session.exec(
            select(model)
            .where(model.id == resource_id)  # type: ignore[attr-defined]
            .options(
                selectinload(model.grants),  # type: ignore[attr-defined]
                selectinload(model.initiative).selectinload(  # type: ignore[attr-defined]
                    Initiative.memberships
                ),
            )
        )
    ).one_or_none()
    if row is None:
        return set()
    if row.initiative_id is not None:
        return permissions_service.audience_user_ids(row)
    members = await _guild_member_ids(session, admins_only=False)
    shared: set[int] = set()
    for grant in row.grants or []:
        if grant.user_id is not None:
            shared.add(grant.user_id)
        elif grant.all_initiative_members:
            shared.update(members)
    return shared & members


async def readers(session: AsyncSession, tool: Tool, resource_id: int) -> set[int]:
    """Everybody who could open the thing now: its audience and the
    community's admins."""
    return await audience(session, tool, resource_id) | await _guild_member_ids(
        session, admins_only=True
    )


async def may_be_told(
    session: AsyncSession, anchor: Anchor | None, user_ids: Iterable[int | None]
) -> list[int]:
    """Of ``user_ids``, the ones who could open ``anchor`` now, in order.

    ``None`` names nothing a notice could be about, so nobody may be told.
    """
    if anchor is None:
        return []
    allowed = await readers(session, *anchor)
    seen: set[int] = set()
    out: list[int] = []
    for user_id in user_ids:
        if user_id is not None and user_id in allowed and user_id not in seen:
            seen.add(user_id)
            out.append(user_id)
    return out

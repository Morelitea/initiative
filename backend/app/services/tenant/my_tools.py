"""What a cross-guild "my tools" list is made of.

The My Tools page is the guild home's table with the guild boundary taken off:
one tool at a time, every community the reader belongs to. Each tool still
answers through its own ``/me/{tool}`` endpoint, because the row a queue
returns is not the row a project returns — but the *question* those endpoints
ask is one question, and it is asked here so the six of them cannot drift.

Two things a caller needs:

``scope_conditions``
    The WHERE legs one guild contributes: the tool's own master switch, what
    reaches this reader (:func:`permissions.granted_scope_clause` — the same
    leg the guild home's table uses), the search box, and the page's
    everything/made-by-me toggle.

``sort_merged`` / :func:`count_across_guilds`
    Ordering and counting over the merged result. Both happen in Python: ids
    are unique per schema, so a single statement cannot span guilds.
"""

from typing import Any, Callable, Optional, Sequence

from sqlalchemy import ColumnElement, func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import CORE_TOOLS, Tool
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.services import permissions as permissions_service
from app.services.cross_guild import gather_across_guilds, member_guild_ids
from app.services.tenant import search as search_service
from app.services.tenant.ownership import OWNABLE

#: What ``sort_by`` accepts on a cross-guild tool list.
#:
#: Shorter than :data:`tool_listing.TOOL_SORT_FIELDS` by one: a guild-wide list
#: orders in SQL and can join the initiative to order by its name, while a
#: cross-guild list is merged and ordered in Python over the summaries
#: themselves — and an initiative's name is not something a tool summary
#: carries. The page's initiative column therefore does not sort.
MY_TOOL_SORT_FIELDS = ("name", "updated_at", "created_at")


def tool_model(tool: Tool) -> Any:
    """The content model backing a tool.

    Reads the ownership registry rather than keeping a second copy of the
    mapping — that one already derives from :class:`Tool` and its own test
    fails if a tool is missing from it.
    """
    return OWNABLE[tool].model


def _tool_enabled_clause(tool: Tool, model: Any) -> Optional[ColumnElement[bool]]:
    """Rows whose tool is switched on for the initiative holding them.

    Core tools have no switch. For the rest the switch is the initiative
    column named by the tool's view permission — and a row belonging to no
    initiative (a guild calendar, mounted by an app) answers to no switch, so
    it is kept.
    """
    if tool in CORE_TOOLS:
        return None
    switch = getattr(Initiative, tool.view_permission)
    return or_(
        model.initiative_id.is_(None),
        model.initiative_id.in_(select(Initiative.id).where(switch.is_(True))),
    )


def scope_conditions(
    tool: Tool,
    *,
    user_id: int,
    guild_id: int,
    search: Optional[str] = None,
    created_by_me: bool = False,
) -> list[ColumnElement[bool]]:
    """The WHERE legs for one guild's contribution to a cross-guild tool list.

    Called once per guild from inside :func:`cross_guild.gather_across_guilds`,
    which has already routed the session into that guild's schema and
    established the reader's role there.
    """
    model = tool_model(tool)
    conditions: list[ColumnElement[bool]] = []

    enabled = _tool_enabled_clause(tool, model)
    if enabled is not None:
        conditions.append(enabled)

    if tool is Tool.project:
        # An archived project and a template are both off the working list;
        # the guild-wide project list says the same.
        conditions.append(Project.is_archived.is_(False))
        conditions.append(Project.is_template.is_(False))

    conditions.append(
        permissions_service.granted_scope_clause(
            tool, model.id, user_id, guild_id=guild_id
        )
    )

    name_match = search_service.tool_search_clause(tool, model.id, search)
    if name_match is not None:
        conditions.append(name_match)

    if created_by_me:
        # The page's other view: what the reader wrote, rather than everything
        # that reaches them. Authorship, not ownership — handing a document to
        # someone else does not take it out of the list of things you wrote.
        conditions.append(model.created_by == user_id)

    return conditions


def sort_merged(
    items: list,
    sort_by: Optional[str],
    sort_dir: Optional[str],
    *,
    default: Callable[[Any], Any],
    default_desc: bool = True,
) -> list:
    """Order a merged cross-guild list of tool summaries.

    ``id`` is always the descending tiebreak, applied as a separate stable
    pass so it holds whichever way the primary sort runs. A request that names
    none of :data:`MY_TOOL_SORT_FIELDS` is left in the tool's own default
    order, which each caller states.
    """
    items.sort(key=lambda row: row.id, reverse=True)
    reverse = sort_dir == "desc"
    if sort_by == "name":
        items.sort(key=lambda row: (row.name or "").lower(), reverse=reverse)
    elif sort_by == "updated_at":
        items.sort(key=lambda row: row.updated_at, reverse=reverse)
    elif sort_by == "created_at":
        items.sort(key=lambda row: row.created_at, reverse=reverse)
    else:
        items.sort(key=default, reverse=default_desc)
    return items


async def count_across_guilds(
    session: AsyncSession,
    current_user: User,
    *,
    guild_ids: Optional[Sequence[int]] = None,
    created_by_me: bool = False,
) -> dict[Tool, int]:
    """How much of each tool reaches this reader, across their communities.

    What the My Tools page's tabs are made of: a tool with nothing behind it
    gets no tab, so the page never offers a reader a table of nothing.
    """
    target_guilds = await member_guild_ids(
        session, current_user.id, restrict_to=guild_ids
    )
    totals: dict[Tool, int] = {tool: 0 for tool in Tool}

    async def _fetch(guild_session: AsyncSession, guild_id: int) -> list:
        for tool in Tool:
            model = tool_model(tool)
            conditions = scope_conditions(
                tool,
                user_id=current_user.id,
                guild_id=guild_id,
                created_by_me=created_by_me,
            )
            subquery = select(model.id).where(*conditions).subquery()
            count = (
                await guild_session.exec(select(func.count()).select_from(subquery))
            ).one()
            totals[tool] += count
        # The tallies accumulate above; the merge itself carries nothing.
        return []

    await gather_across_guilds(session, current_user.id, target_guilds, _fetch)
    return totals

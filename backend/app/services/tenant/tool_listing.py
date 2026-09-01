"""Search and ordering shared by the guild-wide tool lists.

The guild home shows one table for whichever tool is selected, so the six list
endpoints behind it have to order the same way: over the three columns that
table holds in common — name, initiative, last updated.

That belongs in SQL rather than in whichever page the caller happens to be
holding: a sort that only reaches the twenty rows in hand is not a sort of the
guild's work, it is a sort of the accident of pagination. Searching those lists
is ``search.tool_search_clause``, which reads the same index the search page
does.

Each tool keeps its own default order (a project's is the manual one its owner
dragged into place, a calendar's is by name), so a request that asks for none
of these is left exactly as it was.
"""

from typing import Optional

from sqlalchemy import func

from app.models.tenant.initiative import Initiative

#: What ``sort_by`` accepts on every guild-wide tool list.
TOOL_SORT_FIELDS = ("name", "initiative", "updated_at")


def apply_tool_order(
    statement,
    model,
    sort_by: Optional[str],
    sort_dir: Optional[str],
    *,
    default,
    initiative_joined: bool = False,
):
    """Order a tool list by one of :data:`TOOL_SORT_FIELDS`, else by ``default``.

    Ordering by initiative means ordering by its *name*, which is the column
    the table shows, so the statement is joined to ``Initiative`` for it —
    outer, because a tool may hold guild-level rows belonging to no initiative
    (calendars do). Pass ``initiative_joined`` where the caller already joined
    it. ``id`` is the tiebreak throughout, so a page boundary never splits two
    rows that compare equal.
    """
    if sort_by == "name":
        column = func.lower(model.name)
    elif sort_by == "initiative":
        column = func.lower(Initiative.name)
        if not initiative_joined:
            statement = statement.outerjoin(
                Initiative, model.initiative_id == Initiative.id
            )
    elif sort_by == "updated_at":
        column = model.updated_at
    else:
        return statement.order_by(*default)

    order = column.desc() if sort_dir == "desc" else column.asc()
    return statement.order_by(order.nulls_last(), model.id.desc())

"""What can be referred to, and how a reference is resolved.

A `#` link, a `[[ ]]` link and a smart chip all name the same thing: one row,
in one guild schema. Resolving one asks two questions — *what is it called now* and
*may this request see it* — and neither answer is written down here.

Both come from :data:`~app.db.search_index.SEARCH_SOURCES`, which every
searchable table already declares:

- ``title`` — the column holding the row's name (``name``, ``title``, ``label``).
- ``dac_tool`` / ``dac_id`` — the resource whose sharing governs the row, which
  is often its parent: a task is shared as part of its project.

So a tool added to that registry becomes referenceable, resolvable and gated
without an edit here. What this module states is only the shape of the
derivation, and the two kinds that are deliberately not referenceable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import Select, Table, func, null, select, text
from sqlmodel import SQLModel

from app.core.references import NOT_REFERENCEABLE
from app.core.search import SearchEntityType
from app.db.initiative_rls import INITIATIVE_PATHS
from app.db.search_index import SEARCH_SOURCES


def _table_for(entity_type: SearchEntityType) -> str:
    for table, source in SEARCH_SOURCES.items():
        if source.entity_type is entity_type:
            return table
    raise KeyError(entity_type)


def referenceable_types() -> tuple[SearchEntityType, ...]:
    """Every kind a reference can name, sorted."""
    return tuple(
        sorted(
            (
                source.entity_type
                for source in SEARCH_SOURCES.values()
                if source.entity_type not in NOT_REFERENCEABLE
            ),
            key=lambda t: t.value,
        )
    )


def title_column(entity_type: SearchEntityType):
    """The column holding what a row of this kind is called."""
    table = _table_for(entity_type)
    return SQLModel.metadata.tables[table].c[SEARCH_SOURCES[table].title]


def id_column(entity_type: SearchEntityType):
    """The column addressing a row of this kind."""
    return SQLModel.metadata.tables[_table_for(entity_type)].c["id"]


def _live(table: Table):
    """Rows that still exist. Trash is browsed, not linked to."""
    return table.c["deleted_at"].is_(None) if "deleted_at" in table.c else None


def visible_ids(
    entity_type: SearchEntityType, user_id: int, *, need_write: bool = False
) -> Select:
    """Ids of this kind that ``user_id`` may open, or may edit.

    Joins the row to the resource that governs it — its own, or its parent's —
    and asks ``public.resource_access``, the same function the tables' own RLS
    policies call. A kind with no sharing of its own (the guild's tags) is
    reachable by anyone who reached the schema, which is the whole gate for it.

    ``need_write`` asks the same question at edit level. It is the caller's to
    say, because reaching a thing and changing it are different questions and
    only the caller knows which it is asking.
    """
    table_name = _table_for(entity_type)
    source = SEARCH_SOURCES[table_name]
    table = SQLModel.metadata.tables[table_name]

    statement = select(table.c["id"])
    live = _live(table)
    if live is not None:
        statement = statement.where(live)

    if source.dac_tool is None:
        return statement

    resource = SQLModel.metadata.tables[source.dac_tool.plural]
    if resource is table:
        # The row IS the shared resource — a project, a document. Nothing to
        # join to; it answers for itself.
        return statement.where(
            func.resource_access(
                source.dac_tool.value,
                table.c["id"],
                user_id,
                table.c["initiative_id"],
                need_write,
            )
        )

    # The row is shared as part of its parent: a task by its project, an event
    # by its calendar. The pair naming that parent is the one the index stores.
    local = table.c[source.dac_id] if source.dac_id else table.c["id"]
    return statement.select_from(table.join(resource, resource.c["id"] == local)).where(
        func.resource_access(
            source.dac_tool.value,
            resource.c["id"],
            user_id,
            resource.c["initiative_id"],
            need_write,
        )
    )


@dataclass(frozen=True)
class Resolved:
    """What a reference turned out to name."""

    entity_type: SearchEntityType
    id: int
    title: str | None
    #: The initiative the row belongs to. None means one of two different
    #: things, which :attr:`scoped_kind` tells apart.
    initiative_id: int | None
    #: Whether rows of this kind belong to an initiative at all. A tag does not
    #: — it is the guild's own vocabulary — so it pairs with anything in the
    #: guild. A calendar event does, and a NULL there means this particular one
    #: sits on a guild calendar, which is guild-level content rather than
    #: initiative content.
    scoped_kind: bool


async def resolve_many(
    session, entity_type: SearchEntityType, ids: Sequence[int], *, user_id: int
) -> dict[int, Resolved]:
    """The rows of one kind this reader may open, keyed by id.

    One query for the lot. The initiative comes from the same
    ``INITIATIVE_PATHS`` entry that renders the kind's RLS, so a surface asking
    "are these two in one initiative" and the policy deciding who may read them
    are working from one declaration rather than two.
    """
    wanted = [int(i) for i in dict.fromkeys(ids)]
    if not wanted:
        return {}

    table_name = _table_for(entity_type)
    table = SQLModel.metadata.tables[table_name]
    path = INITIATIVE_PATHS.get(table_name)
    initiative = text(path.initiative_expr(table_name)) if path is not None else null()
    rows = await session.exec(
        select(
            table.c["id"],
            title_column(entity_type),
            initiative,
        ).where(
            table.c["id"].in_(wanted),
            table.c["id"].in_(visible_ids(entity_type, user_id)),
        )
    )
    return {
        row[0]: Resolved(
            entity_type=entity_type,
            id=row[0],
            title=row[1],
            initiative_id=row[2],
            scoped_kind=path is not None,
        )
        for row in rows.all()
    }


async def resolve_one(
    session, entity_type: SearchEntityType, entity_id: int, *, user_id: int
) -> Resolved | None:
    """:func:`resolve_many` for one id."""
    found = await resolve_many(session, entity_type, [entity_id], user_id=user_id)
    return found.get(entity_id)

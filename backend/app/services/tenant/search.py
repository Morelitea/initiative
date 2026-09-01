"""Reading the guild search index.

``search_entries`` carries the same ``initiative_member_*`` policies as the
content tables it mirrors. Per-resource sharing is applied here, and
:func:`search_scope_clause` is the ONLY way to read the table.

That single entry point is deliberate: the index spans every tool, so composing
the clause here rather than at each call site means a query cannot be written
without it, and a new tool is covered by construction because the legs derive
from ``Tool``.
"""

from __future__ import annotations

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement

from app.core.tools import Tool
from app.db.schema_provisioning import search_operator_available
from app.models.tenant.search_entry import SearchEntry
from app.services.permissions import dac_scope_clause


def search_scope_clause(
    user_id: int,
    *,
    guild_id: int,
    access: str = "read",
) -> ColumnElement[bool]:
    """The WHERE leg narrowing ``search_entries`` to rows this request may read.

    One leg per :class:`Tool`, each deferring to :func:`dac_scope_clause` — the
    same call the tool's own list endpoint makes, so search and the tool it
    searches answer sharing identically rather than through two implementations.

    Rows carrying no ``dac_tool`` (guild vocabulary such as tags) have no sharing
    gate to apply; reaching this schema at all is the gate they answer to.
    ``dac_scope_clause`` already returns ``true()`` when the request covers the
    whole guild, so guild admin and PAM need no leg here.
    """
    return or_(
        SearchEntry.dac_tool.is_(None),
        *[
            and_(
                SearchEntry.dac_tool == tool.value,
                dac_scope_clause(
                    tool,
                    SearchEntry.dac_id,
                    user_id,
                    guild_id=guild_id,
                    access=access,
                ),
            )
            for tool in Tool
        ],
    )


def search_match_clause(tsquery: ColumnElement) -> ColumnElement[bool]:
    """The text-match predicate, using whichever operator this install can index.

    ``public.@@@`` where ``scripts/create-search-operator.sql`` has been run,
    the stock ``@@`` otherwise. Both return the same rows; only the first can
    use the index. Going through this one function is what keeps a query from
    quietly picking the other.
    """
    if search_operator_available():
        return SearchEntry.tsv.op("OPERATOR(public.@@@)", is_comparison=True)(tsquery)
    return SearchEntry.tsv.op("@@", is_comparison=True)(tsquery)

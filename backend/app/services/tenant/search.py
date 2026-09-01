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

from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement

from app.db.schema_provisioning import search_operator_available
from app.models.tenant.search_entry import SearchEntry


def search_scope_clause(
    user_id: int,
    *,
    guild_id: int,
    access: str = "read",
) -> ColumnElement[bool]:
    """The WHERE leg narrowing ``search_entries`` to rows this request may read.

    Emits ``public.resource_access(...)`` — the same call the table's policies
    make — so the query and the database answer sharing through one
    implementation rather than two that have to agree. ``guild_id`` is accepted
    for symmetry with the other scope helpers; the decision reads the request's
    own context.
    """
    return func.resource_access(
        SearchEntry.dac_tool,
        SearchEntry.dac_id,
        user_id,
        SearchEntry.initiative_id,
        access == "write",
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

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

from typing import Optional, Sequence

from sqlalchemy import Select, false, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.schema_provisioning import search_operator_available
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.db.search_index import entity_types
from app.models.tenant.search_entry import SearchEntry
from app.schemas.tenant.search import SearchHit, SearchResults, SearchSuggestion


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


#: Widest page a caller may ask for.
MAX_LIMIT = 100
#: Jump-to results for the palette. Small on purpose: it is a way to reach one
#: thing, not a way to read a result set.
SUGGEST_LIMIT = 10

_HEADLINE_OPTIONS = "MaxFragments=2,MinWords=5,MaxWords=18,StartSel=<,StopSel=>"


def _tsquery(query: str):
    """The parsed query. ``websearch_to_tsquery`` takes what a person types —
    bare words, "quoted phrases", ``or``, ``-excluded`` — and never raises on
    input it cannot make sense of."""
    return func.websearch_to_tsquery("simple", query)


def _scoped(
    query: str,
    *,
    user_id: int,
    guild_id: int,
    types: Optional[Sequence[SearchEntityType]],
    initiative_id: Optional[int],
) -> tuple[ColumnElement[bool], object]:
    """The predicate every search shares, and the parsed query it uses."""
    parsed = _tsquery(query)
    wanted = tuple(types) if types else entity_types(default_scope_only=True)
    clause = (
        search_match_clause(parsed)
        & SearchEntry.entity_type.in_(wanted)
        & search_scope_clause(user_id, guild_id=guild_id)
    )
    if initiative_id is not None:
        clause = clause & (SearchEntry.initiative_id == initiative_id)
    return clause, parsed


def _best_chunk(clause: ColumnElement[bool], parsed) -> Select:
    """One row per entity — the chunk that matched best.

    Long text is split across rows, so a document can match several times. The
    highest-ranked chunk is the one worth showing, and is what supplies the
    snippet.
    """
    rank = func.ts_rank_cd(SearchEntry.tsv, parsed).label("rank")
    return (
        select(
            SearchEntry.entity_type,
            SearchEntry.entity_id,
            SearchEntry.initiative_id,
            SearchEntry.dac_tool.label("tool"),
            SearchEntry.dac_id.label("tool_id"),
            SearchEntry.title,
            func.ts_headline(
                "simple", SearchEntry.body, parsed, _HEADLINE_OPTIONS
            ).label("snippet"),
            SearchEntry.updated_at,
            rank,
        )
        .where(clause)
        .distinct(SearchEntry.entity_type, SearchEntry.entity_id)
        .order_by(SearchEntry.entity_type, SearchEntry.entity_id, rank.desc())
        .subquery()
    )


async def search(
    session: AsyncSession,
    *,
    query: str,
    user_id: int,
    guild_id: int,
    types: Optional[Sequence[SearchEntityType]] = None,
    initiative_id: Optional[int] = None,
    limit: int = 20,
    offset: int = 0,
) -> SearchResults:
    """Ranked matches across the guild, newest first among equals.

    ``total`` counts entities, not chunks, and is exact: every gate is a
    predicate in this one statement, so there is nothing to filter afterwards.
    """
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)
    if not query.strip():
        return SearchResults(items=[], total=0, limit=limit, offset=offset)

    clause, parsed = _scoped(
        query,
        user_id=user_id,
        guild_id=guild_id,
        types=types,
        initiative_id=initiative_id,
    )
    best = _best_chunk(clause, parsed)
    total = await session.scalar(select(func.count()).select_from(best)) or 0
    rows = (
        await session.exec(
            select(best)
            # entity_type/entity_id last: rank and timestamp both tie, and an
            # order that is not total lets a row repeat on one page and vanish
            # from the next.
            .order_by(
                best.c.rank.desc(),
                best.c.updated_at.desc(),
                best.c.entity_type,
                best.c.entity_id,
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return SearchResults(
        items=[SearchHit.model_validate(r, from_attributes=True) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


async def suggest(
    session: AsyncSession,
    *,
    query: str,
    user_id: int,
    guild_id: int,
    types: Optional[Sequence[SearchEntityType]] = None,
    limit: int = SUGGEST_LIMIT,
) -> list[SearchSuggestion]:
    """Titles to jump to. No snippets and no body ranking — this answers "take
    me to the thing I am naming", which is a different question from search."""
    limit = max(1, min(limit, SUGGEST_LIMIT))
    if not query.strip():
        return []
    parsed = prefix_tsquery(query)
    if parsed is None:
        return []
    # The stored vector carries title AND body, so it narrows through the index
    # but would also offer a row whose title shows nothing of what was typed.
    # Rechecking the title alone keeps the palette's answers legible; it runs on
    # what the index already narrowed to.
    title_match = func.to_tsvector("simple", SearchEntry.title).op(
        "@@", is_comparison=True
    )(parsed)
    wanted = tuple(types) if types else entity_types(default_scope_only=True)
    clause = (
        search_match_clause(parsed)
        & title_match
        & SearchEntry.entity_type.in_(wanted)
        & search_scope_clause(user_id, guild_id=guild_id)
    )
    rank = func.ts_rank_cd(SearchEntry.tsv, parsed)
    rows = (
        await session.exec(
            select(
                SearchEntry.entity_type,
                SearchEntry.entity_id,
                SearchEntry.initiative_id,
                SearchEntry.dac_tool.label("tool"),
                SearchEntry.dac_id.label("tool_id"),
                SearchEntry.title,
            )
            .where(clause, SearchEntry.chunk_ix == 0)
            .order_by(
                rank.desc(),
                SearchEntry.updated_at.desc(),
                SearchEntry.entity_type,
                SearchEntry.entity_id,
            )
            .limit(limit)
        )
    ).all()
    return [SearchSuggestion.model_validate(r, from_attributes=True) for r in rows]


def prefix_tsquery(text: str):
    """A query whose last word matches as a prefix, or ``None`` for no terms.

    What a filter box needs: someone typing ``ven`` should see ``vendor``
    before they finish the word. ``websearch_to_tsquery`` matches whole words
    only, which is right for a results page and wrong for type-ahead.

    Tokens are reduced to alphanumerics, so nothing a person types reaches
    ``to_tsquery`` as syntax.
    """
    tokens = ["".join(c for c in part if c.isalnum()) for part in text.split()]
    tokens = [t for t in tokens if t]
    if not tokens:
        return None
    return func.to_tsquery("simple", " & ".join([*tokens[:-1], f"{tokens[-1]}:*"]))


def tool_search_clause(
    tool: Tool, id_col: ColumnElement[int], search: Optional[str]
) -> Optional[ColumnElement[bool]]:
    """Narrow a tool's list to rows whose indexed text matches ``search``.

    The same index the search page reads, so a tool's filter box and the search
    page agree about what matches — and it reaches a description, not just a
    name. ``None`` when there is nothing to search for, so a caller appends it
    conditionally.

    The subquery reads ``search_entries``, which is gated by its own policies;
    the caller's own access clause still applies to the rows it returns.
    """
    if not search or not search.strip():
        return None
    parsed = prefix_tsquery(search)
    if parsed is None:
        # Something was typed, but it holds no word to match — punctuation only.
        # Nothing matches it, which is a truer answer than the unfiltered list
        # a caller would read as "the filter was ignored".
        return false()
    return id_col.in_(
        select(SearchEntry.entity_id).where(
            SearchEntry.entity_type == tool.value,
            search_match_clause(parsed),
        )
    )

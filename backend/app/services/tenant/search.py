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

from dataclasses import dataclass
from typing import Optional, Sequence

from sqlalchemy import Select, false, func, select, text
from sqlalchemy.exc import SQLAlchemyError
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

#: How many close matches a failed search offers. It is a suggestion, not a
#: result set.
FUZZY_LIMIT = 5
#: How close a word has to be to be worth offering. Measured against the
#: closest RUN of the title rather than the whole of it: a title is a sentence
#: and the query is a word, so comparing them entire scores an exact match at
#: 0.14 and finds nothing. A typo of a real word lands around 0.5.
FUZZY_THRESHOLD = 0.4
#: The close-match read cannot be served from an index — its operator is not
#: leakproof, so under RLS it is a scan — and it only ever runs on a search that
#: already found nothing. Bounded here so a large community gives up rather
#: than making the reader wait for a suggestion.
FUZZY_TIMEOUT_MS = 250


#: A prefix scan widens as the prefix shortens, so the last word earns one only
#: once it is specific enough for that to be worth the reading.
MIN_PREFIX_CHARS = 3

#: What ``websearch_to_tsquery`` reads as syntax rather than as a word.
_WEBSEARCH_OPERATORS = frozenset({"or", "and"})


def _trailing_prefix(query: str) -> tuple[str, Optional[str]]:
    """The query without its last word, and that word to match as a prefix.

    A results page searches as its reader types, so the last word is usually
    half-finished: someone who has got as far as ``thro`` means ``Throne``.
    Only a plain word qualifies — a quoted phrase, an exclusion or an operator
    is what the reader asked for exactly, and is left alone.
    """
    if query.count('"') % 2:
        # Mid-phrase: the quote that would close it has not been typed yet.
        return query, None
    head, _, last = query.rpartition(" ")
    if not last.isalnum() or len(last) < MIN_PREFIX_CHARS:
        return query, None
    if last.lower() in _WEBSEARCH_OPERATORS:
        return query, None
    return head, last


def _tsquery(query: str):
    """The parsed query. ``websearch_to_tsquery`` takes what a person types —
    bare words, "quoted phrases", ``or``, ``-excluded`` — and never raises on
    input it cannot make sense of.

    Its one gap is that it matches whole words, which reads as nothing being
    found while a word is still being typed. So a bare last word is matched as a
    prefix and ANDed onto the rest, which keeps every bit of the syntax above
    and answers as the reader types.
    """
    head, prefix = _trailing_prefix(query)
    if prefix is None:
        return func.websearch_to_tsquery("simple", query)
    # `prefix` is alphanumeric, so it reaches `to_tsquery` as a word and never
    # as syntax.
    tail = func.to_tsquery("simple", f"{prefix}:*")
    if not head.strip():
        return tail
    return func.websearch_to_tsquery("simple", head).op("&&")(tail)


@dataclass(frozen=True)
class Filters:
    """What a caller narrows to, beyond the words themselves.

    Every field only ever removes rows, so narrowing can never reach content
    the gates would not have allowed.

    ``template`` is three-valued on purpose: unset means both, so a results
    page still finds a template by name; a picker choosing where content goes
    asks for ``False``; a template picker asks for ``True``.
    """

    types: Optional[Sequence[SearchEntityType]] = None
    initiative_id: Optional[int] = None
    #: Archived work is indexed and left out unless it is asked for.
    include_archived: bool = False
    template: Optional[bool] = None

    @property
    def entity_types(self) -> tuple[SearchEntityType, ...]:
        """The types to search — the default scope when none were named."""
        return (
            tuple(self.types) if self.types else entity_types(default_scope_only=True)
        )

    def clause(self) -> ColumnElement[bool]:
        """This narrowing as a predicate."""
        clause: ColumnElement[bool] = SearchEntry.entity_type.in_(self.entity_types)
        if self.initiative_id is not None:
            clause = clause & (SearchEntry.initiative_id == self.initiative_id)
        if not self.include_archived:
            clause = clause & SearchEntry.archived.is_(False)
        if self.template is not None:
            clause = clause & SearchEntry.template.is_(self.template)
        return clause


def _scoped(
    query: str, *, user_id: int, guild_id: int, filters: Filters
) -> tuple[ColumnElement[bool], object]:
    """The predicate every search shares, and the parsed query it uses."""
    parsed = _tsquery(query)
    clause = (
        search_match_clause(parsed)
        & filters.clause()
        & search_scope_clause(user_id, guild_id=guild_id)
    )
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


async def _close_titles(
    session: AsyncSession, *, query: str, user_id: int, guild_id: int, filters: Filters
) -> list[SearchHit]:
    """Entities whose TITLE is close to what was typed, for when nothing matched.

    This answers the typo — ``comunity`` finding Community — which whole-word
    matching cannot. Titles only, one row per entity, and never blended into a
    search that worked: a reader is shown these as close matches, not told they
    are what was asked for.
    """
    closeness = func.word_similarity(query, SearchEntry.title)
    clause = (
        (closeness >= FUZZY_THRESHOLD)
        & (SearchEntry.chunk_ix == 0)
        & filters.clause()
        & search_scope_clause(user_id, guild_id=guild_id)
    )

    statement = (
        select(
            SearchEntry.entity_type,
            SearchEntry.entity_id,
            SearchEntry.initiative_id,
            SearchEntry.dac_tool.label("tool"),
            SearchEntry.dac_id.label("tool_id"),
            SearchEntry.title,
        )
        .where(clause)
        .order_by(closeness.desc(), SearchEntry.entity_type, SearchEntry.entity_id)
        .limit(FUZZY_LIMIT)
    )
    try:
        # A savepoint, so giving up leaves the request's transaction usable.
        async with session.begin_nested():
            # ``set_config`` rather than ``SET LOCAL``: the latter takes no
            # bind parameter, so the value would have to be built into the
            # statement. Third argument true makes it transaction-local, which
            # is what ``SET LOCAL`` meant here.
            await session.exec(
                text(
                    "SELECT set_config('statement_timeout', :timeout, true)"
                ).bindparams(timeout=f"{FUZZY_TIMEOUT_MS}ms")
            )
            rows = (await session.exec(statement)).all()
    except SQLAlchemyError:
        # Gave up. The reader gets the empty page they already had.
        return []
    finally:
        # A transaction-local setting outlives the savepoint when it commits,
        # so it is put back rather than left on the rest of the request.
        await session.exec(text("SET LOCAL statement_timeout = DEFAULT"))
    return [SearchHit.model_validate(row, from_attributes=True) for row in rows]


async def search(
    session: AsyncSession,
    *,
    query: str,
    user_id: int,
    guild_id: int,
    filters: Filters = Filters(),
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

    clause, parsed = _scoped(query, user_id=user_id, guild_id=guild_id, filters=filters)
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
    if not rows and offset == 0:
        # Nothing matched what was typed. Offer what is closest to it rather
        # than an empty page — flagged, so the reader is told which they got.
        close = await _close_titles(
            session, query=query, user_id=user_id, guild_id=guild_id, filters=filters
        )
        if close:
            return SearchResults(
                items=close,
                total=len(close),
                limit=limit,
                offset=offset,
                fuzzy=True,
            )

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
    filters: Filters = Filters(),
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
    clause = (
        search_match_clause(parsed)
        & title_match
        & filters.clause()
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


async def recent(
    session: AsyncSession,
    *,
    user_id: int,
    guild_id: int,
    filters: Filters = Filters(),
    limit: int = SUGGEST_LIMIT,
) -> list[SearchSuggestion]:
    """The things most recently changed that a picker could offer.

    What a picker shows before anything is typed. :func:`suggest` answers "take
    me to the thing I am naming"; this answers "what might I be naming", which
    is the same question a person is asking when they open a picker and have
    not yet decided.

    Deliberately the same rows, filters and gate as :func:`suggest` — only the
    ordering differs — so a picker cannot offer something its own search would
    refuse to find.
    """
    limit = max(1, min(limit, SUGGEST_LIMIT))
    clause = filters.clause() & search_scope_clause(user_id, guild_id=guild_id)
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
            # One row per thing: the index holds a row per body chunk as well.
            .where(clause, SearchEntry.chunk_ix == 0)
            .order_by(
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

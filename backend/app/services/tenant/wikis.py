"""Wiki pages: the spine, and the slugs that address it.

A wiki's pages form a tree. That tree is two columns — ``parent_page_id`` and
``position`` — and this module owns every operation that has to keep them
coherent: naming a page, filing it, moving it, and reading the tree back.

Two kinds of thing sit in that tree: the pages written in the wiki, and the
documents borrowed into it. A borrowed document keeps its own address and its
own owner, so the wiki cannot write a position onto it — it records where it
put it instead, in ``Wiki.document_positions`` — and it is always at the top
level, because which page it is filed under would be a fact about a document
that belongs to other places too. :func:`load_list` is the one place pages and
documents are read as a single order, and :func:`place_in_list` is the one
place that order is rewritten.

A third structure, the headings inside a page, is content rather than filing
and lives in the body.

What is deliberately NOT here: anything a page connects to. A page ``part_of``
a task, a page ``related_to`` another wiki's page, and the ``references`` edges
read out of ``[[ ]]`` links in a body are all rows in ``relationships``,
handled by the services that already own that table. The order is navigation;
the edges are meaning, and they are kept apart on purpose.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from sqlalchemy.orm import selectinload

from app.core.messages import WikiMessages
from app.core.tools import Tool
from app.models.tenant.initiative import Initiative
from app.models.tenant.resource_grant import ResourceGrant
from app.models.tenant.wiki import Wiki, WikiPage, WikiPageOrder
from app.services.tenant import tags as tags_service

#: Slugs are addresses, so they are bounded by what stays readable in a URL
#: rather than by the column, which is wider.
MAX_SLUG_LENGTH = 120

#: The slug alphabet. Stated as the set of characters that survive rather than
#: as a pattern of ones that do not, so what a slug may contain is readable
#: here instead of inferred from a negation.
_SLUG_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")


def list_loader_options() -> list:
    """Eager-load what a wiki *list* row needs: its sharing, its initiative's
    memberships (the DAC engine reads them), and the page it opens on."""
    return [
        selectinload(Wiki.grants).selectinload(ResourceGrant.role),
        selectinload(Wiki.initiative).selectinload(Initiative.memberships),
        selectinload(Wiki.home_page),
    ]


def wiki_loader_options() -> list:
    """Eager-load everything wiki serialization + authorization needs."""
    return list_loader_options()


async def get_wiki(
    session: AsyncSession,
    wiki_id: int,
    *,
    populate_existing: bool = False,
) -> Wiki | None:
    """Fetch a wiki with the relationships authorization + serialization need.
    RLS scopes the row to the request's guild."""
    statement = select(Wiki).where(Wiki.id == wiki_id).options(*wiki_loader_options())
    if populate_existing:
        statement = statement.execution_options(populate_existing=True)
    wiki = (await session.exec(statement)).one_or_none()
    if wiki is not None:
        await tags_service.annotate_tags(session, [wiki])
    return wiki


async def get_page(
    session: AsyncSession, wiki_id: int, page_id: int
) -> WikiPage | None:
    """One page of one wiki. Keyed by both so a page id from another wiki
    reads as missing rather than as somebody else's page."""
    statement = (
        select(WikiPage)
        .where(WikiPage.id == page_id, WikiPage.wiki_id == wiki_id)
        .options(selectinload(WikiPage.author))
    )
    return (await session.exec(statement)).one_or_none()


async def get_page_by_slug(
    session: AsyncSession, wiki_id: int, slug: str
) -> WikiPage | None:
    """One page of one wiki, by the name in its URL."""
    statement = (
        select(WikiPage)
        .where(WikiPage.wiki_id == wiki_id, WikiPage.slug == slug)
        .options(selectinload(WikiPage.author))
    )
    return (await session.exec(statement)).one_or_none()


def slugify_page_title(title: str, *, fallback: str = "page") -> str:
    """Kebab-case a page title down to the slug alphabet.

    Anything outside the alphabet becomes a separator, runs of separators
    collapse, and the result is trimmed to length. A title made entirely of
    characters that do not survive — a page called "???" — yields ``fallback``
    rather than an empty address.
    """
    out: list[str] = []
    for char in title.strip().lower():
        if char in _SLUG_CHARS:
            out.append(char)
        elif out and out[-1] != "-":
            out.append("-")
    slug = "".join(out).strip("-")[:MAX_SLUG_LENGTH].strip("-")
    return slug or fallback


async def unique_page_slug(
    session: AsyncSession,
    wiki_id: int,
    title: str,
    *,
    exclude_page_id: int | None = None,
) -> str:
    """A slug free among this wiki's live pages, suffixing ``-2``, ``-3``, ….

    ``exclude_page_id`` is the page being renamed, which must not collide with
    itself. Trashed pages hold no slug — the session filter hides them — so a
    page can take the name of one that was thrown away, and restoring that one
    is where the conflict surfaces.
    """
    base = slugify_page_title(title)
    statement = select(WikiPage.slug).where(WikiPage.wiki_id == wiki_id)
    if exclude_page_id is not None:
        statement = statement.where(WikiPage.id != exclude_page_id)
    taken = set((await session.exec(statement)).all())

    if base not in taken:
        return base
    for suffix in range(2, len(taken) + 3):
        trimmed = base[: MAX_SLUG_LENGTH - len(str(suffix)) - 1].strip("-") or "page"
        candidate = f"{trimmed}-{suffix}"
        if candidate not in taken:
            return candidate
    raise ValueError("could not derive a unique wiki page slug")


async def next_position(
    session: AsyncSession, wiki: Wiki, parent_page_id: int | None = None
) -> int:
    """Where a new page lands: after the last thing filed beside it.

    Positions are sparse and never renumbered on insert, so this is a read of
    the current maximum rather than a count. At the top level it reads the
    documents' places too, because they are filed there and a new page goes
    after them.
    """
    statement = select(WikiPage.position).where(WikiPage.wiki_id == wiki.id)
    statement = (
        statement.where(WikiPage.parent_page_id.is_(None))
        if parent_page_id is None
        else statement.where(WikiPage.parent_page_id == parent_page_id)
    )
    positions = list((await session.exec(statement)).all())
    if parent_page_id is None:
        positions.extend(
            int(spot)
            for spot in (wiki.document_positions or {}).values()
            if isinstance(spot, int) and spot != UNPLACED
        )
    return (max(positions) + 1) if positions else 0


#: How each ordering sorts pages. ``manual`` reads the spine somebody
#: dragged; the others ignore it, which is the point — nobody hand-orders two
#: hundred entries, and a decisions log wants the newest at the top.
_ORDERINGS = {
    WikiPageOrder.manual: lambda: (WikiPage.position, WikiPage.id),
    WikiPageOrder.title: lambda: (func.lower(WikiPage.title), WikiPage.id),
    WikiPageOrder.recently_updated: lambda: (
        WikiPage.updated_at.desc(),
        WikiPage.id.desc(),
    ),
}


async def load_pages(
    session: AsyncSession,
    wiki_id: int,
    *,
    page_order: WikiPageOrder = WikiPageOrder.manual,
    include_drafts: bool = True,
) -> list[WikiPage]:
    """Every live page of a wiki, in the order the navigation draws them.

    ``include_drafts`` is the caller's answer to "may this person write here":
    a draft is a page somebody is still working on, so it is part of the wiki
    for the people who write it and not part of the wiki for the people who
    read it.
    """
    statement = select(WikiPage).where(WikiPage.wiki_id == wiki_id)
    if not include_drafts:
        statement = statement.where(WikiPage.is_draft.is_(False))
    return list(
        (await session.exec(statement.order_by(*_ORDERINGS[page_order]()))).all()
    )


#: Where something nobody has placed sits: after everything that has been. Far
#: enough out that no real position reaches it, and the same for every one of
#: them, so unplaced documents fall back to the tie-break below (their name).
UNPLACED = 1_000_000_000


def _document_position(wiki: Wiki, document: Any) -> int:
    """Where this wiki puts this document, or the end if it has not said."""
    recorded = (wiki.document_positions or {}).get(str(document.id))
    return int(recorded) if isinstance(recorded, int) else UNPLACED


def _sort_key(wiki: Wiki, item: Any, page_order: WikiPageOrder):
    """One key over both kinds of row, so a list can hold them together.

    A page and a document answer the same three questions in different words —
    a page has a ``title`` and a document a ``name`` — so the key asks each in
    its own terms and the comparison never sees the difference.
    """
    is_page = isinstance(item, WikiPage)
    title = (item.title if is_page else item.name) or ""
    if page_order is WikiPageOrder.title:
        return (title.lower(), item.id)
    if page_order is WikiPageOrder.recently_updated:
        # Negated rather than reversed: the whole list sorts one way, and
        # "recently updated" means the newest first.
        return (-item.updated_at.timestamp(), -item.id)
    position = item.position if is_page else _document_position(wiki, item)
    # Ties are ordinary: positions are sparse and a page arrives at 0 before
    # anybody drags anything. Broken by arrival — pages first, then the
    # documents borrowed in — rather than by name, so a list somebody has not
    # arranged still reads in the order it was written.
    return (position, 0 if is_page else 1, item.id)


def _parent_of(item: Any, known: set[int]) -> int | None:
    """What a row is filed under, as far as THIS read can see.

    A page whose parent is not in the set — a draft hidden from a reader, a
    page the reader may not see — is drawn at the top rather than dropped, so a
    partial read still shows every row it was given.
    """
    parent = getattr(item, "parent_page_id", None)
    return parent if parent in known else None


async def load_list(
    session: AsyncSession,
    wiki: Wiki,
    *,
    include_drafts: bool = True,
) -> list[Any]:
    """A wiki's whole tree — its pages and its documents — in reading order.

    Depth-first: each row, then everything filed under it. The navigation draws
    this, and the order it comes back in is the order it reads in. Assembled
    here rather than in SQL because it spans two tables and a wiki's list is
    the size of a table of contents, not of a table.
    """
    pages = await load_pages(
        session, wiki.id, page_order=wiki.page_order, include_drafts=include_drafts
    )
    documents = await linked_documents(session, wiki.id)
    known = {page.id for page in pages}

    filed: dict[int | None, list[Any]] = {}
    for item in (*pages, *documents):
        parent = _parent_of(item, known) if isinstance(item, WikiPage) else None
        filed.setdefault(parent, []).append(item)
    for group in filed.values():
        group.sort(key=lambda item: _sort_key(wiki, item, wiki.page_order))

    ordered: list[Any] = []

    def walk(parent: int | None) -> None:
        for item in filed.get(parent, []):
            ordered.append(item)
            if isinstance(item, WikiPage):
                walk(item.id)

    walk(None)
    return ordered


async def siblings_of(
    session: AsyncSession, wiki: Wiki, parent_page_id: int | None
) -> list[Any]:
    """Everything filed in one place, in order.

    At the top of a wiki that is its unfiled pages and every document borrowed
    into it; under a page it is that page's own, because a document is never
    filed under anything.
    """
    pages = [
        page
        for page in await load_pages(session, wiki.id, page_order=wiki.page_order)
        if page.parent_page_id == parent_page_id
    ]
    group: list[Any] = [*pages]
    if parent_page_id is None:
        group.extend(await linked_documents(session, wiki.id))
    group.sort(key=lambda item: _sort_key(wiki, item, wiki.page_order))
    return group


async def place_in_list(
    session: AsyncSession,
    wiki: Wiki,
    moved: Any,
    position: int,
    parent_page_id: int | None = None,
) -> None:
    """File one row somewhere and put it in order there — what a drag is.

    Only the row's new neighbours are renumbered: positions mean something
    among the things filed together and nothing across the tree, so one pass
    over one group leaves no two of them sharing a number. Each is written
    where it can be — a page in its own column, a document in the wiki's record
    of where it put things — so a document is reordered without being touched.

    Drafts are counted even for a reader who cannot see them: the index comes
    from a list the person dragging was looking at, and they can write here.
    """
    if isinstance(moved, WikiPage):
        moved.parent_page_id = parent_page_id
        session.add(moved)

    others = [
        item
        for item in await siblings_of(session, wiki, parent_page_id)
        if not (type(item) is type(moved) and item.id == moved.id)
    ]
    index = min(position, len(others))
    ordered = [*others[:index], moved, *others[index:]]

    placements = dict(wiki.document_positions or {})
    for spot, item in enumerate(ordered):
        if isinstance(item, WikiPage):
            item.position = spot
            session.add(item)
        else:
            placements[str(item.id)] = spot
    # Replaced rather than mutated: SQLAlchemy tracks the attribute, not what
    # the dict does to itself.
    wiki.document_positions = placements
    session.add(wiki)


def descendant_ids(pages: Iterable[WikiPage], root_id: int) -> set[int]:
    """Every page beneath ``root_id``, the root excluded."""
    filed: dict[int | None, list[int]] = {}
    for page in pages:
        filed.setdefault(page.parent_page_id, []).append(page.id)

    found: set[int] = set()
    frontier = list(filed.get(root_id, []))
    while frontier:
        page_id = frontier.pop()
        if page_id in found:
            continue
        found.add(page_id)
        frontier.extend(filed.get(page_id, []))
    return found


async def validate_reparent(
    session: AsyncSession, page: WikiPage, new_parent_id: int | None
) -> None:
    """Refuse a move that would take a branch out of the tree.

    A page cannot be filed under itself, under one of its own descendants, or
    under a page belonging to another wiki.
    """
    if new_parent_id is None:
        return
    if new_parent_id == page.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=WikiMessages.PAGE_PARENT_ITSELF,
        )

    parent = await get_page(session, page.wiki_id, new_parent_id)
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=WikiMessages.PAGE_NOT_FOUND,
        )

    pages = await load_pages(session, page.wiki_id)
    if new_parent_id in descendant_ids(pages, page.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=WikiMessages.PAGE_PARENT_DESCENDANT,
        )


def forget_document_placement(wiki: Wiki, document_id: int) -> None:
    """Drop a document's place when it leaves the wiki, so it does not come
    back to a spot it was given last time."""
    placements = dict(wiki.document_positions or {})
    if placements.pop(str(document_id), None) is not None:
        wiki.document_positions = placements


#: What an anchor keeps. Mirrors ``slugify`` in the frontend, which is what
#: stamps the ``id`` on a rendered heading — the two have to agree or a link
#: from the navigation lands nowhere.
_ANCHOR_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_-")


def anchor_slug(text: str) -> str:
    """A heading's anchor, as the editor stamps it on the rendered element."""
    kept = "".join(
        ch if ch in _ANCHOR_CHARS else "-" if ch.isspace() else ""
        for ch in text.strip().lower()
    )
    while "--" in kept:
        kept = kept.replace("--", "-")
    return kept.strip("-")


def _node_text(node: Any) -> str:
    """Every bit of text under a node, in order."""
    if not isinstance(node, dict):
        return ""
    own = node.get("text")
    parts = [own] if isinstance(own, str) else []
    children = node.get("children")
    if isinstance(children, list):
        parts.extend(_node_text(child) for child in children)
    return "".join(parts)


def page_headings(content: Any) -> list[dict[str, Any]]:
    """The headings written on a page, in the order they appear.

    Read from the stored body rather than from an editor, because the
    navigation draws the headings of every page in a wiki and only one of them
    is ever open. Level comes from the tag, and the anchor is what the editor
    stamps on the heading when it renders it.
    """
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "heading":
            text = _node_text(node).strip()
            tag = node.get("tag")
            level = int(tag[1:]) if isinstance(tag, str) and tag[1:].isdigit() else 2
            if text:
                found.append(
                    {"text": text, "level": level, "anchor": anchor_slug(text)}
                )
        for child in node.get("children") or []:
            walk(child)

    if isinstance(content, dict):
        walk(content.get("root"))
    return found


async def annotate_page_counts(session: AsyncSession, rows: Sequence[Wiki]) -> None:
    """Set ``page_count`` on each wiki from one grouped query.

    Trashed pages are excluded by the soft-delete filter, so a wiki emptied
    into the trash reads as empty rather than as full.
    """
    ids = [w.id for w in rows if w.id is not None]
    if not ids:
        return
    result = await session.exec(
        select(WikiPage.wiki_id, func.count(WikiPage.id))
        .where(WikiPage.wiki_id.in_(tuple(ids)))
        .group_by(WikiPage.wiki_id)
    )
    counts = dict(result.all())
    for wiki in rows:
        object.__setattr__(wiki, "page_count", counts.get(wiki.id, 0))


async def get_wiki_for_export(
    session: AsyncSession,
    current_user: Any,
    guild_id: int,
    *,
    wiki_id: int,
) -> tuple[Wiki, list[WikiPage]]:
    """The wiki-export adapter's seam: fetch + authorize in one place so the
    rule holds on the worker's render-time replay too. READ access suffices —
    exporting is a formatted read.

    The pages come back with it, in reading order, because a wiki without its
    pages is not a thing anyone wanted a copy of.
    """
    from app.services import permissions as permissions_service

    wiki = await get_wiki(session, wiki_id)
    if wiki is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=Tool.wiki.not_found_code,
        )
    if wiki.initiative is not None and not wiki.initiative.wikis_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=Tool.wiki.feature_disabled_code,
        )
    permissions_service.require_access(
        permissions_service.DAC_RESOURCES[Tool.wiki],
        wiki,
        current_user,
        access="read",
    )
    pages = await load_pages(session, wiki.id, page_order=wiki.page_order)
    await tags_service.annotate_tags(session, pages)
    return wiki, pages


async def linked_documents(session: AsyncSession, wiki_id: int) -> list[Any]:
    """The documents somebody has put in this wiki.

    A document joins a wiki by an edge, not by a column: ``document part_of
    wiki`` is exactly the fact being asserted, and ``relationships`` already
    holds facts of that shape. So a document can sit in a wiki without being
    moved, copied, or owned by it — it stays the document it was, in whatever
    else it also belongs to.
    """
    from app.core.relationships import RelationshipType, decode_node_id, node_id
    from app.core.search import SearchEntityType
    from app.models.tenant.document import Document
    from app.models.tenant.relationship import EntityRelationship

    edges = (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.target_node
                == node_id(SearchEntityType.wiki, wiki_id),
                EntityRelationship.relationship_type == RelationshipType.part_of,
                EntityRelationship.removed_at.is_(None),
            )
        )
    ).all()

    document_ids = [
        entity_id
        for kind, entity_id in (decode_node_id(edge.source_node) for edge in edges)
        if kind is SearchEntityType.document
    ]
    if not document_ids:
        return []

    # RLS is the gate, as everywhere else: a document the reader may not see
    # simply does not come back, and the wiki is shorter by one row.
    rows = (
        await session.exec(select(Document).where(Document.id.in_(document_ids)))
    ).all()
    return list(rows)


async def page_links(session: AsyncSession, page: WikiPage) -> tuple[list, list]:
    """What this page connects to, and what connects to it.

    One query each way over ``relationships``, which is where both the
    ``[[ ]]`` links read out of the body and the connections somebody drew by
    hand already live. The titles are resolved through the same reference
    machinery every other surface uses, so a page names a task the way the
    editor's own chip does.
    """
    from app.core.relationships import node_id
    from app.core.search import SearchEntityType
    from app.models.tenant.relationship import EntityRelationship

    node = node_id(SearchEntityType.wiki_page, page.id)

    outgoing = (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.source_node == node,
                EntityRelationship.removed_at.is_(None),
            )
        )
    ).all()
    incoming = (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.target_node == node,
                EntityRelationship.removed_at.is_(None),
            )
        )
    ).all()
    return list(outgoing), list(incoming)

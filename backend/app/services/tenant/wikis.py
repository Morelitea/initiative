"""Wiki pages: the spine, and the slugs that address it.

A wiki's pages form a tree. That tree is two columns — ``parent_page_id`` and
``position`` — and this module owns every operation that has to keep them
coherent: naming a page, placing it, moving it, and reading the tree back.

What is deliberately NOT here: anything a page connects to that is not its
parent. A page ``part_of`` a task, a page ``related_to`` another wiki's page,
and the ``references`` edges read out of ``[[ ]]`` links in a body are all rows
in ``relationships``, handled by the services that already own that table. The
tree is navigation; the edges are meaning, and they are kept apart on purpose.
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
    session: AsyncSession, wiki_id: int, parent_page_id: int | None
) -> int:
    """Where a new page lands: after its last sibling.

    Positions are sparse and never renumbered on insert, so this is a read of
    the current maximum rather than a count.
    """
    statement = select(WikiPage.position).where(WikiPage.wiki_id == wiki_id)
    statement = (
        statement.where(WikiPage.parent_page_id.is_(None))
        if parent_page_id is None
        else statement.where(WikiPage.parent_page_id == parent_page_id)
    )
    positions = (await session.exec(statement)).all()
    return (max(positions) + 1) if positions else 0


#: How each ordering sorts siblings. ``manual`` reads the spine somebody
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


async def load_tree(
    session: AsyncSession,
    wiki_id: int,
    *,
    page_order: WikiPageOrder = WikiPageOrder.manual,
) -> list[WikiPage]:
    """Every live page of a wiki, in the order the navigation draws them.

    One query for the whole tree. A wiki is read far more often than it is
    written and its pages are small rows, so assembling the shape in Python
    beats a recursive query per level.
    """
    statement = (
        select(WikiPage)
        .where(WikiPage.wiki_id == wiki_id)
        .order_by(*_ORDERINGS[page_order]())
    )
    return list((await session.exec(statement)).all())


def order_depth_first(pages: Sequence[WikiPage]) -> list[WikiPage]:
    """Flatten a wiki's pages into reading order — each page then its children.

    Pages whose parent is missing from ``pages`` are treated as top-level, so a
    partial read still renders every row it was given rather than dropping the
    ones whose parent it cannot see.
    """
    children: dict[int | None, list[WikiPage]] = {}
    ids = {page.id for page in pages}
    for page in pages:
        parent = page.parent_page_id if page.parent_page_id in ids else None
        children.setdefault(parent, []).append(page)

    ordered: list[WikiPage] = []

    def walk(parent_id: int | None) -> None:
        for page in children.get(parent_id, []):
            ordered.append(page)
            walk(page.id)

    walk(None)
    return ordered


def descendant_ids(pages: Iterable[WikiPage], root_id: int) -> set[int]:
    """Every page beneath ``root_id``, the root excluded."""
    by_parent: dict[int | None, list[int]] = {}
    for page in pages:
        by_parent.setdefault(page.parent_page_id, []).append(page.id)

    found: set[int] = set()
    frontier = list(by_parent.get(root_id, []))
    while frontier:
        page_id = frontier.pop()
        if page_id in found:
            continue
        found.add(page_id)
        frontier.extend(by_parent.get(page_id, []))
    return found


async def validate_reparent(
    session: AsyncSession, page: WikiPage, new_parent_id: int | None
) -> None:
    """Refuse a move that would detach a subtree from the tree.

    A page cannot be its own parent, cannot be moved beneath one of its own
    descendants, and cannot be moved under a page belonging to another wiki.
    """
    if new_parent_id is None:
        return
    if new_parent_id == page.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=WikiMessages.PAGE_PARENT_ITSELF,
        )

    parent = await session.get(WikiPage, new_parent_id)
    if parent is None or parent.wiki_id != page.wiki_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=WikiMessages.PAGE_NOT_FOUND,
        )

    pages = await load_tree(session, page.wiki_id)
    if new_parent_id in descendant_ids(pages, page.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=WikiMessages.PAGE_PARENT_DESCENDANT,
        )


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
    pages = order_depth_first(await load_tree(session, wiki.id))
    await tags_service.annotate_tags(session, pages)
    return wiki, pages


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

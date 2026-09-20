"""Wiki source adapter: the importable backup envelope (json).

A wiki is its pages and the shape they sit in, so the envelope carries both:
each page's Lexical body whole, the way the post and document envelopes carry
theirs, and the tree as a ``parent`` slug on each page.

The tree crosses as **slugs, not ids**. Ids mean nothing in the guild a backup
is restored into, and a page's slug is the name its own siblings know it by —
so a restored wiki rebuilds the same shape without having to preserve a single
primary key. Pages are written out in the order the navigation draws them,
which is siblings by position rather than a walk down each branch, so a
child can be written before its parent; the importer resolves every parent
slug in a second pass once all the pages exist.

What the envelope deliberately drops is the sharing and the home page's id.
Sharing is a fact about who is in *this* community. The home page crosses as a
slug for the same reason the tree does.

Access rule: READ on the wiki (exporting is a formatted read), enforced by the
``get_wiki_for_export`` seam at both count and build time, under the caller's
RLS session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.wiki import Wiki, WikiPage
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    envelope_key,
)
from app.services.export.contract import RenderItem

#: What one wiki contributes to a batch: its row and its pages.
Loaded = tuple[Wiki, list[WikiPage]]


class WikiAdapter(ToolExportAdapter):
    tool = Tool.wiki

    async def fetch(
        self, session: AsyncSession, user: User, guild_id: int, wiki_id: int, /
    ) -> Loaded:
        from app.services.tenant.wikis import get_wiki_for_export

        return await get_wiki_for_export(session, user, guild_id, wiki_id=wiki_id)

    def rows(self, loaded: Loaded, /) -> int:
        # One row per page: a wiki's size is what is written in it, not the
        # single row naming it.
        _wiki, pages = loaded
        return len(pages) or 1

    def item(self, loaded: Loaded, ctx: BuildContext, /) -> RenderItem:
        wiki, pages = loaded
        return build_wiki_item(wiki, pages, ctx.now)


def build_wiki_item(wiki: Wiki, pages: list[WikiPage], now: datetime) -> RenderItem:
    # The envelope is importable machine data — stays canonical, never
    # localized (translating field keys breaks import).
    return RenderItem(
        key=envelope_key(Tool.wiki, wiki.name, now.strftime("%Y-%m-%d")),
        data=_envelope(wiki, pages),
    )


def _envelope(wiki: Wiki, pages: list[WikiPage]) -> dict[str, Any]:
    by_id = {page.id: page for page in pages}
    home = by_id.get(wiki.home_page_id) if wiki.home_page_id else None
    return {
        "type": "initiative-wiki",
        "schema_version": 1,
        "name": wiki.name,
        "description": wiki.description,
        "home_page": home.slug if home is not None else None,
        "tags": sorted(tag.name for tag in getattr(wiki, "tags", None) or []),
        "pages": [_page_envelope(page, by_id) for page in pages],
    }


def _page_envelope(page: WikiPage, by_id: dict[int, WikiPage]) -> dict[str, Any]:
    parent = by_id.get(page.parent_page_id) if page.parent_page_id else None
    return {
        "title": page.title,
        "slug": page.slug,
        # What this page is filed under, named the way its siblings name it.
        # None means it sits at the top of the wiki.
        "parent": parent.slug if parent is not None else None,
        "position": page.position,
        # A draft restores as a draft: it is a page somebody has not shown
        # anyone yet, and a restore is not the moment to publish it for them.
        "is_draft": page.is_draft,
        "content": page.content or {},
        "tags": sorted(tag.name for tag in getattr(page, "tags", None) or []),
    }

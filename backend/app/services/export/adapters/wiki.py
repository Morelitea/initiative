"""Wiki source adapter: the importable backup envelope (json).

A wiki is its pages and the shape they sit in, so the envelope carries both:
each page's Lexical body whole, the way the post and document envelopes carry
theirs, and the tree as a ``parent`` slug on each page.

The tree crosses as **slugs, not ids**. Ids mean nothing in the guild a backup
is restored into, and a page's slug is the name its own siblings know it by —
so a restored wiki rebuilds the same shape without having to preserve a single
primary key. Pages are written out in reading order, which means a page's
parent is always already named by the time the page that needs it arrives.

What the envelope deliberately drops is the sharing and the home page's id.
Sharing is a fact about who is in *this* community. The home page crosses as a
slug for the same reason the tree does.

Access rule: READ on the wiki (exporting is a formatted read), enforced by the
``get_wiki_for_export`` seam at both count and build time, under the caller's
RLS session.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User
from app.models.tenant.wiki import Wiki, WikiPage
from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.i18n import localize_now
from app.services.platform.csv_export import safe_filename_component


class WikiAdapter:
    source = "wiki"
    template_id = "data-table"  # protocol requirement; json never renders one
    formats = frozenset({"json"})

    async def count(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> int:
        # One row per page: a wiki's size is what is written in it, not the
        # single row naming it.
        return sum(
            len(pages) or 1
            for _wiki, pages in await self._wikis(session, user, guild_id, params)
        )

    async def build(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> RenderRequest:
        loaded = await self._wikis(session, user, guild_id, params)
        now = localize_now(datetime.now(timezone.utc), params.get("tz"))
        return RenderRequest(
            guild_id=guild_id,
            template_id=self.template_id,
            format=format,
            batch=tuple(build_wiki_item(wiki, pages, now) for wiki, pages in loaded),
        )

    async def _wikis(
        self, session: AsyncSession, user: User, guild_id: int, params: dict
    ) -> list[tuple[Wiki, list[WikiPage]]]:
        from app.services.export.adapters._common import selection_ids
        from app.services.tenant.wikis import get_wiki_for_export

        return [
            await get_wiki_for_export(session, user, guild_id, wiki_id=wiki_id)
            for wiki_id in selection_ids(
                params, single_key="wiki_id", multi_key="wiki_ids"
            )
        ]


def build_wiki_item(wiki: Wiki, pages: list[WikiPage], now: datetime) -> RenderItem:
    date = now.strftime("%Y-%m-%d")
    stem = safe_filename_component(wiki.name).lower()
    # The envelope is importable machine data — stays canonical, never
    # localized (translating field keys breaks import).
    return RenderItem(
        key=f"{stem}-{date}.initiative-wiki",
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
        "pages": [_page_envelope(page) for page in pages],
    }


def _page_envelope(page: WikiPage) -> dict[str, Any]:
    return {
        "title": page.title,
        "slug": page.slug,
        "position": page.position,
        "content": page.content or {},
        "tags": sorted(tag.name for tag in getattr(page, "tags", None) or []),
    }

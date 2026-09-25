"""Wiki source adapter: the importable envelope (json), or the whole wiki as
one document (pdf, md, docx) — and, beside either, the documents filed in it.

As a document, the pages are read in the order the tree gives them, each under
a heading with its title, nested as deep as the page sits; drafts are left
out, because a copy to read is not where an unfinished page gets shown. The
documents filed in the wiki ride in the same download under ``documents/``,
each in the format that fits its type — a text document in the format asked
for, a spreadsheet as a workbook, an upload as itself. The importable file
carries them inside the wiki's envelope instead, with where each is filed, so
an import files them again; an upload's bytes ride under ``assets/``. A wiki
exported on its own is always a zip, filed documents or not, so its download
is one kind of file whatever it holds. Only the documents the exporter could export on their own come
along: filing a document in a wiki is not a way to hand over a copy of it.

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

from dataclasses import replace

from fastapi import HTTPException

from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.document import Document, DocumentType
from app.models.tenant.wiki import Wiki, WikiPage
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    envelope_key,
    export_stem,
)
from app.services.export.contract import RenderItem
from app.services.permissions import EXPORT_ACCESS

#: What one wiki contributes to a batch: its row, its pages, and the documents
#: filed in it that come along.
Loaded = tuple[Wiki, list[WikiPage], list[Document]]

#: Where the filed documents sit in the download.
DOCUMENTS_DIR = "documents/"


class WikiAdapter(ToolExportAdapter):
    tool = Tool.wiki
    template_id = "document"  # the Lexical PDF template documents use
    formats = ("json", "pdf", "md", "docx")
    #: Always a zip: the wiki and the documents filed in it are one download.
    force_zip = True

    async def fetch(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        wiki_id: int,
        /,
        *,
        access: str = EXPORT_ACCESS,
    ) -> Loaded:
        from app.services.tenant.documents import get_document_for_export
        from app.services.tenant.wikis import linked_documents

        wiki, pages, _ = await self.fetch_pages(
            session, user, guild_id, wiki_id, access=access
        )
        documents: list[Document] = []
        for linked in await linked_documents(session, wiki.id):
            try:
                documents.append(
                    await get_document_for_export(
                        session, user, guild_id, document_id=linked.id, access=access
                    )
                )
            except HTTPException:
                # Not theirs to export: it stays out of the download.
                continue
        return wiki, pages, documents

    async def fetch_pages(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        wiki_id: int,
        /,
        *,
        access: str = EXPORT_ACCESS,
    ) -> Loaded:
        """The wiki and its pages, with no filed documents. An initiative or
        community backup writes those as entries of their own and places them
        in the wiki from there."""
        from app.services.tenant.wikis import get_wiki_for_export

        wiki, pages = await get_wiki_for_export(
            session, user, guild_id, wiki_id=wiki_id, access=access
        )
        return wiki, pages, []

    async def initiative_ids(
        self, session: AsyncSession, user: User, guild_id: int, initiative_id: int, /
    ) -> list[int]:
        from app.services.tenant.wikis import list_wiki_ids_for_export

        return await list_wiki_ids_for_export(
            session, user, guild_id, initiative_ids=[initiative_id]
        )

    def title(self, loaded: Loaded, /) -> str:
        wiki, _pages, _documents = loaded
        return wiki.name

    def rows(self, loaded: Loaded, /) -> int:
        # One row per page and per filed document: a wiki's size is what is
        # written in it, not the single row naming it.
        _wiki, pages, documents = loaded
        return (len(pages) + len(documents)) or 1

    def item(self, loaded: Loaded, ctx: BuildContext, /) -> RenderItem:
        wiki, pages, _documents = loaded
        if ctx.format == "json":
            return build_wiki_item(wiki, pages, ctx.now)
        return build_wiki_document_item(wiki, pages, ctx)

    def items(self, loaded: Loaded, ctx: BuildContext, /) -> tuple[RenderItem, ...]:
        """The wiki, then each document filed in it — beside it as a file of
        its own, or inside its envelope with an upload's bytes beside it."""
        wiki, pages, documents = loaded
        if ctx.format == "json":
            filed, uploads = filed_document_records(wiki, pages, documents, ctx)
            return (build_wiki_item(wiki, pages, ctx.now, documents=filed), *uploads)
        return (
            self.item(loaded, ctx),
            *(filed_document_item(document, ctx) for document in documents),
        )


def _reading_order(pages: list[WikiPage]) -> list[tuple[WikiPage, int]]:
    """Each page with its depth, parents before their children.

    ``pages`` come in navigation order — siblings by position — so a page can
    precede its parent; walking the tree from the top puts every page under
    the one it is filed in. A page whose parent is not in the list sits at the
    top.
    """
    ids = {page.id for page in pages}
    children: dict[int | None, list[WikiPage]] = {}
    for page in pages:
        parent = page.parent_page_id if page.parent_page_id in ids else None
        children.setdefault(parent, []).append(page)
    ordered: list[tuple[WikiPage, int]] = []
    seen: set[int | None] = set()

    def walk(parent: int | None, depth: int) -> None:
        for page in children.get(parent, []):
            if page.id in seen:
                continue
            seen.add(page.id)
            ordered.append((page, depth))
            walk(page.id, depth + 1)

    walk(None, 0)
    return ordered


def _heading(text: str, depth: int) -> dict[str, Any]:
    return {
        "type": "heading",
        "tag": f"h{min(depth + 1, 6)}",
        "version": 1,
        "direction": "ltr",
        "format": "",
        "indent": 0,
        "children": [
            {
                "type": "text",
                "version": 1,
                "text": text,
                "format": 0,
                "style": "",
                "mode": "normal",
                "detail": 0,
            }
        ],
    }


def _page_state(page: WikiPage, depth: int) -> dict[str, Any]:
    """One page as an editor state: its title as a heading at its depth, then
    its body."""
    children: list[Any] = [_heading(page.title, depth)]
    root = (page.content or {}).get("root")
    if isinstance(root, dict):
        children.extend(root.get("children") or [])
    return {"root": {"type": "root", "version": 1, "children": children}}


def build_wiki_document_item(
    wiki: Wiki, pages: list[WikiPage], ctx: BuildContext
) -> RenderItem:
    """The wiki as one document, in the format asked for."""
    from app.services.export.i18n import et, export_locale
    from app.services.export.lexical import blocks_from_editor_state

    loc = export_locale(ctx.user)
    stem = export_stem(wiki.name, ctx.date)
    # Each page starts a page of its own in a PDF or a Word file.
    blocks: list[dict[str, Any]] = []
    assets: dict[str, dict[str, Any]] = {}
    for page, depth in _reading_order([page for page in pages if not page.is_draft]):
        page_blocks, page_assets = blocks_from_editor_state(
            _page_state(page, depth), guild_id=ctx.guild_id
        )
        if blocks:
            blocks.append({"type": "pagebreak"})
        blocks.extend(page_blocks)
        for asset in page_assets:
            assets.setdefault(asset["key"], asset)
    return RenderItem(
        key=stem,
        data={
            # Title and footer are the wiki's own name (user data).
            "title": wiki.name,
            "footer": wiki.name,
            "page_of": et("pageOf", loc),
            "stem": stem,
            "blocks": blocks,
            "assets": list(assets.values()),
        },
    )


def filed_format(document: Document, format: str) -> str:
    """The format a filed document travels in beside a wiki exported as
    ``format``: its own type decides what it can be."""
    doc_type = getattr(document.document_type, "value", document.document_type)
    if doc_type == DocumentType.native.value:
        return format
    if doc_type == DocumentType.spreadsheet.value:
        return "json" if format == "json" else "xlsx"
    if doc_type == DocumentType.file.value:
        return "file"
    if doc_type == DocumentType.smart_link.value:
        return "json" if format == "json" else "md"
    # A whiteboard is only ever its scene.
    return "json"


def filed_document_item(document: Document, ctx: BuildContext) -> RenderItem:
    """One filed document, under ``documents/`` in the wiki's download."""
    from app.services.export.adapters.document import build_document_item
    from app.services.export.i18n import export_locale

    format = filed_format(document, ctx.format)
    item = build_document_item(
        document,
        format,
        guild_id=ctx.guild_id,
        date=ctx.date,
        loc=export_locale(ctx.user),
    )
    if format == "file":
        name = str(item.data.get("filename") or item.key)
    elif format == "json":
        name = f"{envelope_key(Tool.document, document.name, ctx.date)}.json"
    else:
        name = f"{item.key}.{format}"
    return replace(item, format=format, filename=f"{DOCUMENTS_DIR}{name}")


def build_wiki_item(
    wiki: Wiki,
    pages: list[WikiPage],
    now: datetime,
    *,
    documents: list[dict[str, Any]] | None = None,
) -> RenderItem:
    # The envelope is importable machine data — stays canonical, never
    # localized (translating field keys breaks import).
    data = _envelope(wiki, pages)
    if documents:
        data["documents"] = documents
    return RenderItem(
        key=envelope_key(Tool.wiki, wiki.name, now.strftime("%Y-%m-%d")),
        data=data,
    )


def filed_document_records(
    wiki: Wiki, pages: list[WikiPage], documents: list[Document], ctx: BuildContext
) -> tuple[list[dict[str, Any]], list[RenderItem]]:
    """Each filed document as the wiki's envelope carries it — whole, or for
    an upload the row and the key its bytes are zipped under — and the upload
    blobs to zip beside it. An upload whose file is gone is left out."""
    from app.services.export.adapters.document import build_document_item
    from app.services.export.i18n import export_locale
    from app.services.storage import get_guild_storage
    from app.services.tenant.wikis import document_parent, document_position

    slugs = {page.id: page.slug for page in pages}
    storage = get_guild_storage(ctx.guild_id)
    loc = export_locale(ctx.user)
    records: list[dict[str, Any]] = []
    uploads: list[RenderItem] = []
    for document in documents:
        parent = document_parent(wiki, document.id)
        record: dict[str, Any] = {
            "page": slugs.get(parent) if parent is not None else None,
            "position": document_position(wiki, document.id),
            "external_ref": f"document:{document.id}",
        }
        doc_type = getattr(document.document_type, "value", document.document_type)
        if doc_type == DocumentType.file.value:
            key = (document.file_url or "").split("/")[-1]
            if not key or not storage.exists(key):
                continue
            record["upload"] = {
                "name": document.name,
                "storage_key": key,
                "original_filename": document.original_filename,
                "content_type": document.file_content_type,
                "tags": sorted(tag.name for tag in document.tags or []),
            }
            uploads.append(
                RenderItem(
                    key=key,
                    data={
                        "storage_key": key,
                        "content_type": document.file_content_type,
                    },
                    filename=f"assets/{key}",
                    format="file",
                )
            )
        else:
            record["envelope"] = build_document_item(
                document, "json", guild_id=ctx.guild_id, date=ctx.date, loc=loc
            ).data
        records.append(record)
    return records, uploads


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
        # When it was written, and when it was last edited. A restore that
        # dated every page to the day it was restored lost the one thing a
        # wiki's reading order is usually checked against.
        "created_at": page.created_at.isoformat() if page.created_at else None,
        "updated_at": page.updated_at.isoformat() if page.updated_at else None,
        # The name this page answers to across one import, so a reference to
        # it elsewhere in the same restore points at the page it became.
        "external_ref": f"wiki_page:{page.id}",
    }

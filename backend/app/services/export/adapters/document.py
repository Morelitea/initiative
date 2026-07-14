"""Document source adapter: one source, per-type format rules.

A document's exportable formats depend on its type, so the static registry
declares the union and this adapter enforces the per-type subset at count
time (before a job is created, so a mismatch is an immediate 400):

* ``native`` (Lexical)  -> ``json`` (the generic document envelope with the
  raw editor state as ``content`` — the editor toolbar's import unwraps it,
  so an engine export still round-trips), plus ``md`` (zipped with an
  ``assets/`` folder when images are referenced), ``pdf`` and ``docx`` (both
  embedding referenced same-guild images) via the ``lexical`` converter
  module.
* ``whiteboard``        -> ``json``  — the generic document envelope with
  the scene (as the standard Excalidraw file shape) under ``content``, so a
  backup keeps tags/properties and unwrapping still yields a file any
  Excalidraw opens. Pixel exports (PNG/SVG) are deliberately client-side:
  only Excalidraw's own JS renders scenes faithfully, and the design forbids
  a JS runtime here.
* ``spreadsheet``       -> ``csv`` / ``xlsx`` — the sparse grid, with the
  formatting model mapped for xlsx — and ``json``, the canonical snapshot in
  an importable envelope (the snapshot is already the versioned format the
  write-path normalizer validates, so a future import consumes it directly).
* ``file``              -> ``file`` — the stored upload, unconverted, under
  its original name.
* ``smart_link``        -> ``md``  — the title and URL — and ``json``, the
  generic document envelope (importable backup, like spreadsheets).

Every ``initiative-document`` envelope carries the document's ``tags`` (by
name) and custom ``properties`` (flat, by name — the shared encoding in
``export/property_values.py``), so backups don't shed metadata.

Access: READ suffices (exporting is a formatted read), enforced by the
``get_document_for_export`` seam at both count and build time under the
caller's RLS session.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ExportMessages
from app.models.platform.user import User
from app.models.tenant.document import Document, DocumentType
from app.services.export.adapters._common import selection_ids
from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.engine import ExportError
from app.services.platform.csv_export import safe_filename_component

_TYPE_FORMATS: dict[str, frozenset[str]] = {
    DocumentType.native.value: frozenset({"json", "md", "pdf", "docx"}),
    DocumentType.whiteboard.value: frozenset({"json"}),
    DocumentType.spreadsheet.value: frozenset({"csv", "xlsx", "json"}),
    DocumentType.file.value: frozenset({"file"}),
    DocumentType.smart_link.value: frozenset({"md", "json"}),
}

# The size proxy divisor for file passthroughs: one "row" per MiB, so the
# inline threshold (rows) doubles as an inline size cap in MiB.
_FILE_SIZE_ROW_BYTES = 1_048_576


class DocumentAdapter:
    source = "document"
    template_id = "document"  # the Lexical PDF template
    formats = frozenset().union(*_TYPE_FORMATS.values())

    async def count(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> int:
        documents = await self._documents(session, user, guild_id, params, format)
        return sum(_document_count(d) for d in documents)

    async def build(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> RenderRequest:
        from app.services.export.i18n import export_locale, localize_now

        documents = await self._documents(session, user, guild_id, params, format)
        date = localize_now(datetime.now(timezone.utc), params.get("tz")).strftime(
            "%Y-%m-%d"
        )
        loc = export_locale(user)
        return RenderRequest(
            guild_id=guild_id,
            template_id=self.template_id,
            format=format,
            batch=tuple(
                build_document_item(
                    document, format, guild_id=guild_id, date=date, loc=loc
                )
                for document in documents
            ),
        )

    async def _documents(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> list[Document]:
        """Fetch + authorize every selected document (read suffices), and
        enforce the per-type format rule on each — a selection is only
        exportable in a format every member of it supports."""
        from app.services.tenant.documents import get_document_for_export

        documents = []
        for document_id in _document_ids(params):
            document = await get_document_for_export(
                session, user, guild_id, document_id=document_id
            )
            allowed = _TYPE_FORMATS.get(_doc_type(document), frozenset())
            if format not in allowed:
                raise ExportError(ExportMessages.EXPORT_INVALID_FORMAT)
            documents.append(document)
        return documents


def _document_count(document: Document) -> int:
    doc_type = _doc_type(document)
    if doc_type == DocumentType.spreadsheet.value:
        return len((document.content or {}).get("cells") or {})
    if doc_type == DocumentType.file.value:
        return int(document.file_size or 0) // _FILE_SIZE_ROW_BYTES
    return 1


def build_document_item(
    document: Document, format: str, *, guild_id: int, date: str, loc: str
) -> RenderItem:
    """One document's render item — a selection export is just a batch of
    these (the engine zips a batch of N into a single download)."""
    from app.services.export.i18n import et

    doc_type = _doc_type(document)
    stem = f"{safe_filename_component(document.title).lower()}-{date}"

    if doc_type == DocumentType.native.value and format != "json":
        from app.services.export.lexical import blocks_from_editor_state

        blocks, assets = blocks_from_editor_state(
            document.content or {}, guild_id=guild_id
        )
        data = {
            # Title/footer are the document's own name (user data).
            "title": document.title,
            "subtitle": et("exported", loc, date=date),
            "footer": document.title,
            "page_of": et("pageOf", loc),
            "stem": stem,
            "blocks": blocks,
            "assets": assets,
        }
        return RenderItem(key=stem, data=data)
    if doc_type == DocumentType.whiteboard.value:
        # Importable backup: the scene wrapped as the standard Excalidraw
        # file shape INSIDE the generic envelope — a future import
        # discriminates by kind like every other document type, and
        # unwrapping `content` still yields a file any Excalidraw opens.
        content = document.content or {}
        data = _envelope(
            document,
            content={
                "type": "excalidraw",
                "version": 2,
                "source": "initiative",
                "elements": content.get("elements") or [],
                "appState": content.get("appState") or {},
                "files": content.get("files") or {},
            },
        )
    elif doc_type == DocumentType.native.value:
        # Importable backup: the raw editor state inside the generic
        # document envelope. The editor toolbar's import unwraps the
        # envelope, so round-trip through the editor survives.
        data = _envelope(document, content=document.content or {})
    elif doc_type == DocumentType.spreadsheet.value:
        if format == "json":
            # Importable backup: the canonical (already-versioned) snapshot
            # in the generic document envelope, so a future import can
            # discriminate file kinds uniformly.
            data = _envelope(document, content=document.content or {})
        else:
            data = {"title": document.title, "grid": document.content or {}}
    elif doc_type == DocumentType.file.value:
        storage_key = (document.file_url or "").split("/")[-1]
        data = {
            "storage_key": storage_key,
            "filename": document.original_filename or storage_key,
            "content_type": document.file_content_type,
        }
    else:  # smart_link
        if format == "json":
            data = _envelope(
                document,
                content={"url": (document.content or {}).get("url", "")},
            )
        else:
            data = {
                "layout": "link",
                "title": document.title,
                "url": (document.content or {}).get("url", ""),
            }

    return RenderItem(key=stem, data=data)


def _envelope(document: Document, *, content: dict) -> dict:
    """The generic ``initiative-document`` envelope: kind + schema_version
    discriminate the file for a future import; tags (by name) and custom
    properties (flat, by name) ride along so a backup keeps the document's
    metadata."""
    from app.services.export.property_values import property_export_dict

    return {
        "kind": "initiative-document",
        "schema_version": 1,
        "document_type": _doc_type(document),
        "title": document.title,
        "content": content,
        "tags": sorted(
            link.tag.name for link in document.tag_links or [] if link.tag is not None
        ),
        "properties": [
            property_export_dict(pv)
            for pv in document.property_values or []
            if pv.property_definition is not None
        ],
    }


def _doc_type(document: Document) -> str:
    doc_type = document.document_type
    return doc_type.value if hasattr(doc_type, "value") else str(doc_type)


def _document_ids(params: dict) -> list[int]:
    return selection_ids(params, single_key="document_id", multi_key="document_ids")

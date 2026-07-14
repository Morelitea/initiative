"""Document source adapter: one source, per-type format rules.

A document's exportable formats depend on its type, so the static registry
declares the union and this adapter enforces the per-type subset at count
time (before a job is created, so a mismatch is an immediate 400):

* ``native`` (Lexical)  -> ``json`` (a ``.lexical`` file in the exact
  ``@lexical/file`` schema the editor's toolbar IMPORT button consumes, so
  an engine export round-trips through the existing import), plus ``md``
  (zipped with an ``assets/`` folder when images are referenced), ``pdf``
  and ``docx`` (both embedding referenced same-guild images) via the
  ``lexical`` converter module.
* ``whiteboard``        -> ``json``  — the scene wrapped in the standard
  Excalidraw file shape, so the download opens in any Excalidraw. Pixel
  exports (PNG/SVG) are deliberately client-side: only Excalidraw's own JS
  renders scenes faithfully, and the design forbids a JS runtime here.
* ``spreadsheet``       -> ``csv`` / ``xlsx`` — the sparse grid, with the
  formatting model mapped for xlsx — and ``json``, the canonical snapshot in
  an importable envelope (the snapshot is already the versioned format the
  write-path normalizer validates, so a future import consumes it directly).
* ``file``              -> ``file`` — the stored upload, unconverted, under
  its original name.
* ``smart_link``        -> ``md``  — the title and URL.

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
from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.engine import ExportError
from app.services.platform.csv_export import safe_filename_component

_TYPE_FORMATS: dict[str, frozenset[str]] = {
    DocumentType.native.value: frozenset({"json", "md", "pdf", "docx"}),
    DocumentType.whiteboard.value: frozenset({"json"}),
    DocumentType.spreadsheet.value: frozenset({"csv", "xlsx", "json"}),
    DocumentType.file.value: frozenset({"file"}),
    DocumentType.smart_link.value: frozenset({"md"}),
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
                _item(document, format, guild_id=guild_id, date=date, loc=loc)
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


def _item(
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
        # The standard Excalidraw file shape — importable by any Excalidraw
        # (app or excalidraw.com), not just this instance.
        content = document.content or {}
        data = {
            "type": "excalidraw",
            "version": 2,
            "source": "initiative",
            "elements": content.get("elements") or [],
            "appState": content.get("appState") or {},
            "files": content.get("files") or {},
        }
    elif doc_type == DocumentType.native.value:
        # The @lexical/file SerializedDocument shape — byte-compatible with
        # the editor toolbar's import (which only accepts .lexical files,
        # hence the explicit filename below).
        from app.core.version import get_version

        data = {
            "editorState": document.content or {},
            "lastSaved": int(document.updated_at.timestamp() * 1000),
            "source": "Initiative",
            "version": get_version(),
        }
        return RenderItem(key=stem, data=data, filename=f"{stem}.lexical")
    elif doc_type == DocumentType.spreadsheet.value:
        if format == "json":
            # Importable backup: the canonical (already-versioned) snapshot
            # in the generic document envelope, so a future import can
            # discriminate file kinds uniformly.
            data = {
                "kind": "initiative-document",
                "schema_version": 1,
                "document_type": doc_type,
                "title": document.title,
                "content": document.content or {},
            }
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
        data = {
            "layout": "link",
            "title": document.title,
            "url": (document.content or {}).get("url", ""),
        }

    return RenderItem(key=stem, data=data)


def _doc_type(document: Document) -> str:
    doc_type = document.document_type
    return doc_type.value if hasattr(doc_type, "value") else str(doc_type)


# Bound on a single selection: page-size multiples, not initiative dumps —
# each id costs a fetch+authorize round trip at count AND build time.
_MAX_SELECTION = 100


def selection_ids(params: dict, *, single_key: str, multi_key: str) -> list[int]:
    """Normalize a selection selector to a validated id list. Accepts either
    the legacy single-id key or the multi-id key (job params round-trip
    through JSON — validate, don't trust). Order-preserving dedupe."""
    raw = params.get(multi_key)
    if raw is None and params.get(single_key) is not None:
        raw = [params[single_key]]
    if not isinstance(raw, list) or not raw or len(raw) > _MAX_SELECTION:
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
    try:
        ids = [int(value) for value in raw]
    except (TypeError, ValueError):
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
    return list(dict.fromkeys(ids))


def _document_ids(params: dict) -> list[int]:
    return selection_ids(params, single_key="document_id", multi_key="document_ids")

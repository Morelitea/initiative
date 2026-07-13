"""Document source adapter: one source, per-type format rules.

A document's exportable formats depend on its type, so the static registry
declares the union and this adapter enforces the per-type subset at count
time (before a job is created, so a mismatch is an immediate 400):

* ``native`` (Lexical)  -> ``json``  — the editor state wrapped in a small
  importable envelope. (md/pdf/docx conversion is the next phase.)
* ``whiteboard``        -> ``json``  — the scene wrapped in the standard
  Excalidraw file shape, so the download opens in any Excalidraw. Pixel
  exports (PNG/SVG) are deliberately client-side: only Excalidraw's own JS
  renders scenes faithfully, and the design forbids a JS runtime here.
* ``spreadsheet``       -> ``csv`` / ``xlsx`` — the sparse grid, with the
  formatting model mapped for xlsx.
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
    DocumentType.native.value: frozenset({"json"}),
    DocumentType.whiteboard.value: frozenset({"json"}),
    DocumentType.spreadsheet.value: frozenset({"csv", "xlsx"}),
    DocumentType.file.value: frozenset({"file"}),
    DocumentType.smart_link.value: frozenset({"md"}),
}

# The size proxy divisor for file passthroughs: one "row" per MiB, so the
# inline threshold (rows) doubles as an inline size cap in MiB.
_FILE_SIZE_ROW_BYTES = 1_048_576


class DocumentAdapter:
    source = "document"
    template_id = "document"  # no PDF template yet (Lexical PDF is next phase)
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
        document = await self._document(session, user, guild_id, params, format)
        doc_type = _doc_type(document)
        if doc_type == DocumentType.spreadsheet.value:
            return len((document.content or {}).get("cells") or {})
        if doc_type == DocumentType.file.value:
            return int(document.file_size or 0) // _FILE_SIZE_ROW_BYTES
        return 1

    async def build(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> RenderRequest:
        document = await self._document(session, user, guild_id, params, format)
        doc_type = _doc_type(document)
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        stem = f"{safe_filename_component(document.title).lower()}-{date}"

        if doc_type == DocumentType.whiteboard.value:
            # The standard Excalidraw file shape — importable by any
            # Excalidraw (app or excalidraw.com), not just this instance.
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
            data = {
                "kind": "initiative-document",
                "schema_version": 1,
                "document_type": doc_type,
                "title": document.title,
                "content": document.content or {},
            }
        elif doc_type == DocumentType.spreadsheet.value:
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

        return RenderRequest(
            guild_id=guild_id,
            template_id=self.template_id,
            format=format,
            batch=(RenderItem(key=stem, data=data),),
        )

    async def _document(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> Document:
        from app.services.tenant.documents import get_document_for_export

        document = await get_document_for_export(
            session, user, guild_id, document_id=_document_id(params)
        )
        allowed = _TYPE_FORMATS.get(_doc_type(document), frozenset())
        if format not in allowed:
            raise ExportError(ExportMessages.EXPORT_INVALID_FORMAT)
        return document


def _doc_type(document: Document) -> str:
    doc_type = document.document_type
    return doc_type.value if hasattr(doc_type, "value") else str(doc_type)


def _document_id(params: dict) -> int:
    """The job row's params round-trip through JSON — validate, don't trust."""
    try:
        return int(params["document_id"])
    except (KeyError, TypeError, ValueError):
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)

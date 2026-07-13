"""``LocalRenderBackend`` — typst-py in a thread pool.

The single-container FOSS renderer: compiles a ``.typ`` template with the
item's data passed as ``sys.inputs`` (never interpolated into template
source), inside ``run_in_executor`` — the PyO3 binding releases the GIL, so a
heavy render doesn't stall the event loop. ``ignore_system_fonts=True`` pins
rendering to the fonts embedded in the typst wheel, so output is
deterministic across images with no font bundling step.

Non-PDF formats dispatch to lightweight renderers: the tabular module
(csv/xlsx/md over columns/rows payloads, or a spreadsheet document's sparse
grid), verbatim JSON, and the ``file`` passthrough (an uploaded blob exported
unconverted — the one format whose content type and filename come from the
stored object, not a static map).
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import typst

from app.services.export import lexical, spreadsheet, tabular
from app.services.export.contract import (
    RenderedArtifact,
    RenderItem,
    RenderRequest,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Template ids are internal identifiers, never user text — but the id does
# reach the filesystem, so whitelist the alphabet anyway (no traversal).
_TEMPLATE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "md": "text/markdown; charset=utf-8",
    "json": "application/json",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "file": "application/octet-stream",  # per-item override from the blob
}


class UnknownTemplateError(ValueError):
    pass


def resolve_template(template_id: str) -> Path:
    if not _TEMPLATE_ID_RE.match(template_id):
        raise UnknownTemplateError(template_id)
    path = TEMPLATES_DIR / f"{template_id}.typ"
    if not path.is_file():
        raise UnknownTemplateError(template_id)
    return path


class LocalRenderBackend:
    async def render(self, req: RenderRequest) -> list[RenderedArtifact]:
        # Only the PDF path involves a template; tabular formats consume the
        # payload's columns/rows directly. Resolve (and thereby validate) the
        # template up front so a bad id fails before the executor hop.
        template = resolve_template(req.template_id) if req.format == "pdf" else None
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._render_sync, template, req)

    @staticmethod
    def _render_sync(
        template: Path | None, req: RenderRequest
    ) -> list[RenderedArtifact]:
        return [_render_item(template, req, item) for item in req.batch]


def _render_item(
    template: Path | None, req: RenderRequest, item: RenderItem
) -> RenderedArtifact:
    format = req.format
    content_type = _CONTENT_TYPES[format]
    filename: str | None = item.filename
    if format == "file":
        content, content_type, filename = _read_passthrough(req.guild_id, item.data)
    elif format == "csv":
        content = (
            spreadsheet.render_csv(item.data["grid"])
            if "grid" in item.data
            else tabular.render_csv(item)
        )
    elif format == "xlsx":
        content = (
            spreadsheet.render_xlsx(
                item.data["grid"], title=str(item.data.get("title", item.key))
            )
            if "grid" in item.data
            else tabular.render_xlsx(item)
        )
    elif format == "md":
        if "blocks" in item.data:
            content, content_type, lexical_name = lexical.render_markdown(
                item.data, _blob_reader(req.guild_id)
            )
            filename = lexical_name or filename
        else:
            content = tabular.render_md(item)
    elif format == "docx":
        content = lexical.render_docx(item.data, _blob_reader(req.guild_id))
    elif format == "json":
        # The payload IS the artifact (e.g. a backup envelope); indent for a
        # human-inspectable file.
        content = json.dumps(item.data, ensure_ascii=False, indent=2).encode("utf-8")
    else:
        assert template is not None  # resolve_template ran for the pdf path
        if item.data.get("assets") or item.assets_inline:
            content = _compile_with_assets(template, format, item, req.guild_id)
        else:
            content = _compile(template, format, item)
    return RenderedArtifact(
        key=item.key, content_type=content_type, content=content, filename=filename
    )


def _blob_reader(guild_id: int):
    """Bytes-by-storage-key reader for renderers that embed uploads (asset
    images, file passthrough). Keys are derived by adapters from document
    rows under the caller's RLS session — never from raw user input."""
    from app.services.storage import get_guild_storage

    storage = get_guild_storage(guild_id)

    def read(key: str) -> bytes:
        blob = storage.open_readable(str(key))
        if blob is None:
            raise FileNotFoundError(key)
        if blob.path is not None:
            return Path(blob.path).read_bytes()
        return blob.stream.read()  # type: ignore[union-attr]

    return read


def _read_passthrough(
    guild_id: int, data: dict[str, Any]
) -> tuple[bytes, str, str | None]:
    """Read a stored upload blob for unconverted export."""
    from app.services.storage import get_guild_storage

    blob = get_guild_storage(guild_id).open_readable(str(data["storage_key"]))
    if blob is None:
        raise FileNotFoundError(data["storage_key"])
    content = _blob_reader(guild_id)(str(data["storage_key"]))
    content_type = (
        str(data.get("content_type") or "")
        or blob.content_type
        or "application/octet-stream"
    )
    filename = str(data.get("filename") or "") or None
    return content, content_type, filename


def _compile(template: Path, format: str, item: RenderItem) -> bytes:
    # Data crosses into the template ONLY as a sys.inputs string (the
    # typst-injection guard): the template decodes it with
    # json(bytes(sys.inputs.data)) — user text is data, never Typst markup.
    return typst.compile(
        str(template),
        format=format,
        sys_inputs={"data": json.dumps(item.data, ensure_ascii=False)},
        ignore_system_fonts=True,
    )


def _compile_with_assets(
    template: Path, format: str, item: RenderItem, guild_id: int
) -> bytes:
    """Compile with referenced images staged into the project root — Typst
    reads files only under its root, so a temp dir holds a copy of the template
    plus an assets/ folder. Two sources feed it: storage-backed upload images
    (``data["assets"]``, keyed into guild storage) and inline bytes
    (``assets_inline``, e.g. the guild-icon header decoded from the guild
    row)."""
    import shutil
    import tempfile

    read = _blob_reader(guild_id)
    with tempfile.TemporaryDirectory(prefix="export-render-") as tmp:
        root = Path(tmp)
        main = root / template.name
        shutil.copyfile(template, main)
        assets_dir = root / "assets"
        assets_dir.mkdir()
        staged: set[str] = set()
        for asset in item.data.get("assets") or []:
            try:
                content = read(asset["key"])
            except Exception:
                # Gone from storage: skip — the block degrades below rather
                # than the whole export failing.
                continue
            # Names come from safe_filename_component — no traversal.
            (assets_dir / asset["name"]).write_bytes(content)
            staged.add(asset["name"])
        # Inline assets (filename -> bytes) are already validated (raster,
        # size-capped) at the branding layer; filenames are literals we choose.
        for name, blob in item.assets_inline.items():
            (assets_dir / name).write_bytes(blob)
            staged.add(name)
        # Typst FAILS the compile on a missing image file, so any image block
        # whose asset didn't stage degrades to its alt text.
        data = dict(item.data)
        data["blocks"] = [
            {"type": "paragraph", "runs": [{"text": b.get("alt") or "[image]"}]}
            if b.get("type") == "image" and b.get("asset") and b["asset"] not in staged
            else b
            for b in data.get("blocks") or []
        ]
        return typst.compile(
            str(main),
            root=str(root),
            format=format,
            sys_inputs={"data": json.dumps(data, ensure_ascii=False)},
            ignore_system_fonts=True,
        )

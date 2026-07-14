"""The universal render contract and the ``RenderBackend`` seam.

Everything — one report or ten thousand — is a batch of render jobs. The
contract is backend-agnostic: it knows nothing about where it runs, which is
what keeps a future distributed/cloud render backend a no-op addition (a
second ``RenderBackend`` implementation behind ``EXPORT_BACKEND``, touching
no adapter, template, or endpoint).

``RenderItem.data`` is structured JSON the template reads (Typst
``sys.inputs``) — never string-interpolated into ``.typ`` source. That is the
typst-injection guard, the analogue of the CSV formula-injection
neutralization in ``app/services/platform/csv_export.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class RenderItem:
    """One artifact to render: ``key`` names it within the job (the download
    filename stem for batch=1), ``data`` is the payload the template reads.

    ``filename`` overrides the default ``{key}.{format}`` download name when
    the adapter needs a specific extension (e.g. the ``.lexical`` files the
    editor's import button accepts).

    ``assets_inline`` maps a staged filename to raw bytes to write into the
    Typst compile root's ``assets/`` folder — for images that aren't in guild
    storage (the guild icon in the report header, decoded from the guild row).
    Kept off ``data`` because ``data`` is JSON-serialized into ``sys.inputs``;
    bytes ride alongside.

    ``format`` / ``template_id`` override the request's values for THIS item —
    the aggregate sources mix formats in one batch (a backup zips envelopes
    beside file blobs; an à-la-carte report zips a project PDF beside a queue
    CSV). ``None`` inherits the request value, so single-format sources are
    untouched."""

    key: str
    data: dict[str, Any]
    filename: str | None = None
    assets_inline: dict[str, bytes] = field(default_factory=dict)
    format: str | None = None
    template_id: str | None = None


@dataclass(frozen=True)
class RenderRequest:
    """A batch of render jobs. len(batch)==1 is a single report; len N is
    mail-merge — same engine path either way."""

    guild_id: int
    template_id: str
    format: str  # "pdf" (v1)
    batch: tuple[RenderItem, ...]


@dataclass(frozen=True)
class RenderedArtifact:
    """The produced bytes for one batch item. The backend renders; the engine
    decides where the bytes go (inline response vs the guild storage backend),
    so filesystem/object-store access stays confined to the engine layer.

    ``filename`` overrides the default ``{key}.{format}`` download name —
    passthrough artifacts (an uploaded file exported unconverted) keep their
    original name and extension this way."""

    key: str
    content_type: str
    content: bytes
    filename: str | None = None


class RenderBackend(Protocol):
    """The swappable renderer seam. A distributed/cloud backend is a second
    implementation of this same interface — nothing else changes."""

    async def render(self, req: RenderRequest) -> list[RenderedArtifact]: ...

"""``LocalRenderBackend`` — typst-py in a thread pool.

The single-container FOSS renderer: compiles a ``.typ`` template with the
item's data passed as ``sys.inputs`` (never interpolated into template
source), inside ``run_in_executor`` — the PyO3 binding releases the GIL, so a
heavy render doesn't stall the event loop. ``ignore_system_fonts=True`` pins
rendering to the fonts embedded in the typst wheel, so output is
deterministic across images with no font bundling step.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import typst

from app.services.export.contract import (
    RenderedArtifact,
    RenderItem,
    RenderRequest,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Template ids are internal identifiers, never user text — but the id does
# reach the filesystem, so whitelist the alphabet anyway (no traversal).
_TEMPLATE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

_CONTENT_TYPES = {"pdf": "application/pdf"}


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
        template = resolve_template(req.template_id)
        content_type = _CONTENT_TYPES[req.format]
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._render_sync, template, content_type, req
        )

    @staticmethod
    def _render_sync(
        template: Path, content_type: str, req: RenderRequest
    ) -> list[RenderedArtifact]:
        out: list[RenderedArtifact] = []
        for item in req.batch:
            out.append(
                RenderedArtifact(
                    key=item.key,
                    content_type=content_type,
                    content=_compile(template, req.format, item),
                )
            )
        return out


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

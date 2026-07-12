"""Unit tests for the local Typst render backend."""

import pytest

from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.local_backend import (
    LocalRenderBackend,
    UnknownTemplateError,
    resolve_template,
)

pytestmark = pytest.mark.unit


def _request(**data) -> RenderRequest:
    payload = {
        "title": "Tasks",
        "subtitle": "unit test",
        "footer": "Tasks export",
        "rows": [
            {
                "title": "A task",
                "project": "P",
                "status": "To Do",
                "priority": "high",
                "due": "2026-07-12",
                "assignees": "Alice",
            }
        ],
    }
    payload.update(data)
    return RenderRequest(
        guild_id=1,
        template_id="task-table",
        format="pdf",
        batch=(RenderItem(key="tasks", data=payload),),
    )


async def test_renders_pdf_bytes():
    artifacts = await LocalRenderBackend().render(_request())
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.key == "tasks"
    assert artifact.content_type == "application/pdf"
    assert artifact.content.startswith(b"%PDF")


async def test_user_text_is_data_not_markup():
    """Typst markup / code syntax in user strings must render as literal text,
    not execute — the sys.inputs guard. A successful compile of hostile
    strings (unbalanced markup would otherwise be a compile error) is the
    signal."""
    hostile = {
        "title": '#import "x.typ"; *bold* #sys.inputs [',
        "rows": [
            {
                "title": "#eval(1+1) ]] #footnote[x] $ broken math",
                "project": "*",
                "status": "_",
                "priority": "#",
                "due": "[",
                "assignees": "]",
            }
        ],
    }
    artifacts = await LocalRenderBackend().render(_request(**hostile))
    assert artifacts[0].content.startswith(b"%PDF")


async def test_empty_rows_renders():
    artifacts = await LocalRenderBackend().render(_request(rows=[]))
    assert artifacts[0].content.startswith(b"%PDF")


def test_template_id_is_whitelisted():
    assert resolve_template("task-table").name == "task-table.typ"
    for bad in ("../secrets", "task table", "no-such-template", "TASK-TABLE", ""):
        with pytest.raises(UnknownTemplateError):
            resolve_template(bad)

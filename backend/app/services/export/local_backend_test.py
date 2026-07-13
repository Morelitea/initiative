"""Unit tests for the local Typst render backend."""

import pytest

from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.local_backend import (
    LocalRenderBackend,
    UnknownTemplateError,
    resolve_template,
)

pytestmark = pytest.mark.unit


def _request(format: str = "pdf", **data) -> RenderRequest:
    payload = {
        "title": "Tasks",
        "subtitle": "unit test",
        "footer": "Tasks export",
        "columns": [
            {"key": "title", "label": "Task"},
            {"key": "status", "label": "Status"},
        ],
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
        format=format,
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


async def test_renders_csv_with_formula_neutralization():
    """CSV rides the platform exporter's safety: BOM prefix and a leading
    formula trigger prefixed so spreadsheets treat the cell as text."""
    artifacts = await LocalRenderBackend().render(
        _request(
            format="csv",
            rows=[{"title": "=HYPERLINK(evil)", "status": "To Do"}],
        )
    )
    artifact = artifacts[0]
    assert artifact.content_type.startswith("text/csv")
    text = artifact.content.decode("utf-8")
    assert text.startswith("﻿")
    assert "Task,Status" in text
    assert "'=HYPERLINK(evil)" in text


async def test_renders_xlsx_with_formula_neutralization():
    from io import BytesIO

    from openpyxl import load_workbook

    artifacts = await LocalRenderBackend().render(
        _request(
            format="xlsx",
            rows=[{"title": "=CMD|dangerous", "status": "Done"}],
        )
    )
    artifact = artifacts[0]
    assert artifact.content.startswith(b"PK")  # zip container
    sheet = load_workbook(BytesIO(artifact.content)).active
    assert [c.value for c in sheet[1]] == ["Task", "Status"]
    row = [c.value for c in sheet[2]]
    assert row == ["'=CMD|dangerous", "Done"]
    # Neutralized: stored as a string cell, not an inferred formula.
    assert sheet.cell(row=2, column=1).data_type == "s"


async def test_renders_markdown_table_with_escaped_cells():
    """Pipes and newlines in user text must not break the GFM table."""
    artifacts = await LocalRenderBackend().render(
        _request(
            format="md",
            rows=[{"title": "a | b\nmultiline", "status": "To Do"}],
        )
    )
    artifact = artifacts[0]
    assert artifact.content_type.startswith("text/markdown")
    text = artifact.content.decode("utf-8")
    lines = text.splitlines()
    assert lines[0] == "# Tasks"
    assert "| Task | Status |" in lines
    assert "| --- | --- |" in lines
    assert "| a \\| b multiline | To Do |" in lines


async def test_renders_markdown_checklist_layout():
    """layout=checklist renders GitHub-style task items — checked from the
    row's done flag, details from the non-title columns, empties skipped."""
    artifacts = await LocalRenderBackend().render(
        _request(
            format="md",
            layout="checklist",
            rows=[
                {"title": "Open item", "status": "To Do", "done": False},
                {"title": "Shipped | piped", "status": "Done", "done": True},
                {"title": "", "status": "", "done": False},
            ],
        )
    )
    text = artifacts[0].content.decode("utf-8")
    lines = text.splitlines()
    assert "- [ ] Open item (To Do)" in lines
    assert "- [x] Shipped \\| piped (Done)" in lines
    assert "- [ ] (untitled)" in lines
    assert not any("---" in line for line in lines)  # no table separator


async def test_xlsx_sanitizes_sheet_title():
    """openpyxl raises InvalidSheetTitle on []:*?/\\ — a title carrying user
    text (e.g. a guild named "My App: Dev") must render, not crash."""
    from io import BytesIO

    from openpyxl import load_workbook

    artifacts = await LocalRenderBackend().render(
        _request(format="xlsx", title="Tasks — My App: Dev [beta] a/b\\c *?")
    )
    sheet = load_workbook(BytesIO(artifacts[0].content)).active
    assert sheet.title == "Tasks — My App Dev beta abc"
    assert len(sheet.title) <= 31

    # A title reduced to nothing falls back to the item key.
    artifacts = await LocalRenderBackend().render(_request(format="xlsx", title=":::"))
    sheet = load_workbook(BytesIO(artifacts[0].content)).active
    assert sheet.title == "tasks"


async def test_xlsx_preserves_numeric_cells():
    """Neutralization must not coerce numbers to strings: ``-5`` looks like a
    formula trigger as text, but openpyxl can't infer a formula from an int,
    and a string cell would break sorting/arithmetic in the sheet."""
    from io import BytesIO

    from openpyxl import load_workbook

    artifacts = await LocalRenderBackend().render(
        _request(
            format="xlsx",
            columns=[
                {"key": "title", "label": "Task"},
                {"key": "count", "label": "Count"},
            ],
            rows=[{"title": "-starts with trigger", "count": -5}],
        )
    )
    sheet = load_workbook(BytesIO(artifacts[0].content)).active
    assert sheet.cell(row=2, column=1).value == "'-starts with trigger"
    assert sheet.cell(row=2, column=2).value == -5
    assert sheet.cell(row=2, column=2).data_type == "n"


async def test_document_template_interleaves_nested_lists():
    """A nested list must render directly beneath its parent item, not after
    all siblings — and the parent numbering must continue past the detour."""
    import io

    from pypdf import PdfReader

    request = RenderRequest(
        guild_id=1,
        template_id="document",
        format="pdf",
        batch=(
            RenderItem(
                key="doc",
                data={
                    "title": "T",
                    "blocks": [
                        {
                            "type": "list",
                            "ordered": True,
                            "checklist": False,
                            "items": [
                                {"runs": [{"text": "ALPHA"}]},
                                {
                                    "runs": [{"text": "BRAVO"}],
                                    "children": [
                                        {
                                            "type": "list",
                                            "ordered": False,
                                            "checklist": False,
                                            "items": [
                                                {"runs": [{"text": "NESTEDBRAVO"}]}
                                            ],
                                        }
                                    ],
                                },
                                {"runs": [{"text": "CHARLIE"}]},
                            ],
                        }
                    ],
                },
            ),
        ),
    )
    artifacts = await LocalRenderBackend().render(request)
    text = PdfReader(io.BytesIO(artifacts[0].content)).pages[0].extract_text()
    assert text.index("ALPHA") < text.index("BRAVO")
    assert text.index("BRAVO") < text.index("NESTEDBRAVO")
    assert text.index("NESTEDBRAVO") < text.index("CHARLIE")
    assert "3. CHARLIE" in text  # numbering survives the nested detour


async def test_tabular_formats_skip_template_resolution():
    """A csv/xlsx render must not require a .typ template — the payload's
    columns/rows are the whole input."""
    req = RenderRequest(
        guild_id=1,
        template_id="no-such-template",
        format="csv",
        batch=(
            RenderItem(
                key="tasks",
                data={"columns": [{"key": "title", "label": "Task"}], "rows": []},
            ),
        ),
    )
    artifacts = await LocalRenderBackend().render(req)
    assert artifacts[0].content_type.startswith("text/csv")

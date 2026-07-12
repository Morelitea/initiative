"""Tabular renderers (CSV/XLSX) for the export engine.

Same source adapters, different renderer: a tabular format consumes the
``columns``/``rows`` of the same data payload the PDF template reads, so a
source that declares the format gets it with no adapter changes.

Both formats absorb the platform CSV exporter's injection safety rather than
duplicating it: every cell passes ``csv_export._neutralize_cell`` — XLSX
included, because openpyxl infers a string cell starting with ``=`` as a
formula, so the spreadsheet-injection class isn't CSV-only.
"""

from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook

from app.services.export.contract import RenderItem
from app.services.platform.csv_export import _neutralize_cell, build_csv

# Sheet titles have a 31-char limit and a forbidden character set in the XLSX
# spec; our sources use short safe keys ("tasks"), but clamp defensively.
_SHEET_TITLE_MAX = 31


def _table(item: RenderItem) -> tuple[list[str], list[list[Any]]]:
    """Project the payload's ``columns``/``rows`` into header + cell lists."""
    columns = item.data.get("columns") or []
    keys = [c["key"] for c in columns]
    headers = [c.get("label", c["key"]) for c in columns]
    rows = [[row.get(key, "") for key in keys] for row in item.data.get("rows") or []]
    return headers, rows


def render_csv(item: RenderItem) -> bytes:
    headers, rows = _table(item)
    return build_csv(headers, rows)


def render_xlsx(item: RenderItem) -> bytes:
    headers, rows = _table(item)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = str(item.data.get("title", item.key))[:_SHEET_TITLE_MAX] or item.key
    sheet.append([_neutralize_cell(value) for value in headers])
    for row in rows:
        sheet.append([_neutralize_cell(value) for value in row])
    sheet.freeze_panes = "A2"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()

"""Spreadsheet-document renderers: the sparse cell map as CSV or styled XLSX.

Input is the canonical v2 snapshot ``documents_spreadsheet`` persists:
``{dimensions, cells, columns, rows, cellStyles, frozen}`` with ``"r:c"``
keys. CSV carries values only (with the platform exporter's BOM and
formula-injection neutralization); XLSX additionally maps the formatting
model — fonts, colors, alignment, borders, number formats, column widths,
row heights, frozen panes. The app's spreadsheets store no formulas (out of
scope in the snapshot schema), so there is nothing formula-shaped to carry
over; string cells are neutralized exactly like the tabular exports.

Style precedence mirrors the editor: column style, then row style, then the
cell's own style, later layers winning per key.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.services.platform.csv_export import neutralize_cell

# Frontend sizes are CSS pixels; Excel wants points (rows) and its own
# character-width unit (columns, ~7px per unit at the default font).
_PX_TO_POINTS = 0.75
_PX_PER_WIDTH_UNIT = 7.0

_VALIGN_MAP = {"top": "top", "middle": "center", "bottom": "bottom"}

_DATE_FORMATS = {"iso": "yyyy-mm-dd", "us": "mm/dd/yyyy", "eu": "dd/mm/yyyy"}


def _grid_size(content: dict) -> tuple[int, int]:
    dimensions = content.get("dimensions") or {}
    rows = int(dimensions.get("rows") or 0)
    cols = int(dimensions.get("cols") or 0)
    for key in content.get("cells") or {}:
        r, c = key.split(":")
        rows = max(rows, int(r) + 1)
        cols = max(cols, int(c) + 1)
    return rows, cols


def render_csv(content: dict) -> bytes:
    rows, cols = _grid_size(content)
    cells = content.get("cells") or {}
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for r in range(rows):
        writer.writerow([neutralize_cell(cells.get(f"{r}:{c}")) for c in range(cols)])
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def render_xlsx(content: dict, *, title: str) -> bytes:
    rows, cols = _grid_size(content)
    cells = content.get("cells") or {}
    columns = content.get("columns") or {}
    row_fmts = content.get("rows") or {}
    cell_styles = content.get("cellStyles") or {}

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = _sheet_title(title)

    for r in range(rows):
        for c in range(cols):
            value = cells.get(f"{r}:{c}")
            if isinstance(value, str):
                value = neutralize_cell(value)
            cell = sheet.cell(row=r + 1, column=c + 1)
            if value is not None:
                cell.value = value
            style = _effective_style(columns, row_fmts, cell_styles, r, c)
            if style:
                _apply_style(cell, style)

    for key, entry in columns.items():
        width = entry.get("width") if isinstance(entry, dict) else None
        if isinstance(width, (int, float)):
            letter = get_column_letter(int(key) + 1)
            sheet.column_dimensions[letter].width = width / _PX_PER_WIDTH_UNIT
    for key, entry in row_fmts.items():
        height = entry.get("height") if isinstance(entry, dict) else None
        if isinstance(height, (int, float)):
            sheet.row_dimensions[int(key) + 1].height = height * _PX_TO_POINTS

    frozen = content.get("frozen") or {}
    frozen_rows = int(frozen.get("rows") or 0)
    frozen_cols = int(frozen.get("cols") or 0)
    if frozen_rows or frozen_cols:
        sheet.freeze_panes = sheet.cell(row=frozen_rows + 1, column=frozen_cols + 1)

    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def _sheet_title(title: str) -> str:
    cleaned = title.translate(str.maketrans("", "", "[]:*?/\\")).strip()
    return cleaned[:31] or "Sheet1"


def _effective_style(
    columns: dict, row_fmts: dict, cell_styles: dict, r: int, c: int
) -> dict[str, Any]:
    """Merge column -> row -> cell styles, later layers winning per key."""
    merged: dict[str, Any] = {}
    for layer in (
        (columns.get(str(c)) or {}).get("style"),
        (row_fmts.get(str(r)) or {}).get("style"),
        cell_styles.get(f"{r}:{c}"),
    ):
        if isinstance(layer, dict):
            merged.update(layer)
    return merged


def _apply_style(cell, style: dict[str, Any]) -> None:
    font_kwargs: dict[str, Any] = {}
    if style.get("bold"):
        font_kwargs["bold"] = True
    if style.get("italic"):
        font_kwargs["italic"] = True
    if style.get("underline"):
        font_kwargs["underline"] = "single"
    if style.get("strike"):
        font_kwargs["strike"] = True
    color = style.get("color")
    if isinstance(color, str) and color.startswith("#"):
        font_kwargs["color"] = f"FF{color[1:].upper()}"
    font_size = style.get("fontSize")
    if isinstance(font_size, (int, float)):
        font_kwargs["size"] = round(font_size * _PX_TO_POINTS, 1)
    if font_kwargs:
        cell.font = Font(**font_kwargs)

    fill = style.get("fill")
    if isinstance(fill, str) and fill.startswith("#"):
        rgb = f"FF{fill[1:].upper()}"
        cell.fill = PatternFill(start_color=rgb, end_color=rgb, fill_type="solid")

    align = style.get("align")
    valign = _VALIGN_MAP.get(style.get("valign") or "")
    if align or valign:
        cell.alignment = Alignment(horizontal=align, vertical=valign)

    border = style.get("border")
    if isinstance(border, dict):
        sides: dict[str, Side] = {}
        for edge in ("top", "right", "bottom", "left"):
            spec = border.get(edge)
            if isinstance(spec, dict):
                edge_color = str(spec.get("color", "#000000"))[1:].upper()
                sides[edge] = Side(
                    style=spec.get("style", "thin"), color=f"FF{edge_color}"
                )
        if sides:
            cell.border = Border(**sides)

    fmt = style.get("format")
    if isinstance(fmt, dict):
        number_format = _number_format(fmt)
        if number_format:
            cell.number_format = number_format


def _number_format(fmt: dict[str, Any]) -> str | None:
    ftype = fmt.get("type")
    decimals = int(fmt.get("decimals") or 0)
    places = f".{'0' * decimals}" if decimals else ""
    grouping = "#,##0" if fmt.get("grouping", True) else "0"
    if ftype == "percent":
        return f"0{places}%"
    if ftype == "date":
        return _DATE_FORMATS.get(fmt.get("pattern") or "iso", "yyyy-mm-dd")
    if ftype == "fixed":
        return f"{grouping}{places}"
    if ftype == "currency":
        code = str(fmt.get("currency") or "USD")
        base = f'{grouping}{places}\\ "{code}"'
        if fmt.get("negatives") in ("red", "redParens"):
            return f"{base};[Red]-{base}"
        return base
    return None  # "plain" and unknowns: leave the default General format

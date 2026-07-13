"""Tabular renderers (CSV/XLSX) for the export engine.

Same source adapters, different renderer: a tabular format consumes the
``columns``/``rows`` of the same data payload the PDF template reads, so a
source that declares the format gets it with no adapter changes.

Both formats absorb the platform CSV exporter's injection safety rather than
duplicating it (``csv_export.neutralize_cell``) — XLSX included, because
openpyxl infers a *string* cell starting with ``=`` as a formula, so the
spreadsheet-injection class isn't CSV-only. XLSX neutralizes string cells
only, keeping numeric cells typed (see ``_xlsx_cell``).
"""

from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook

from app.services.export.contract import RenderItem
from app.services.platform.csv_export import build_csv, neutralize_cell

# Sheet titles have a 31-char limit and a forbidden character set in the XLSX
# spec (openpyxl raises InvalidSheetTitle). The payload title can carry user
# text (a guild or project name), so sanitize rather than trust it.
_SHEET_TITLE_MAX = 31
_SHEET_TITLE_FORBIDDEN = str.maketrans("", "", "[]:*?/\\")


def _sheet_title(item: RenderItem) -> str:
    raw = str(item.data.get("title", item.key)).translate(_SHEET_TITLE_FORBIDDEN)
    fallback = item.key.translate(_SHEET_TITLE_FORBIDDEN)[:_SHEET_TITLE_MAX]
    return raw.strip()[:_SHEET_TITLE_MAX] or fallback or "Export"


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


def _md_cell(value: Any) -> str:
    """A cell must not break the GFM table structure: escape pipes and
    collapse newlines. Markdown has no execution surface, so this is layout
    integrity, not injection defense."""
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\r\n", " ").replace("\n", " ")


def render_md(item: RenderItem) -> bytes:
    headers, rows = _table(item)
    lines: list[str] = []
    title = str(item.data.get("title", "")).strip()
    subtitle = str(item.data.get("subtitle", "")).strip()
    if title:
        lines.append(f"# {_md_cell(title)}")
        lines.append("")
    if subtitle:
        lines.append(_md_cell(subtitle))
        lines.append("")
    lines.append("| " + " | ".join(_md_cell(h) for h in headers) + " |")
    lines.append("|" + "|".join(" --- " for _ in headers) + "|")
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(value) for value in row) + " |")
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def _xlsx_cell(value: Any) -> Any:
    """Neutralize only STRING cells for XLSX. Unlike CSV (where every value
    becomes text anyway), XLSX cells are typed: a number must stay a number
    (coercing ``-5`` to ``"'-5"`` would break sorting/arithmetic in the
    sheet), and openpyxl cannot infer a formula from an int/float/date, so
    only strings can smuggle a formula trigger."""
    if isinstance(value, str):
        return neutralize_cell(value)
    return value


def render_xlsx(item: RenderItem) -> bytes:
    headers, rows = _table(item)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = _sheet_title(item)
    sheet.append([_xlsx_cell(value) for value in headers])
    for row in rows:
        sheet.append([_xlsx_cell(value) for value in row])
    sheet.freeze_panes = "A2"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()

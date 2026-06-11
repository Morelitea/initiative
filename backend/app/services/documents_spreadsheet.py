"""Validation and normalization for spreadsheet-type documents.

Spreadsheet content is a sparse cell map keyed by ``"row:col"`` strings,
plus a ``dimensions`` hint, optional formatting structures, and a
``schema_version`` for forward compatibility. The full live state is
maintained on the frontend as a set of Y.Maps synced over the existing
collaboration provider; the JSON shape this module validates is the
snapshot persisted to ``Document.content`` whenever the room empties (or
the user creates the document via a non-collab POST/PATCH).

Schema versions
---------------
* **v1** (legacy): ``{schema_version, kind, dimensions, cells}``.
* **v2** (current): adds ``columns`` / ``rows`` / ``cellStyles``
  formatting maps and a ``frozen`` pane hint.

Any v1 payload is accepted and **upcast in place** to v2 (empty
formatting structures) so existing documents keep saving without a data
migration. The output ``schema_version`` is always the current one.

Strictness asymmetry (deliberate)
---------------------------------
A non-scalar value in ``cells`` is a data-integrity bug and is rejected
(422). A malformed *formatting* entry (bad hex, unknown ``align``,
unknown style key) is dropped silently so a presentational glitch never
blocks the user's actual data save. A container-type violation
(``"columns": []``) is still rejected.

Out of scope here: formulas, multiple sheets.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.messages import DocumentMessages
from app.services.documents import DocumentContentError


SCHEMA_VERSION = 2
"""Current snapshot shape. Bump on breaking changes."""

SUPPORTED_SCHEMA_VERSIONS = (1, 2)
"""Inbound versions we accept. Anything else is a hard reject. v1 is
upcast to ``SCHEMA_VERSION`` transparently."""

MAX_ROWS = 100_000
MAX_COLS = 1_000

MIN_COL_WIDTH = 24
MAX_COL_WIDTH = 2_000
MIN_ROW_HEIGHT = 16
MAX_ROW_HEIGHT = 1_000
MAX_DECIMALS = 10
MAX_FROZEN = 8
MIN_FONT_SIZE = 6
MAX_FONT_SIZE = 96

_CELL_KEY_RE = re.compile(r"^(\d+):(\d+)$")
_INDEX_KEY_RE = re.compile(r"^\d+$")
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_CURRENCY_RE = re.compile(r"^[A-Za-z]{3}$")
_SCALAR_TYPES = (str, int, float, bool, type(None))

_ALIGN_VALUES = frozenset({"left", "center", "right"})
_VALIGN_VALUES = frozenset({"top", "middle", "bottom"})
_NEGATIVE_STYLES = frozenset({"red", "parens", "redParens"})
_DATE_PATTERNS = frozenset({"iso", "us", "eu"})
_FORMAT_TYPES = frozenset({"currency", "percent", "date", "fixed", "plain"})
_BORDER_STYLES = frozenset({"thin", "medium", "thick", "dashed", "dotted", "double"})
_BORDER_EDGES = ("top", "right", "bottom", "left")


def normalize_spreadsheet_content(payload: Any) -> dict[str, Any]:
    """Coerce an inbound payload into the canonical v2 spreadsheet shape.

    Accepts ``None`` / non-dict payloads as the empty spreadsheet (the
    same forgiving behavior whiteboard uses for fresh docs). Otherwise
    walks the payload, rejects anything that violates the cell / container
    invariants, drops malformed formatting entries, upcasts v1 → v2, and
    returns a sanitized dict.
    """
    if not isinstance(payload, dict):
        return _empty_snapshot()

    schema_version = payload.get("schema_version", SCHEMA_VERSION)
    # ``isinstance(True, int)`` is ``True`` in Python — exclude bools so
    # ``"schema_version": true`` doesn't silently pass the version guard.
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version not in SUPPORTED_SCHEMA_VERSIONS
    ):
        raise DocumentContentError(DocumentMessages.SPREADSHEET_INVALID_PAYLOAD)

    # Use ``.get(...)`` directly (no ``or {}`` shortcut) so falsy non-dict
    # values like ``[]``, ``""``, or ``False`` reach the isinstance guard
    # below instead of being silently coerced to an empty cell map.
    cells_in = payload.get("cells", {})
    if not isinstance(cells_in, dict):
        raise DocumentContentError(DocumentMessages.SPREADSHEET_INVALID_PAYLOAD)

    cells_out: dict[str, Any] = {}
    max_row = -1
    max_col = -1
    for key, value in cells_in.items():
        if not isinstance(key, str):
            raise DocumentContentError(DocumentMessages.SPREADSHEET_INVALID_PAYLOAD)
        match = _CELL_KEY_RE.match(key)
        if match is None:
            raise DocumentContentError(DocumentMessages.SPREADSHEET_INVALID_PAYLOAD)
        row = int(match.group(1))
        col = int(match.group(2))
        if row >= MAX_ROWS or col >= MAX_COLS:
            raise DocumentContentError(DocumentMessages.SPREADSHEET_INVALID_PAYLOAD)
        if not isinstance(value, _SCALAR_TYPES):
            raise DocumentContentError(DocumentMessages.SPREADSHEET_INVALID_PAYLOAD)
        # ``True``/``False`` are instances of ``int`` in Python, which is
        # fine — they're valid scalar values either way. Empty strings /
        # ``None`` mean "cleared cell"; drop them from the persisted
        # snapshot so the storage stays sparse.
        if value is None or value == "":
            continue
        # Re-emit the key from the parsed integers so non-canonical
        # forms ("01:2", "1:02", "00001:2", …) all collapse to "1:2".
        # JS produces canonical keys via ``String(number)``, so when
        # the snapshot hydrates into a Y.Map and edits round-trip back
        # through the JS layer, mismatched stored / canonical keys would
        # silently lose cells.
        cells_out[f"{row}:{col}"] = value
        if row > max_row:
            max_row = row
        if col > max_col:
            max_col = col

    dims_in = payload.get("dimensions", {})
    if not isinstance(dims_in, dict):
        raise DocumentContentError(DocumentMessages.SPREADSHEET_INVALID_PAYLOAD)
    rows = _coerce_dim(dims_in.get("rows"), default=max(max_row + 1, 100), cap=MAX_ROWS)
    cols = _coerce_dim(dims_in.get("cols"), default=max(max_col + 1, 26), cap=MAX_COLS)

    # Formatting structures. Absent for v1 payloads → empty maps (the
    # upcast). Each container must be a dict (a list / scalar is a real
    # serialization bug → reject); individual malformed entries are
    # dropped, not rejected.
    columns = _normalize_index_map(
        payload.get("columns", {}), cap=MAX_COLS, allow_width=True
    )
    rows_fmt = _normalize_index_map(
        payload.get("rows", {}), cap=MAX_ROWS, allow_width=False
    )
    cell_styles = _normalize_cellstyles(payload.get("cellStyles", {}))
    frozen = _normalize_frozen(payload.get("frozen", {}), rows_dim=rows, cols_dim=cols)

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "spreadsheet",
        "dimensions": {"rows": rows, "cols": cols},
        "cells": cells_out,
        "columns": columns,
        "rows": rows_fmt,
        "cellStyles": cell_styles,
        "frozen": frozen,
    }


def _empty_snapshot() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "spreadsheet",
        "dimensions": {"rows": 100, "cols": 26},
        "cells": {},
        "columns": {},
        "rows": {},
        "cellStyles": {},
        "frozen": {"rows": 0, "cols": 0},
    }


def _coerce_dim(value: Any, *, default: int, cap: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        return min(default, cap)
    if value < 1:
        return min(default, cap)
    return min(value, cap)


def _clamp_int(value: Any, lo: int, hi: int) -> int | None:
    """Clamp an int into ``[lo, hi]``. Non-ints (and bools, which are
    int subclasses) return ``None`` so the caller can drop the key."""
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return max(lo, min(value, hi))


def _clamp_decimals(value: Any, *, default: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        return default
    return max(0, min(value, MAX_DECIMALS))


def _normalize_style(value: Any) -> dict[str, Any] | None:
    """Sanitize a ``CellStyle``. Unknown keys are stripped; bad values
    drop their key. Explicit ``bold``/``italic`` booleans are preserved
    (including ``False``) so a per-cell override can switch a
    column/row-level style back off via the spread-merge resolution."""
    if not isinstance(value, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("bold", "italic", "underline", "strike"):
        flag = value.get(key)
        if isinstance(flag, bool):
            out[key] = flag
    for key in ("color", "fill"):
        hexv = value.get(key)
        if isinstance(hexv, str) and _HEX_COLOR_RE.match(hexv):
            out[key] = hexv.lower()
    align = value.get("align")
    if isinstance(align, str) and align in _ALIGN_VALUES:
        out["align"] = align
    valign = value.get("valign")
    if isinstance(valign, str) and valign in _VALIGN_VALUES:
        out["valign"] = valign
    font_size = _clamp_int(value.get("fontSize"), MIN_FONT_SIZE, MAX_FONT_SIZE)
    if font_size is not None:
        out["fontSize"] = font_size
    border = _normalize_border(value.get("border"))
    if border is not None:
        out["border"] = border
    return out or None


def _normalize_border(value: Any) -> dict[str, Any] | None:
    """Sanitize a per-edge border. Each edge is independent; a bad edge
    is dropped, not the whole border. No valid edge → ``None``."""
    if not isinstance(value, dict):
        return None
    out: dict[str, Any] = {}
    for edge in _BORDER_EDGES:
        spec = value.get(edge)
        if not isinstance(spec, dict):
            continue
        style = spec.get("style")
        color = spec.get("color")
        if style not in _BORDER_STYLES:
            continue
        if not isinstance(color, str) or not _HEX_COLOR_RE.match(color):
            continue
        out[edge] = {"style": style, "color": color.lower()}
    return out or None


def _normalize_format(value: Any) -> dict[str, Any] | None:
    """Sanitize a ``NumberFormat`` preset. Unknown ``type`` → dropped."""
    if not isinstance(value, dict):
        return None
    ftype = value.get("type")
    if ftype not in _FORMAT_TYPES:
        return None
    if ftype == "plain":
        return {"type": "plain"}
    if ftype == "date":
        pattern = value.get("pattern")
        if pattern not in _DATE_PATTERNS:
            pattern = "iso"
        return {"type": "date", "pattern": pattern}
    negatives = value.get("negatives")
    has_negatives = isinstance(negatives, str) and negatives in _NEGATIVE_STYLES
    grouping = value.get("grouping")
    has_grouping = isinstance(grouping, bool)
    if ftype == "currency":
        currency = value.get("currency")
        if isinstance(currency, str) and _CURRENCY_RE.match(currency.strip()):
            currency = currency.strip().upper()
        else:
            currency = "USD"
        out = {
            "type": "currency",
            "currency": currency,
            "decimals": _clamp_decimals(value.get("decimals"), default=2),
        }
        if has_grouping:
            out["grouping"] = grouping
        if has_negatives:
            out["negatives"] = negatives
        return out
    if ftype == "percent":
        return {
            "type": "percent",
            "decimals": _clamp_decimals(value.get("decimals"), default=1),
        }
    # fixed
    out = {
        "type": "fixed",
        "decimals": _clamp_decimals(value.get("decimals"), default=2),
    }
    if has_grouping:
        out["grouping"] = grouping
    if has_negatives:
        out["negatives"] = negatives
    return out


def _normalize_index_map(value: Any, *, cap: int, allow_width: bool) -> dict[str, Any]:
    """Normalize a ``columns`` / ``rows`` map keyed by index strings.

    ``allow_width`` selects the sizing key: ``width`` (columns) clamped
    to ``[MIN_COL_WIDTH, MAX_COL_WIDTH]`` vs ``height`` (rows) clamped to
    ``[MIN_ROW_HEIGHT, MAX_ROW_HEIGHT]``. Bad keys/entries are dropped;
    a non-dict container is a serialization bug → reject.
    """
    if not isinstance(value, dict):
        raise DocumentContentError(DocumentMessages.SPREADSHEET_INVALID_PAYLOAD)
    size_key = "width" if allow_width else "height"
    size_lo = MIN_COL_WIDTH if allow_width else MIN_ROW_HEIGHT
    size_hi = MAX_COL_WIDTH if allow_width else MAX_ROW_HEIGHT
    out: dict[str, Any] = {}
    for key, entry in value.items():
        if not isinstance(key, str) or _INDEX_KEY_RE.match(key) is None:
            continue
        idx = int(key)
        if idx >= cap:
            continue
        if not isinstance(entry, dict):
            continue
        norm: dict[str, Any] = {}
        size = _clamp_int(entry.get(size_key), size_lo, size_hi)
        if size is not None:
            norm[size_key] = size
        if allow_width:
            fmt = _normalize_format(entry.get("format"))
            if fmt is not None:
                norm["format"] = fmt
        style = _normalize_style(entry.get("style"))
        if style is not None:
            norm["style"] = style
        if norm:
            # Canonical index key collapses "007" → "7".
            out[str(idx)] = norm
    return out


def _normalize_cellstyles(value: Any) -> dict[str, Any]:
    """Normalize the per-cell override map keyed by ``"row:col"``."""
    if not isinstance(value, dict):
        raise DocumentContentError(DocumentMessages.SPREADSHEET_INVALID_PAYLOAD)
    out: dict[str, Any] = {}
    for key, entry in value.items():
        if not isinstance(key, str):
            continue
        match = _CELL_KEY_RE.match(key)
        if match is None:
            continue
        row = int(match.group(1))
        col = int(match.group(2))
        if row >= MAX_ROWS or col >= MAX_COLS:
            continue
        if not isinstance(entry, dict):
            continue
        norm: dict[str, Any] = {}
        style = _normalize_style(entry.get("style"))
        if style is not None:
            norm["style"] = style
        fmt = _normalize_format(entry.get("format"))
        if fmt is not None:
            norm["format"] = fmt
        if norm:
            out[f"{row}:{col}"] = norm
    return out


def _normalize_frozen(value: Any, *, rows_dim: int, cols_dim: int) -> dict[str, int]:
    """Clamp the frozen-pane hint against the final dimensions. A
    non-dict ``frozen`` degrades to ``{0, 0}`` (presentational, lenient)
    rather than rejecting the whole document."""
    rows = 0
    cols = 0
    if isinstance(value, dict):
        rows = _clamp_int(value.get("rows"), 0, min(MAX_FROZEN, rows_dim)) or 0
        cols = _clamp_int(value.get("cols"), 0, min(MAX_FROZEN, cols_dim)) or 0
    return {"rows": rows, "cols": cols}

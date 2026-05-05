"""Validation and normalization for spreadsheet-type documents.

Spreadsheet content is a sparse cell map keyed by ``"row:col"`` strings,
plus a ``dimensions`` hint and a ``schema_version`` for forward
compatibility. The full live cell map is maintained on the frontend as
a Y.Map and synced over the existing collaboration provider; the JSON
shape this module validates is the snapshot persisted to
``Document.content`` whenever the room empties (or the user creates the
document via a non-collab POST/PATCH).

Out of scope here: formulas, cell styles, multiple sheets. See plan.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.messages import DocumentMessages
from app.services.documents import DocumentContentError


SCHEMA_VERSION = 1
"""Bump on breaking changes to the cell-snapshot shape."""

MAX_ROWS = 100_000
MAX_COLS = 1_000

_CELL_KEY_RE = re.compile(r"^(\d+):(\d+)$")
_SCALAR_TYPES = (str, int, float, bool, type(None))


def normalize_spreadsheet_content(payload: Any) -> dict[str, Any]:
    """Coerce an inbound payload into the canonical spreadsheet shape.

    Accepts ``None`` / non-dict payloads as the empty spreadsheet (the
    same forgiving behavior whiteboard uses for fresh docs). Otherwise
    walks the payload, rejects anything that violates the invariants
    listed in the module docstring, and returns a sanitized dict.
    """
    if not isinstance(payload, dict):
        return _empty_snapshot()

    schema_version = payload.get("schema_version", SCHEMA_VERSION)
    # ``isinstance(True, int)`` is ``True`` in Python — exclude bools so
    # ``"schema_version": true`` doesn't silently pass the version guard.
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != SCHEMA_VERSION
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
        # PR 3 hydrates this snapshot into a Y.Map and edits round-trip
        # back through the JS layer, mismatched stored / canonical keys
        # would silently lose cells.
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

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "spreadsheet",
        "dimensions": {"rows": rows, "cols": cols},
        "cells": cells_out,
    }


def _empty_snapshot() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "spreadsheet",
        "dimensions": {"rows": 100, "cols": 26},
        "cells": {},
    }


def _coerce_dim(value: Any, *, default: int, cap: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        return min(default, cap)
    if value < 1:
        return min(default, cap)
    return min(value, cap)

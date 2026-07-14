"""Helpers shared by the source adapters."""

from __future__ import annotations

from app.core.messages import ExportMessages
from app.services.export.engine import ExportError

# Bound on a single selection: page-size multiples, not initiative dumps —
# each id costs a fetch+authorize round trip at count AND build time.
MAX_SELECTION = 100


def selection_ids(params: dict, *, single_key: str, multi_key: str) -> list[int]:
    """Normalize a selection selector to a validated id list. Accepts either
    the legacy single-id key or the multi-id key (job params round-trip
    through JSON — validate, don't trust). Order-preserving dedupe."""
    raw = params.get(multi_key)
    if raw is None and params.get(single_key) is not None:
        raw = [params[single_key]]
    if not isinstance(raw, list) or not raw or len(raw) > MAX_SELECTION:
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
    try:
        ids = [int(value) for value in raw]
    except (TypeError, ValueError):
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
    return list(dict.fromkeys(ids))

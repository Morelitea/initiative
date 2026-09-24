"""Which request bodies the transport bounds, and how tightly."""

from __future__ import annotations

import pytest

from app.core.body_limit import _RULES
from app.services.import_engine import limits as import_limits

pytestmark = pytest.mark.unit


def _limit(path: str) -> int | None:
    for pattern, limit, _code in _RULES:
        if pattern.match(path):
            return limit()
    return None


def test_the_atlassian_routes_are_bounded_where_they_are():
    """The connect and the import take a handful of strings; the export
    upload takes a zip as large as a backup."""
    connect = _limit("/api/v1/g/1/imports/atlassian/connect")
    start = _limit("/api/v1/g/1/imports/atlassian/import")
    export = _limit("/api/v1/g/1/imports/atlassian/export")
    assert connect is not None and connect == start
    assert export is not None and export > import_limits.IMPORT_MAX_BACKUP_UPLOAD_BYTES
    assert export == _limit("/api/v1/g/1/imports/backup")

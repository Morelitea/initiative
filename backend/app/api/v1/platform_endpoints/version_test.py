"""Tests for the version/changelog endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.schemas.base import MAX_PLAIN_TEXT_LENGTH


@pytest.mark.integration
async def test_changelog_returns_typed_entries(client: AsyncClient):
    """The changelog is served as ``{entries: [{version, date, changes}]}`` —
    the typed shape Orval generates from ChangelogResponse."""
    resp = await client.get("/api/v1/changelog?limit=1")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "entries" in body
    for entry in body["entries"]:
        assert set(entry.keys()) == {"version", "date", "changes"}


@pytest.mark.integration
async def test_changelog_returns_large_sections_verbatim(client: AsyncClient):
    """A single version's ``changes`` routinely exceeds the plain-text
    sanitizer's length cap. ``changes`` is RawTextStr, so the section is
    returned verbatim rather than rejected — pinning that a plain ``str`` field
    (which raises past the cap) is never reintroduced."""
    resp = await client.get("/api/v1/changelog?limit=1000")
    assert resp.status_code == 200, resp.text
    entries = resp.json()["entries"]
    assert entries, "the repo CHANGELOG.md should yield released entries"
    assert any(len(entry["changes"]) > MAX_PLAIN_TEXT_LENGTH for entry in entries), (
        "expected at least one released section to exceed the plain-text cap; "
        "the endpoint must return it intact, not 500 on sanitization"
    )

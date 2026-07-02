"""Tests for import parse endpoints — error response shape."""

import pytest
from httpx import AsyncClient

from app.models.platform.guild import GuildRole


@pytest.mark.integration
async def test_todoist_parse_bad_csv_opaque_error(client: AsyncClient, acting_user):
    """Todoist CSV with a non-numeric INDENT triggers ValueError, returns the opaque constant."""
    a = await acting_user(guild_role=GuildRole.member)
    response = await client.post(
        a.g("/imports/todoist/parse"),
        headers={**a.headers, "Content-Type": "text/plain"},
        content=b"TYPE,CONTENT,INDENT\ntask,My Task,not-a-number",
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail == "IMPORT_PARSE_FAILED"
    assert "Traceback" not in detail
    assert "Error" not in detail


@pytest.mark.integration
async def test_vikunja_parse_bad_json_opaque_error(client: AsyncClient, acting_user):
    """Malformed Vikunja JSON returns the constant, not a raw exception."""
    a = await acting_user(guild_role=GuildRole.member)
    response = await client.post(
        a.g("/imports/vikunja/parse"),
        headers={**a.headers, "Content-Type": "text/plain"},
        content=b"this is not json }{{{",
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "IMPORT_PARSE_FAILED"


@pytest.mark.integration
async def test_ticktick_parse_bad_csv_opaque_error(client: AsyncClient, acting_user):
    """Malformed TickTick CSV returns the constant, not a raw exception."""
    a = await acting_user(guild_role=GuildRole.member)
    response = await client.post(
        a.g("/imports/ticktick/parse"),
        headers={**a.headers, "Content-Type": "text/plain"},
        content=b"\x00\x01\x02\x03binary garbage",
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "IMPORT_PARSE_FAILED"

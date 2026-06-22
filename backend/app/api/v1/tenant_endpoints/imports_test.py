"""Tests for import parse endpoints — error response shape."""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.testing import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
)


@pytest.mark.integration
async def test_todoist_parse_bad_csv_opaque_error(
    client: AsyncClient, session: AsyncSession
):
    """Todoist CSV with a non-numeric INDENT triggers ValueError, returns the opaque constant."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    response = await client.post(
        f"/api/v1/g/{guild.id}/imports/todoist/parse",
        headers={**get_auth_headers(user), "Content-Type": "text/plain"},
        content=b"TYPE,CONTENT,INDENT\ntask,My Task,not-a-number",
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail == "IMPORT_PARSE_FAILED"
    assert "Traceback" not in detail
    assert "Error" not in detail


@pytest.mark.integration
async def test_vikunja_parse_bad_json_opaque_error(
    client: AsyncClient, session: AsyncSession
):
    """Malformed Vikunja JSON returns the constant, not a raw exception."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    response = await client.post(
        f"/api/v1/g/{guild.id}/imports/vikunja/parse",
        headers={**get_auth_headers(user), "Content-Type": "text/plain"},
        content=b"this is not json }{{{",
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "IMPORT_PARSE_FAILED"


@pytest.mark.integration
async def test_ticktick_parse_bad_csv_opaque_error(
    client: AsyncClient, session: AsyncSession
):
    """Malformed TickTick CSV returns the constant, not a raw exception."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    response = await client.post(
        f"/api/v1/g/{guild.id}/imports/ticktick/parse",
        headers={**get_auth_headers(user), "Content-Type": "text/plain"},
        content=b"\x00\x01\x02\x03binary garbage",
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "IMPORT_PARSE_FAILED"

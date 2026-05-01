"""Integration tests for spreadsheet-type documents.

Covers the JSON-snapshot path: create / get / patch / validation.
The live Y.Map collaboration layer is exercised separately on the
frontend; these tests are about the durable storage shape.
"""

from dataclasses import dataclass

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.models.initiative import Initiative
from app.models.user import User
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_user,
    get_guild_headers,
)


@dataclass
class _SpreadsheetEnv:
    user: User
    initiative: Initiative
    headers: dict[str, str]


@pytest.fixture
async def env(session: AsyncSession) -> _SpreadsheetEnv:
    """Shared user / guild / membership / initiative setup for every
    spreadsheet endpoint test. Per-test scope so each gets a fresh
    initiative — the round-trip and PATCH tests don't need to be
    isolated from each other but the validation tests do, and a
    function-scoped fixture is the cheap, consistent default."""
    user = await create_user(session, email="owner@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Init")
    return _SpreadsheetEnv(
        user=user, initiative=initiative, headers=get_guild_headers(guild, user)
    )


@pytest.mark.integration
async def test_create_spreadsheet_round_trips_cells(
    client: AsyncClient, env: _SpreadsheetEnv
):
    payload = {
        "title": "Q2 Numbers",
        "initiative_id": env.initiative.id,
        "document_type": "spreadsheet",
        "content": {
            "schema_version": 1,
            "kind": "spreadsheet",
            "dimensions": {"rows": 100, "cols": 26},
            "cells": {
                "0:0": "Date",
                "0:1": "Amount",
                "1:0": "2026-05-01",
                "1:1": 42.5,
                "2:1": True,
            },
        },
    }

    response = await client.post("/api/v1/documents/", headers=env.headers, json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    doc_id = data["id"]
    assert data["document_type"] == "spreadsheet"

    # GET round-trip preserves the cell map exactly.
    response = await client.get(f"/api/v1/documents/{doc_id}", headers=env.headers)
    assert response.status_code == 200
    content = response.json()["content"]
    assert content["schema_version"] == 1
    assert content["kind"] == "spreadsheet"
    assert content["cells"] == {
        "0:0": "Date",
        "0:1": "Amount",
        "1:0": "2026-05-01",
        "1:1": 42.5,
        "2:1": True,
    }


@pytest.mark.integration
async def test_patch_spreadsheet_replaces_cells(
    client: AsyncClient, env: _SpreadsheetEnv
):
    create_response = await client.post(
        "/api/v1/documents/",
        headers=env.headers,
        json={
            "title": "Sheet",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": {"cells": {"0:0": "before"}},
        },
    )
    assert create_response.status_code == 201
    doc_id = create_response.json()["id"]

    # PATCH replaces the content snapshot wholesale (snapshot path).
    patch_response = await client.patch(
        f"/api/v1/documents/{doc_id}",
        headers=env.headers,
        json={"content": {"cells": {"0:0": "after", "5:7": 99}}},
    )
    assert patch_response.status_code == 200, patch_response.text
    cells = patch_response.json()["content"]["cells"]
    assert cells == {"0:0": "after", "5:7": 99}


@pytest.mark.integration
async def test_create_spreadsheet_rejects_nested_value(
    client: AsyncClient, env: _SpreadsheetEnv
):
    response = await client.post(
        "/api/v1/documents/",
        headers=env.headers,
        json={
            "title": "Bad Sheet",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": {"cells": {"0:0": {"nested": "object"}}},
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "DOCUMENT_SPREADSHEET_INVALID_PAYLOAD"


@pytest.mark.integration
async def test_create_spreadsheet_rejects_unknown_schema_version(
    client: AsyncClient, env: _SpreadsheetEnv
):
    response = await client.post(
        "/api/v1/documents/",
        headers=env.headers,
        json={
            "title": "Bad Sheet",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": {"schema_version": 999, "cells": {"0:0": "ok"}},
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "DOCUMENT_SPREADSHEET_INVALID_PAYLOAD"


@pytest.mark.integration
async def test_create_spreadsheet_rejects_bool_schema_version(
    client: AsyncClient, env: _SpreadsheetEnv
):
    """``isinstance(True, int)`` is ``True`` in Python — make sure the
    version guard rejects ``"schema_version": true`` instead of treating
    it as the integer ``1``."""
    response = await client.post(
        "/api/v1/documents/",
        headers=env.headers,
        json={
            "title": "Bad Sheet",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": {"schema_version": True, "cells": {"0:0": "ok"}},
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "DOCUMENT_SPREADSHEET_INVALID_PAYLOAD"


@pytest.mark.integration
async def test_create_spreadsheet_rejects_non_dict_cells(
    client: AsyncClient, env: _SpreadsheetEnv
):
    """A serialization bug that sends ``"cells": []`` instead of
    ``{}`` should produce a 400 — falsy non-dict values must reach the
    isinstance guard, not be silently coerced to an empty map."""
    response = await client.post(
        "/api/v1/documents/",
        headers=env.headers,
        json={
            "title": "Bad Sheet",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": {"cells": []},
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "DOCUMENT_SPREADSHEET_INVALID_PAYLOAD"


@pytest.mark.integration
async def test_create_spreadsheet_rejects_non_dict_dimensions(
    client: AsyncClient, env: _SpreadsheetEnv
):
    response = await client.post(
        "/api/v1/documents/",
        headers=env.headers,
        json={
            "title": "Bad Sheet",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": {"cells": {}, "dimensions": []},
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "DOCUMENT_SPREADSHEET_INVALID_PAYLOAD"


@pytest.mark.integration
async def test_create_spreadsheet_with_empty_content(
    client: AsyncClient, env: _SpreadsheetEnv
):
    """Fresh spreadsheets default to an empty cell map and a 100x26 canvas."""
    response = await client.post(
        "/api/v1/documents/",
        headers=env.headers,
        json={
            "title": "Empty Sheet",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
        },
    )
    assert response.status_code == 201, response.text
    content = response.json()["content"]
    assert content["cells"] == {}
    assert content["dimensions"] == {"rows": 100, "cols": 26}
    assert content["kind"] == "spreadsheet"
    assert content["schema_version"] == 1

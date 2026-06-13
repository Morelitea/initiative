"""Integration tests for spreadsheet-type documents.

Covers the JSON-snapshot path: create / get / patch / validation.
The live Y.Map collaboration layer is exercised separately on the
frontend; these tests are about the durable storage shape.
"""

from dataclasses import dataclass

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import Guild, GuildRole
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
    guild: Guild
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
        user=user,
        guild=guild,
        initiative=initiative,
        headers=await get_guild_headers(session, guild, user),
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

    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/", headers=env.headers, json=payload
    )
    assert response.status_code == 201, response.text
    data = response.json()
    doc_id = data["id"]
    assert data["document_type"] == "spreadsheet"

    # GET round-trip preserves the cell map exactly.
    response = await client.get(
        f"/api/v1/g/{env.guild.id}/documents/{doc_id}", headers=env.headers
    )
    assert response.status_code == 200
    content = response.json()["content"]
    # v1 input is upcast to the current schema version on save.
    assert content["schema_version"] == 2
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
        f"/api/v1/g/{env.guild.id}/documents/",
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
        f"/api/v1/g/{env.guild.id}/documents/{doc_id}",
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
        f"/api/v1/g/{env.guild.id}/documents/",
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
        f"/api/v1/g/{env.guild.id}/documents/",
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
        f"/api/v1/g/{env.guild.id}/documents/",
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
        f"/api/v1/g/{env.guild.id}/documents/",
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
        f"/api/v1/g/{env.guild.id}/documents/",
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
async def test_create_spreadsheet_canonicalizes_cell_keys(
    client: AsyncClient, env: _SpreadsheetEnv
):
    """Non-canonical numeric keys ("01:2", "0001:0002") round-trip as
    canonical "r:c" — JS emits ``String(number)`` form when the snapshot
    is hydrated into a Y.Map, so any leading-zero form stored verbatim
    would silently disappear after a collaboration round-trip."""
    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/",
        headers=env.headers,
        json={
            "title": "Sheet",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": {
                "cells": {
                    "01:2": "padded row",
                    "3:04": "padded col",
                    "0005:0006": "padded both",
                    "7:8": "canonical",
                }
            },
        },
    )
    assert response.status_code == 201, response.text
    cells = response.json()["content"]["cells"]
    assert cells == {
        "1:2": "padded row",
        "3:4": "padded col",
        "5:6": "padded both",
        "7:8": "canonical",
    }


@pytest.mark.integration
async def test_create_spreadsheet_with_empty_content(
    client: AsyncClient, env: _SpreadsheetEnv
):
    """Fresh spreadsheets default to an empty cell map and a 100x26 canvas."""
    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/",
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
    assert content["schema_version"] == 2
    # Fresh docs default to empty formatting structures.
    assert content["columns"] == {}
    assert content["rows"] == {}
    assert content["cellStyles"] == {}
    assert content["frozen"] == {"rows": 0, "cols": 0}


@pytest.mark.integration
async def test_v1_payload_upcasts_to_v2(client: AsyncClient, env: _SpreadsheetEnv):
    """An explicit v1 payload (no formatting keys) is accepted and saved
    as v2 with empty formatting structures — existing documents keep
    working without a data migration and never 422."""
    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/",
        headers=env.headers,
        json={
            "title": "Legacy Sheet",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": {
                "schema_version": 1,
                "kind": "spreadsheet",
                "dimensions": {"rows": 100, "cols": 26},
                "cells": {"0:0": "kept"},
            },
        },
    )
    assert response.status_code == 201, response.text
    content = response.json()["content"]
    assert content["schema_version"] == 2
    assert content["cells"] == {"0:0": "kept"}
    assert content["columns"] == {}
    assert content["rows"] == {}
    assert content["cellStyles"] == {}
    assert content["frozen"] == {"rows": 0, "cols": 0}


@pytest.mark.integration
async def test_v2_formatting_round_trips(client: AsyncClient, env: _SpreadsheetEnv):
    """A full v2 payload round-trips: widths, styles, number formats,
    per-cell overrides, and the frozen-pane hint."""
    payload_content = {
        "schema_version": 2,
        "kind": "spreadsheet",
        "dimensions": {"rows": 100, "cols": 26},
        "cells": {"0:0": "Revenue", "1:0": 1234.5},
        "columns": {
            "0": {
                "width": 180,
                "format": {"type": "currency", "currency": "USD", "decimals": 2},
                "style": {"bold": True, "align": "right"},
            }
        },
        "rows": {"0": {"height": 32, "style": {"bold": True}}},
        "cellStyles": {
            "1:0": {
                "style": {"fill": "#ffeecc"},
                "format": {"type": "fixed", "decimals": 1},
            }
        },
        "frozen": {"rows": 1, "cols": 1},
    }
    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/",
        headers=env.headers,
        json={
            "title": "Formatted",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": payload_content,
        },
    )
    assert response.status_code == 201, response.text
    content = response.json()["content"]
    assert content["schema_version"] == 2
    assert content["columns"] == {
        "0": {
            "width": 180,
            "format": {"type": "currency", "currency": "USD", "decimals": 2},
            "style": {"bold": True, "align": "right"},
        }
    }
    assert content["rows"] == {"0": {"height": 32, "style": {"bold": True}}}
    assert content["cellStyles"] == {
        "1:0": {
            "style": {"fill": "#ffeecc"},
            "format": {"type": "fixed", "decimals": 1},
        }
    }
    assert content["frozen"] == {"rows": 1, "cols": 1}


@pytest.mark.integration
async def test_v2_clamps_sizes_and_frozen(client: AsyncClient, env: _SpreadsheetEnv):
    """Out-of-range widths/heights/decimals/frozen are clamped, not
    rejected."""
    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/",
        headers=env.headers,
        json={
            "title": "Clamp",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": {
                "schema_version": 2,
                "cells": {},
                "dimensions": {"rows": 100, "cols": 26},
                "columns": {
                    "0": {"width": 99999, "format": {"type": "fixed", "decimals": 99}}
                },
                "rows": {"0": {"height": 0}},
                "frozen": {"rows": 50, "cols": -3},
            },
        },
    )
    assert response.status_code == 201, response.text
    content = response.json()["content"]
    assert content["columns"]["0"]["width"] == 2000
    assert content["columns"]["0"]["format"]["decimals"] == 10
    assert content["rows"]["0"]["height"] == 16
    assert content["frozen"] == {"rows": 8, "cols": 0}


@pytest.mark.integration
async def test_v2_drops_malformed_formatting(client: AsyncClient, env: _SpreadsheetEnv):
    """A bad ``align``, bad hex, and an unknown style key are stripped —
    the document still saves (201, NOT 400) because formatting failures
    must never block the user's actual data."""
    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/",
        headers=env.headers,
        json={
            "title": "Lenient",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": {
                "schema_version": 2,
                "cells": {"0:0": "data"},
                "columns": {
                    "0": {
                        "style": {
                            "align": "diagonal",
                            "color": "red",
                            "squiggly": True,
                            "bold": True,
                        },
                        "format": {"type": "bogus"},
                    },
                    "not-an-index": {"width": 100},
                },
                "cellStyles": {"garbage-key": {"style": {"bold": True}}},
            },
        },
    )
    assert response.status_code == 201, response.text
    content = response.json()["content"]
    # Only the valid ``bold`` survived; the column entry is kept.
    assert content["columns"] == {"0": {"style": {"bold": True}}}
    assert content["cellStyles"] == {}


@pytest.mark.integration
async def test_v2_rejects_non_dict_columns(client: AsyncClient, env: _SpreadsheetEnv):
    """A serialization bug that sends ``"columns": []`` is a
    container-type violation → 400 (same strictness as ``cells``)."""
    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/",
        headers=env.headers,
        json={
            "title": "Bad",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": {"schema_version": 2, "cells": {}, "columns": []},
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "DOCUMENT_SPREADSHEET_INVALID_PAYLOAD"


@pytest.mark.integration
async def test_v2_canonicalizes_formatting_keys(
    client: AsyncClient, env: _SpreadsheetEnv
):
    """Leading-zero index/cell keys collapse to canonical form so they
    survive the JS Y.Map round-trip, exactly like the cell map."""
    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/",
        headers=env.headers,
        json={
            "title": "Canon",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": {
                "schema_version": 2,
                "cells": {},
                "columns": {"007": {"width": 90}},
                "cellStyles": {"01:02": {"style": {"italic": True}}},
            },
        },
    )
    assert response.status_code == 201, response.text
    content = response.json()["content"]
    assert content["columns"] == {"7": {"width": 90}}
    assert content["cellStyles"] == {"1:2": {"style": {"italic": True}}}


@pytest.mark.integration
async def test_v2_border_round_trips_and_drops_bad_edges(
    client: AsyncClient, env: _SpreadsheetEnv
):
    """Valid border edges round-trip (color lowercased); a bad style
    enum, a bad hex, and an unknown edge are dropped without 400."""
    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/",
        headers=env.headers,
        json={
            "title": "Borders",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": {
                "schema_version": 2,
                "cells": {"0:0": "x"},
                "cellStyles": {
                    "0:0": {
                        "style": {
                            "border": {
                                "top": {"style": "thin", "color": "#ABCDEF"},
                                "bottom": {"style": "huge", "color": "#000000"},
                                "left": {"style": "thick", "color": "red"},
                                "diagonal": {"style": "thin", "color": "#000000"},
                            }
                        }
                    }
                },
            },
        },
    )
    assert response.status_code == 201, response.text
    content = response.json()["content"]
    assert content["cellStyles"] == {
        "0:0": {"style": {"border": {"top": {"style": "thin", "color": "#abcdef"}}}}
    }


@pytest.mark.integration
async def test_v2_tier1_style_and_number_options(
    client: AsyncClient, env: _SpreadsheetEnv
):
    """Underline/strike/valign/fontSize and number-format grouping +
    negatives round-trip; fontSize is clamped, bad valign/negatives are
    dropped without a 400."""
    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/",
        headers=env.headers,
        json={
            "title": "Tier1",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": {
                "schema_version": 2,
                "cells": {"0:0": -5},
                "cellStyles": {
                    "0:0": {
                        "style": {
                            "underline": True,
                            "strike": False,
                            "valign": "sideways",
                            "fontSize": 9999,
                        },
                        "format": {
                            "type": "fixed",
                            "decimals": 2,
                            "grouping": True,
                            "negatives": "redParens",
                        },
                    },
                    "1:0": {
                        "format": {
                            "type": "currency",
                            "currency": "EUR",
                            "decimals": 0,
                            "negatives": "bogus",
                        }
                    },
                },
            },
        },
    )
    assert response.status_code == 201, response.text
    content = response.json()["content"]
    assert content["cellStyles"]["0:0"]["style"] == {
        "underline": True,
        "strike": False,
        "fontSize": 96,
    }
    assert content["cellStyles"]["0:0"]["format"] == {
        "type": "fixed",
        "decimals": 2,
        "grouping": True,
        "negatives": "redParens",
    }
    # Unknown negative style dropped; currency otherwise preserved.
    assert content["cellStyles"]["1:0"]["format"] == {
        "type": "currency",
        "currency": "EUR",
        "decimals": 0,
    }

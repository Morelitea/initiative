"""Integration tests for spreadsheet-type documents.

Covers the JSON-snapshot path: create / get / patch / validation.
The live Y.Map collaboration layer is exercised separately on the
frontend; these tests are about the durable storage shape.
"""

from dataclasses import dataclass

import pytest
from httpx import AsyncClient

from app.models.platform.guild import Guild, GuildRole
from app.models.tenant.initiative import Initiative
from app.models.platform.user import User


def _sheet(content: dict, index: int = 0) -> dict:
    """One sheet out of a v3 workbook snapshot. Cells, dimensions, and the
    formatting maps live per sheet; only ``kind`` / ``schema_version`` sit
    at the top level."""
    return content["sheets"][index]


@dataclass
class _SpreadsheetEnv:
    user: User
    guild: Guild
    initiative: Initiative
    headers: dict[str, str]


@pytest.fixture
async def env(acting_user) -> _SpreadsheetEnv:
    """Shared user / guild / membership / initiative setup for every
    spreadsheet endpoint test. Per-test scope so each gets a fresh
    initiative — the round-trip and PATCH tests don't need to be
    isolated from each other but the validation tests do, and a
    function-scoped fixture is the cheap, consistent default."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    return _SpreadsheetEnv(
        user=a.user,
        guild=a.guild,
        initiative=a.initiative,
        headers=a.headers,
    )


@pytest.mark.integration
async def test_create_spreadsheet_round_trips_cells(
    client: AsyncClient, env: _SpreadsheetEnv
):
    payload = {
        "name": "Q2 Numbers",
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
    assert content["schema_version"] == 3
    assert content["kind"] == "spreadsheet"
    assert _sheet(content)["cells"] == {
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
            "name": "Sheet",
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
    cells = _sheet(patch_response.json()["content"])["cells"]
    assert cells == {"0:0": "after", "5:7": 99}


@pytest.mark.integration
@pytest.mark.parametrize(
    ("case", "content"),
    [
        ("a cell holding an object", {"cells": {"0:0": {"nested": "object"}}}),
        (
            "a schema version we do not speak",
            {"schema_version": 999, "cells": {"0:0": "ok"}},
        ),
        # isinstance(True, int) is True in Python, so the version guard has to
        # refuse a bool rather than read it as the integer 1.
        (
            "a bool where the version goes",
            {"schema_version": True, "cells": {"0:0": "ok"}},
        ),
        # Falsy non-dict containers must reach the type guard rather than being
        # coerced to an empty map.
        ("cells that are not a map", {"cells": []}),
        ("dimensions that are not a map", {"cells": {}, "dimensions": []}),
        (
            "v2 columns that are not a map",
            {"schema_version": 2, "cells": {}, "columns": []},
        ),
        (
            "v3 sheets that are not a list",
            {"schema_version": 3, "kind": "spreadsheet", "sheets": {}},
        ),
        # The cell invariant holds on every sheet, not only the first.
        (
            "a bad cell on a later v3 sheet",
            {
                "schema_version": 3,
                "kind": "spreadsheet",
                "sheets": [
                    {"id": "s1", "name": "Fine", "cells": {"0:0": "ok"}},
                    {"id": "s2", "name": "Broken", "cells": {"0:0": {"nested": 1}}},
                ],
            },
        ),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
async def test_create_spreadsheet_refuses_a_malformed_payload(
    client: AsyncClient, env: _SpreadsheetEnv, case: str, content: dict
):
    """Every shape the sheet parser cannot trust is refused the same way, so a
    malformed payload never lands half-read."""
    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/",
        headers=env.headers,
        json={
            "name": "Bad Sheet",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": content,
        },
    )
    assert response.status_code == 400, response.text
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
            "name": "Sheet",
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
    cells = _sheet(response.json()["content"])["cells"]
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
            "name": "Empty Sheet",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
        },
    )
    assert response.status_code == 201, response.text
    content = response.json()["content"]
    assert _sheet(content)["cells"] == {}
    assert _sheet(content)["dimensions"] == {"rows": 100, "cols": 26}
    assert content["kind"] == "spreadsheet"
    assert content["schema_version"] == 3
    # Fresh docs default to empty formatting structures.
    assert _sheet(content)["columns"] == {}
    assert _sheet(content)["rows"] == {}
    assert _sheet(content)["cellStyles"] == {}
    assert _sheet(content)["frozen"] == {"rows": 0, "cols": 0}


@pytest.mark.integration
async def test_v1_payload_upcasts_to_current(client: AsyncClient, env: _SpreadsheetEnv):
    """An explicit v1 payload (no formatting keys) is accepted and saved
    as v2 with empty formatting structures — existing documents keep
    working without a data migration and never 422."""
    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/",
        headers=env.headers,
        json={
            "name": "Legacy Sheet",
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
    assert content["schema_version"] == 3
    assert _sheet(content)["cells"] == {"0:0": "kept"}
    assert _sheet(content)["columns"] == {}
    assert _sheet(content)["rows"] == {}
    assert _sheet(content)["cellStyles"] == {}
    assert _sheet(content)["frozen"] == {"rows": 0, "cols": 0}


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
            "name": "Formatted",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": payload_content,
        },
    )
    assert response.status_code == 201, response.text
    content = response.json()["content"]
    assert content["schema_version"] == 3
    assert _sheet(content)["columns"] == {
        "0": {
            "width": 180,
            "format": {"type": "currency", "currency": "USD", "decimals": 2},
            "style": {"bold": True, "align": "right"},
        }
    }
    assert _sheet(content)["rows"] == {"0": {"height": 32, "style": {"bold": True}}}
    assert _sheet(content)["cellStyles"] == {
        "1:0": {
            "style": {"fill": "#ffeecc"},
            "format": {"type": "fixed", "decimals": 1},
        }
    }
    assert _sheet(content)["frozen"] == {"rows": 1, "cols": 1}


@pytest.mark.integration
async def test_v2_clamps_sizes_and_frozen(client: AsyncClient, env: _SpreadsheetEnv):
    """Out-of-range widths/heights/decimals/frozen are clamped, not
    rejected."""
    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/",
        headers=env.headers,
        json={
            "name": "Clamp",
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
    assert _sheet(content)["columns"]["0"]["width"] == 2000
    assert _sheet(content)["columns"]["0"]["format"]["decimals"] == 10
    assert _sheet(content)["rows"]["0"]["height"] == 16
    assert _sheet(content)["frozen"] == {"rows": 8, "cols": 0}


@pytest.mark.integration
async def test_v2_drops_malformed_formatting(client: AsyncClient, env: _SpreadsheetEnv):
    """A bad ``align``, bad hex, and an unknown style key are stripped —
    the document still saves (201, NOT 400) because formatting failures
    must never block the user's actual data."""
    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/",
        headers=env.headers,
        json={
            "name": "Lenient",
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
    assert _sheet(content)["columns"] == {"0": {"style": {"bold": True}}}
    assert _sheet(content)["cellStyles"] == {}


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
            "name": "Canon",
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
    assert _sheet(content)["columns"] == {"7": {"width": 90}}
    assert _sheet(content)["cellStyles"] == {"1:2": {"style": {"italic": True}}}


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
            "name": "Borders",
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
    assert _sheet(content)["cellStyles"] == {
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
            "name": "Tier1",
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
    assert _sheet(content)["cellStyles"]["0:0"]["style"] == {
        "underline": True,
        "strike": False,
        "fontSize": 96,
    }
    assert _sheet(content)["cellStyles"]["0:0"]["format"] == {
        "type": "fixed",
        "decimals": 2,
        "grouping": True,
        "negatives": "redParens",
    }
    # Unknown negative style dropped; currency otherwise preserved.
    assert _sheet(content)["cellStyles"]["1:0"]["format"] == {
        "type": "currency",
        "currency": "EUR",
        "decimals": 0,
    }


# ---------------------------------------------------------------------------
# v3: multiple sheets
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_v3_multiple_sheets_round_trip(client: AsyncClient, env: _SpreadsheetEnv):
    """A workbook keeps its sheets, their order, and each sheet's own cells,
    dimensions, and formatting."""
    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/",
        headers=env.headers,
        json={
            "name": "Workbook",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": {
                "schema_version": 3,
                "kind": "spreadsheet",
                "sheets": [
                    {
                        "id": "s1",
                        "name": "Summary",
                        "dimensions": {"rows": 100, "cols": 26},
                        "cells": {"0:0": "=SUM(Data!A1:A3)"},
                        "frozen": {"rows": 1, "cols": 0},
                    },
                    {
                        "id": "sabc123",
                        "name": "Data",
                        "dimensions": {"rows": 100, "cols": 26},
                        "cells": {"0:0": 1, "1:0": 2, "2:0": 3},
                        "columns": {"0": {"width": 140}},
                    },
                ],
            },
        },
    )
    assert response.status_code == 201, response.text
    content = response.json()["content"]
    assert content["schema_version"] == 3
    assert [s["name"] for s in content["sheets"]] == ["Summary", "Data"]
    assert [s["id"] for s in content["sheets"]] == ["s1", "sabc123"]
    # The cross-sheet formula is opaque text to the backend and survives.
    assert _sheet(content, 0)["cells"] == {"0:0": "=SUM(Data!A1:A3)"}
    assert _sheet(content, 0)["frozen"] == {"rows": 1, "cols": 0}
    assert _sheet(content, 1)["cells"] == {"0:0": 1, "1:0": 2, "2:0": 3}
    assert _sheet(content, 1)["columns"] == {"0": {"width": 140}}


@pytest.mark.integration
async def test_v2_payload_upcasts_to_single_sheet(
    client: AsyncClient, env: _SpreadsheetEnv
):
    """A pre-multi-sheet payload is read as the workbook's one sheet, keeping
    its cells and formatting — existing documents never 422 and never lose
    data on their next save."""
    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/",
        headers=env.headers,
        json={
            "name": "Legacy",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": {
                "schema_version": 2,
                "kind": "spreadsheet",
                "dimensions": {"rows": 100, "cols": 26},
                "cells": {"0:0": "kept"},
                "columns": {"0": {"width": 200}},
                "frozen": {"rows": 1, "cols": 1},
            },
        },
    )
    assert response.status_code == 201, response.text
    content = response.json()["content"]
    assert content["schema_version"] == 3
    assert len(content["sheets"]) == 1
    assert _sheet(content)["id"] == "s1"
    assert _sheet(content)["name"] == "Sheet1"
    assert _sheet(content)["cells"] == {"0:0": "kept"}
    assert _sheet(content)["columns"] == {"0": {"width": 200}}
    assert _sheet(content)["frozen"] == {"rows": 1, "cols": 1}


@pytest.mark.integration
async def test_v3_sheet_names_are_sanitized_and_deduplicated(
    client: AsyncClient, env: _SpreadsheetEnv
):
    """Names are load-bearing (a formula addresses a sheet by name), so the
    forbidden characters are stripped, the length is capped at Excel's 31,
    and collisions are broken case-insensitively."""
    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/",
        headers=env.headers,
        json={
            "name": "Names",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": {
                "schema_version": 3,
                "kind": "spreadsheet",
                "sheets": [
                    {"id": "s1", "name": "Q1/Q2: *plan*?", "cells": {}},
                    {"id": "s2", "name": "budget", "cells": {}},
                    {"id": "s3", "name": "BUDGET", "cells": {}},
                    {"id": "s4", "name": "   ", "cells": {}},
                    {"id": "s5", "name": "x" * 50, "cells": {}},
                ],
            },
        },
    )
    assert response.status_code == 201, response.text
    names = [s["name"] for s in response.json()["content"]["sheets"]]
    assert names[0] == "Q1Q2 plan"
    assert names[1] == "budget"
    # Case-insensitive collision — a reference resolves case-insensitively.
    assert names[2] == "BUDGET 2"
    # Nothing usable left; falls back to the positional default.
    assert names[3] == "Sheet4"
    assert names[4] == "x" * 31


@pytest.mark.integration
async def test_v3_duplicate_sheet_ids_are_repaired(
    client: AsyncClient, env: _SpreadsheetEnv
):
    """Two sheets sharing an id would share one Yjs container on the client,
    so the second is re-issued rather than rejected."""
    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/",
        headers=env.headers,
        json={
            "name": "Ids",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": {
                "schema_version": 3,
                "kind": "spreadsheet",
                "sheets": [
                    {"id": "s1", "name": "One", "cells": {"0:0": "a"}},
                    {"id": "s1", "name": "Two", "cells": {"0:0": "b"}},
                ],
            },
        },
    )
    assert response.status_code == 201, response.text
    sheets = response.json()["content"]["sheets"]
    assert len({s["id"] for s in sheets}) == 2
    assert _sheet(response.json()["content"], 1)["cells"] == {"0:0": "b"}


@pytest.mark.integration
async def test_v3_empty_sheets_list_yields_one_sheet(
    client: AsyncClient, env: _SpreadsheetEnv
):
    """An editor with no sheet has nothing to render, so an empty list is
    repaired into the default single sheet rather than persisted."""
    response = await client.post(
        f"/api/v1/g/{env.guild.id}/documents/",
        headers=env.headers,
        json={
            "name": "Empty",
            "initiative_id": env.initiative.id,
            "document_type": "spreadsheet",
            "content": {"schema_version": 3, "kind": "spreadsheet", "sheets": []},
        },
    )
    assert response.status_code == 201, response.text
    sheets = response.json()["content"]["sheets"]
    assert len(sheets) == 1
    assert sheets[0]["name"] == "Sheet1"

"""Tests for reading a spreadsheet file into the workbook shape.

The ones that matter most go out through the renderer and back in, because
import and export only stay agreed about how a fill or a currency is spelled
while something checks that they do.
"""

import pytest

from app.core.messages import DocumentMessages
from app.services.export.spreadsheet import render_xlsx
from app.services.tenant.documents_spreadsheet import (
    DocumentContentError,
    normalize_spreadsheet_content,
)
from app.services.tenant.spreadsheet_import import parse_spreadsheet_file


def workbook(**sheet) -> dict:
    """A canonical one-sheet workbook, normalized the way a stored one is."""
    base = {
        "id": "s1",
        "name": "Budget",
        "dimensions": {"rows": 5, "cols": 3},
        "cells": {},
        "columns": {},
        "rows": {},
        "cellStyles": {},
        "frozen": {"rows": 0, "cols": 0},
    }
    base.update(sheet)
    return normalize_spreadsheet_content(
        {"schema_version": 3, "kind": "spreadsheet", "sheets": [base]}
    )


# ── CSV ──────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_a_csv_becomes_one_sheet_named_after_its_file() -> None:
    sheets = parse_spreadsheet_file("Q1 sales.csv", b"a,b\n1,2\n")

    assert len(sheets) == 1
    assert sheets[0]["name"] == "Q1 sales"


@pytest.mark.unit
def test_numbers_arrive_as_numbers_and_text_as_text() -> None:
    sheets = parse_spreadsheet_file("x.csv", b"Widget,3,4.5,-2\n")

    assert sheets[0]["cells"] == {
        "0:0": "Widget",
        "0:1": 3,
        "0:2": 4.5,
        "0:3": -2,
    }


@pytest.mark.unit
def test_a_formula_stays_a_formula() -> None:
    """``=`` text is how this app stores a formula; the grid evaluates it."""
    sheets = parse_spreadsheet_file("x.csv", b"=1+1\n")

    assert sheets[0]["cells"]["0:0"] == "=1+1"


@pytest.mark.unit
def test_empty_fields_leave_no_cell() -> None:
    sheets = parse_spreadsheet_file("x.csv", b"a,,c\n")

    assert sheets[0]["cells"] == {"0:0": "a", "0:2": "c"}


@pytest.mark.unit
def test_a_tsv_is_split_on_tabs() -> None:
    sheets = parse_spreadsheet_file("x.tsv", b"a\tb\n")

    assert sheets[0]["cells"] == {"0:0": "a", "0:1": "b"}


@pytest.mark.unit
def test_a_file_that_is_not_a_spreadsheet_is_refused() -> None:
    with pytest.raises(DocumentContentError) as excinfo:
        parse_spreadsheet_file("notes.pdf", b"%PDF-1.4")

    assert excinfo.value.code == DocumentMessages.SPREADSHEET_UNREADABLE_FILE


@pytest.mark.unit
def test_an_xlsx_that_is_not_one_is_refused() -> None:
    with pytest.raises(DocumentContentError):
        parse_spreadsheet_file("broken.xlsx", b"not a zip at all")


@pytest.mark.unit
def test_text_that_is_not_utf8_still_imports() -> None:
    """A file from an older tool is worth a mangled accent, not a refusal."""
    sheets = parse_spreadsheet_file("x.csv", "café".encode("cp1252"))

    assert sheets[0]["cells"]["0:0"].startswith("caf")


# ── XLSX, through the renderer and back ──────────────────────────────────────


@pytest.mark.unit
def test_values_survive_the_round_trip() -> None:
    content = workbook(
        cells={"0:0": "Item", "1:0": "Widget", "1:1": 12.5, "2:1": "=B2*2"}
    )

    back = parse_spreadsheet_file("b.xlsx", render_xlsx(content, title="Budget"))

    assert back[0]["cells"] == content["sheets"][0]["cells"]


@pytest.mark.unit
def test_a_cells_look_survives_the_round_trip() -> None:
    content = workbook(
        cells={"0:0": "Item"},
        cellStyles={
            "0:0": {
                "style": {
                    "bold": True,
                    "italic": True,
                    "fill": "#ffee88",
                    "color": "#223344",
                    "align": "center",
                    "valign": "middle",
                }
            }
        },
    )

    back = parse_spreadsheet_file("b.xlsx", render_xlsx(content, title="Budget"))

    assert back[0]["cellStyles"]["0:0"]["style"] == {
        "bold": True,
        "italic": True,
        "fill": "#ffee88",
        "color": "#223344",
        "align": "center",
        "valign": "middle",
    }


@pytest.mark.unit
def test_a_number_format_survives_the_round_trip() -> None:
    content = workbook(
        cells={"0:0": 12.5},
        cellStyles={
            "0:0": {"format": {"type": "currency", "currency": "USD", "decimals": 2}}
        },
    )

    back = parse_spreadsheet_file("b.xlsx", render_xlsx(content, title="Budget"))
    fmt = back[0]["cellStyles"]["0:0"]["format"]

    assert fmt["type"] == "currency"
    assert fmt["currency"] == "USD"
    assert fmt["decimals"] == 2


@pytest.mark.unit
def test_a_percent_keeps_its_decimals() -> None:
    content = workbook(
        cells={"0:0": 0.25},
        cellStyles={"0:0": {"format": {"type": "percent", "decimals": 1}}},
    )

    back = parse_spreadsheet_file("b.xlsx", render_xlsx(content, title="Budget"))

    assert back[0]["cellStyles"]["0:0"]["format"] == {
        "type": "percent",
        "decimals": 1,
    }


@pytest.mark.unit
def test_frozen_panes_and_column_widths_survive() -> None:
    content = workbook(
        cells={"0:0": "Item"},
        columns={"0": {"width": 140}},
        frozen={"rows": 1, "cols": 2},
    )

    back = parse_spreadsheet_file("b.xlsx", render_xlsx(content, title="Budget"))

    assert back[0]["frozen"] == {"rows": 1, "cols": 2}
    assert back[0]["columns"]["0"]["width"] == 140


@pytest.mark.unit
def test_an_imported_sheet_has_room_to_work_in() -> None:
    """A three-row CSV should not open as a three-row grid."""
    sheets = parse_spreadsheet_file("x.csv", b"a\nb\nc\n")

    assert sheets[0]["dimensions"]["rows"] >= 100
    assert sheets[0]["dimensions"]["cols"] >= 26


@pytest.mark.unit
def test_a_cell_nobody_styled_carries_no_style() -> None:
    """Excel writes a font on every cell; carrying that over would pin a whole
    imported sheet to one size and colour."""
    content = workbook(cells={"0:0": "plain", "1:1": 3})

    back = parse_spreadsheet_file("b.xlsx", render_xlsx(content, title="Budget"))

    assert back[0]["cellStyles"] == {}


@pytest.mark.unit
def test_every_tab_of_a_workbook_arrives() -> None:
    content = normalize_spreadsheet_content(
        {
            "schema_version": 3,
            "kind": "spreadsheet",
            "sheets": [
                {"id": "a", "name": "Q1", "cells": {"0:0": "one"}},
                {"id": "b", "name": "Q2", "cells": {"0:0": "two"}},
            ],
        }
    )

    back = parse_spreadsheet_file("y.xlsx", render_xlsx(content, title="Year"))

    assert [s["name"] for s in back] == ["Q1", "Q2"]
    assert [s["cells"]["0:0"] for s in back] == ["one", "two"]

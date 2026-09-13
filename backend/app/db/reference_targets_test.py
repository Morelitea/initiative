"""What a reference resolves to, and that the registry saying so is not stale.

:data:`~app.db.reference_targets.VISUALS` names columns as strings, which is the
only way a table-keyed registry can name them — and a string survives a rename
that would have broken an attribute. These are the checks that fail instead of a
request failing at runtime.
"""

import importlib
import pkgutil

import pytest
from sqlmodel import SQLModel

import app.models.tenant as tenant_models
from app.core.relationships import ENDPOINT_KINDS
from app.db.reference_targets import VISUALS, Visual, _table_for
from app.db.search_index import SEARCH_SOURCES

pytestmark = pytest.mark.unit


def _tables():
    """Every tenant table, keyed by bare name."""
    for module in pkgutil.iter_modules(tenant_models.__path__):
        importlib.import_module(f"app.models.tenant.{module.name}")
    return {
        key.split(".")[-1]: table for key, table in SQLModel.metadata.tables.items()
    }


def test_every_visual_names_columns_that_exist():
    tables = _tables()
    for table_name, visual in VISUALS.items():
        assert table_name in tables, f"{table_name} is not a table"
        columns = set(tables[table_name].columns.keys())
        named = [
            *visual.image,
            *(name for name in (visual.icon, visual.color) if name),
            *(
                name
                for name in (visual.document_type, visual.mime, visual.filename)
                if name
            ),
        ]
        if visual.link_in_json is not None:
            named.append(visual.link_in_json[0])
        missing = [name for name in named if name not in columns]
        assert not missing, f"{table_name} has no column {missing}"


def test_a_preview_points_at_real_columns_on_a_real_table():
    tables = _tables()
    for table_name, visual in VISUALS.items():
        preview = visual.preview
        if preview is None:
            continue
        assert preview.chosen_fk in tables[table_name].columns
        other = tables[preview.table]
        for name in (preview.parent_fk, preview.newest_by, *preview.columns):
            assert name in other.columns, f"{preview.table} has no column {name}"


def test_a_kind_declares_at_most_one_look():
    """The card tries picture, emoji, colour in that order and draws the first,
    so a kind declaring two would silently never show the second."""
    for table_name, visual in VISUALS.items():
        looks = [
            bool(visual.image or visual.preview),
            bool(visual.icon),
            bool(visual.color),
        ]
        assert sum(looks) == 1, f"{table_name} declares more than one look"


def test_visuals_only_describe_kinds_an_edge_can_name():
    """A look nothing reads is a look nobody maintains."""
    linkable = {_table_for(kind) for kind in ENDPOINT_KINDS}
    assert set(VISUALS) <= linkable


def test_a_kind_with_no_entry_still_resolves_to_nothing():
    """`VISUALS.get` is what makes most kinds free, so the default has to be the
    empty one rather than a KeyError."""
    assert VISUALS.get("tasks", Visual()) == Visual()
    assert "tasks" in SEARCH_SOURCES

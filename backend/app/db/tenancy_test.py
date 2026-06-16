"""Completeness guard for the schema-per-guild table classification.

These tests fail if any ``table=True`` model is missing a placement decision,
or if the manifest names a table that does not exist. They are the safety net
that keeps ``tenancy.py`` honest as the schema evolves: adding a new table
without classifying it (the dangerous case — an unclassified guild-scoped
table would leak across tenants) breaks CI here.

Pure metadata checks — no database required.
"""

import pytest
from sqlmodel import SQLModel

from app.db import base  # noqa: F401  # populates SQLModel.metadata with every table
from app.db.tenancy import (
    ALL_CLASSIFIED_TABLES,
    GUILD_SCOPED_TABLES,
    SHARED_TABLES,
    is_guild_scoped,
    is_shared,
)

pytestmark = pytest.mark.unit


def _metadata_tables() -> set[str]:
    return set(SQLModel.metadata.tables.keys())


def test_shared_and_guild_scoped_are_disjoint():
    """A table cannot be both shared and guild-scoped."""
    overlap = SHARED_TABLES & GUILD_SCOPED_TABLES
    assert not overlap, f"Tables classified in BOTH buckets: {sorted(overlap)}"


def test_every_table_is_classified():
    """Every real table must appear in exactly one bucket (no silent gaps)."""
    unclassified = _metadata_tables() - ALL_CLASSIFIED_TABLES
    assert not unclassified, (
        "These tables exist but are not placed in SHARED_TABLES or "
        f"GUILD_SCOPED_TABLES in app/db/tenancy.py: {sorted(unclassified)}. "
        "Add each to the correct bucket — an unclassified guild-scoped table "
        "would leak across tenants."
    )


def test_manifest_has_no_phantom_tables():
    """The manifest must not name tables that don't exist (typos / renames)."""
    phantom = ALL_CLASSIFIED_TABLES - _metadata_tables()
    assert not phantom, (
        "These tables are classified in app/db/tenancy.py but do not exist in "
        f"the model metadata: {sorted(phantom)}. Remove or fix the names."
    )


def test_helpers_agree_with_sets():
    assert is_guild_scoped("tasks") and not is_shared("tasks")
    assert is_shared("users") and not is_guild_scoped("users")
    # Unknown tables are neither (forces an explicit decision rather than a default).
    assert not is_guild_scoped("does_not_exist")
    assert not is_shared("does_not_exist")

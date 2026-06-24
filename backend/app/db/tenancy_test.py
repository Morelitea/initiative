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
    GUILD_LEVEL_TABLES,
    GUILD_SCOPED_TABLES,
    INITIATIVE_SCOPED_TABLES,
    SHARED_TABLES,
    is_guild_scoped,
    is_initiative_scoped,
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
    """Every real table must appear in exactly one bucket (no silent gaps).

    ``GUILD_SCOPED_TABLES`` is derived as ``INITIATIVE_SCOPED_TABLES |
    GUILD_LEVEL_TABLES``, so a new guild table that's in neither the
    ``initiative_rls`` path registry nor ``GUILD_LEVEL_TABLES`` lands here.
    """
    unclassified = _metadata_tables() - ALL_CLASSIFIED_TABLES
    assert not unclassified, (
        f"These tables exist but are unclassified in app/db: {sorted(unclassified)}. "
        "Add each to SHARED_TABLES (public), or — for guild content — a path in "
        "app/db/initiative_rls.py INITIATIVE_PATHS (initiative-scoped) or to "
        "GUILD_LEVEL_TABLES in tenancy.py (guild-wide). An unclassified guild "
        "table would leak across tenants."
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


# --- Second-level: initiative-scoped vs guild-level -------------------------
# INITIATIVE_SCOPED_TABLES derives from the app/db/initiative_rls path registry
# and GUILD_SCOPED_TABLES derives from (initiative | guild-level), so the
# "registry matches the set" and "they partition GUILD_SCOPED" invariants hold
# by construction — no test needed. What still needs guarding: the two halves
# must be disjoint, and the polymorphic recent_views path must cover every
# entity type the app records.


def test_initiative_and_guild_level_are_disjoint():
    """A guild table must be initiative-scoped XOR guild-level, never both.

    (GUILD_SCOPED is their union, so an overlap wouldn't show up there — it would
    silently get initiative policies while also being declared 'exempt'.)
    """
    overlap = INITIATIVE_SCOPED_TABLES & GUILD_LEVEL_TABLES
    assert not overlap, (
        f"Tables in BOTH the initiative_rls registry and GUILD_LEVEL_TABLES: "
        f"{sorted(overlap)}. Pick one."
    )


def test_recent_views_path_covers_entity_types():
    """recent_views' polymorphic RLS path must join every entity type the app can
    record — otherwise rows of an uncovered type would be silently invisible."""
    from app.db.initiative_rls import RECENT_ENTITY_TABLES
    from app.models.tenant.recent_view import RECENT_ENTITY_TYPES

    uncovered = set(RECENT_ENTITY_TYPES) - set(RECENT_ENTITY_TABLES)
    assert not uncovered, (
        f"recent_views_path() has no initiative join for entity types {sorted(uncovered)} "
        "— add them to RECENT_ENTITY_TABLES in app/db/initiative_rls.py."
    )


def test_initiative_scoped_helper():
    assert is_initiative_scoped("projects") and not is_initiative_scoped(
        "guild_settings"
    )
    assert not is_initiative_scoped("uploads")  # guild-level
    assert not is_initiative_scoped("users")  # shared, not even guild-scoped

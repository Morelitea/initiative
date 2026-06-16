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


# --- Second-level partition: initiative-scoped vs guild-level ---------------
# These keep tenancy.py honest as guild tables are added: a new guild-scoped
# table must be classified initiative-scoped (and so receive initiative_access
# policies via gen_guild_rls.py) or explicitly exempted as guild-level.


def test_initiative_and_guild_level_are_disjoint():
    """A guild table can't be both initiative-scoped and guild-level."""
    overlap = INITIATIVE_SCOPED_TABLES & GUILD_LEVEL_TABLES
    assert not overlap, (
        f"Tables in BOTH initiative-scoped and guild-level: {sorted(overlap)}"
    )


def test_initiative_and_guild_level_partition_guild_scoped():
    """Every guild-scoped table is in exactly one second-level bucket — no gaps.

    A missing table is the dangerous case: it would land in a guild schema with
    no initiative RLS *and* no conscious 'this is guild-level' decision.
    """
    second_level = INITIATIVE_SCOPED_TABLES | GUILD_LEVEL_TABLES
    unclassified = GUILD_SCOPED_TABLES - second_level
    assert not unclassified, (
        "These guild-scoped tables have no initiative-scoped/guild-level decision in "
        f"app/db/tenancy.py: {sorted(unclassified)}. Add each to INITIATIVE_SCOPED_TABLES "
        "(and a path in scripts/gen_guild_rls.py) or to GUILD_LEVEL_TABLES."
    )
    phantom = second_level - GUILD_SCOPED_TABLES
    assert not phantom, (
        f"These tables are second-level-classified but not GUILD_SCOPED: {sorted(phantom)}."
    )


def test_generator_registry_covers_initiative_scoped_exactly():
    """scripts/gen_guild_rls.py must hold a path for exactly the initiative-scoped
    set — so an initiative table can't ship without its policies, and a stale path
    can't linger for a reclassified table. (The generator also asserts this on
    import; this surfaces it as a named test.)"""
    from scripts.gen_guild_rls import INITIATIVE_PATHS

    assert set(INITIATIVE_PATHS) == set(INITIATIVE_SCOPED_TABLES), (
        "gen_guild_rls.INITIATIVE_PATHS must match INITIATIVE_SCOPED_TABLES. "
        f"missing paths: {sorted(set(INITIATIVE_SCOPED_TABLES) - set(INITIATIVE_PATHS))}; "
        f"stale paths: {sorted(set(INITIATIVE_PATHS) - set(INITIATIVE_SCOPED_TABLES))}"
    )


def test_initiative_scoped_helper():
    assert is_initiative_scoped("projects") and not is_initiative_scoped(
        "guild_settings"
    )
    assert not is_initiative_scoped("uploads")  # guild-level
    assert not is_initiative_scoped("users")  # shared, not even guild-scoped

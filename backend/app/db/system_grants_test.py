"""Completeness guard for the shared-table grant registry (issue #782).

Mirrors ``tenancy_test``: these fail when a shared table has no grant decision
for a directly-granted login role — a new ``public`` table must give the system
engine (and the bare login role) *nothing* until this registry says so, making
"decide and grant" a real edit rather than a comment in CLAUDE.md.

Pure metadata — no database. The complementary check that the *live catalog*
matches the registry (drift in either direction) lives in
``security_invariants_test`` (integration).
"""

import pytest

from app.db.system_grants import (
    GRANTABLE_SHARED_TABLES,
    SHARED_TABLE_APP_USER_GRANTS,
    SHARED_TABLE_SYSTEM_GRANTS,
    VALID_GRANT_VERBS,
    grant_sql,
)

pytestmark = pytest.mark.unit

_MATRICES = [
    ("app_admin", SHARED_TABLE_SYSTEM_GRANTS),
    ("app_user", SHARED_TABLE_APP_USER_GRANTS),
]


@pytest.mark.parametrize("role, matrix", _MATRICES)
def test_registry_covers_exactly_the_shared_tables(role, matrix):
    """Every shared table — and only shared tables — has an explicit grant
    decision. A new ``public`` table with no entry fails the ``missing`` half
    (forcing the "grant it nothing until decided" step to be a real edit); a
    typo or a dropped table fails the ``phantom`` half."""
    missing = GRANTABLE_SHARED_TABLES - set(matrix)
    assert not missing, (
        f"{role}: shared tables with no grant decision {sorted(missing)}. Add each "
        "to app/db/system_grants.py (a verb set, or None for no access)."
    )
    phantom = set(matrix) - GRANTABLE_SHARED_TABLES
    assert not phantom, (
        f"{role}: registry names non-shared or nonexistent tables {sorted(phantom)}. "
        "Remove them or fix the names (shared tables come from tenancy.SHARED_TABLES)."
    )


@pytest.mark.parametrize("role, matrix", _MATRICES)
def test_registry_uses_only_known_dml_verbs(role, matrix):
    """Guard against a typo'd or non-DML verb silently dropping out of the
    rendered GRANT (``grant_sql`` only emits the known verbs)."""
    for table, verbs in matrix.items():
        if verbs is None:
            continue
        unknown = set(verbs) - VALID_GRANT_VERBS
        assert not unknown, f"{role}.{table}: unknown grant verbs {sorted(unknown)}"


def test_grant_sql_renders_canonical_order():
    assert (
        grant_sql(frozenset({"DELETE", "SELECT", "INSERT"})) == "SELECT, INSERT, DELETE"
    )
    assert grant_sql(frozenset({"SELECT"})) == "SELECT"


def test_grant_sql_returns_none_for_no_access():
    assert grant_sql(None) is None
    assert grant_sql(frozenset()) is None

"""The shared-table grant registry (issue #782): verbs and their render.

Pure metadata — no database. That every shared table has a record is
``public_rls_test``; that the live catalog matches the registry (drift in
either direction) is ``security_invariants_test`` (integration).
"""

from dataclasses import fields

from app.db.public_rls import PLATFORM_TIER_ROLES, SHARED_TABLE_REGISTRY, Grants
from app.db.system_grants import VALID_GRANT_VERBS, grant_sql, tier_table_grants


def test_registry_uses_only_known_dml_verbs():
    """Guard against a typo'd or non-DML verb silently dropping out of the
    rendered GRANT (``grant_sql`` only emits the known verbs)."""
    for table, shared in SHARED_TABLE_REGISTRY.items():
        held = {role.name: getattr(shared.grants, role.name) for role in fields(Grants)}
        held |= {str(capability): verbs for capability, verbs in shared.tiers.items()}
        for holder, verbs in held.items():
            if verbs is None:
                continue
            assert verbs, f"{table}.{holder}: empty verb set (use None)"
            unknown = set(verbs) - VALID_GRANT_VERBS
            assert not unknown, f"{table}.{holder}: unknown verbs {sorted(unknown)}"


def test_grant_sql_renders_canonical_order():
    assert (
        grant_sql(frozenset({"DELETE", "SELECT", "INSERT"})) == "SELECT, INSERT, DELETE"
    )
    assert grant_sql(frozenset({"SELECT"})) == "SELECT"
    assert grant_sql(None) is None
    assert grant_sql(frozenset()) is None


def test_tier_grants_render_to_every_tier():
    """Every tier has an entry, and a capability's verbs land on each tier
    holding it."""
    rendered = tier_table_grants()
    assert set(rendered) == PLATFORM_TIER_ROLES
    assert rendered["platform_owner"]["app_settings"] == frozenset(
        {"INSERT", "UPDATE", "DELETE"}
    )
    assert rendered["platform_member"] == {}

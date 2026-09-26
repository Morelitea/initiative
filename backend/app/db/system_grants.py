"""The grants the request-path Postgres roles hold on the shared (``public``)
tables, as views of ``app.db.public_rls.SHARED_TABLE_REGISTRY``.

Each shared table is declared once there, row security and grants together
(``SharedTable``). This module reads it per role: ``ROLE_GRANTS`` is one
table -> verbs matrix per role in ``Grants``, and ``tier_table_grants`` spells
the capability-keyed tier grants as the ``platform_<tier>`` roles holding each
capability. Those views are what the catalog is held to:

* ``security_invariants_test`` fails on any drift in either direction (a
  hotfix ``GRANT`` the registry doesn't know about, or a registry verb the
  catalog lacks);
* ``public_rls_test`` fails when a shared table has no registry record.

Migrations remain the immutable record of *when* a grant changed (they still
run the actual ``GRANT``/``REVOKE``). See issue #782.
"""

from __future__ import annotations

from dataclasses import fields

from app.core.capabilities import roles_with_capability
from app.db.public_rls import (
    PLATFORM_TIER_ROLES,
    SHARED_TABLE_REGISTRY,
    Grants,
    platform_tier,
)
from app.db.tenancy import SHARED_TABLES

__all__ = [
    "ROLE_GRANTS",
    "NON_MODEL_SHARED_TABLES",
    "GRANTABLE_SHARED_TABLES",
    "VALID_GRANT_VERBS",
    "grant_sql",
    "tier_table_grants",
]

# Public tables that carry no SQLModel (so they're absent from ``SHARED_TABLES``,
# which derives from model metadata) yet still exist in ``public`` and so still
# need an explicit "grant it nothing" decision for the login roles.
# ``storage_backfill_state`` is created lazily at runtime (see
# app.services.storage_backfill), not by a migration; its registry record is what
# the service's own GRANT renders from.
NON_MODEL_SHARED_TABLES: frozenset[str] = frozenset(
    {"alembic_version", "storage_backfill_state"}
)

# Every ``public`` table that requires a per-role grant decision.
GRANTABLE_SHARED_TABLES: frozenset[str] = SHARED_TABLES | NON_MODEL_SHARED_TABLES

# Canonical DML verb order for rendered ``GRANT`` statements. Grant order is
# semantically irrelevant, so the registry stores verb *sets* (compared directly
# against the catalog) and only imposes an order when rendering SQL — this keeps
# a re-grant written in a different order from reading as spurious "drift".
_VERB_ORDER: tuple[str, ...] = ("SELECT", "INSERT", "UPDATE", "DELETE")
VALID_GRANT_VERBS: frozenset[str] = frozenset(_VERB_ORDER)


#: One matrix per role in ``Grants`` (``app_admin``, ``app_user``, the four
#: floors): table -> the verbs it holds, or ``None``.
ROLE_GRANTS: dict[str, dict[str, frozenset[str] | None]] = {
    role.name: {
        table: getattr(shared.grants, role.name)
        for table, shared in SHARED_TABLE_REGISTRY.items()
    }
    for role in fields(Grants)
}


def tier_table_grants() -> dict[str, dict[str, frozenset[str]]]:
    """The registry's tier grants spelled as tiers: every ``platform_<tier>``
    role, unprefixed, with the verbs it holds per table. A tier holding no
    capability named there maps to an empty dict."""
    rendered: dict[str, dict[str, frozenset[str]]] = {
        role: {} for role in PLATFORM_TIER_ROLES
    }
    for table, shared in SHARED_TABLE_REGISTRY.items():
        for capability, verbs in shared.tiers.items():
            for role in roles_with_capability(capability):
                tables = rendered[platform_tier(role)]
                tables[table] = tables.get(table, frozenset()) | verbs
    return rendered


def grant_sql(verbs: frozenset[str] | None) -> str | None:
    """Render a registry verb set as a canonical ``GRANT`` verb list (fixed
    order), or ``None`` when the role gets no access — lets a future migration
    emit the grant straight from the registry instead of re-typing verbs."""
    if not verbs:
        return None
    return ", ".join(v for v in _VERB_ORDER if v in verbs)

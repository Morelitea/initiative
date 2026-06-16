"""Generate alembic/guild/guild_rls.sql — the initiative-member RLS policies for
the per-guild CONTENT tables.

The access RULE lives in ONE place, ``public.initiative_access(...)`` (initiative
member OR guild admin OR PAM, read from the request GUCs). This generator owns
the OTHER half: the per-table *path* that resolves a row's initiative id and the
uniform policy boilerplate (ENABLE/FORCE RLS + DROP/CREATE × 4 commands, the
``current_user_id`` GUC snippet, read vs write flag).

The registry ``INITIATIVE_PATHS`` below must cover exactly
``app.db.tenancy.INITIATIVE_SCOPED_TABLES`` — the module asserts this on import,
so a table can't become initiative-scoped without a path here, and a path can't
linger for a table that's been re-classified as guild-level. That is the
"hard enforcement": no initiative-level table ships without its policies.

Run after any guild-scoped schema change that adds/removes an initiative-scoped
table (or changes an FK path):

    python scripts/gen_guild_rls.py        # writes alembic/guild/guild_rls.sql

``schema_provisioning.apply_guild_rls`` applies the result to guild_template +
every guild_<id>. ``guild_rls_test.py`` fails CI if the committed file drifts
from this generator's output.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

# Allow ``python scripts/gen_guild_rls.py`` from backend/ to import the app.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.tenancy import INITIATIVE_SCOPED_TABLES  # noqa: E402

_OUT = Path(__file__).resolve().parents[1] / "alembic" / "guild" / "guild_rls.sql"

# The request-GUC user id, NULLIF-guarded so an unset/PAM context yields NULL
# (no membership) rather than faulting the cast for every row.
_UID = "(NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer"

# A path builder takes (table_name, write_flag) and returns the SQL predicate
# (an initiative_access(...) call, possibly wrapped in an EXISTS join) that the
# four policies share — read uses write=False, write commands use write=True.
PathBuilder = Callable[[str, bool], str]


def _access(initiative_expr: str, write: bool) -> str:
    return f"public.initiative_access({initiative_expr}, {_UID}, {'true' if write else 'false'})"


def direct() -> PathBuilder:
    """The table has its own ``initiative_id`` column."""
    return lambda t, w: _access(f"{t}.initiative_id", w)


def via(parent: str, fk: str, *, parent_pk: str = "id") -> PathBuilder:
    """One hop: ``table.<fk> -> parent.<parent_pk>``; parent has ``initiative_id``."""
    return lambda t, w: (
        f"EXISTS (SELECT 1 FROM {parent} "
        f"WHERE {parent}.{parent_pk} = {t}.{fk} "
        f"AND {_access(f'{parent}.initiative_id', w)})"
    )


def via_task_project(fk: str = "task_id") -> PathBuilder:
    """Two hops: ``table.<fk> -> tasks -> projects.initiative_id``."""
    return lambda t, w: (
        f"EXISTS (SELECT 1 FROM tasks tk JOIN projects pr ON pr.id = tk.project_id "
        f"WHERE tk.id = {t}.{fk} "
        f"AND {_access('pr.initiative_id', w)})"
    )


def via_queue_item(fk: str = "queue_item_id") -> PathBuilder:
    """Two hops: ``table.<fk> -> queue_items -> queues.initiative_id``."""
    return lambda t, w: (
        f"EXISTS (SELECT 1 FROM queue_items qi JOIN queues q ON q.id = qi.queue_id "
        f"WHERE qi.id = {t}.{fk} "
        f"AND {_access('q.initiative_id', w)})"
    )


def via_property(entity_from: str, entity_pred: str, entity_init: str) -> PathBuilder:
    """Property-value rows: join the entity and ``property_definitions`` and
    require both resolve to the SAME initiative, then check access on it.

    ``entity_from`` is the FROM clause for the entity (e.g. ``documents d``),
    ``entity_pred`` ties the value row to that entity (e.g. ``d.id =
    {t}.document_id``), and ``entity_init`` is the entity's initiative column
    (e.g. ``d.initiative_id``)."""
    return lambda t, w: (
        f"EXISTS (SELECT 1 FROM {entity_from} "
        f"JOIN property_definitions pd ON pd.id = {t}.property_id "
        f"WHERE {entity_pred.format(t=t)} AND {entity_init} = pd.initiative_id "
        f"AND {_access('pd.initiative_id', w)})"
    )


def comments_path() -> PathBuilder:
    """Comments hang off EITHER a task or a document."""
    return lambda t, w: (
        f"(({t}.task_id IS NOT NULL AND EXISTS ("
        f"SELECT 1 FROM tasks tk JOIN projects pr ON pr.id = tk.project_id "
        f"WHERE tk.id = {t}.task_id AND {_access('pr.initiative_id', w)})) "
        f"OR ({t}.document_id IS NOT NULL AND EXISTS ("
        f"SELECT 1 FROM documents d WHERE d.id = {t}.document_id "
        f"AND {_access('d.initiative_id', w)})))"
    )


# recent_views is polymorphic over (entity_type, entity_id). Every entity it can
# point at is an initiative-scoped table with a direct initiative_id, so the path
# is a per-type EXISTS join. Keyed by the entity_type string the app stores.
_RECENT_ENTITY_TABLES: dict[str, str] = {
    "project": "projects",
    "document": "documents",
    "queue": "queues",
    "counter_group": "counter_groups",
}


def recent_views_path() -> PathBuilder:
    def build(t: str, w: bool) -> str:
        legs = [
            f"({t}.entity_type = '{etype}' AND EXISTS (SELECT 1 FROM {tbl} "
            f"WHERE {tbl}.id = {t}.entity_id AND {_access(f'{tbl}.initiative_id', w)}))"
            for etype, tbl in _RECENT_ENTITY_TABLES.items()
        ]
        return "(" + " OR ".join(legs) + ")"

    return build


def document_links_path() -> PathBuilder:
    """A link must clear initiative access on BOTH endpoints. With only the
    source checked, a write-member of one initiative could point
    ``target_document_id`` at a document in an initiative they can't reach (and
    on read a cross-initiative link would leak the other side's existence)."""

    def _leg(fk: str, t: str, w: bool) -> str:
        return (
            f"EXISTS (SELECT 1 FROM documents WHERE documents.id = {t}.{fk} "
            f"AND {_access('documents.initiative_id', w)})"
        )

    return lambda t, w: (
        f"({_leg('source_document_id', t, w)} AND {_leg('target_document_id', t, w)})"
    )


# table -> how its rows resolve an initiative for initiative_access(...).
# MUST cover exactly INITIATIVE_SCOPED_TABLES (asserted below).
INITIATIVE_PATHS: dict[str, PathBuilder] = {
    # Own initiative_id column
    "projects": direct(),
    "documents": direct(),
    "queues": direct(),
    "counter_groups": direct(),
    "calendar_events": direct(),
    "property_definitions": direct(),
    # One hop -> projects
    "tasks": via("projects", "project_id"),
    "task_statuses": via("projects", "project_id"),
    "project_documents": via("projects", "project_id"),
    "project_permissions": via("projects", "project_id"),
    "project_tags": via("projects", "project_id"),
    # One hop -> documents
    "document_tags": via("documents", "document_id"),
    "document_permissions": via("documents", "document_id"),
    "document_file_versions": via("documents", "document_id"),
    "document_links": document_links_path(),
    # One hop -> initiative_roles (role-based ACL rows)
    "project_role_permissions": via("initiative_roles", "initiative_role_id"),
    "document_role_permissions": via("initiative_roles", "initiative_role_id"),
    # One hop -> queues
    "queue_items": via("queues", "queue_id"),
    "queue_permissions": via("queues", "queue_id"),
    "queue_role_permissions": via("queues", "queue_id"),
    # One hop -> counter_groups
    "counters": via("counter_groups", "counter_group_id"),
    "counter_group_permissions": via("counter_groups", "counter_group_id"),
    "counter_group_role_permissions": via("counter_groups", "counter_group_id"),
    # One hop -> calendar_events
    "calendar_event_attendees": via("calendar_events", "calendar_event_id"),
    "calendar_event_documents": via("calendar_events", "calendar_event_id"),
    "calendar_event_tags": via("calendar_events", "calendar_event_id"),
    # Two hops -> tasks -> projects
    "subtasks": via_task_project("task_id"),
    "task_assignees": via_task_project("task_id"),
    "task_tags": via_task_project("task_id"),
    # Two hops -> queue_items -> queues
    "queue_item_documents": via_queue_item("queue_item_id"),
    "queue_item_tags": via_queue_item("queue_item_id"),
    "queue_item_tasks": via_queue_item("queue_item_id"),
    # Property values (entity + property_definitions, same-initiative)
    "document_property_values": via_property(
        "documents d", "d.id = {t}.document_id", "d.initiative_id"
    ),
    "task_property_values": via_property(
        "tasks tk JOIN projects pr ON pr.id = tk.project_id",
        "tk.id = {t}.task_id",
        "pr.initiative_id",
    ),
    "calendar_event_property_values": via_property(
        "calendar_events ce", "ce.id = {t}.event_id", "ce.initiative_id"
    ),
    # Multi-parent
    "comments": comments_path(),
    # Per-user state, scoped via the entity it points at
    "project_orders": via("projects", "project_id"),
    "project_favorites": via("projects", "project_id"),
    "task_assignment_digest_items": via("projects", "project_id"),
    "event_reminder_dispatches": via("calendar_events", "event_id"),
    "recent_views": recent_views_path(),
}

# --- Hard enforcement: the registry must mirror the classification ----------
# Plain raises (not asserts): these guard real invariants and must survive
# ``python -O``, which strips assert statements.
_missing = INITIATIVE_SCOPED_TABLES - INITIATIVE_PATHS.keys()
_stale = INITIATIVE_PATHS.keys() - INITIATIVE_SCOPED_TABLES
if _missing:
    raise RuntimeError(
        f"INITIATIVE_SCOPED_TABLES has tables with no RLS path in gen_guild_rls.py: "
        f"{sorted(_missing)}. Add a path (or move the table to GUILD_LEVEL_TABLES)."
    )
if _stale:
    raise RuntimeError(
        f"gen_guild_rls.py has paths for non-initiative-scoped tables: {sorted(_stale)}. "
        f"Remove them (or add the table to INITIATIVE_SCOPED_TABLES)."
    )

# recent_views' polymorphic path must cover every entity type the app records.
from app.models.recent_view import RECENT_ENTITY_TYPES  # noqa: E402

_uncovered = set(RECENT_ENTITY_TYPES) - _RECENT_ENTITY_TABLES.keys()
if _uncovered:
    raise RuntimeError(
        f"recent_views_path() is missing initiative joins for entity types "
        f"{sorted(_uncovered)} — add them to _RECENT_ENTITY_TABLES."
    )


_HEADER = """\
-- AUTOGENERATED by scripts/gen_guild_rls.py — DO NOT EDIT BY HAND.
-- Initiative-member-level RLS for the per-guild CONTENT tables. Schema-relative
-- (run with search_path = <guild_schema>, public). Idempotent.
--
-- The access RULE lives in ONE place, public.initiative_access (initiative member
-- OR guild admin OR PAM, read from the request GUCs); each policy below is just the
-- join that resolves a table's initiative id and defers to it.
--
-- SCOPE: only INITIATIVE-scoped CONTENT tables are here, exactly
-- app.db.tenancy.INITIATIVE_SCOPED_TABLES. The STRUCTURAL initiative tables
-- (initiatives, initiative_members, initiative_roles, initiative_role_permissions)
-- and guild-level / own-row tables (app.db.tenancy.GUILD_LEVEL_TABLES) are NOT
-- initiative-member-scoped: they are guild-scoped by the schema boundary (the
-- membership table can't be gated by the membership check it backs without
-- recursing; own-row scoping would break co-member rosters). The app layer still
-- does finer filtering (e.g. the initiatives list shows member-only for non-admins).
--
-- To add a new initiative-scoped table: add it to INITIATIVE_SCOPED_TABLES and a
-- path to INITIATIVE_PATHS in scripts/gen_guild_rls.py, then regenerate.
"""

_COMMANDS = (
    ("select", "SELECT", "USING", False),
    ("insert", "INSERT", "WITH CHECK", True),
    ("update", "UPDATE", "USING-CHECK", True),
    ("delete", "DELETE", "USING", True),
)


def _table_block(table: str, build: PathBuilder) -> str:
    lines = [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
    ]
    for suffix, command, clause, write in _COMMANDS:
        pred = build(table, write)
        name = f"initiative_member_{suffix}"
        lines.append(f"DROP POLICY IF EXISTS {name} ON {table};")
        lines.append(f"CREATE POLICY {name} ON {table} AS PERMISSIVE FOR {command}")
        if clause == "USING-CHECK":
            lines.append(f"  USING ({pred}) WITH CHECK ({pred});")
        elif clause == "WITH CHECK":
            lines.append(f"  WITH CHECK ({pred});")
        else:  # USING
            lines.append(f"  USING ({pred});")
    return "\n".join(lines)


def generate() -> str:
    blocks = [_table_block(t, INITIATIVE_PATHS[t]) for t in sorted(INITIATIVE_PATHS)]
    return _HEADER + "\n\n" + "\n\n".join(blocks) + "\n"


if __name__ == "__main__":
    _OUT.write_text(generate())
    print(f"Wrote {len(INITIATIVE_PATHS)} table policy blocks -> {_OUT}")

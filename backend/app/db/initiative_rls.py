"""Single source of truth for the initiative-member RLS layer.

Each per-guild CONTENT table that is scoped to initiative membership is declared
exactly once here, in ``INITIATIVE_PATHS`` — mapping the table to *how a row
resolves its initiative* for ``public.initiative_access(...)``. From that one
declaration we derive:

- ``INITIATIVE_SCOPED_TABLES`` (``app.db.tenancy`` re-exports it and folds it
  into ``GUILD_SCOPED_TABLES``), and
- ``alembic/guild/guild_rls.sql`` (``scripts/gen_guild_rls.py`` stamps the
  uniform policy boilerplate around each path).

So a new initiative-scoped table is added in ONE place — add a path here — and
both the classification and the generated policies follow. ``tenancy_test.py``
and ``guild_rls_test.py`` enforce that nothing drifts.

This module is intentionally dependency-free (no models, no SQLAlchemy) so it can
be imported by ``tenancy`` and by the build-time generator alike.
"""

from __future__ import annotations

from typing import Callable

# The request-GUC user id, NULLIF-guarded so an unset/PAM context yields NULL
# (no membership) rather than faulting the cast for every row.
_UID = "(NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer"

# A path builder takes (table_name, write_flag) and returns the SQL predicate
# (an initiative_access(...) call, possibly wrapped in an EXISTS join) shared by
# the four policies — read uses write=False, write commands use write=True.
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
# is a per-type EXISTS join. Keyed by the entity_type string the app stores; a
# test (test_recent_views_path_covers_entity_types) asserts this stays in sync
# with app.models.recent_view.RECENT_ENTITY_TYPES.
RECENT_ENTITY_TABLES: dict[str, str] = {
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
            for etype, tbl in RECENT_ENTITY_TABLES.items()
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


# table -> how its rows resolve an initiative for initiative_access(...). THE
# source of truth: INITIATIVE_SCOPED_TABLES and guild_rls.sql both derive from
# this dict, so a new initiative-scoped table is declared here exactly once.
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

# Derived — the classification follows the registry, never duplicates it.
INITIATIVE_SCOPED_TABLES: frozenset[str] = frozenset(INITIATIVE_PATHS)

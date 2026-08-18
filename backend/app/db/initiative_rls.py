"""Single source of truth for the initiative-member RLS layer.

Each per-guild CONTENT table that is scoped to initiative membership is declared
exactly once here, in ``INITIATIVE_PATHS`` — mapping the table to *how a row
resolves its initiative* for ``public.initiative_access(...)``. From that one
declaration we derive:

- ``INITIATIVE_SCOPED_TABLES`` (``app.db.tenancy`` re-exports it and folds it
  into ``GUILD_SCOPED_TABLES``), and
- the rendered RLS DDL (``app.db.guild_ddl`` stamps the
  uniform policy boilerplate around each path).

So a new initiative-scoped table is added in ONE place — add a path here — and
both the classification and the generated policies follow. ``tenancy_test.py``
and ``guild_rls_test.py`` enforce that nothing drifts.

This module is intentionally dependency-free (no models, no SQLAlchemy) so it can
be imported by ``tenancy`` and by the build-time generator alike.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.core.tools import RECENTABLE_TOOLS

# The request-GUC user id, NULLIF-guarded so an unset/PAM context yields NULL
# (no membership) rather than faulting the cast for every row.
_UID = "(NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer"

# A path builder takes (table_name, write_flag) and returns the SQL predicate
# (an initiative_access(...) call, possibly wrapped in an EXISTS join) shared by
# the four policies — read uses write=False, write commands use write=True.
PathBuilder = Callable[[str, bool], str]

# A row-locator takes a trigger row alias ("NEW"/"OLD") and returns a scalar SQL
# expression yielding that row's initiative id (or NULL).
RowLocator = Callable[[str], str]


@dataclass(frozen=True)
class InitiativePath:
    """How one table's rows resolve an initiative, rendered two ways.

    ``predicate`` builds the RLS policy body; ``initiative_expr`` builds the
    scalar lookup the change-capture trigger stamps onto an outbox row. Both come
    from the SAME declaration, so a table cannot be gated by one initiative and
    have its events attributed to another. Adding a table still means one entry
    in ``INITIATIVE_PATHS`` — the builders below produce both forms.
    """

    predicate: PathBuilder
    initiative_expr: RowLocator


#: The routed guild-admin leg, for rows that span every initiative in a guild.
_GUILD_ADMIN = "current_setting('app.current_guild_role'::text, true) = 'admin'::text"


def _access(initiative_expr: str, write: bool) -> str:
    return f"public.initiative_access({initiative_expr}, {_UID}, {'true' if write else 'false'})"


def direct() -> InitiativePath:
    """The table has its own ``initiative_id`` column."""
    return InitiativePath(
        predicate=lambda t, w: _access(f"{t}.initiative_id", w),
        initiative_expr=lambda r: f"{r}.initiative_id",
    )


def via(parent: str, fk: str, *, parent_pk: str = "id") -> InitiativePath:
    """One hop: ``table.<fk> -> parent.<parent_pk>``; parent has ``initiative_id``."""
    return InitiativePath(
        predicate=lambda t, w: (
            f"EXISTS (SELECT 1 FROM {parent} "
            f"WHERE {parent}.{parent_pk} = {t}.{fk} "
            f"AND {_access(f'{parent}.initiative_id', w)})"
        ),
        initiative_expr=lambda r: (
            f"(SELECT {parent}.initiative_id FROM {parent} "  # noqa: S608
            f"WHERE {parent}.{parent_pk} = {r}.{fk})"
        ),
    )


def via_task_project(fk: str = "task_id") -> InitiativePath:
    """Two hops: ``table.<fk> -> tasks -> projects.initiative_id``."""
    return InitiativePath(
        predicate=lambda t, w: (
            f"EXISTS (SELECT 1 FROM tasks tk JOIN projects pr ON pr.id = tk.project_id "
            f"WHERE tk.id = {t}.{fk} "
            f"AND {_access('pr.initiative_id', w)})"
        ),
        initiative_expr=lambda r: (
            f"(SELECT pr.initiative_id FROM tasks tk "  # noqa: S608
            f"JOIN projects pr ON pr.id = tk.project_id WHERE tk.id = {r}.{fk})"
        ),
    )


def via_queue_item(fk: str = "queue_item_id") -> InitiativePath:
    """Two hops: ``table.<fk> -> queue_items -> queues.initiative_id``."""
    return InitiativePath(
        predicate=lambda t, w: (
            f"EXISTS (SELECT 1 FROM queue_items qi JOIN queues q ON q.id = qi.queue_id "
            f"WHERE qi.id = {t}.{fk} "
            f"AND {_access('q.initiative_id', w)})"
        ),
        initiative_expr=lambda r: (
            f"(SELECT q.initiative_id FROM queue_items qi "  # noqa: S608
            f"JOIN queues q ON q.id = qi.queue_id WHERE qi.id = {r}.{fk})"
        ),
    )


def via_event_calendar(fk: str = "calendar_event_id") -> InitiativePath:
    """Two hops: ``table.<fk> -> calendar_events -> calendars.initiative_id``."""
    return InitiativePath(
        predicate=lambda t, w: (
            f"EXISTS (SELECT 1 FROM calendar_events ce "
            f"JOIN calendars cal ON cal.id = ce.calendar_id "
            f"WHERE ce.id = {t}.{fk} "
            f"AND {_access('cal.initiative_id', w)})"
        ),
        initiative_expr=lambda r: (
            f"(SELECT cal.initiative_id FROM calendar_events ce "  # noqa: S608
            f"JOIN calendars cal ON cal.id = ce.calendar_id WHERE ce.id = {r}.{fk})"
        ),
    )


def via_property(
    entity_from: str, entity_pred: str, entity_init: str
) -> InitiativePath:
    """Property-value rows: join the entity and ``property_definitions`` and
    require both resolve to the SAME initiative, then check access on it.

    ``entity_from`` is the FROM clause for the entity (e.g. ``documents d``),
    ``entity_pred`` ties the value row to that entity (e.g. ``d.id =
    {t}.document_id``), and ``entity_init`` is the entity's initiative column
    (e.g. ``d.initiative_id``).

    Every fragment interpolated here is a string literal from the
    INITIATIVE_PATHS registry in this module — policy DDL rendering, never
    user input."""
    return InitiativePath(
        predicate=lambda t, w: (
            f"EXISTS (SELECT 1 FROM {entity_from} "  # noqa: S608
            f"JOIN property_definitions pd ON pd.id = {t}.property_id "
            f"WHERE {entity_pred.format(t=t)} AND {entity_init} = pd.initiative_id "
            f"AND {_access('pd.initiative_id', w)})"
        ),
        # The policy already requires entity and definition to share an
        # initiative, so either side names the same one; the definition is a
        # single-table lookup.
        initiative_expr=lambda r: (
            f"(SELECT pd.initiative_id FROM property_definitions pd "  # noqa: S608
            f"WHERE pd.id = {r}.property_id)"
        ),
    )


def comments_path() -> InitiativePath:
    """Comments hang off EITHER a task or a document."""
    return InitiativePath(
        predicate=lambda t, w: (
            f"(({t}.task_id IS NOT NULL AND EXISTS ("
            f"SELECT 1 FROM tasks tk JOIN projects pr ON pr.id = tk.project_id "
            f"WHERE tk.id = {t}.task_id AND {_access('pr.initiative_id', w)})) "
            f"OR ({t}.document_id IS NOT NULL AND EXISTS ("
            f"SELECT 1 FROM documents d WHERE d.id = {t}.document_id "
            f"AND {_access('d.initiative_id', w)})))"
        ),
        initiative_expr=lambda r: (
            "COALESCE("
            f"(SELECT pr.initiative_id FROM tasks tk "  # noqa: S608
            f"JOIN projects pr ON pr.id = tk.project_id WHERE tk.id = {r}.task_id), "
            f"(SELECT d.initiative_id FROM documents d WHERE d.id = {r}.document_id))"
        ),
    )


# recent_views is polymorphic over (entity_type, entity_id). Every entity it can
# point at is an initiative-scoped table with a direct initiative_id, so the path
# is a per-type EXISTS join. Derived from the canonical Tool enum: entity_type is
# the tool's string value, its table is the pluralized stem.
RECENT_ENTITY_TABLES: dict[str, str] = {t.value: t.plural for t in RECENTABLE_TOOLS}


def webhook_subscription_path() -> InitiativePath:
    """A subscription is reached by whoever can reach what it watches.

    Naming an initiative makes it that initiative's integration config, seen and
    managed by its members exactly like the content it reports on — the same gate
    as everything else in a guild, not a private note belonging to whoever typed
    the URL.

    Naming NO initiative is the guild-wide case, and there the ordinary
    ``initiative_access`` answer is wrong: a NULL means "the initiative gate has
    nothing to decide", which admits any member. A guild-wide subscription
    reports across every initiative, so reaching it is guild-admin authority —
    the one role that already spans them.
    """
    return InitiativePath(
        predicate=lambda t, w: (
            f"(CASE WHEN {t}.initiative_id IS NULL "
            f"THEN {_GUILD_ADMIN} "
            f"ELSE {_access(f'{t}.initiative_id', w)} END)"
        ),
        initiative_expr=lambda r: f"{r}.initiative_id",
    )


def recent_views_path() -> InitiativePath:
    def build(t: str, w: bool) -> str:
        legs = [
            f"({t}.entity_type = '{etype}' AND EXISTS (SELECT 1 FROM {tbl} "
            f"WHERE {tbl}.id = {t}.entity_id AND {_access(f'{tbl}.initiative_id', w)}))"
            for etype, tbl in RECENT_ENTITY_TABLES.items()
        ]
        return "(" + " OR ".join(legs) + ")"

    def locate(r: str) -> str:
        arms = " ".join(
            f"WHEN '{etype}' THEN "
            f"(SELECT {tbl}.initiative_id FROM {tbl} WHERE {tbl}.id = {r}.entity_id)"  # noqa: S608
            for etype, tbl in RECENT_ENTITY_TABLES.items()
        )
        return f"(CASE {r}.entity_type {arms} END)"

    return InitiativePath(predicate=build, initiative_expr=locate)


def document_links_path() -> InitiativePath:
    """A link must clear initiative access on BOTH endpoints. With only the
    source checked, a write-member of one initiative could point
    ``target_document_id`` at a document in an initiative they can't reach (and
    on read a cross-initiative link would leak the other side's existence)."""

    def _leg(fk: str, t: str, w: bool) -> str:
        return (
            f"EXISTS (SELECT 1 FROM documents WHERE documents.id = {t}.{fk} "
            f"AND {_access('documents.initiative_id', w)})"
        )

    return InitiativePath(
        predicate=lambda t, w: (
            f"({_leg('source_document_id', t, w)} AND {_leg('target_document_id', t, w)})"
        ),
        # Both endpoints clear the same gate to exist, so the source names the
        # initiative the link belongs to.
        initiative_expr=lambda r: (
            f"(SELECT documents.initiative_id FROM documents "  # noqa: S608
            f"WHERE documents.id = {r}.source_document_id)"
        ),
    )


# table -> how its rows resolve an initiative for initiative_access(...). THE
# source of truth: INITIATIVE_SCOPED_TABLES and the rendered RLS DDL (app.db.guild_ddl) both derive from
# this dict, so a new initiative-scoped table is declared here exactly once.
INITIATIVE_PATHS: dict[str, InitiativePath] = {
    # Own initiative_id column
    "projects": direct(),
    "documents": direct(),
    "queues": direct(),
    "counter_groups": direct(),
    "calendars": direct(),
    "dashboards": direct(),
    "property_definitions": direct(),
    "resource_grants": direct(),
    # The change log itself. Scoped like the rows it describes, which is what
    # lets the poller read it AS the subscriber (see EVENTED_TABLES below).
    "event_outbox": direct(),
    # Integration config, reached by whoever can reach what it watches.
    "webhook_subscriptions": webhook_subscription_path(),
    # One hop -> projects
    "tasks": via("projects", "project_id"),
    "task_statuses": via("projects", "project_id"),
    "project_documents": via("projects", "project_id"),
    "project_tags": via("projects", "project_id"),
    # One hop -> documents
    "document_tags": via("documents", "document_id"),
    "document_file_versions": via("documents", "document_id"),
    "document_links": document_links_path(),
    # One hop -> queues
    "queue_items": via("queues", "queue_id"),
    "queue_tags": via("queues", "queue_id"),
    # One hop -> counter_groups
    "counters": via("counter_groups", "counter_group_id"),
    "counter_group_tags": via("counter_groups", "counter_group_id"),
    # One hop -> calendars
    "calendar_events": via("calendars", "calendar_id"),
    "calendar_tags": via("calendars", "calendar_id"),
    # One hop -> dashboards
    "dashboard_tags": via("dashboards", "dashboard_id"),
    # Two hops -> tasks -> projects
    "subtasks": via_task_project("task_id"),
    "task_assignees": via_task_project("task_id"),
    "task_tags": via_task_project("task_id"),
    # Two hops -> queue_items -> queues
    "queue_item_documents": via_queue_item("queue_item_id"),
    "queue_item_tags": via_queue_item("queue_item_id"),
    "queue_item_tasks": via_queue_item("queue_item_id"),
    # Two hops -> calendar_events -> calendars
    "calendar_event_attendees": via_event_calendar("calendar_event_id"),
    "calendar_event_documents": via_event_calendar("calendar_event_id"),
    "calendar_event_tags": via_event_calendar("calendar_event_id"),
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
        "calendar_events ce JOIN calendars cal ON cal.id = ce.calendar_id",
        "ce.id = {t}.event_id",
        "cal.initiative_id",
    ),
    # Multi-parent
    "comments": comments_path(),
    # Per-user state, scoped via the entity it points at
    "project_orders": via("projects", "project_id"),
    "project_favorites": via("projects", "project_id"),
    "task_assignment_digest_items": via("projects", "project_id"),
    "event_reminder_dispatches": via_event_calendar("event_id"),
    "recent_views": recent_views_path(),
}

# Derived — the classification follows the registry, never duplicates it.
INITIATIVE_SCOPED_TABLES: frozenset[str] = frozenset(INITIATIVE_PATHS)


# Tables that get NO change-capture trigger, and why. Stated as an EXCLUSION so
# the default is "a new content table is evented": a new entry in
# INITIATIVE_PATHS starts emitting with no second edit, and anything that should
# stay silent has to say so here deliberately. An inclusion list would instead
# let a new table ship emitting nothing, which is the failure this whole
# mechanism exists to remove.
NON_EVENTED_TABLES: frozenset[str] = frozenset(
    {
        # The log cannot log itself.
        "event_outbox",
        # Per-user viewing/ordering state and internal dispatch bookkeeping.
        # These record what one member did with their own UI, not a change to
        # the initiative's content, so emitting them is pure noise on every
        # subscription.
        "recent_views",
        "project_orders",
        "project_favorites",
        "task_assignment_digest_items",
        "event_reminder_dispatches",
        # Integration config — it has no changes of its own to report.
        "webhook_subscriptions",
    }
)

# Tables that EMIT events but do not carry initiative-member RLS, mapped to how
# an event about one resolves its initiative.
#
# Emitting and being initiative-scoped are different questions, and deriving the
# first from the second is a mistake: the structural initiative tables are
# deliberately exempt from the RLS (a membership table cannot be gated by the
# membership check it backs without the policy recursing), and that exemption
# must not also mean "invisible to every automation". Creating an initiative,
# adding a member, changing a role are all things a subscriber can act on.
#
# These get a capture trigger and nothing else — no policies are rendered from
# this registry. The resulting outbox row carries a real initiative_id, so RLS on
# ``event_outbox`` scopes the EVENT normally even though the source table is not
# scoped: members of that initiative, and guild admins, see it.
GUILD_LEVEL_EVENTED: dict[str, RowLocator] = {
    # An event about an initiative belongs to that initiative.
    "initiatives": lambda r: f"{r}.id",
    "initiative_members": lambda r: f"{r}.initiative_id",
    "initiative_roles": lambda r: f"{r}.initiative_id",
    "initiative_role_permissions": lambda r: (
        f"(SELECT initiative_roles.initiative_id FROM initiative_roles "  # noqa: S608
        f"WHERE initiative_roles.id = {r}.initiative_role_id)"
    ),
}

# Tables that emit with NO initiative at all — the row carries a NULL
# initiative_id, which the access function treats as "the initiative gate has
# nothing to decide" and admits for any guild member.
#
# That is the correct disclosure here, not a weakening: these rows are already
# readable by every member of the guild (they are guild-level precisely because
# they belong to no initiative), so an event naming one reveals nothing its
# subscriber could not read directly. The envelope carries ids and column names
# only, never values.
#
# The trigger is told a NULL is expected for these, so an unresolvable initiative
# on an initiative-scoped table still means "skip" rather than "broadcast".
GUILD_WIDE_EVENTED: frozenset[str] = frozenset(
    {
        # Tags run through most flows and are shared across initiatives, so an
        # automation that cannot see them is missing an ordinary trigger.
        "tags",
    }
)

# Guild-level tables that emit NOTHING, and why — recorded so the absence is a
# decision rather than a silent gap.
SILENT_GUILD_TABLES: frozenset[str] = frozenset(
    {
        # Safe to emit by the same reasoning as tags (the row is guild-readable;
        # blob CONTENT is gated at the document layer, and no content rides in an
        # envelope). Left out on volume, not disclosure: uploads churn on every
        # attachment and avatar write, and every subscription would pay for them.
        # Cheap to add if someone wants it.
        "uploads",
    }
)

# The tables the capture trigger is installed on: initiative-scoped content
# (minus the deliberate exclusions) plus the guild-level tables that resolve an
# initiative for their events.
EVENTED_TABLES: frozenset[str] = (
    (INITIATIVE_SCOPED_TABLES - NON_EVENTED_TABLES)
    | frozenset(GUILD_LEVEL_EVENTED)
    | GUILD_WIDE_EVENTED
)

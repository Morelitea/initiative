"""Which guild tables an app can reach, and under which scope.

One registry, ``APP_TABLE_ACCESS``, table -> :class:`AppTableAccess`. What an
app's routed role is granted on a table, and the scope that table's policies
ask of an app, are both read from it. A guild table with no entry is out of
every app's reach.

Most of it is derived:

- a table a tool governs (``initiative_rls.governing_path``) takes that tool's
  scope, so ``tasks`` answers to ``projects`` and ``calendar_events`` to
  ``calendars``;
- the surfaces that span tools, and the read-only structure an app needs to
  address an initiative, are named here.

What is left out on purpose is listed in :data:`_NOT_APP_SURFACE`: rows that
are one person's own state, and machinery a scheduler or an operator runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.core.app_scopes import AppScopeResource, READ_ONLY_RESOURCES, tool_resource
from app.db.initiative_rls import INITIATIVE_PATHS, governing_path


class AppTableKind(str, Enum):
    #: Content an app reads, and writes when its scope allows.
    scoped = "scoped"
    #: Written as a consequence of a scoped write (a trigger, or a service
    #: step), never addressed by an app.
    side_effect = "side_effect"
    #: Event subscriptions: reachable with the read scope of each event's tool,
    #: which is a property of the row rather than of the table.
    subscriptions = "subscriptions"


@dataclass(frozen=True)
class AppTableAccess:
    kind: AppTableKind
    resource: AppScopeResource | None = None

    @property
    def writable(self) -> bool:
        """Whether an app may ever write this table directly."""
        if self.kind is AppTableKind.scoped:
            return self.resource not in READ_ONLY_RESOURCES
        return self.kind is AppTableKind.subscriptions


def _scoped(resource: str) -> AppTableAccess:
    return AppTableAccess(AppTableKind.scoped, AppScopeResource(resource))


#: Tables a tool governs that are not an app's to touch.
_NOT_APP_SURFACE: frozenset[str] = frozenset(
    {
        # One person's own state: their ordering, favourites, saved filters,
        # read markers and ballots.
        "project_orders",
        "project_favorites",
        "project_filter_presets",
        "post_reads",
        "post_poll_votes",
        # Run by the reminder scheduler.
        "event_reminder_dispatches",
        # Operations intake, which the community's own staff runs.
        "intake_bindings",
        "intake_cases",
    }
)

#: Written as a consequence of a scoped write.
_SIDE_EFFECTS: frozenset[str] = frozenset(
    {
        # The change log, written by the capture trigger.
        "event_outbox",
        # The search index, written by the refresh trigger.
        "search_entries",
        # Queued when a task is assigned, cleared when it is unassigned.
        "task_assignment_digest_items",
    }
)

#: The tables no tool governs that an app reaches, by name.
_NAMED: dict[str, AppTableAccess] = {
    "comments": _scoped("comments"),
    "relationships": _scoped("relationships"),
    "tags": _scoped("tags"),
    "initiatives": _scoped("initiatives"),
    "initiative_roles": _scoped("initiatives"),
    "property_definitions": _scoped("initiatives"),
    "initiative_members": _scoped("members"),
    "webhook_subscriptions": AppTableAccess(AppTableKind.subscriptions),
    **{table: AppTableAccess(AppTableKind.side_effect) for table in _SIDE_EFFECTS},
}


def _derive() -> dict[str, AppTableAccess]:
    access: dict[str, AppTableAccess] = {}
    for table in INITIATIVE_PATHS:
        if table in _NOT_APP_SURFACE or table in _NAMED:
            continue
        governed = governing_path(table)
        if governed is not None:
            access[table] = AppTableAccess(
                AppTableKind.scoped, tool_resource(governed[0])
            )
    access.update(_NAMED)
    return access


APP_TABLE_ACCESS: dict[str, AppTableAccess] = _derive()

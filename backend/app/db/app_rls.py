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
        # One person's own state: their ordering, favourites, read markers and
        # ballots. (A project's filter presets are the project's own, seeded
        # when it or its first task is created, so they follow ``projects``.)
        "project_orders",
        "project_favorites",
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

#: Tables no app reaches, whose policies refuse an installed app outright
#: beside the grant it does not hold: a reaction and the line queued about it
#: are one person's gesture, and a recent view one person's history.
APP_REFUSED_TABLES: frozenset[str] = frozenset(
    {"reactions", "reaction_digest_items", "recent_views"}
)


#: The trigger function every tool table carries (``tr_<table>_install_owns``,
#: attached with the tool's value as its argument): when an installed app's
#: request creates a tool's resource, it writes the one owner row. That row
#: names the install, or, for a member token, the member it acts for. A
#: request a person makes names no install, and the function writes nothing.
#: Shared, in ``public``; the row lands in the schema the trigger fired in.
#: Restated in full by the migration that sets it (20260924_0385).
INSTALL_OWNS_WHAT_IT_CREATES = """
CREATE OR REPLACE FUNCTION public.fn_install_owns_what_it_creates() RETURNS trigger
    LANGUAGE plpgsql AS $owns$
DECLARE
    v_install integer := NULLIF(
        current_setting('app.current_install_id', true), ''
    )::integer;
    v_member integer := NULLIF(
        current_setting('app.current_user_id', true), ''
    )::integer;
BEGIN
    IF v_install IS NULL THEN
        RETURN NULL;
    END IF;
    IF v_member IS NULL THEN
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, app_install_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_install;
    ELSE
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, user_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_member;
    END IF;
    RETURN NULL;
END;
$owns$;
"""

"""Render the per-guild DDL from its two live sources — no committed artifacts.

A guild schema has two layers, each with a single source of truth:

* **Structure** (tables, indexes, constraints, guild_id triggers) — the
  Alembic-maintained ``guild_template`` schema. :func:`render_guild_schema_ddl`
  reflects it live (columns/PK/UNIQUE via SQLAlchemy; CHECK/FK/index/trigger
  text via ``pg_get_*def`` — PG's authoritative text, preserving opclasses and
  partial-index predicates reflection loses) and emits idempotent,
  schema-relative DDL (run with ``search_path = <guild_schema>, public``).
  Cross-schema FKs (to public.users/guilds/…) are omitted — those refs stay
  soft; the schema is the tenant boundary.
* **Initiative RLS policies** — the ``INITIATIVE_PATHS`` registry.
  :func:`render_guild_rls_ddl` stamps the uniform policy boilerplate around
  each table's path.

``schema_provisioning.get_provisioning_bundle()`` renders both once per
process and derives the skip-stamp from them, so NEW guilds always match the
live template + registry by construction, and any change to either triggers
the one-time re-provisioning sweep. Guild-schema CHANGES are ordinary Alembic
migrations (``scripts/gen_guild_migration.py``).
"""

from __future__ import annotations

import re

from sqlalchemy import MetaData, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.schema import CheckConstraint, CreateTable

from app.core.app_scopes import AppScopeResource, tool_resource
from app.core.tools import Tool
from app.db.app_rls import (
    APP_REFUSED_TABLES,
    APP_TABLE_ACCESS,
    SEARCH_ENTRY_READ_SCOPE,
    AppTableKind,
)
from app.db.initiative_rls import (
    ANSWERED,
    INITIATIVE_PATHS,
    INITIATIVE_SCOPED_TABLES,
    dac_asks_at_write,
    governing_path,
    render_entity_access_fn,
    InitiativePath,
)
from app.db.authorization import (
    GUILD_ADMIN,
    GUILD_SEAT,
    IN_POLICY,
    RETIRED_GUILD_FUNCTION_SIGNATURES,
    SETTINGS_ADMIN,
    STANDING,
    STANDING_IS_THIS_GUILD,
    SYSTEM_SESSION,
    app_refused,
    app_scope,
    render_guild_authorization_functions,
    sql_values,
    standing_ids,
)
from app.db.frozen import (
    FROZEN_TABLES,
    freeze_leg,
    frozen_write_triggers,
    frozen_guard_trigger,
    render_frozen_ancestor_fn,
    render_frozen_guard_fn,
    render_frozen_parent_guard_fn,
    render_resource_frozen_fn,
    render_resource_frozen_for_grant_fn,
)
from app.db.soft_delete_filter import SOFT_DELETE_TABLES
from app.db.tenancy import (
    GUILD_SCOPED_TABLES,
    LEDGER_TABLES,
    MANAGED_TABLES,
    OWN_ROW_TABLES,
    SEAT_TABLES,
)
from app.models.tenant.initiative import InitiativeJoinPolicy
from app.models.tenant.resource_grant import ResourceAccessLevel


# Hard delete = purge, and only a guild admin may purge (the interactive endpoint
# 403s otherwise; the background auto-purge worker runs as app_admin/BYPASSRLS, so
# RLS — including this RESTRICTIVE policy — does not apply to it). We back that with
# a DB-layer RESTRICTIVE FOR DELETE guard so a stray non-admin DELETE is refused by
# Postgres, not just by app code. The source of truth for "which tables are
# soft-deletable" is SOFT_DELETE_TABLES (derived from the SoftDeleteMixin
# subclasses). The guard goes on EVERY soft-delete table, split by how RLS is
# already set up on the table:
#   - initiative-scoped soft-delete tables already ENABLE RLS (for the membership
#     gate), so the RESTRICTIVE policy is appended to their existing block.
#   - the guild-level soft-delete tables (initiatives, tags) are RLS-free; they get
#     a dedicated guard block that ENABLEs RLS solely to host the purge guard (see
#     _guild_level_guard_block — the access policy there is a deliberate allow-all,
#     NOT a membership gate; initiative is the gate, guilds gate at the schema).
_PURGE_GUARD_TABLES: frozenset[str] = (
    frozenset(SOFT_DELETE_TABLES) & INITIATIVE_SCOPED_TABLES
)
_GUILD_LEVEL_PURGE_TABLES: frozenset[str] = (
    frozenset(SOFT_DELETE_TABLES) - INITIATIVE_SCOPED_TABLES
)

# Admit only a community's administrator, or trusted system maintenance.
# Matches the same two legs of initiative_access exactly: the admin fact the
# standing statement computed from the membership row, and the connection's own
# login for a sweep.
_PURGE_GUARD_PREDICATE = f"({SYSTEM_SESSION} OR {GUILD_ADMIN})"

# Who may READ a row that is in the trash. Deleting something takes it out of
# sight, so the ordinary answer is nobody: the trash is a place to recover from,
# not a second copy of the guild's content that outlives the decision to remove
# it. Two legs open it — the guild admin, who manages the trash for everyone,
# and whoever deleted the row, who gets their own deletions back from /me/trash.
# RESTRICTIVE, so it AND-combines with the membership gate rather than widening
# it: a trashed row is still only visible to someone who could see it alive.
_TRASH_READ_PREDICATE = (
    "deleted_at IS NULL"
    f" OR {_PURGE_GUARD_PREDICATE}"
    " OR deleted_by = NULLIF(current_setting('app.current_user_id'::text, true),"
    " ''::text)::integer"
)


def _trash_read_policy(table: str) -> list[str]:
    """Hide a trashed row from everyone but the admin and whoever deleted it."""
    return [
        f"DROP POLICY IF EXISTS trashed_read ON {table};",
        f"CREATE POLICY trashed_read ON {table} AS RESTRICTIVE FOR SELECT",
        f"  USING ({_TRASH_READ_PREDICATE});",
    ]


# Reader-written SQL reports on live content only.
#
# The trash is a place to recover from, and recovering from it is what the
# trash screen is for. A dashboard is a different question: what it counts
# should be the same for everybody reading it, and a deleted row is not part of
# that for anyone. RESTRICTIVE and keyed on the query flag, so it applies to the
# statements a reader writes and to nothing else.
_QUERY_TRASH_PREDICATE = (
    "deleted_at IS NULL"
    " OR current_setting('app.query'::text, true) IS DISTINCT FROM 'true'::text"
)


def _query_trash_policy(table: str) -> list[str]:
    """Keep a trashed row out of what a reader's own statement returns."""
    return [
        f"DROP POLICY IF EXISTS query_excludes_trash ON {table};",
        f"CREATE POLICY query_excludes_trash ON {table} AS RESTRICTIVE FOR SELECT",
        f"  USING ({_QUERY_TRASH_PREDICATE});",
    ]


_HEADER = """\
-- RENDERED AT RUNTIME from app/db/initiative_rls.py (INITIATIVE_PATHS).
-- Initiative-member-level RLS for the per-guild CONTENT tables. Schema-relative
-- (run with search_path = <guild_schema>, public). Idempotent.
--
-- The access RULE lives in ONE place, initiative_access (initiative member
-- OR guild admin OR PAM, read from the request GUCs); each policy below is just the
-- join that resolves a table's initiative id and defers to it. The per-table paths
-- are the single source of truth in app/db/initiative_rls.py (INITIATIVE_PATHS).
--
-- SCOPE: only INITIATIVE-scoped CONTENT tables are here, exactly
-- app.db.initiative_rls.INITIATIVE_SCOPED_TABLES. The STRUCTURAL initiative tables
-- (initiatives, initiative_members, initiative_roles, initiative_role_permissions)
-- are read within the schema boundary (co-members read their roster, and the
-- standing statement reads the membership table before any standing exists) and
-- written by their managers — the managed_* policies further down, from
-- app.db.tenancy.MANAGED_TABLES. Guild-level / own-row tables
-- (app.db.tenancy.GUILD_LEVEL_TABLES) are guild-scoped by the schema boundary.
-- The app layer still does finer filtering (e.g. the initiatives list shows
-- member-only for non-admins).
--
-- To add a new initiative-scoped table: add a path to INITIATIVE_PATHS in
-- app/db/initiative_rls.py — provisioning and the boot back-fill apply the
-- rendered policies automatically (the provisioning stamp includes this
-- rendering, so a registry change triggers the one-time sweep).
--
-- One table deviates on INSERT: the change log (event_outbox) is written by the
-- capture trigger and by nothing else, so its insert policy admits the trigger
-- rather than re-deciding the writer's access — see _TRIGGER_WRITTEN_INSERT.
--
-- Soft-delete tables additionally carry a RESTRICTIVE FOR DELETE policy
-- (soft_delete_admin_purge): hard delete = purge, and only a community's
-- administrator may. It is RESTRICTIVE, so it AND-combines with the PERMISSIVE
-- delete policy above — a write-member clears the latter but not this one. The
-- purge sweep is admitted by the connection's own login. Source of truth for the table set is
-- app.db.soft_delete_filter.SOFT_DELETE_TABLES (the SoftDeleteMixin subclasses).
-- The guild-level soft-delete tables (initiatives, tags) are RLS-free, so they get
-- the guard via the dedicated section at the bottom of this file.
--
-- Write commands additionally carry the LIFECYCLE freeze (app.db.frozen):
-- archived and trashed content is read-only, and so is everything under it.
-- INSERT carries a RESTRICTIVE policy deferring to one function,
-- resource_frozen(kind, id, trashed_ok), which walks the same join chains
-- the sharing legs are rendered from. UPDATE and DELETE are triggers, at the
-- bottom of this file — telling an edit from an unarchive needs the old row and
-- the new row together, which a policy never has. SELECT carries neither.
"""

# Header for the guild-level guard section (initiatives, tags).
_GUILD_LEVEL_SECTION = """\
-- ===========================================================================
-- Guild-level soft-delete tables: admin-only purge guard ONLY.
--
-- These tables are NOT initiative-membership-gated: initiative is the gate (its
-- content tables point AT it via initiative_access), and the initiative anchor
-- tables can't gate themselves; guilds gate at the SCHEMA level (SET ROLE), which
-- already isolates these rows. RLS is enabled here SOLELY to host the RESTRICTIVE
-- admin-only-purge guard, so the access policy (guild_level_open) is a deliberate
-- allow-all — it adds no row gate, it just lets the RESTRICTIVE delete policy bind.
-- ==========================================================================="""

# Header for the own-row section (export_jobs, …).
_OWN_ROW_SECTION = """\
-- ===========================================================================
-- Own-row guild-level tables (app.db.tenancy.OWN_ROW_TABLES): rows belong to
-- ONE user. Unlike guild_level_open, this IS a row gate — a member must not
-- see another member's rows (an export_jobs row leaks the selector and gates
-- the artifact download). Owner OR the community's administrator OR trusted
-- system maintenance; the last two legs match initiative_access and the purge
-- guard exactly. A settings rung reads them, and writes them only beside a
-- read_write grant. A read-only PAM grantee is routed to guild_<id>_ro with
-- none of them set: no rows, by design.
-- ==========================================================================="""

# Own-row predicate: the owner column is compared against the request GUC.
# NULLIF-guard the cast — an unset context leaves the value empty, and a bare
# ''::int raises and faults the whole query for every PERMISSIVE policy on the
# table (same rule as the public shared-table policies; see CLAUDE.md §5).
_MANAGED_SECTION = """\
-- ===========================================================================
-- The structural initiative tables (app.db.tenancy.MANAGED_TABLES): read within
-- the schema, written by the initiative's managers. Reading stays open — a
-- roster is read by its co-members, and the standing statement reads
-- initiative_members before any standing exists. Writing asks the standing:
-- a manager of that initiative (app.manager_initiatives, a value the seam
-- computed, so the membership table is not gated by a read of itself), the
-- community's admin, a settings rung beside a read_write grant, or the system
-- engine. A member's own row into an initiative whose join policy is open is
-- the one further way in. initiatives keeps its purge guard and trash reads.
-- ==========================================================================="""

_PAM_WRITE = "current_setting('app.pam_write'::text, true) = 'true'::text"


def _managed_write_predicate(initiative_expr: str) -> str:
    """Who changes an initiative's structure: its managers by the standing, the
    community's admin, a settings rung writing beside a read_write grant, or
    the system engine."""
    return (
        f"({SYSTEM_SESSION} OR {GUILD_ADMIN} OR ({SETTINGS_ADMIN} AND {_PAM_WRITE})"
        f" OR ({STANDING_IS_THIS_GUILD}"
        f" AND ({initiative_expr}) = ANY ({standing_ids('app.manager_initiatives')})))"
    )


#: A member's own row into an initiative that is open to join — the self-join
#: route. Names the community's members (``app.current_guild_id`` is set for a
#: membership routing and for nothing else) and the initiative's policy.
_SELF_JOIN_LEG = (
    "(user_id = NULLIF(current_setting('app.current_user_id'::text, true), '')::int"
    " AND NULLIF(current_setting('app.current_guild_id'::text, true), '') IS NOT NULL"
    " AND EXISTS (SELECT 1 FROM initiatives i WHERE i.id = initiative_id"
    f" AND i.join_policy = '{InitiativeJoinPolicy.open.value}' AND i.deleted_at IS NULL))"
)


def _managed_block(table: str, initiative_expr: str) -> str:
    """RLS for a structural initiative table: reading open within the schema,
    writing by the managed-write predicate. ``initiatives`` keeps its admin-only
    purge guard and trash-read policies beside these."""
    pred = _managed_write_predicate(initiative_expr)
    insert_pred = (
        f"({pred} OR {_SELF_JOIN_LEG})" if table == "initiative_members" else pred
    )
    lines = [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
        # The shape before this one: an allow-all for every command.
        f"DROP POLICY IF EXISTS guild_level_open ON {table};",
        f"DROP POLICY IF EXISTS managed_select ON {table};",
        f"CREATE POLICY managed_select ON {table} AS PERMISSIVE FOR SELECT",
        "  USING (true);",
        f"DROP POLICY IF EXISTS managed_insert ON {table};",
        f"CREATE POLICY managed_insert ON {table} AS PERMISSIVE FOR INSERT",
        f"  WITH CHECK ({insert_pred});",
        f"DROP POLICY IF EXISTS managed_update ON {table};",
        f"CREATE POLICY managed_update ON {table} AS PERMISSIVE FOR UPDATE",
        f"  USING ({pred}) WITH CHECK ({pred});",
        f"DROP POLICY IF EXISTS managed_delete ON {table};",
        f"CREATE POLICY managed_delete ON {table} AS PERMISSIVE FOR DELETE",
        f"  USING ({pred});",
    ]
    if table in _GUILD_LEVEL_PURGE_TABLES:
        lines += [
            f"DROP POLICY IF EXISTS soft_delete_admin_purge ON {table};",
            f"CREATE POLICY soft_delete_admin_purge ON {table} AS RESTRICTIVE FOR DELETE",
            f"  USING ({_PURGE_GUARD_PREDICATE});",
            *_trash_read_policy(table),
            *_query_trash_policy(table),
        ]
    return "\n".join(lines)


_OWN_ROW_OWNER = (
    "{col} = NULLIF(current_setting('app.current_user_id'::text, true), '')::int"
)

#: Who reads an own-row table's rows: the owner, the community's admin, a
#: settings rung, or the system engine.
_OWN_ROW_READ_PREDICATE = (
    f"({_OWN_ROW_OWNER} OR {SYSTEM_SESSION} OR {GUILD_ADMIN} OR {SETTINGS_ADMIN})"
)

#: Who writes them: the same, with a settings rung writing only beside a
#: read_write grant.
_OWN_ROW_WRITE_PREDICATE = (
    f"({_OWN_ROW_OWNER} OR {SYSTEM_SESSION} OR {GUILD_ADMIN}"
    f" OR ({SETTINGS_ADMIN} AND {_PAM_WRITE}))"
)

_COMMANDS = (
    ("select", "SELECT", "USING", False),
    ("insert", "INSERT", "WITH CHECK", True),
    ("update", "UPDATE", "USING-CHECK", True),
    ("delete", "DELETE", "USING", True),
)

# Tables written only by a trigger, never by hand: their INSERT policy admits the
# capture trigger instead of re-deciding the writer's access.
#
# ``event_outbox`` is the one. A row lands there as a consequence of a content
# write that already cleared its own table's gate, so the log RECORDS what
# happened rather than deciding it a second time — including a change that ends
# the writer's own access, which it must still be able to record. Who may READ
# the log is unchanged: the initiative gate, via the other three policies.
_TRIGGER_WRITTEN_INSERT: dict[str, str] = {
    "event_outbox": "pg_trigger_depth() > 0",
    # The search index is derived: rows arrive from the refresh trigger as a
    # consequence of a content write that already cleared its own table's gate.
    # The reindex sweep routes as the guild admin, which is the second leg.
    "search_entries": f"pg_trigger_depth() > 0 OR {SYSTEM_SESSION} OR {GUILD_ADMIN}",
}


def _table_block(table: str, path: InitiativePath) -> str:
    lines = [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
    ]
    for suffix, command, clause, write in _COMMANDS:
        pred = path.predicate(table, write)
        if path.dac is not None:
            # What the command asks of sharing is per table: changing content
            # takes write on the resource, where responding to it (a comment,
            # a reaction) and keeping a reader's own record of it do not.
            sharing = path.dac.predicate(
                table, command, dac_asks_at_write(table, command)
            )
            # A resource has no sharing before it exists, so the table that IS
            # the resource carries no leg on INSERT — creating one answers to
            # the initiative-role gate instead. A child table keeps it: adding a
            # task means reaching the project it goes in.
            if sharing is not None and sharing != ANSWERED:
                pred = f"{pred} AND {sharing}"
        if command == "INSERT" and table in _TRIGGER_WRITTEN_INSERT:
            pred = _TRIGGER_WRITTEN_INSERT[table]
        name = f"initiative_member_{suffix}"
        lines.append(f"DROP POLICY IF EXISTS {name} ON {table};")
        lines.append(f"CREATE POLICY {name} ON {table} AS PERMISSIVE FOR {command}")
        if clause == "USING-CHECK":
            lines.append(f"  USING ({pred}) WITH CHECK ({pred});")
        elif clause == "WITH CHECK":
            lines.append(f"  WITH CHECK ({pred});")
        else:  # USING
            lines.append(f"  USING ({pred});")
    lines.extend(_freeze_policies(table))
    if table in SOFT_DELETE_TABLES:
        lines.extend(_trash_read_policy(table))
        lines.extend(_query_trash_policy(table))
    if table in _PURGE_GUARD_TABLES:
        # Admin-only hard delete (purge), AND-combined with the PERMISSIVE delete
        # policy above. RESTRICTIVE, so a write-member who clears the permissive
        # leg is still refused unless they are the routed guild admin.
        lines.append("DROP POLICY IF EXISTS soft_delete_admin_purge ON " + table + ";")
        lines.append(
            f"CREATE POLICY soft_delete_admin_purge ON {table} AS RESTRICTIVE FOR DELETE"
        )
        lines.append(f"  USING ({_PURGE_GUARD_PREDICATE});")
    return "\n".join(lines)


def _freeze_policies(table: str) -> list[str]:
    """The lifecycle freeze for one table on INSERT: a RESTRICTIVE policy
    refusing a row whose ancestors are archived or trashed.

    RESTRICTIVE, so it AND-combines with the permissive access policies.
    ``WITH CHECK``, so a failure is raised rather than filtered out of the
    statement. UPDATE and DELETE are triggers (see ``app.db.frozen``) — they
    need the old row and the new row together, which a policy never has —
    and SELECT takes neither.
    """
    lines: list[str] = []
    for command in ("INSERT",):
        leg = freeze_leg(table, command)
        name = f"frozen_ancestor_{command.lower()}"
        lines.append(f"DROP POLICY IF EXISTS {name} ON {table};")
        if leg is None:
            continue
        lines.append(f"CREATE POLICY {name} ON {table} AS RESTRICTIVE FOR {command}")
        lines.append(f"  WITH CHECK (NOT {leg});")
    # Earlier shapes carried these; drop them wherever one was left.
    lines.append(f"DROP POLICY IF EXISTS frozen_ancestor_update ON {table};")
    lines.append(f"DROP POLICY IF EXISTS frozen_ancestor_delete ON {table};")
    return lines


def _own_row_block(table: str, owner_col: str) -> str:
    """RLS for an own-row guild-level table: per-command policies admitting the
    row's owner or the routed guild admin. INSERT/UPDATE WITH CHECK use the
    write predicate, so a member can't author rows owned by someone else
    either."""
    read = _OWN_ROW_READ_PREDICATE.format(col=owner_col)
    write = _OWN_ROW_WRITE_PREDICATE.format(col=owner_col)
    return "\n".join(
        [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
            *_policies(table, "own_row", read, write),
        ]
    )


_SEAT_SECTION = """\
-- ===========================================================================
-- Seat-held guild-level tables (app.db.tenancy.SEAT_TABLES): configuration the
-- community's seat holds. Read within the schema — a member's AI request reads
-- the connection it runs on, and opening an app reads where it is placed.
-- Written by the seat (app.guild_seat, from the standing), which a lent seat
-- holds beside a read_write content grant, or by the system engine. A table a
-- trigger also fills admits that trigger on INSERT.
-- ==========================================================================="""

_SEAT_WRITE_PREDICATE = (
    f"({SYSTEM_SESSION} OR ({GUILD_SEAT} AND ({GUILD_ADMIN} OR {_PAM_WRITE})))"
)


# Seat tables a trigger also writes: table -> the leg OR'd into the INSERT
# policy beside the seat's. ``app_placements`` gains a row for each install that
# follows new initiatives when an initiative's built-in moderator role is
# created, by whoever created the initiative.
_SEAT_TRIGGER_WRITTEN_INSERT: dict[str, str] = {
    "app_placements": "pg_trigger_depth() > 0",
}


def _policies(
    table: str,
    prefix: str,
    read: str,
    write: str,
    *,
    insert: str | None = None,
) -> list[str]:
    """One PERMISSIVE policy per command: ``read`` for SELECT, ``write`` for
    the other three — or ``insert`` for INSERT, when given."""
    lines: list[str] = []
    for suffix, command, clause, is_write in _COMMANDS:
        pred = write if is_write else read
        if command == "INSERT" and insert is not None:
            pred = insert
        name = f"{prefix}_{suffix}"
        lines.append(f"DROP POLICY IF EXISTS {name} ON {table};")
        lines.append(f"CREATE POLICY {name} ON {table} AS PERMISSIVE FOR {command}")
        if clause == "USING-CHECK":
            lines.append(f"  USING ({pred}) WITH CHECK ({pred});")
        elif clause == "WITH CHECK":
            lines.append(f"  WITH CHECK ({pred});")
        else:  # USING
            lines.append(f"  USING ({pred});")
    return lines


def _seat_block(table: str) -> str:
    """RLS for a seat-held guild-level table: reading open within the schema,
    writing by the seat or the system engine, and inserting by a trigger too
    where ``_SEAT_TRIGGER_WRITTEN_INSERT`` names one."""
    trigger = _SEAT_TRIGGER_WRITTEN_INSERT.get(table)
    insert = f"({trigger} OR {_SEAT_WRITE_PREDICATE})" if trigger else None
    return "\n".join(
        [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
            *_policies(table, "seat", "true", _SEAT_WRITE_PREDICATE, insert=insert),
        ]
    )


_LEDGER_SECTION = """\
-- ===========================================================================
-- Ledger guild-level tables (app.db.tenancy.LEDGER_TABLES): bookkeeping a
-- system job keeps about a parent row. Read through the parent — the sub-select
-- runs the parent's own SELECT policy, so a row is visible to whoever sees its
-- parent. Written by the system engine alone.
-- ==========================================================================="""


def _ledger_block(table: str, parent: str, fk: str) -> str:
    """RLS for a ledger table: read through its parent, written by the system
    engine."""
    read = (
        f"({SYSTEM_SESSION} OR EXISTS (SELECT 1 FROM {parent}"
        f" WHERE {parent}.id = {table}.{fk}))"
    )
    return "\n".join(
        [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
            *_policies(table, "ledger", read, SYSTEM_SESSION),
        ]
    )


_APP_SECTION = """\
-- ===========================================================================
-- An installed app's scopes, on the tables no tool's gate answers for
-- (app.db.app_rls.APP_TABLE_ACCESS). RESTRICTIVE, so each AND-combines with
-- the table's own policies, and each opens with the install id: a request a
-- person makes carries none and passes in one comparison, once per statement.
--
-- One policy per command, because reading and writing ask different scopes:
-- SELECT asks the resource's read scope, INSERT/UPDATE/DELETE its write scope
-- (nothing, for a resource no scope writes). An install reads the initiatives
-- it is placed in whatever its scopes, since its own standing and the
-- lifecycle checks on its writes read them. An install sees and changes its
-- own event subscriptions and no one else's. The change log and the search
-- index are written by triggers, and an install writes them only there; it
-- reads a search entry with the read scope of the entry's kind and of the tool
-- governing it, and a narrowed token reads no entry of a tool that belongs to
-- no initiative, as on the tables the entries describe. The
-- grants an install's request writes are the owner row naming it (the
-- member, for a member token), written by the trigger on the resource it
-- creates, and, with sharing:write and the tool's write scope, the read and
-- write shares of a resource it holds write on. Reactions and recent views
-- are refused. A member token also reads
-- the member's own roster rows and the roles they name, and its own install's
-- consent rows, which its standing reads; it writes no consent.
-- ==========================================================================="""

_APP_POLICY_PREFIX = "app_scope"

_IID = IN_POLICY.install_id


def _app_placed_initiatives() -> str:
    """The initiatives the install is placed in, narrowed like its token."""
    scope = IN_POLICY.scope
    return (
        "(SELECT p.initiative_id FROM app_placements p"
        f" WHERE p.install_id = {_IID}"
        f" AND ({scope} IS NULL OR p.initiative_id = {scope}))"
    )


#: The member a member token acts for, read back from the routing. Empty for
#: an installation token, which then matches no row.
_APP_MEMBER = "NULLIF(current_setting('app.current_user_id'::text, true), '')::int"

#: The owner row on a tool's resource an installed app creates, written by
#: ``public.fn_install_owns_what_it_creates`` and never by the request itself.
#: It names the install, or, for a member token, the member it acts for.
_APP_CREATED_OWNER_ROW = (
    "(pg_trigger_depth() > 0"
    f" AND level = '{ResourceAccessLevel.owner.value}'"
    " AND role_id IS NULL"
    " AND NOT all_initiative_members AND dashboard_id IS NULL"
    f" AND ((app_install_id = {_IID} AND user_id IS NULL AND {_APP_MEMBER} IS NULL)"
    f" OR (user_id = {_APP_MEMBER} AND app_install_id IS NULL)))"
)

#: The write scope of the tool a grant row is about: the row names its tool
#: by value, and the scope by the tool's plural.
_GRANT_TOOL_SCOPE = (
    "(CASE resource_grants.resource_type "
    + " ".join(
        f"WHEN '{tool.value}' THEN '{tool_resource(tool).value}'" for tool in Tool
    )
    + " END)"
)

#: The rungs a share gives; owner is held, never shared.
_SHARED_LEVELS = (ResourceAccessLevel.read, ResourceAccessLevel.write)

#: A sharing row an installed app with ``sharing:write`` changes, as a person
#: with its rung changes one: it holds the scope and the tool's write scope,
#: and the rung that lets a person share, which is write on the resource
#: (``resource_access`` asked at write, through the grantee leg). The row
#: shares with a person, a role or all initiative members at read or write;
#: owner rows, a published view's rows and app grants are not a share.
_APP_SHARE_ROW = (
    f"('{AppScopeResource.sharing.value}' = ANY ({IN_POLICY.field('install_write')})"
    f" AND COALESCE({_GRANT_TOOL_SCOPE}"
    f" = ANY ({IN_POLICY.field('install_write')}), false)"
    f" AND level IN ({sql_values(level.value for level in _SHARED_LEVELS)})"
    " AND app_install_id IS NULL AND dashboard_id IS NULL"
    " AND resource_access(resource_grants.resource_type, resource_grants.resource_id,"
    f" {_APP_MEMBER}, resource_grants.initiative_id, true, {STANDING}))"
)

#: What an installed app's request writes on ``resource_grants``: the owner
#: row on what it creates, and, with ``sharing:write``, the sharing rows of a
#: resource it may share. A share is rewritten by deleting and inserting rows,
#: so an install updates none.
_APP_GRANT_INSERT = f"({_IID} IS NULL OR {_APP_CREATED_OWNER_ROW} OR {_APP_SHARE_ROW})"
_APP_GRANT_DELETE = f"({_IID} IS NULL OR {_APP_SHARE_ROW})"

#: What a member token's standing reads of the member's own place in their
#: initiatives, whatever its scopes: their roster rows, and the roles those
#: rows name. Read beside the resource's scope, never instead of the row's own
#: policies.
_APP_MEMBER_OWN_READ: dict[str, str] = {
    "initiative_members": f"initiative_members.user_id = {_APP_MEMBER}",
    "initiative_roles": (
        "initiative_roles.id IN (SELECT im.role_id FROM initiative_members im"
        f" WHERE im.user_id = {_APP_MEMBER})"
    ),
}

#: A member's answers to the apps asking to act as them. A member token's
#: standing reads the one for its own install and purpose; nothing an app
#: sends reads or writes the table otherwise.
_APP_CONSENT_READ = f"({_IID} IS NULL OR app_member_consents.install_id = {_IID})"


def _app_search_read() -> str:
    """What an installed app asks to read one search entry.

    The read scope of the entry's kind (``SEARCH_ENTRY_READ_SCOPE``), and of
    the tool governing it where it names one, which is what the table the
    entry describes asks. A token narrowed to one initiative reads no entry of
    a tool's content that belongs to no initiative; the guild's tags stay
    readable to it, as the tags table is. The table's own policies still ask
    placement, the tool's switch, the role and sharing, as they do of a person.
    """
    held = IN_POLICY.field("install_read")
    kinds = " ".join(
        f"WHEN '{kind.value}' THEN '{resource.value}'"
        for kind, resource in sorted(
            SEARCH_ENTRY_READ_SCOPE.items(), key=lambda item: item[0].value
        )
    )
    tools = " ".join(
        f"WHEN '{tool.value}' THEN '{tool_resource(tool).value}'" for tool in Tool
    )
    return (
        f"(COALESCE((CASE search_entries.entity_type {kinds} END) = ANY ({held}), false)"
        " AND (search_entries.dac_tool IS NULL"
        f" OR COALESCE((CASE search_entries.dac_tool {tools} END) = ANY ({held}), false))"
        f" AND ({IN_POLICY.scope} IS NULL OR search_entries.dac_tool IS NULL"
        " OR search_entries.initiative_id IS NOT NULL))"
    )


def _app_predicates(table: str) -> dict[str, str]:
    """What each command asks of an installed app on ``table``, beside what
    the table's own policies ask. Empty where a tool's gate already asks it."""
    refused = app_refused(IN_POLICY)
    if table == "resource_grants":
        return {
            "INSERT": _APP_GRANT_INSERT,
            "UPDATE": refused,
            "DELETE": _APP_GRANT_DELETE,
        }
    if table == "app_member_consents":
        return {
            "SELECT": _APP_CONSENT_READ,
            "INSERT": refused,
            "UPDATE": refused,
            "DELETE": refused,
        }
    if table in APP_REFUSED_TABLES:
        return dict.fromkeys(("SELECT", "INSERT", "UPDATE", "DELETE"), refused)
    access = APP_TABLE_ACCESS[table]
    if access.kind is AppTableKind.subscriptions:
        own = f"({_IID} IS NULL OR app_install_id = {_IID})"
        return dict.fromkeys(("SELECT", "INSERT", "UPDATE", "DELETE"), own)
    if access.kind is AppTableKind.side_effect:
        if table not in _TRIGGER_WRITTEN_INSERT:
            return {}
        by_trigger = f"({_IID} IS NULL OR pg_trigger_depth() > 0)"
        predicates = dict.fromkeys(("SELECT", "INSERT", "UPDATE", "DELETE"), by_trigger)
        if table == "search_entries":
            predicates["SELECT"] = (
                f"({_IID} IS NULL OR pg_trigger_depth() > 0 OR {_app_search_read()})"
            )
        return predicates
    if governing_path(table) is not None or access.resource is None:
        return {}
    read = app_scope(access.resource, False, IN_POLICY)
    if table == "initiatives":
        read = f"({read} OR initiatives.id IN {_app_placed_initiatives()})"
    elif table in _APP_MEMBER_OWN_READ:
        read = f"({read} OR {_APP_MEMBER_OWN_READ[table]})"
    write = app_scope(access.resource, True, IN_POLICY) if access.writable else refused
    return {"SELECT": read, "INSERT": write, "UPDATE": write, "DELETE": write}


#: Every table carrying the policies above.
APP_POLICY_TABLES: frozenset[str] = frozenset(
    t
    for t in (
        *APP_TABLE_ACCESS,
        *APP_REFUSED_TABLES,
        "resource_grants",
        "app_member_consents",
    )
    if _app_predicates(t)
)


def _app_block(table: str) -> str:
    """The installed-app policies on one table: RESTRICTIVE, one per command
    it asks something of, and the others dropped wherever an earlier render
    left them."""
    predicates = _app_predicates(table)
    lines: list[str] = []
    for suffix, command, clause, _write in _COMMANDS:
        name = f"{_APP_POLICY_PREFIX}_{suffix}"
        lines.append(f"DROP POLICY IF EXISTS {name} ON {table};")
        pred = predicates.get(command)
        if pred is None:
            continue
        lines.append(f"CREATE POLICY {name} ON {table} AS RESTRICTIVE FOR {command}")
        if clause == "USING-CHECK":
            lines.append(f"  USING ({pred}) WITH CHECK ({pred});")
        elif clause == "WITH CHECK":
            lines.append(f"  WITH CHECK ({pred});")
        else:  # USING
            lines.append(f"  USING ({pred});")
    return "\n".join(lines)


def _guild_level_guard_block(table: str) -> str:
    """RLS for a guild-level soft-delete table (initiatives, tags): a permissive
    allow-all (isolation is the schema boundary, not RLS) plus the RESTRICTIVE
    admin-only-purge guard. NOT an access gate — see _GUILD_LEVEL_SECTION."""
    return "\n".join(
        [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
            f"DROP POLICY IF EXISTS guild_level_open ON {table};",
            f"CREATE POLICY guild_level_open ON {table} AS PERMISSIVE FOR ALL",
            "  USING (true) WITH CHECK (true);",
            f"DROP POLICY IF EXISTS soft_delete_admin_purge ON {table};",
            f"CREATE POLICY soft_delete_admin_purge ON {table} AS RESTRICTIVE FOR DELETE",
            f"  USING ({_PURGE_GUARD_PREDICATE});",
            *_trash_read_policy(table),
            *_query_trash_policy(table),
        ]
    )


_FREEZE_SECTION = """\
-- ===========================================================================
-- The lifecycle freeze: the parts that need the old row and the new row
-- together, which a policy never has.
--
-- tr_<t>_frozen_guard: the row is itself archived or trashed.
-- tr_<t>_frozen_ancestor_update: it carries no stamp of its own and hangs off
--   something that is, or is being moved to hang off something that is.
-- Both permit a change to the lifecycle columns and nothing else, so a frozen
-- row can still be unarchived, restored, or given a new purge date. Their WHEN
-- clauses keep an ordinary write on live content from reaching the function.
--
-- tr_<t>_frozen_trashed_ancestor_update: the same rule about coming out
--   unstamped, for a row that can be trashed but never archived. Unstamped
--   inside an archived thing is the only state such a row has, so it is asked
--   about a trashed ancestry alone — otherwise a restore could never put the
--   comments, queue items, counters, pictures and events back.
--
-- tr_<t>_frozen_delete / tr_<t>_frozen_ancestor_delete: DELETE has no WITH
-- CHECK, so RLS could only refuse it by returning no rows. A row that carries
-- its own stamp is asked about itself; one that does not is asked about its
-- ancestry, with trashed_ok so a purge cascade — the one delete a trashed row
-- is FOR — runs.
-- ==========================================================================="""


def render_retired_functions_ddl() -> str:
    """Drop the functions an earlier render put in the schema and this one no
    longer calls. Last in the script, after every policy that named one has
    been re-created without it.

    Only the copy in the schema being rendered. The script runs with the
    search path set to ``<schema>, public``, so an unqualified name with no
    local copy resolves to ``public`` — and a release that kept the function
    there (0.71 did) has every other guild's policies still bound to that
    copy. Dropping it from one guild's render fails that guild, and then the
    next, so no guild is ever re-rendered. The shared copy is retired once, at
    boot, after every guild has stopped using it
    (``ensure_public_copies_dropped``).
    """
    drops = " ".join(
        f"IF to_regprocedure(format('%I.{name}{args}', current_schema())) "
        "IS NOT NULL THEN "
        f"EXECUTE format('DROP FUNCTION %I.{name}{args}', current_schema()); "
        "END IF;"
        for name, args in RETIRED_GUILD_FUNCTION_SIGNATURES
    )
    return f"DO $retire$ BEGIN {drops} END $retire$;"


def render_guild_rls_ddl() -> str:
    blocks = [_table_block(t, INITIATIVE_PATHS[t]) for t in sorted(INITIATIVE_PATHS)]
    # Shared, and written before the policies that call it. Re-rendered on every
    # provisioning run from the same registry the policies come from, so a kind
    # added to the graph reaches the gate the moment its entry does.
    out = (
        _HEADER
        + "\n"
        + render_guild_authorization_functions()
        + "\n"
        + render_entity_access_fn()
        + "\n"
        + render_resource_frozen_fn()
        + "\n"
        + render_resource_frozen_for_grant_fn()
        + "\n"
        + render_frozen_guard_fn()
        + "\n"
        + render_frozen_parent_guard_fn()
        + "\n"
        + render_frozen_ancestor_fn()
        + "\n"
        + "\n\n".join(blocks)
    )
    guards = [
        _guild_level_guard_block(t)
        for t in sorted(_GUILD_LEVEL_PURGE_TABLES - set(MANAGED_TABLES))
    ]
    if guards:
        out += "\n\n" + _GUILD_LEVEL_SECTION + "\n\n" + "\n\n".join(guards)
    managed = [_managed_block(t, e) for t, e in sorted(MANAGED_TABLES.items())]
    out += "\n\n" + _MANAGED_SECTION + "\n\n" + "\n\n".join(managed)
    own_rows = [_own_row_block(t, c) for t, c in sorted(OWN_ROW_TABLES.items())]
    if own_rows:
        out += "\n\n" + _OWN_ROW_SECTION + "\n\n" + "\n\n".join(own_rows)
    seats = [_seat_block(t) for t in sorted(SEAT_TABLES)]
    out += "\n\n" + _SEAT_SECTION + "\n\n" + "\n\n".join(seats)
    ledgers = [_ledger_block(t, p, fk) for t, (p, fk) in sorted(LEDGER_TABLES.items())]
    out += "\n\n" + _LEDGER_SECTION + "\n\n" + "\n\n".join(ledgers)
    # After every block above, so each table's RLS is on before its app
    # policies join the ones already there.
    apps = [_app_block(t) for t in sorted(APP_POLICY_TABLES)]
    out += "\n\n" + _APP_SECTION + "\n\n" + "\n\n".join(apps)
    guards = [f"{frozen_guard_trigger(t)};" for t in sorted(FROZEN_TABLES)]
    guards += [
        f"{trigger};"
        for table in sorted(INITIATIVE_PATHS)
        for trigger in frozen_write_triggers(table)
    ]
    out += "\n\n" + _FREEZE_SECTION + "\n" + "\n".join(guards)
    return out + "\n\n" + render_retired_functions_ddl() + "\n"


# ============================================================================
# Structure rendering (reflected live from guild_template)
# ============================================================================

_DIALECT = postgresql.dialect()

# The schema the artifact is reflected from: Alembic-maintained guild_template.
# Public because provisioning also re-asserts RLS on it, and the name should
# be stated once.
TEMPLATE_SCHEMA = "guild_template"
_SRC_SCHEMA = TEMPLATE_SCHEMA

# CHECK + FK constraint definitions straight from Postgres (authoritative text).
# The session search_path is set to "<src>, public" before these run, so
# pg_get_constraintdef / pg_get_indexdef / pg_get_triggerdef emit visible names
# UNQUALIFIED — the artifact stays schema-relative.
_CONSTRAINT_SQL = text(
    f"""
    SELECT cl.relname AS tbl, con.conname, con.contype::text AS contype,
           pg_get_constraintdef(con.oid) AS condef,
           tgt.relname AS tgt
    FROM pg_constraint con
    JOIN pg_class cl ON cl.oid = con.conrelid
    JOIN pg_namespace ns ON ns.oid = cl.relnamespace AND ns.nspname = '{_SRC_SCHEMA}'
    LEFT JOIN pg_class tgt ON tgt.oid = con.confrelid
    WHERE con.contype IN ('c', 'f') AND cl.relname = ANY(:t)
    ORDER BY con.contype, cl.relname, con.conname
    """
)


def _build_tables(sync_conn) -> list[str]:
    md = MetaData()
    md.reflect(
        bind=sync_conn, schema=_SRC_SCHEMA, only=lambda n, _m: n in GUILD_SCOPED_TABLES
    )
    rel = MetaData()
    out: list[str] = []
    for name in sorted(GUILD_SCOPED_TABLES):
        t = md.tables[f"{_SRC_SCHEMA}.{name}"].to_metadata(rel, schema=None)
        # CHECK + FK come from pg_get_constraintdef below; drop them here so the
        # CREATE TABLE only carries columns + PRIMARY KEY + UNIQUE.
        for con in list(t.constraints):
            if isinstance(con, CheckConstraint):
                t.constraints.discard(con)
        # ``CreateTable`` renders constraints in the order reflection happened to
        # build them, which the catalog does not promise to repeat. That order
        # reaches the provisioning stamp, and the stamp is what decides whether a
        # guild schema is stale — so an unstable one would re-provision every
        # guild on every boot. Restamp it from each constraint's own name, which
        # is fixed. Only visible on a table carrying more than one.
        for order, con in enumerate(
            sorted(t.constraints, key=lambda c: (type(c).__name__, c.name or ""))
        ):
            con._creation_order = order
        for col in t.columns:
            if hasattr(col.type, "create_type"):
                col.type.create_type = False  # ty: ignore[invalid-assignment]
        out.append(
            str(
                CreateTable(
                    t, if_not_exists=True, include_foreign_key_constraints=[]
                ).compile(dialect=_DIALECT)
            ).strip()
            + ";"
        )
    return out


# Non-constraint indexes from Postgres itself (pg_get_indexdef preserves opclasses
# like jsonb_path_ops, partial-index WHERE, etc. that SQLAlchemy reflection drops).
# The only interpolation below is the _SRC_SCHEMA string literal — no user input
# reaches this module's rendered SQL (scanner: hardcoded_sql_expressions is the
# point; this file IS the DDL renderer).
_INDEX_SQL = text(  # noqa: S608
    f"""
    SELECT tc.relname AS tbl, pg_get_indexdef(i.indexrelid) AS indexdef
    FROM pg_index i
    JOIN pg_class ic ON ic.oid = i.indexrelid
    JOIN pg_class tc ON tc.oid = i.indrelid
    JOIN pg_namespace n ON n.oid = tc.relnamespace AND n.nspname = '{_SRC_SCHEMA}'
    WHERE tc.relname = ANY(:t)
      AND NOT EXISTS (SELECT 1 FROM pg_constraint con WHERE con.conindid = i.indexrelid)
    ORDER BY tc.relname, ic.relname
    """
)


def _schema_relative_index(indexdef: str) -> str:
    # CREATE [UNIQUE] INDEX name ON <src>.tbl USING ...  ->  schema-relative + idempotent
    indexdef = re.sub(
        r"^CREATE (UNIQUE )?INDEX ", r"CREATE \1INDEX IF NOT EXISTS ", indexdef
    )
    indexdef = indexdef.replace(f" ON {_SRC_SCHEMA}.", " ON ")
    return indexdef + ";"


# The migration-owned triggers (``tr_<t>_set_created_by``, migration 0188). The
# trigger FUNCTIONS are shared in public with no pinned search_path, so under
# search_path=<guild_schema>,public they act on the guild's own rows. Triggers
# the registries render (freeze, capture, search) are not structure and are
# left out by name below — see ``rendered_trigger_names`` — so a template that
# still carries them from an earlier boot contributes nothing of theirs here.
_TRIGGER_SQL = text(  # noqa: S608 — interpolates only the _SRC_SCHEMA literal
    f"""
    SELECT cl.relname AS tbl, tg.tgname AS name, pg_get_triggerdef(tg.oid) AS triggerdef
    FROM pg_trigger tg
    JOIN pg_class cl ON cl.oid = tg.tgrelid
    JOIN pg_namespace n ON n.oid = cl.relnamespace AND n.nspname = '{_SRC_SCHEMA}'
    WHERE NOT tg.tgisinternal AND cl.relname = ANY(:t)
    ORDER BY cl.relname, tg.tgname
    """
)


def _schema_relative_trigger(triggerdef: str) -> str:
    # CREATE TRIGGER name ... ON <src>.tbl ... EXECUTE FUNCTION fn()  ->
    # schema-relative + idempotent (CREATE OR REPLACE; the function stays shared).
    triggerdef = triggerdef.replace("CREATE TRIGGER ", "CREATE OR REPLACE TRIGGER ")
    triggerdef = triggerdef.replace(f" ON {_SRC_SCHEMA}.", " ON ")
    return triggerdef + ";"


_TRIGGER_NAME_RE = re.compile(r"CREATE (?:OR REPLACE )?TRIGGER (\w+)")
_CONSTRAINT_NAME_RE = re.compile(r"ADD CONSTRAINT (\w+)")


def _registry_ddl() -> str:
    """Everything the registries render into a guild schema, as one text."""
    from app.db.event_capture import render_guild_capture_ddl
    from app.db.search_index import render_guild_search_ddl

    return "\n".join(
        (
            render_guild_rls_ddl(),
            render_guild_capture_ddl(),
            render_guild_search_ddl(None),
        )
    )


def rendered_trigger_names() -> frozenset[str]:
    """Every trigger name the registries render into a guild schema.

    Read off the rendered DDL itself — the freeze triggers in the RLS render,
    the change-capture triggers, the search-index triggers — so the set is
    whatever the renderers currently produce, with no list to keep in step.
    The structure reflection and the clone-fidelity test both use it to tell a
    migration-owned object from a rendered one.
    """
    return frozenset(_TRIGGER_NAME_RE.findall(_registry_ddl()))


def rendered_constraint_names() -> frozenset[str]:
    """Every constraint name the registries render into a guild schema.

    Today that is the search index's entity-type CHECK, which names the
    indexed set and is re-asserted per guild so a source added to the registry
    is admitted everywhere. Read off the rendered DDL, like the triggers.
    """
    return frozenset(_CONSTRAINT_NAME_RE.findall(_registry_ddl()))


def _guard(conname: str, body: str) -> str:
    # Idempotent ADD CONSTRAINT: skip if a constraint of this name already exists
    # in the current schema (search_path puts the guild schema first).
    return (
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        f"WHERE conname = '{conname}' AND connamespace = current_schema()::regnamespace) "
        f"THEN {body}; END IF; END $$;"
    )


async def render_guild_schema_ddl(engine: AsyncEngine) -> str:
    """Reflect the live ``guild_template`` and return the schema-relative,
    idempotent structure DDL for provisioning a guild schema."""
    async with engine.connect() as conn:
        # Visible-name resolution: with the template first on the search_path,
        # pg_get_*def emit its tables unqualified (and shared public objects
        # qualified only when shadowed) — keeping the DDL schema-relative.
        await conn.execute(text(f'SET search_path TO "{_SRC_SCHEMA}", public'))
        table_stmts = await conn.run_sync(_build_tables)
        index_rows = (
            await conn.execute(_INDEX_SQL, {"t": sorted(GUILD_SCOPED_TABLES)})
        ).fetchall()
        rows = (
            await conn.execute(_CONSTRAINT_SQL, {"t": sorted(GUILD_SCOPED_TABLES)})
        ).fetchall()
        trigger_rows = (
            await conn.execute(_TRIGGER_SQL, {"t": sorted(GUILD_SCOPED_TABLES)})
        ).fetchall()

    rendered = rendered_trigger_names()
    rendered_constraints = rendered_constraint_names()
    indexes = [_schema_relative_index(r.indexdef) for r in index_rows]
    triggers = [
        _schema_relative_trigger(r.triggerdef)
        for r in trigger_rows
        if r.name not in rendered
    ]
    checks, fks = [], []
    for r in rows:
        if r.contype == "c" and r.conname not in rendered_constraints:
            checks.append(
                _guard(
                    r.conname,
                    f'ALTER TABLE "{r.tbl}" ADD CONSTRAINT "{r.conname}" {r.condef}',
                )
            )
        elif r.contype == "f" and r.tgt in GUILD_SCOPED_TABLES:  # intra-schema only
            fks.append(
                _guard(
                    r.conname,
                    f'ALTER TABLE "{r.tbl}" ADD CONSTRAINT "{r.conname}" {r.condef}',
                )
            )

    header = (
        "-- RENDERED AT RUNTIME from the live guild_template schema. Schema-relative:\n"
        "-- run with search_path = <guild_schema>, public. Idempotent.\n\n"
    )
    return (
        header
        + "\n".join(table_stmts)
        + "\n\n-- indexes\n"
        + "\n".join(indexes)
        + "\n\n-- CHECK constraints\n"
        + "\n".join(checks)
        + "\n\n-- intra-schema FOREIGN KEYs\n"
        + "\n".join(fks)
        + "\n\n-- migration-owned triggers (functions are shared in public)\n"
        + "\n".join(triggers)
        + "\n"
    )

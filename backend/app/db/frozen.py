"""The lifecycle freeze: archived and trashed content takes no writes.

Archiving and trashing promise the same thing — *this is finished, leave it
alone* — and this module is where that promise is kept, in Postgres, for every
guild-content table at once.

A row is **frozen** when it is archived (``is_archived``), in the trash
(``deleted_at``), or hangs off something that is. Frozen content accepts no
writes; the only writes it accepts are the ones that end the state or move it
along — unarchive, restore, purge.

Freeze is a **lifecycle** state, and it is orthogonal to who may do what: a
frozen row is read-only for everybody, so the way to edit one is to bring it
back first.

Where each command is caught:

* **INSERT, against the row's ancestors** — a RESTRICTIVE policy with a
  ``WITH CHECK``.
* **UPDATE** — BEFORE UPDATE triggers: one for the row's own state, one for its
  ancestors, the latter asking about both the ancestry the row has and the one
  it would end up under. Telling an edit from an unarchive needs the old row and
  the new row together, which a policy never has, so all of it is trigger work.
  Each is attached with a ``WHEN`` clause naming the state it cares about, so an
  ordinary write on live content calls nothing.
* **DELETE** — a BEFORE DELETE trigger.
* **SELECT** — nothing. Reading frozen content is the point of keeping it.

All of them walk the same declaration, ``public.resource_frozen(kind, id)``,
rendered below from the join chains already in ``app.db.initiative_rls``. A
table names its first ancestor and the function walks the rest, so each policy
and trigger carries one call rather than a chain of its own.
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import DBAPIError
from sqlmodel import SQLModel

import app.db.base  # noqa: F401 — registers every model's table on the metadata
from app.core.reactions import ReactionTarget
from app.core.relationships import ENDPOINT_KINDS
from app.core.tools import Tool
from app.db.initiative_rls import (
    COMMENT_PARENT_COLUMNS,
    INITIATIVE_PATHS,
    governing_path,
)
from app.db.errors import INSUFFICIENT_PRIVILEGE_SQLSTATE, dbapi_sqlstate
from app.db.soft_delete_filter import SOFT_DELETE_TABLES
from app.db.tenancy import GUILD_SCOPED_TABLES

#: The SQLSTATE the guard raises, with a constraint name so it is told apart
#: from any other object-not-in-prerequisite-state error. 55000 is Postgres's
#: own code for "the object is not in the state this operation needs".
FROZEN_SQLSTATE = "55000"
FROZEN_CONSTRAINT = "frozen_row_guard"

#: Transaction-local flag marking a transaction as a purge.
#:
#: Purge is the one lifecycle step that writes frozen content rather than only
#: removing it: a document being purged leaves wikilinks behind in the documents
#: that pointed at it, and those are unresolved before the row goes — including
#: in documents that are themselves in the trash, which would otherwise be
#: restored holding a link to nothing.
#:
#: Set with ``SET LOCAL`` by ``hard_purge_entity``, so it lasts one transaction
#: and never reaches a pooled connection.
PURGE_GUC = "app.purging"

_PURGING = f"current_setting('{PURGE_GUC}'::text, true) = 'true'::text"

#: What a frozen row may still change: the columns that describe the freeze
#: itself, plus the timestamp every write touches. Everything else is content.
LIFECYCLE_COLUMNS: tuple[str, ...] = (
    "is_archived",
    "archived_at",
    "deleted_at",
    "deleted_by",
    "purge_at",
    "updated_at",
)

#: Tables carrying ``is_archived``, read off the mapped models rather than
#: listed — a model that gains the column joins the freeze by declaring it.
ARCHIVABLE_TABLES: frozenset[str] = frozenset(
    name
    for name, table in SQLModel.metadata.tables.items()
    if "is_archived" in table.c and name in GUILD_SCOPED_TABLES
)

#: Tables carrying the trash-can lifecycle (the ``SoftDeleteMixin`` subclasses).
TRASHABLE_TABLES: frozenset[str] = frozenset(SOFT_DELETE_TABLES)

#: Every table a row can be frozen ON. These carry the BEFORE UPDATE guard.
FROZEN_TABLES: frozenset[str] = ARCHIVABLE_TABLES | TRASHABLE_TABLES


#: Tables the freeze does not reach, and why. Reading frozen content still
#: happens, and reading writes rows — so the freeze would otherwise turn a page
#: view of an archived project into an error.
#:
#: - A reader's own record OF a resource: where they were, what they have seen,
#:   how they like their list arranged. None of it is the resource changing.
#: - Derived and log tables, written by a trigger as a consequence of a write
#:   that already cleared its own gate — including the unarchive itself, which
#:   has to be recordable.
#: - Notification bookkeeping, queued in the same transaction as the change that
#:   caused it. If the change is refused the row never exists; if it is allowed
#:   the record of it must not be.
#:
#: Deliberate responses are NOT here: a comment, a reaction, a poll answer and
#: an RSVP are gestures on the content, and frozen content takes none of them.
FREEZE_EXEMPT_TABLES: frozenset[str] = frozenset(
    {
        "recent_views",
        "post_reads",
        "project_orders",
        "project_favorites",
        "event_outbox",
        "search_entries",
        "reaction_digest_items",
        "task_assignment_digest_items",
        "event_reminder_dispatches",
    }
)

#: Edge tables, which name two ends and belong to neither. They take the freeze
#: on INSERT and UPDATE — no new link to or from frozen content, because a link
#: shows on both ends — but not on DELETE: purging one end drops every edge that
#: names it, and the surviving end may be an archived row that is not going
#: anywhere.
_EDGE_TABLES: frozenset[str] = frozenset({"relationships", "document_links"})


def row_is_frozen(row: Any) -> bool:
    """Whether a loaded resource is archived or in the trash — or sits in an
    initiative that is.

    Read by the app so it can answer in its own words, and so the client-facing
    permission level is capped and an archived thing arrives with its edit
    affordances already off. It reads the same columns the database does, so the
    two answers agree.

    The initiative is consulted only when it is already loaded: this runs on the
    request path, a lazy load there would be a second round trip at best and an
    error under async at worst, and the answer it would give is one the database
    gives anyway a moment later.
    """
    if row is None:
        return False
    if getattr(row, "is_archived", False):
        return True
    if getattr(row, "deleted_at", None) is not None:
        return True
    try:
        unloaded = sa_inspect(row).unloaded
    except Exception:  # noqa: BLE001 — not a mapped instance; nothing to walk
        return False
    if "initiative" in unloaded:
        return False
    return row_is_frozen(getattr(row, "initiative", None))


#: The prefix every ancestor policy's name carries; Postgres puts it in the
#: message it raises.
_ANCESTOR_POLICY_PREFIX = "frozen_ancestor_"


def is_frozen_write(exc: DBAPIError) -> bool:
    """Whether this error is the freeze refusing a write.

    Two shapes, because the rule is enforced two ways: the triggers raise with a
    constraint name of their own, and the policies raise with the name of the
    policy that refused. Matching on both is what lets a frozen write answer 409
    where a role-layer denial answers 403.
    """
    sqlstate = dbapi_sqlstate(exc)
    if sqlstate == FROZEN_SQLSTATE:
        return FROZEN_CONSTRAINT in str(getattr(exc, "orig", exc))
    if sqlstate == INSUFFICIENT_PRIVILEGE_SQLSTATE:
        return _ANCESTOR_POLICY_PREFIX in str(getattr(exc, "orig", exc))
    return False


def _own_frozen(alias: str, table: str) -> str | None:
    """Whether the row aliased ``alias`` is itself archived or trashed."""
    legs = []
    if table in ARCHIVABLE_TABLES:
        legs.append(f"{alias}.is_archived")
    if table in TRASHABLE_TABLES:
        legs.append(f"{alias}.deleted_at IS NOT NULL")
    if not legs:
        return None
    return " OR ".join(legs)


def _trashed(alias: str, table: str) -> str | None:
    if table not in TRASHABLE_TABLES:
        return None
    return f"{alias}.deleted_at IS NOT NULL"


def _parent_call(table: str, alias: str, *, trashed_ok: str) -> str | None:
    """The call that carries the walk one hop up from ``table``.

    Read off the join chain the table already declares for sharing: the first
    hop is the only one a caller needs, because the function walks the rest. A
    table with no hop resolves its initiative directly.
    """
    deviation = _FREEZE_DEVIATIONS.get(table)
    if deviation is not None:
        # Its ancestors are a property of the row, not of the table.
        return deviation(alias, trashed_ok)
    walk = governing_path(table)
    if walk is None:
        # Nothing above it this registry knows about: the initiative anchor
        # itself, and the tables that name only an initiative (below).
        return None
    _tool, hops = walk
    if not hops:
        return (
            f"public.resource_frozen('initiatives', "
            f"{alias}.initiative_id, {trashed_ok})"
        )
    column, parent = hops[0]
    return f"public.resource_frozen('{parent}', {alias}.{column}, {trashed_ok})"


#: Every kind ``resource_frozen`` can be asked about: the tables a row can be
#: frozen on, plus the tables that merely sit ON a walk (a poll between an
#: option and its notice) and have to forward the question upward.
def _dispatch_tables() -> tuple[str, ...]:
    hops = {
        hop[0][1]
        for table in INITIATIVE_PATHS
        if (walk := governing_path(table)) is not None and (hop := walk[1])
    }
    guild_frozen = {t for t in FROZEN_TABLES if t in INITIATIVE_PATHS}
    return tuple(sorted(hops | guild_frozen | {"initiatives"}))


def render_resource_frozen_fn() -> str:
    """``public.resource_frozen(kind, id, trashed_ok)`` — one walk, every caller.

    ``trashed_ok`` is what a DELETE asks: under a trashed parent, deleting is
    the lifecycle rather than a change to it, so the walk stops there and
    answers no. Under an archived one it answers yes, and the delete is refused.

    Created in ``public`` with no ``SET search_path``, like
    ``public.initiative_access``, so it resolves the guild-local tables of
    whoever calls it.
    """
    arms = []
    for table in _dispatch_tables():
        lines = [
            f"      WHEN '{table}' THEN",
            f"        SELECT * INTO fz FROM {table} WHERE id = rid;",  # noqa: S608
            "        IF NOT FOUND THEN RETURN false; END IF;",
        ]
        trashed = _trashed("fz", table)
        if trashed is not None:
            # Asked by a DELETE, a trashed row ends the walk: what is under it
            # is being purged, not edited.
            lines.append(
                f"        IF trashed_ok AND ({trashed}) THEN RETURN false; END IF;"
            )
        checks = [
            c
            for c in (
                _own_frozen("fz", table),
                _parent_call(table, "fz", trashed_ok="trashed_ok"),
            )
            if c is not None
        ]
        body = " OR ".join(f"({c})" for c in checks) if checks else "false"
        lines.append(f"        RETURN {body};")
        arms.append("\n".join(lines))
    return _RESOURCE_FROZEN_TEMPLATE.format(arms="\n".join(arms), purging=_PURGING)


def render_frozen_ancestor_fn() -> str:
    """``public.fn_frozen_ancestor_guard()`` — says no, and nothing else.

    The decision is in each trigger's ``WHEN`` clause, rendered per table from
    the same walk the policies use, so this stays one function for every table.
    """
    return f"""
CREATE OR REPLACE FUNCTION public.fn_frozen_ancestor_guard() RETURNS trigger
    LANGUAGE plpgsql AS $frozen_ancestor$
BEGIN
    RAISE EXCEPTION 'content of an archived or trashed parent is read-only'
        USING ERRCODE = '{FROZEN_SQLSTATE}', CONSTRAINT = '{FROZEN_CONSTRAINT}';
END;
$frozen_ancestor$;
"""


def frozen_ancestor_triggers(table: str) -> list[str]:
    """The ancestor attachments for one table, or none where the freeze does
    not reach it.

    UPDATE asks about BOTH ancestries — the one the row has and the one it would
    end up under — so neither editing under a frozen parent nor moving into one
    gets through, and reparenting is covered by the database rather than by each
    endpoint that does it. It runs the row guard, so the lifecycle columns may
    still change: a trashed task under an archived project can be restored.

    DELETE asks only about the ancestry the row has, with ``trashed_ok`` so a
    purge cascade runs.
    """
    out: list[str] = []
    prior = freeze_leg(table, "UPDATE", alias="OLD")
    proposed = freeze_leg(table, "UPDATE", alias="NEW")
    if prior is not None and proposed is not None:
        out.append(
            f"CREATE OR REPLACE TRIGGER tr_{table}_frozen_ancestor_update "
            f"BEFORE UPDATE ON {table} FOR EACH ROW "
            f"WHEN ({prior} OR {proposed}) "
            f"EXECUTE FUNCTION public.fn_frozen_row_guard()"
        )
    doomed = freeze_leg(table, "DELETE", alias="OLD")
    if doomed is not None:
        out.append(
            f"CREATE OR REPLACE TRIGGER tr_{table}_frozen_ancestor_delete "
            f"BEFORE DELETE ON {table} FOR EACH ROW WHEN ({doomed}) "
            f"EXECUTE FUNCTION public.fn_frozen_ancestor_guard()"
        )
    return out


def render_frozen_guard_fn() -> str:
    """``public.fn_frozen_row_guard()`` — the row's own half of the rule.

    Attached BEFORE UPDATE with a ``WHEN`` clause naming the frozen state, so a
    live row never reaches it. Once here, the row IS frozen: the only change it
    may carry is one to the columns that describe the freeze.
    """
    cols = ", ".join(f"'{c}'" for c in LIFECYCLE_COLUMNS)
    purging = _PURGING
    return f"""
CREATE OR REPLACE FUNCTION public.fn_frozen_row_guard() RETURNS trigger
    LANGUAGE plpgsql AS $frozen_guard$
DECLARE
    lifecycle text[] := ARRAY[{cols}];
BEGIN
    IF {purging} THEN
        RETURN NEW;
    END IF;
    IF (to_jsonb(NEW) - lifecycle) IS DISTINCT FROM (to_jsonb(OLD) - lifecycle) THEN
        RAISE EXCEPTION 'archived or trashed content is read-only'
            USING ERRCODE = '{FROZEN_SQLSTATE}', CONSTRAINT = '{FROZEN_CONSTRAINT}';
    END IF;
    RETURN NEW;
END;
$frozen_guard$;
"""


def frozen_guard_trigger(table: str) -> str:
    """The BEFORE UPDATE attachment for one frozen-capable table.

    The ``WHEN`` clause is the whole of the fast path: the executor evaluates it
    against the old row and calls nothing for a live one. Named so it sorts
    before the other row triggers, so what it compares is the statement's own
    change rather than another trigger's edit of it.
    """
    when = _own_frozen("OLD", table)
    if when is None:  # pragma: no cover — FROZEN_TABLES is built from these
        raise ValueError(f"{table} carries no lifecycle columns")
    return (
        f"CREATE OR REPLACE TRIGGER tr_{table}_frozen_guard "
        f"BEFORE UPDATE ON {table} FOR EACH ROW WHEN ({when}) "
        f"EXECUTE FUNCTION public.fn_frozen_row_guard()"
    )


_RESOURCE_FROZEN_TEMPLATE = """
CREATE OR REPLACE FUNCTION public.resource_frozen(
    kind text, rid bigint, trashed_ok boolean DEFAULT false
) RETURNS boolean LANGUAGE plpgsql STABLE AS $resource_frozen$
DECLARE
    fz record;
BEGIN
    IF rid IS NULL OR {purging} THEN
        RETURN false;
    END IF;
    CASE kind
{arms}
      ELSE
        RETURN false;
    END CASE;
END;
$resource_frozen$;
"""


def _comment_parent_table(column: str) -> str:
    """The table a comment's parent column points at.

    ``task_id`` is the one that is not a tool's own column; every other parent
    is the tool named by the column stem, which is how ``_comments_dac`` reads
    the same list.
    """
    if column == "task_id":
        return "tasks"
    return Tool(column.removesuffix("_id")).plural


def _comments_leg(alias: str, trashed_ok: str) -> str:
    """A comment freezes with the one thing it hangs off."""
    legs = [
        f"({alias}.{column} IS NOT NULL AND public.resource_frozen("
        f"'{_comment_parent_table(column)}', {alias}.{column}, {trashed_ok}))"
        for column in COMMENT_PARENT_COLUMNS
    ]
    return "(" + " OR ".join(legs) + ")"


def _reactions_leg(alias: str, trashed_ok: str) -> str:
    """A reaction freezes with the thing it is on."""
    arms = " ".join(
        f"WHEN '{target.value}' THEN public.resource_frozen("
        f"'{target.table}', {alias}.target_id, {trashed_ok})"
        for target in ReactionTarget
    )
    return f"COALESCE((CASE {alias}.target_type {arms} ELSE false END), false)"


def _edge_leg(alias: str, trashed_ok: str) -> str:
    """An edge freezes with EITHER end.

    A link shows on both ends — following it one way is a backlink the other —
    so naming a frozen thing changes that thing, and the edge is refused.
    """
    ends = []
    for side in ("source", "target"):
        arms = " ".join(
            f"WHEN '{kind.value}' THEN public.resource_frozen("
            f"'{endpoint.table}', {alias}.{side}_id, {trashed_ok})"
            for kind, endpoint in ENDPOINT_KINDS.items()
        )
        ends.append(
            f"COALESCE((CASE {alias}.{side}_type {arms} ELSE false END), false)"
        )
    return "(" + " OR ".join(ends) + ")"


def _document_links_leg(alias: str, trashed_ok: str) -> str:
    """Both ends again, but the kind is known: a link between two documents."""
    return (
        f"(public.resource_frozen('documents', {alias}.source_document_id, {trashed_ok})"
        f" OR public.resource_frozen('documents', {alias}.target_document_id,"
        f" {trashed_ok}))"
    )


def _resource_grants_leg(alias: str, trashed_ok: str) -> str:
    """A grant freezes with the resource it shares.

    Sharing an archived project is a change to the project, which is why the
    endpoint already refused it — this is the same rule, one layer down.
    """
    arms = " ".join(
        f"WHEN '{tool.value}' THEN public.resource_frozen("
        f"'{tool.plural}', {alias}.resource_id, {trashed_ok})"
        for tool in Tool
    )
    return f"COALESCE((CASE {alias}.resource_type {arms} ELSE false END), false)"


#: Tables whose ancestors are a property of the ROW rather than of the table,
#: so the walk cannot be read off a join chain and is declared here instead.
#: Read by BOTH halves — the policy leg and the dispatch function's own arm —
#: so a polymorphic row is never gated through one parent and frozen by another.
_FREEZE_DEVIATIONS: dict[str, Callable[[str, str], str]] = {
    "comments": _comments_leg,
    "reactions": _reactions_leg,
    "relationships": _edge_leg,
    "document_links": _document_links_leg,
    "resource_grants": _resource_grants_leg,
}


def freeze_leg(table: str, command: str, *, alias: str | None = None) -> str | None:
    """The RLS leg for one table and one write command, or None where the
    freeze does not reach it.

    ``DELETE`` asks with ``trashed_ok``: under a trashed ancestor, deleting is
    the lifecycle — that is what purge IS — where under an archived one it is a
    change to living content and is refused.
    """
    if table in FREEZE_EXEMPT_TABLES:
        return None
    if command == "DELETE" and table in _EDGE_TABLES:
        return None
    trashed_ok = "true" if command == "DELETE" else "false"
    alias = alias or table

    walked = _parent_call(table, alias, trashed_ok=trashed_ok)
    if walked is not None:
        return walked

    # No governing tool, but the row names its initiative: guild-wide
    # integration config and the initiative's own property definitions. They
    # freeze with the initiative and with nothing else.
    columns = SQLModel.metadata.tables[table].c
    if "initiative_id" in columns:
        return (
            f"public.resource_frozen('initiatives', "
            f"{alias}.initiative_id, {trashed_ok})"
        )
    return None

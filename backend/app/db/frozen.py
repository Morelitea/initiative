"""The lifecycle freeze: archived and trashed content takes no writes.

Archiving and trashing promise the same thing — *this is finished, leave it
alone* — and this module is where that promise is kept, in Postgres, for every
guild-content table at once.

A row is **frozen** when it is archived (``archived_at``), in the trash
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
from app.db.errors import (
    INSUFFICIENT_PRIVILEGE_SQLSTATE,
    dbapi_constraint,
    dbapi_sqlstate,
)
from app.db.soft_delete_filter import SOFT_DELETE_TABLES
from app.models.tenant._mixins import archive_models

#: The SQLSTATE the guard raises, with a constraint name so it is told apart
#: from any other object-not-in-prerequisite-state error. 55000 is Postgres's
#: own code for "the object is not in the state this operation needs".
FROZEN_SQLSTATE = "55000"
FROZEN_CONSTRAINT = "frozen_row_guard"

#: The refusal that names the thing ABOVE the row: it is archived or in the
#: trash, so this one cannot come out from under it on its own.
FROZEN_PARENT_CONSTRAINT = "frozen_parent_guard"

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
    "archived_at",
    "deleted_at",
    "deleted_by",
    "purge_at",
    "updated_at",
)

#: Tables carrying the archive lifecycle (the ``ArchiveMixin`` subclasses).
ARCHIVABLE_TABLES: frozenset[str] = frozenset(
    str(model.__tablename__) for model in archive_models()
)

#: Tables carrying the trash-can lifecycle (the ``SoftDeleteMixin`` subclasses).
TRASHABLE_TABLES: frozenset[str] = frozenset(SOFT_DELETE_TABLES)

#: Every table a row can be frozen ON. These carry the BEFORE UPDATE guard.
FROZEN_TABLES: frozenset[str] = ARCHIVABLE_TABLES | TRASHABLE_TABLES

#: Tables whose own two columns are the whole answer.
#:
#: Both lifecycles CASCADE — archiving an initiative stamps the tools in it and
#: a project stamps its tasks (``services.tenant.archive``), and the trash does
#: the same (``services.tenant.soft_delete``) — so a row here already carries
#: what its parent's state would have told us. Asking upward as well would be
#: the same question answered twice, from two places that could disagree.
#:
#: What is NOT here still asks: a comment or a picture carries a ``deleted_at``
#: but no ``archived_at``, and a row that carries neither — an assignee, a
#: property value, a grant — has nothing of its own to read. They inherit from
#: the nearest ancestor that does, which is one hop for most and two at worst.
SELF_STAMPED_TABLES: frozenset[str] = ARCHIVABLE_TABLES & TRASHABLE_TABLES


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
_EDGE_TABLES: frozenset[str] = frozenset({"relationships"})


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
    if getattr(row, "archived_at", None) is not None:
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

#: The constraint names the guards raise under.
_FROZEN_CONSTRAINTS = frozenset({FROZEN_CONSTRAINT, FROZEN_PARENT_CONSTRAINT})


def frozen_refusal(exc: DBAPIError) -> str | None:
    """Which freeze refused this write — its constraint name, or None.

    The two answer differently: one says the thing you wrote is archived or in
    the trash, the other says what it sits inside is, and the caller is told to
    bring back a different thing in each case.
    """
    if not is_frozen_write(exc):
        return None
    named = dbapi_constraint(exc)
    return named if named in _FROZEN_CONSTRAINTS else FROZEN_CONSTRAINT


def is_frozen_write(exc: DBAPIError) -> bool:
    """Whether this error is the freeze refusing a write.

    Two shapes, because the rule is enforced two ways: the triggers raise under
    a constraint name of their own, carried as an attribute of the error rather
    than in its text, and the policies raise with the name of the policy that
    refused, which Postgres does put in the message. Matching on both is what
    lets a frozen write answer 409 where a role-layer denial answers 403.
    """
    sqlstate = dbapi_sqlstate(exc)
    if sqlstate == FROZEN_SQLSTATE:
        return dbapi_constraint(exc) in _FROZEN_CONSTRAINTS
    if sqlstate == INSUFFICIENT_PRIVILEGE_SQLSTATE:
        return _ANCESTOR_POLICY_PREFIX in str(getattr(exc, "orig", exc))
    return False


def _own_frozen(alias: str, table: str) -> str | None:
    """Whether the row aliased ``alias`` is itself archived or trashed."""
    legs = []
    if table in ARCHIVABLE_TABLES:
        legs.append(f"{alias}.archived_at IS NOT NULL")
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

    A row that carries both lifecycle columns answers from itself and stops:
    the cascades already put its parent's state on it. Only a row with nothing
    of its own to read asks upward.

    A row it cannot find is treated as frozen. The caller reads under its own
    policies, and a trashed row is hidden from everyone but the guild admin and
    whoever deleted it — so "no such row" and "a row I may not see" arrive here
    as the same answer, and only one of them is safe to guess. Everything this
    walks is reached by a foreign key from a row that exists, so a miss means
    the second. Purge says so explicitly and is exempt above.

    ``trashed_ok`` is what a DELETE asks: a trashed row ends the walk, because
    deleting there is the lifecycle rather than a change to it. An archived one
    answers yes, and the delete is refused.

    Created in ``public`` with no ``SET search_path``, like
    ``public.initiative_access``, so it resolves the guild-local tables of
    whoever calls it.
    """
    arms = []
    for table in _dispatch_tables():
        lines = [
            f"      WHEN '{table}' THEN",
            f"        SELECT * INTO fz FROM {table} WHERE id = rid;",  # noqa: S608
            "        IF NOT FOUND THEN RETURN true; END IF;",
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
                None
                if table in SELF_STAMPED_TABLES
                else _parent_call(table, "fz", trashed_ok="trashed_ok"),
            )
            if c is not None
        ]
        body = " OR ".join(f"({c})" for c in checks) if checks else "false"
        lines.append(f"        RETURN {body};")
        arms.append("\n".join(lines))
    return _RESOURCE_FROZEN_TEMPLATE.format(arms="\n".join(arms), purging=_PURGING)


_RESOURCE_FROZEN_FOR_GRANT_TEMPLATE = """
CREATE OR REPLACE FUNCTION public.resource_frozen_for_grant(
    kind text, rid bigint, trashed_ok boolean DEFAULT false
) RETURNS boolean LANGUAGE plpgsql STABLE AS $resource_frozen_for_grant$
BEGIN
    IF rid IS NULL THEN
        RETURN false;
    END IF;
    PERFORM 1 FROM resource_grants g
     WHERE g.resource_type = kind AND g.resource_id = rid;
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    CASE kind
{arms}
      ELSE
        RETURN false;
    END CASE;
END;
$resource_frozen_for_grant$;
"""


def render_resource_frozen_for_grant_fn() -> str:
    """``public.resource_frozen_for_grant(tool, id, trashed_ok)`` — the freeze,
    asked the way a grant has to ask it.

    A grant is what makes a resource reachable, so the FIRST one is written
    while the resource still answers to nobody. Asked the ordinary way — where
    a row the caller cannot find is a row put away — no resource could ever be
    created, because the question is about a row this very statement is about
    to make visible.

    What tells that state apart from every other invisible one is the grants
    themselves: a resource with none is one being created, and a resource that
    has any is an existing one being shared, which asks in full. Grants outlive
    both lifecycles and carry no visibility rule of their own, so they answer
    here whatever state the resource is in.

    A function rather than the test written beside the call, because this leg is
    rendered into trigger ``WHEN`` clauses as well as policies, and a ``WHEN``
    takes no subquery.
    """
    arms = "\n".join(
        f"      WHEN '{tool.value}' THEN\n"
        f"        RETURN public.resource_frozen("
        f"'{tool.plural}', rid, trashed_ok);"
        for tool in Tool
    )
    return _RESOURCE_FROZEN_FOR_GRANT_TEMPLATE.format(arms=arms)


def render_frozen_ancestor_fn() -> str:
    """``public.fn_frozen_ancestor_guard()`` — says no, and nothing else.

    The decision is in each trigger's ``WHEN`` clause, rendered per table from
    the same declaration the policies use, so this stays one function for every
    table and both reasons — a frozen ancestry, and a row's own frozen state on
    a delete. It keeps the name it was created under: the triggers that call it
    depend on it, so renaming it would mean dropping and rebuilding every one.
    """
    return f"""
CREATE OR REPLACE FUNCTION public.fn_frozen_ancestor_guard() RETURNS trigger
    LANGUAGE plpgsql AS $frozen_ancestor$
BEGIN
    RAISE EXCEPTION 'archived or trashed content is read-only'
        USING ERRCODE = '{FROZEN_SQLSTATE}', CONSTRAINT = '{FROZEN_CONSTRAINT}';
END;
$frozen_ancestor$;
"""


def frozen_write_triggers(table: str) -> list[str]:
    """What refuses a write to one table, beyond the row's own UPDATE guard.

    A cascade says where a row has BEEN, never where it is going. That is the
    line these are drawn on.

    A row that carries both lifecycle columns already has its parent's state on
    it, so nothing here asks about the ancestry it HAS — its own UPDATE guard
    covers that, and asking upward too would be one question answered twice from
    two places that could disagree. It still takes:

    * a DELETE guard on its own state, since the row guard is BEFORE UPDATE and
      says nothing about removal. Deleting a TRASHED row is exempt: that is what
      purge is.
    * an UPDATE guard on the ancestry it would END UP under, because no cascade
      can have stamped a row for a parent it has not reached yet — the same
      reason INSERT keeps its walk.

    A row with nothing of its own to read inherits instead, and asks about both
    ancestries: the one it has as well as the one it is moving to.
    """
    out: list[str] = []
    if table in SELF_STAMPED_TABLES:
        own = _own_frozen("OLD", table)
        trashed = _trashed("OLD", table)
        out.append(
            f"CREATE OR REPLACE TRIGGER tr_{table}_frozen_delete "
            f"BEFORE DELETE ON {table} FOR EACH ROW "
            f"WHEN (({own}) AND NOT ({trashed})) "
            f"EXECUTE FUNCTION public.fn_frozen_ancestor_guard()"
        )
        moving_into = freeze_leg(table, "UPDATE", alias="NEW")
        prior = freeze_leg(table, "UPDATE", alias="OLD")
        if moving_into is not None and prior is not None:
            moving_into = f"{prior} OR {moving_into}"
        if moving_into is not None:
            out.append(
                f"CREATE OR REPLACE TRIGGER tr_{table}_frozen_ancestor_update "
                f"BEFORE UPDATE ON {table} FOR EACH ROW WHEN ({moving_into}) "
                f"EXECUTE FUNCTION public.fn_frozen_parent_guard()"
            )
        return out

    prior = freeze_leg(table, "UPDATE", alias="OLD")
    proposed = freeze_leg(table, "UPDATE", alias="NEW")
    if prior is not None and proposed is not None:
        out.append(
            f"CREATE OR REPLACE TRIGGER tr_{table}_frozen_ancestor_update "
            f"BEFORE UPDATE ON {table} FOR EACH ROW "
            f"WHEN ({prior} OR {proposed}) "
            f"EXECUTE FUNCTION public.fn_frozen_parent_guard()"
        )
    doomed = freeze_leg(table, "DELETE", alias="OLD")
    if doomed is not None:
        out.append(
            f"CREATE OR REPLACE TRIGGER tr_{table}_frozen_ancestor_delete "
            f"BEFORE DELETE ON {table} FOR EACH ROW WHEN ({doomed}) "
            f"EXECUTE FUNCTION public.fn_frozen_ancestor_guard()"
        )
    return out


def render_frozen_parent_guard_fn() -> str:
    """``public.fn_frozen_parent_guard()`` — the row guard, plus one rule.

    A row under something archived or trashed may still change its lifecycle
    columns: that is what lets a whole tree be stamped, and a trashed task in an
    archived project be taken out of the trash — it stays archived, with its
    project, which is the state it should be in.

    What it may not do is end up with NO stamp at all while the thing above it
    still carries one. It would then be live inside a finished thing, and a row
    that carries its own stamp is not asked about its ancestry again once it is
    live — so it could be moved or deleted straight out.

    Read through ``to_jsonb`` rather than by column, because one function serves
    tables that have both lifecycle columns and tables that have neither.
    """
    cols = ", ".join(f"'{c}'" for c in LIFECYCLE_COLUMNS)
    return f"""
CREATE OR REPLACE FUNCTION public.fn_frozen_parent_guard() RETURNS trigger
    LANGUAGE plpgsql AS $frozen_parent$
DECLARE
    lifecycle text[] := ARRAY[{cols}];
    was jsonb := to_jsonb(OLD);
    now_ jsonb := to_jsonb(NEW);
BEGIN
    IF {_PURGING} THEN
        RETURN NEW;
    END IF;
    IF (was ? 'archived_at' OR was ? 'deleted_at')
       AND now_ ->> 'archived_at' IS NULL
       AND now_ ->> 'deleted_at' IS NULL THEN
        RAISE EXCEPTION 'what this is inside is archived or in the trash'
            USING ERRCODE = '{FROZEN_SQLSTATE}',
                  CONSTRAINT = '{FROZEN_PARENT_CONSTRAINT}';
    END IF;
    IF (now_ - lifecycle) IS DISTINCT FROM (was - lifecycle) THEN
        RAISE EXCEPTION 'archived or trashed content is read-only'
            USING ERRCODE = '{FROZEN_SQLSTATE}', CONSTRAINT = '{FROZEN_CONSTRAINT}';
    END IF;
    RETURN NEW;
END;
$frozen_parent$;
"""


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


def _resource_grants_leg(alias: str, trashed_ok: str) -> str:
    """A grant freezes with the resource it shares, WHEN it can see it.

    Sharing an archived project is a change to the project, which is why the
    endpoint already refused it — this is the same rule, one layer down.

    Asked through ``resource_frozen_for_grant``, which is what makes that rule
    expressible here at all: the first grant on a resource is part of creating
    it, and every later one is sharing. That function carries the whole of the
    distinction, including the per-tool dispatch, so this leg is one call.
    """
    return (
        f"COALESCE(public.resource_frozen_for_grant("
        f"{alias}.resource_type, {alias}.resource_id, {trashed_ok}), false)"
    )


#: Tables whose ancestors are a property of the ROW rather than of the table,
#: so the walk cannot be read off a join chain and is declared here instead.
#: Read by BOTH halves — the policy leg and the dispatch function's own arm —
#: so a polymorphic row is never gated through one parent and frozen by another.
_FREEZE_DEVIATIONS: dict[str, Callable[[str, str], str]] = {
    "comments": _comments_leg,
    "reactions": _reactions_leg,
    "relationships": _edge_leg,
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

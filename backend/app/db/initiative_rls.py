"""Single source of truth for the initiative-member RLS layer.

Each per-guild CONTENT table that is scoped to initiative membership is declared
exactly once here, in ``INITIATIVE_PATHS`` — mapping the table to *how a row
resolves its initiative* for ``public.initiative_access(...)``. From that one
declaration we derive:

- ``INITIATIVE_SCOPED_TABLES`` (``app.db.tenancy`` re-exports it and folds it
  into ``GUILD_SCOPED_TABLES``),
- the rendered RLS DDL (``app.db.guild_ddl`` stamps the
  uniform policy boilerplate around each path), and
- change capture: the table emits events, scoped by that same path and naming
  itself, unless ``EVENT_SOURCES`` (below) says otherwise.

So a new initiative-scoped table is added in ONE place — add a path here — and
the classification, the generated policies, and its event stream all follow.
``tenancy_test.py``, ``guild_rls_test.py`` and ``event_readback_test.py``
enforce that nothing drifts.

This module is intentionally dependency-free (no models, no SQLAlchemy) so it can
be imported by ``tenancy`` and by the build-time generator alike.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.core.reactions import ReactionTarget
from app.core.tools import CORE_TOOLS, RECENTABLE_TOOLS, Tool

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

# A DAC builder has the same shape as a PathBuilder but may answer None, for a
# table no tool's sharing governs — the guild's own vocabulary, an initiative's
# configuration. None renders no leg at all rather than a `true` one.
DacBuilder = Callable[[str, str, bool], "str | None"]

#: Every tool's own table, keyed by table name. The sharing gate is DERIVED from
#: this rather than declared per table: a row is governed by the tool it belongs
#: to, and a table that belongs to none is governed by none. So a seventh tool
#: gates its own rows and its children's the day its table exists.
_TOOL_BY_TABLE: dict[str, Tool] = {tool.plural: tool for tool in Tool}


@dataclass(frozen=True)
class DacPath:
    """How a row names the tool that governs it — gates 3 and 4, as SQL.

    ``predicate`` renders the tool gate that the table's policies AND onto the
    membership one, or None where no tool governs the table. Both gates come
    from the same declaration and the same join, so a child table asks its
    parent about its role and its sharing once rather than twice.
    """

    predicate: DacBuilder


def _resource_call(tool: str, resource_id: str, initiative: str, write: bool) -> str:
    """Gate 4 alone, for a row that names its governing tool in a COLUMN.

    The search index is the one: which tool governs an entry differs per row,
    so the tool cannot be rendered into the policy and gate 3 — whose switch is
    a different column per tool — has nothing static to ask. The index is
    derived from content that carries both gates already, and the query that
    reads it applies the tool switches.
    """
    return (
        f"public.resource_access({tool}, {resource_id}, {_UID}, "
        f"{initiative}, {'true' if write else 'false'})"
    )


def _tool_gate(
    tool: Tool,
    resource_id: str,
    initiative: str,
    command: str,
    write: bool,
    *,
    creating: bool,
) -> str:
    """Gates 3 and 4 for one tool, against one row's initiative.

    Gate 3 is two conditions the schema already holds: the initiative's master
    switch for the tool, and what the reader's role in that initiative permits.
    The switch is a different column per tool, so it renders here where the tool
    is known rather than inside the function.

    ``creating`` is the INSERT of the governed resource itself — that asks for
    the tool's create right, where every other command asks to view it, and it
    asks gate 4 nothing.
    """
    legs: list[str] = []

    if tool not in CORE_TOOLS:
        # Opt-in tools carry a switch on the initiative; the core two are always
        # on and have no column. A guild admin or a PAM grantee reaches the
        # content of a tool that is switched off — the endpoints still refuse
        # them, and a maintenance sweep has to be able to see it.
        legs.append(
            f"({_GUILD_ADMIN} OR {_PAM_ANY} OR {initiative} IS NULL"
            f" OR COALESCE((SELECT i.{tool.plural}_enabled FROM initiatives i"
            f" WHERE i.id = {initiative}), false))"
        )

    key = tool.create_permission if creating else tool.view_permission
    default = "false" if creating else str(tool in CORE_TOOLS).lower()
    legs.append(
        f"public.initiative_role_permits({initiative}, {_UID}, '{key}', {default})"
    )

    if not creating:
        legs.append(
            f"public.resource_access('{tool.value}', {resource_id}, {_UID}, "
            f"{initiative}, {'true' if write else 'false'})"
        )

    return "(" + " AND ".join(legs) + ")"


def _dac_self(tool: Tool | None = None) -> DacPath:
    """The row IS the shared resource. Which tool that is comes from the table
    name at render time, so a table that is no tool's renders nothing; a caller
    reaching the table under an alias (reactions, below) names the tool itself.
    """

    def build(t: str, command: str, w: bool) -> str | None:
        governing = tool if tool is not None else _TOOL_BY_TABLE.get(t)
        if governing is None:
            return None
        return _tool_gate(
            governing,
            f"{t}.id",
            f"{t}.initiative_id",
            command,
            w,
            # An INSERT is the resource being made only where the table IS the
            # resource. A caller that names the tool reached it under an alias
            # (a reaction on a notice), and there the INSERT is the reaction's:
            # the notice already exists and answers for itself.
            creating=command == "INSERT" and tool is None,
        )

    return DacPath(predicate=build)


def _dac_via(
    parent: str, fk: str, *, parent_pk: str = "id", alias: str = "dac"
) -> DacPath:
    """The row is shared as part of its parent — a task by its project."""
    tool = _TOOL_BY_TABLE.get(parent)
    if tool is None:
        return DacPath(predicate=lambda t, c, w: None)

    return DacPath(
        predicate=lambda t, c, w: (
            f"EXISTS (SELECT 1 FROM {parent} {alias} "
            f"WHERE {alias}.{parent_pk} = {t}.{fk} AND "
            + _tool_gate(
                tool,
                f"{alias}.id",
                f"{alias}.initiative_id",
                c,
                w,
                creating=False,
            )
            + ")"
        )
    )


def _dac_two_hop(mid: str, mid_fk: str, parent: str, fk: str) -> DacPath:
    """Two hops to the governing resource: ``table.<fk> -> mid -> parent`` — a
    subtask by its task's project, an attendee by its event's calendar."""
    tool = _TOOL_BY_TABLE[parent]
    return DacPath(
        predicate=lambda t, c, w: (
            f"EXISTS (SELECT 1 FROM {mid} dmid JOIN {parent} dpar "
            f"ON dpar.id = dmid.{mid_fk} WHERE dmid.id = {t}.{fk} AND "
            + _tool_gate(tool, "dpar.id", "dpar.initiative_id", c, w, creating=False)
            + ")"
        )
    )


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
    #: The sharing leg (gate 4), ANDed onto ``predicate`` by the DDL renderer.
    #: Derived by the factories below from the parent a table already declares,
    #: so it is never a second list to keep in step.
    dac: DacPath | None = None


#: The routed guild-admin leg, for rows that span every initiative in a guild.
_GUILD_ADMIN = "current_setting('app.current_guild_role'::text, true) = 'admin'::text"

#: A live PAM window, either level. Used where a leg is about what a guild has
#: switched on rather than about what one person may reach.
_PAM_ANY = (
    "current_setting('app.pam_read'::text, true) = 'true'::text"
    " OR current_setting('app.pam_write'::text, true) = 'true'::text"
)


def _access(initiative_expr: str, write: bool) -> str:
    return f"public.initiative_access({initiative_expr}, {_UID}, {'true' if write else 'false'})"


def direct() -> InitiativePath:
    """The table has its own ``initiative_id`` column."""
    return InitiativePath(
        predicate=lambda t, w: _access(f"{t}.initiative_id", w),
        initiative_expr=lambda r: f"{r}.initiative_id",
        dac=_dac_self(),
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
        dac=_dac_via(parent, fk, parent_pk=parent_pk),
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
        dac=_dac_two_hop("tasks", "project_id", "projects", fk),
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
        dac=_dac_two_hop("queue_items", "queue_id", "queues", fk),
    )


def via_post_poll(fk: str = "poll_id") -> InitiativePath:
    """Two hops: ``table.<fk> -> post_polls -> posts.initiative_id``."""
    return InitiativePath(
        predicate=lambda t, w: (
            f"EXISTS (SELECT 1 FROM post_polls pp JOIN posts po ON po.id = pp.post_id "
            f"WHERE pp.id = {t}.{fk} "
            f"AND {_access('po.initiative_id', w)})"
        ),
        initiative_expr=lambda r: (
            f"(SELECT po.initiative_id FROM post_polls pp "  # noqa: S608
            f"JOIN posts po ON po.id = pp.post_id WHERE pp.id = {r}.{fk})"
        ),
        dac=_dac_two_hop("post_polls", "post_id", "posts", fk),
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
        dac=_dac_two_hop("calendar_events", "calendar_id", "calendars", fk),
    )


def via_property(
    entity_from: str, entity_pred: str, entity_init: str, dac: DacPath | None = None
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
        dac=dac,
    )


# Comment parents: (comment column, FROM clause, tie to the row, initiative
# column). One declaration per parent — the policy legs and the outbox locator
# below both render from it, so a comment cannot be gated through one parent
# and have its events attributed through another. Every Tool appears here plus
# the task, matching the comment table's single-parent constraint.
_COMMENT_PARENTS: tuple[tuple[str, str, str, str], ...] = (
    (
        "task_id",
        "tasks tk JOIN projects pr ON pr.id = tk.project_id",
        "tk.id",
        "pr.initiative_id",
    ),
    ("document_id", "documents d", "d.id", "d.initiative_id"),
    ("project_id", "projects p", "p.id", "p.initiative_id"),
    ("queue_id", "queues q", "q.id", "q.initiative_id"),
    ("counter_group_id", "counter_groups cg", "cg.id", "cg.initiative_id"),
    ("calendar_id", "calendars cal", "cal.id", "cal.initiative_id"),
    ("dashboard_id", "dashboards dsh", "dsh.id", "dsh.initiative_id"),
    ("post_id", "posts po", "po.id", "po.initiative_id"),
)


#: The comment columns naming a parent, in declaration order. Search reads this
#: to work out which tool's sharing governs a comment, so the parent set is
#: stated once and the two derivations cannot disagree.
COMMENT_PARENT_COLUMNS: tuple[str, ...] = tuple(col for col, *_ in _COMMENT_PARENTS)


def _comments_dac() -> DacPath:
    """Which tool's sharing governs a comment — its one parent's.

    Derived from ``_COMMENT_PARENTS``, so the sharing legs and the membership
    legs are the same list read twice. A comment on a task is the one parent
    whose resource is not its own column: a task is shared as part of its
    project.
    """

    def build(t: str, command: str, w: bool) -> str:
        legs = []
        for col, *_ in _COMMENT_PARENTS:
            if col == "task_id":
                leg = _dac_two_hop("tasks", "project_id", "projects", col)
            else:
                leg = _dac_via(Tool(col.removesuffix("_id")).plural, col)
            legs.append(f"({t}.{col} IS NOT NULL AND {leg.predicate(t, command, w)})")
        return "(" + " OR ".join(legs) + ")"

    return DacPath(predicate=build)


def comments_path() -> InitiativePath:
    """Comments hang off exactly one parent — a task or any tool entity —
    declared once in ``_COMMENT_PARENTS`` and rendered here both ways."""

    def build(t: str, w: bool) -> str:
        legs = [
            f"({t}.{col} IS NOT NULL AND EXISTS ("
            f"SELECT 1 FROM {frm} WHERE {tie} = {t}.{col} "
            f"AND {_access(init, w)}))"
            for col, frm, tie, init in _COMMENT_PARENTS
        ]
        return "(" + " OR ".join(legs) + ")"

    def locate(r: str) -> str:
        lookups = ", ".join(
            f"(SELECT {init} FROM {frm} WHERE {tie} = {r}.{col})"  # noqa: S608
            for col, frm, tie, init in _COMMENT_PARENTS
        )
        return f"COALESCE({lookups})"

    return InitiativePath(predicate=build, initiative_expr=locate, dac=_comments_dac())


def reactions_path() -> InitiativePath:
    """A reaction is reached by whoever can reach the thing it is on.

    Polymorphic over ``(target_type, target_id)``, so each kind is one EXISTS
    leg into the target's table, and the target's OWN path decides — for a
    comment that is the multi-parent predicate declared just above, reused here
    rather than restated. A new reactable kind adds a leg by adding a
    ``ReactionTarget`` member; nothing about the gate is written twice.
    """
    legs: dict[ReactionTarget, InitiativePath] = {
        ReactionTarget.comment: comments_path(),
        ReactionTarget.post: direct(),
    }
    # The same targets, read for sharing. A post answers for itself and is
    # named explicitly, because under an alias the table name no longer says
    # which tool it is.
    dac_legs: dict[ReactionTarget, DacPath] = {
        ReactionTarget.comment: _comments_dac(),
        ReactionTarget.post: _dac_self(Tool.post),
    }

    def build_dac(t: str, command: str, w: bool) -> str:
        return (
            "("
            + " OR ".join(
                f"({t}.target_type = '{target.value}' AND EXISTS ("
                f"SELECT 1 FROM {target.table} rdac WHERE rdac.id = {t}.target_id "
                f"AND {path.predicate('rdac', command, w)}))"
                for target, path in dac_legs.items()
            )
            + ")"
        )

    def build(t: str, w: bool) -> str:
        return (
            "("
            + " OR ".join(
                f"({t}.target_type = '{target.value}' AND EXISTS ("
                f"SELECT 1 FROM {target.table} rt WHERE rt.id = {t}.target_id "
                f"AND {path.predicate('rt', w)}))"
                for target, path in legs.items()
            )
            + ")"
        )

    def locate(r: str) -> str:
        arms = " ".join(
            f"WHEN '{target.value}' THEN "
            f"(SELECT {path.initiative_expr('rt')} FROM {target.table} rt "  # noqa: S608
            f"WHERE rt.id = {r}.target_id)"
            for target, path in legs.items()
        )
        return f"(CASE {r}.target_type {arms} END)"

    return InitiativePath(
        predicate=build, initiative_expr=locate, dac=DacPath(predicate=build_dac)
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


def _search_tool_gate(t: str, write: bool) -> str:
    """Gates 3 and 4 for a search entry, keyed on the tool it names.

    Every other table has one governing tool rendered into its policy. An entry
    names its own in ``dac_tool``, so the switch and the role key are a CASE
    over that column — one arm per tool, and rows naming none (the guild's
    vocabulary) fall through the ELSE.

    An entry outlives the content it describes by as long as the sweep takes,
    so it answers the same three questions the source does rather than trusting
    that it was right when it was written.
    """
    switch_arms = " ".join(
        f"WHEN '{tool.value}' THEN "
        + (
            "true"
            if tool in CORE_TOOLS
            else (
                f"({_GUILD_ADMIN} OR {_PAM_ANY} OR {t}.initiative_id IS NULL"
                f" OR COALESCE((SELECT i.{tool.plural}_enabled FROM initiatives i"
                f" WHERE i.id = {t}.initiative_id), false))"
            )
        )
        for tool in Tool
    )
    role_arms = " ".join(
        f"WHEN '{tool.value}' THEN public.initiative_role_permits("
        f"{t}.initiative_id, {_UID}, '{tool.view_permission}', "
        f"{str(tool in CORE_TOOLS).lower()})"
        for tool in Tool
    )
    return (
        f"((CASE {t}.dac_tool {switch_arms} ELSE true END)"
        f" AND (CASE {t}.dac_tool {role_arms} ELSE true END)"
        f" AND {_resource_call(f'{t}.dac_tool', f'{t}.dac_id', f'{t}.initiative_id', write)})"
    )


def search_entries_path() -> InitiativePath:
    """The search index is reached exactly like the content it describes.

    It stores ``initiative_id`` directly, so unlike ``recent_views`` this needs
    no per-type EXISTS join — the row was stamped with its source's initiative
    by the same registry that renders that source's own policies.

    A NULL initiative is the guild-level case (a tag, a guild calendar): the
    initiative gate has nothing to decide, and these are rows every member
    already sees everywhere else in the app. It is not an ungated leg — a row
    carrying a ``dac_tool`` still answers to sharing, and reaching this schema
    at all is the guild gate.
    """
    return InitiativePath(
        predicate=lambda t, w: (
            f"(CASE WHEN {t}.initiative_id IS NULL "
            f"THEN true "
            f"ELSE {_access(f'{t}.initiative_id', w)} END)"
        ),
        initiative_expr=lambda r: f"{r}.initiative_id",
        # The index stores the governing pair, so the legs need no join. Which
        # tool governs an entry differs per row, so the two that name a tool are
        # a CASE over it rather than a rendered constant.
        dac=DacPath(predicate=lambda t, c, w: _search_tool_gate(t, w)),
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

    def build_dac(t: str, command: str, w: bool) -> str:
        legs = [
            f"({t}.entity_type = '{etype}' AND "
            f"{_dac_via(tbl, 'entity_id').predicate(t, command, w)})"
            for etype, tbl in RECENT_ENTITY_TABLES.items()
        ]
        return "(" + " OR ".join(legs) + ")"

    return InitiativePath(
        predicate=build, initiative_expr=locate, dac=DacPath(predicate=build_dac)
    )


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

    def _dac_leg(fk: str, t: str, command: str, w: bool) -> str:
        return str(
            _dac_via("documents", fk, alias=f"dac_{fk}").predicate(t, command, w)
        )

    return InitiativePath(
        predicate=lambda t, w: (
            f"({_leg('source_document_id', t, w)} AND {_leg('target_document_id', t, w)})"
        ),
        dac=DacPath(
            predicate=lambda t, c, w: (
                f"({_dac_leg('source_document_id', t, c, w)} AND "
                f"{_dac_leg('target_document_id', t, c, w)})"
            )
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
    "posts": direct(),
    "property_definitions": direct(),
    # Sharing itself. It carries no sharing leg of its own: resource_access
    # reads this table, so a policy here that called it would not resolve.
    # ``direct()`` derives none, because the table is no tool's own.
    "resource_grants": direct(),
    # The change log itself. Scoped like the rows it describes, which is what
    # lets the poller read it AS the subscriber (see EVENT_SOURCES below).
    # Reading is the question this path answers; writing is the capture
    # trigger's alone (app.db.guild_ddl._TRIGGER_WRITTEN_INSERT).
    "event_outbox": direct(),
    # The search index. Derived from the content tables, and gated like them.
    "search_entries": search_entries_path(),
    # Integration config, reached by whoever can reach what it watches.
    "webhook_subscriptions": webhook_subscription_path(),
    # One hop -> projects
    "tasks": via("projects", "project_id"),
    "task_statuses": via("projects", "project_id"),
    "project_filter_presets": via("projects", "project_id"),
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
    # One hop -> posts
    "post_tags": via("posts", "post_id"),
    "post_reads": via("posts", "post_id"),
    "post_polls": via("posts", "post_id"),
    # Two hops -> tasks -> projects
    "subtasks": via_task_project("task_id"),
    "task_assignees": via_task_project("task_id"),
    "task_tags": via_task_project("task_id"),
    # Two hops -> queue_items -> queues
    "queue_item_documents": via_queue_item("queue_item_id"),
    "queue_item_tags": via_queue_item("queue_item_id"),
    "queue_item_tasks": via_queue_item("queue_item_id"),
    # Two hops -> post_polls -> posts
    "post_poll_options": via_post_poll("poll_id"),
    "post_poll_votes": via_post_poll("poll_id"),
    # Two hops -> calendar_events -> calendars
    "calendar_event_attendees": via_event_calendar("calendar_event_id"),
    "calendar_event_documents": via_event_calendar("calendar_event_id"),
    "calendar_event_tags": via_event_calendar("calendar_event_id"),
    # Property values (entity + property_definitions, same-initiative)
    "document_property_values": via_property(
        "documents d",
        "d.id = {t}.document_id",
        "d.initiative_id",
        _dac_via("documents", "document_id"),
    ),
    "task_property_values": via_property(
        "tasks tk JOIN projects pr ON pr.id = tk.project_id",
        "tk.id = {t}.task_id",
        "pr.initiative_id",
        _dac_two_hop("tasks", "project_id", "projects", "task_id"),
    ),
    "calendar_event_property_values": via_property(
        "calendar_events ce JOIN calendars cal ON cal.id = ce.calendar_id",
        "ce.id = {t}.event_id",
        "cal.initiative_id",
        _dac_two_hop("calendar_events", "calendar_id", "calendars", "event_id"),
    ),
    # Multi-parent
    "comments": comments_path(),
    # Polymorphic over what it is on; gated by that thing's own path.
    "reactions": reactions_path(),
    # Per-user state, scoped via the entity it points at
    "project_orders": via("projects", "project_id"),
    "project_favorites": via("projects", "project_id"),
    "task_assignment_digest_items": via("projects", "project_id"),
    # Same polymorphic target columns as the reactions themselves, so the
    # queued line is gated exactly like the gesture it describes.
    "reaction_digest_items": reactions_path(),
    "event_reminder_dispatches": via_event_calendar("event_id"),
    "recent_views": recent_views_path(),
}

# Derived — the classification follows the registry, never duplicates it.
INITIATIVE_SCOPED_TABLES: frozenset[str] = frozenset(INITIATIVE_PATHS)


#: Which commands ask the sharing gate at WRITE level, for the tables that
#: deviate from the default — where every writing command does.
#:
#: An entry states what the table's own endpoints state, so the policy and the
#: service ask the same question of the same row:
#:
#: - **Nothing** for a reader's own record OF a resource — a favourite, a view,
#:   a read receipt, a poll answer, an RSVP. Reordering and favouriting a
#:   project, recording a view, marking a notice read, answering a poll and
#:   answering an invitation are all endpoints that take read access; the RSVP
#:   one says so in as many words ("RSVPing is answering an invitation, not
#:   editing the event").
#: - **Nothing** for comments and reactions. Responding to something is not
#:   editing it: you may answer a notice you cannot rewrite. What gates a
#:   response is whether you can reach the thing at all, plus the thread's own
#:   switch — so every command here asks at read, and the switch is the
#:   endpoint's to apply.
#:
#: Membership is a statement about the table, not about the gate: initiative
#: membership and the schema boundary still apply in full.
#: Responding to something asks nothing of write — named, so the tables that
#: are one gesture and its bookkeeping cannot drift apart.
_RESPONDING: frozenset[str] = frozenset()

DAC_WRITE_COMMANDS: dict[str, frozenset[str]] = {
    "project_orders": frozenset(),
    "project_favorites": frozenset(),
    "recent_views": frozenset(),
    "post_reads": frozenset(),
    "post_poll_votes": frozenset(),
    "calendar_event_attendees": frozenset(),
    # A record that this reader was reminded, written where the reminder is
    # sent. Being told about an event is a reader's business, not a change to
    # the calendar.
    "event_reminder_dispatches": _RESPONDING,
    "comments": _RESPONDING,
    "reactions": _RESPONDING,
    # The queued line describing a reaction is written in the SAME request as
    # the reaction, so it answers at the same level. It shares
    # ``reactions_path``; this is the other half of that sharing.
    "reaction_digest_items": _RESPONDING,
}

#: The default: a command that writes asks at write level.
ALL_WRITE_COMMANDS: frozenset[str] = frozenset({"INSERT", "UPDATE", "DELETE"})

assert DAC_WRITE_COMMANDS.keys() <= INITIATIVE_SCOPED_TABLES, (
    "DAC_WRITE_COMMANDS names a table that is not initiative-scoped: "
    f"{sorted(DAC_WRITE_COMMANDS.keys() - INITIATIVE_SCOPED_TABLES)}"
)
assert all(
    commands <= ALL_WRITE_COMMANDS for commands in DAC_WRITE_COMMANDS.values()
), "DAC_WRITE_COMMANDS names a command that does not write"


def dac_asks_at_write(table: str, command: str) -> bool:
    """Whether ``table``'s sharing leg asks at write level for ``command``."""
    return command in DAC_WRITE_COMMANDS.get(table, ALL_WRITE_COMMANDS)


# ---------------------------------------------------------------------------
# Change capture: what emits, and as what
# ---------------------------------------------------------------------------
#
# One registry, holding only DEVIATIONS from the default. The default is derived:
# a table in INITIATIVE_PATHS emits, scoped by that same path, naming itself.
# So an ordinary new content table needs no entry here at all — which is the
# whole point, and why the deviations are stated rather than the members.


@dataclass(frozen=True)
class ReportsAs:
    """Report a table's changes as an update to a DIFFERENT resource.

    Some tables have an id of their own without being something a subscriber
    fetches on its own: a project's statuses, a document's version history, an
    initiative's roles, a resource's sharing. Each is a facet of the thing it
    belongs to, and saying so is what keeps every event's id resolvable — the
    parent already has a detail route, so adding one of these owes no new API
    surface.

    Junctions get this shape for free (``task_tags`` -> ``tasks.updated`` with
    ``changed = ['tags']``, derived from the composite key). This is the explicit
    form, for tables whose own primary key would otherwise make them look
    independently addressable.
    """

    #: Resource types an event from this table can name. Usually one; a grant
    #: names whichever tool it is on, so the vocabulary needs the whole set.
    resource_types: frozenset[str]
    #: Row expression yielding that resource's id.
    id_expr: RowLocator
    #: Label reported in ``changed``.
    facet: str
    #: Row expression yielding the resource TYPE, for the polymorphic case.
    #: ``None`` when ``resource_types`` holds the single constant answer.
    type_expr: RowLocator | None = None


def reports_as(parent: str, fk: str, facet: str) -> ReportsAs:
    """Facet of one fixed parent, reached by a foreign key on the row."""
    return ReportsAs(
        resource_types=frozenset({parent}),
        id_expr=lambda r: f'{r}."{fk}"',
        facet=facet,
    )


def grants_report_on_their_resource() -> ReportsAs:
    """A grant is sharing ON something — report it against that something.

    ``resource_type`` holds the Tool value and ``resource_id`` its id, so the
    event lands on the project (or document, queue, …) whose access changed.
    That is both what a subscriber wants to hear and already resolvable, where
    the grant row's own id resolves nowhere.

    An unrecognized ``resource_type`` yields NULL from the CASE and the row is
    skipped, so the vocabulary below and what the trigger can emit stay the same
    set.
    """
    arms = " ".join(f"WHEN '{t.value}' THEN '{t.plural}'" for t in Tool)
    return ReportsAs(
        resource_types=frozenset(t.plural for t in Tool),
        id_expr=lambda r: f"{r}.resource_id",
        facet="sharing",
        type_expr=lambda r: f"(CASE {r}.resource_type {arms} END)",
    )


def reactions_report_on_their_target() -> ReportsAs:
    """A reaction is a facet OF what it is on — report it there.

    The reaction row's own id resolves to no route (there is no
    ``/reactions/{id}`` to re-read), where the comment it lands on already has
    one. So the event says "this comment changed, facet: reactions" and the
    subscriber re-reads the comment, whose read carries the current counts.
    """
    arms = " ".join(
        f"WHEN '{target.value}' THEN '{target.table}'" for target in ReactionTarget
    )
    return ReportsAs(
        resource_types=frozenset(target.table for target in ReactionTarget),
        id_expr=lambda r: f"{r}.target_id",
        facet="reactions",
        type_expr=lambda r: f"(CASE {r}.target_type {arms} END)",
    )


def poll_options_report_on_their_post() -> ReportsAs:
    """A poll option is a facet of the notice that asks the question.

    Its own id resolves to no route — there is no ``/poll-options/{id}`` to
    re-read — where the post already has one, and re-reading the post carries
    the whole poll back. The poll itself reports the same way through its own
    ``post_id``; this is the one hop further out.
    """
    return ReportsAs(
        resource_types=frozenset({"posts"}),
        id_expr=lambda r: (
            f"(SELECT post_polls.post_id FROM post_polls "  # noqa: S608
            f"WHERE post_polls.id = {r}.poll_id)"
        ),
        facet="poll",
    )


def _role_initiative(r: str) -> str:
    """The initiative a row's ``initiative_role_id`` belongs to."""
    return (
        f"(SELECT initiative_roles.initiative_id FROM initiative_roles "  # noqa: S608
        f"WHERE initiative_roles.id = {r}.initiative_role_id)"
    )


@dataclass(frozen=True)
class Silent:
    """This table gets no capture trigger, and why not."""

    reason: str


@dataclass(frozen=True)
class Emit:
    """This table emits, deviating from the derived default in some respect."""

    #: How a row resolves its initiative, when INITIATIVE_PATHS has no entry —
    #: i.e. the table emits but carries no initiative-member RLS.
    initiative: RowLocator | None = None
    #: The row belongs to no initiative at all and a NULL is EXPECTED. Only ever
    #: correct for a table every guild member can already read.
    guild_wide: bool = False
    #: Report against a parent resource instead of naming this table.
    reports_as: ReportsAs | None = None
    #: Publish this table's own events under this resource type instead of the
    #: table's name, for a table whose API segment differs from it. Keeps the
    #: readback rule (``resource_type`` -> the detail route that serves the id)
    #: derivable without a second route. Meaningless beside ``reports_as``,
    #: which names its parent instead.
    resource_type: str | None = None


#: table -> how it deviates. Anything absent takes the derived default.
EVENT_SOURCES: dict[str, Emit | Silent] = {
    # -- Silent ------------------------------------------------------------
    "event_outbox": Silent("the log cannot log itself"),
    # What one member did with their own UI, not a change to the initiative's
    # content, so every subscription would pay for pure noise.
    "recent_views": Silent("one member's own viewing state"),
    "search_entries": Silent("derived index, rebuilt from the content it mirrors"),
    "project_orders": Silent("one member's own ordering state"),
    # A vote row names the person who cast it, and an event carries the actor
    # that wrote it. A poll may be anonymous, so it emits nothing at all rather
    # than emitting only for the polls that are not — one rule, no way to get
    # the flag wrong. Results reach a reader through the post's own reads.
    "post_poll_votes": Silent("a vote names its voter; a poll may be anonymous"),
    "project_favorites": Silent("one member's own pinning state"),
    "task_assignment_digest_items": Silent("internal digest bookkeeping"),
    "reaction_digest_items": Silent("internal digest bookkeeping"),
    "event_reminder_dispatches": Silent("internal reminder bookkeeping"),
    "webhook_subscriptions": Silent(
        "integration config; it reports on content, not on itself"
    ),
    # Guild-level, and kept out on disclosure: an upload row is reachable from
    # more than one place, so the initiative gate is not the whole answer for it
    # the way it is for tags. Gate it properly or leave it silent — silent.
    "uploads": Silent("reached through several parents; not gated by one of them"),
    # -- Guild-level tables that emit ---------------------------------------
    # The structural initiative tables are deliberately exempt from
    # initiative-member RLS (a membership table gated by the membership check it
    # backs would recurse), and that exemption must not also mean "invisible to
    # every automation" — creating an initiative, adding a member, changing a
    # role are all things a subscriber acts on. They get a capture trigger and
    # nothing else; no policy is rendered from this registry. The outbox row
    # carries a real initiative_id, so RLS scopes the EVENT normally.
    "initiatives": Emit(initiative=lambda r: f"{r}.id"),
    "initiative_members": Emit(initiative=lambda r: f"{r}.initiative_id"),
    "initiative_roles": Emit(
        initiative=lambda r: f"{r}.initiative_id",
        reports_as=reports_as("initiatives", "initiative_id", "roles"),
    ),
    "initiative_role_permissions": Emit(
        initiative=_role_initiative,
        # The resource IS the initiative, so its id is the same lookup.
        reports_as=ReportsAs(
            resource_types=frozenset({"initiatives"}),
            id_expr=_role_initiative,
            facet="roles",
        ),
    ),
    # -- Guild-wide: no initiative at all -----------------------------------
    # The row carries a NULL initiative_id, which the access function reads as
    # "the initiative gate has nothing to decide" and admits for any guild
    # member. Correct here rather than weakening: tags are already readable by
    # every member of the guild, run through most flows, and an automation that
    # cannot see them is missing an ordinary trigger. The envelope carries ids
    # and column names only, never values.
    #
    # The trigger is told a NULL is expected here specifically, so an
    # initiative-scoped row whose lookup fails still means "skip".
    "tags": Emit(guild_wide=True),
    # Installed apps, same reasoning: the install row is guild-wide knowledge
    # (every member's sidebar lists it), so its lifecycle emits guild-wide too.
    # A subscriber hears an install appear, change (``config_state`` moving is
    # the moment an app becomes usable), or go away, and re-reads current state
    # through the API like any other event. Published as ``apps`` because that
    # is the segment the install's detail route lives at (``/apps/{id}``).
    "guild_apps": Emit(guild_wide=True, resource_type="apps"),
    # -- Facets of their parent ---------------------------------------------
    "task_statuses": Emit(reports_as=reports_as("projects", "project_id", "statuses")),
    "project_filter_presets": Emit(
        reports_as=reports_as("projects", "project_id", "filter_presets")
    ),
    "document_file_versions": Emit(
        reports_as=reports_as("documents", "document_id", "versions")
    ),
    "resource_grants": Emit(reports_as=grants_report_on_their_resource()),
    "post_polls": Emit(reports_as=reports_as("posts", "post_id", "poll")),
    "post_poll_options": Emit(reports_as=poll_options_report_on_their_post()),
    "reactions": Emit(reports_as=reactions_report_on_their_target()),
}

_SILENT: frozenset[str] = frozenset(
    t for t, source in EVENT_SOURCES.items() if isinstance(source, Silent)
)

# The tables the capture trigger is installed on: initiative-scoped content,
# plus the guild-level tables that declared themselves emitters, minus whatever
# declared itself silent.
EVENTED_TABLES: frozenset[str] = (
    INITIATIVE_SCOPED_TABLES
    | frozenset(t for t, source in EVENT_SOURCES.items() if isinstance(source, Emit))
) - _SILENT


def event_source(table: str) -> Emit:
    """How ``table`` emits — its declared deviations, or the derived default."""
    source = EVENT_SOURCES.get(table)
    return source if isinstance(source, Emit) else Emit()


def initiative_locator(table: str) -> RowLocator:
    """Row expression yielding the initiative an event about ``table`` belongs to.

    One question, answered from the registry that already knows: an
    initiative-scoped table reuses the very path that renders its RLS, so a row
    can never be gated by one initiative and have its events attributed to
    another. Guild-level emitters say so themselves.
    """
    source = event_source(table)
    if source.guild_wide:
        return lambda _row: "NULL::integer"
    if source.initiative is not None:
        return source.initiative
    path = INITIATIVE_PATHS.get(table)
    if path is None:
        raise RuntimeError(
            f"{table} emits events but nothing resolves the initiative they "
            "belong to — add an INITIATIVE_PATHS entry, or an Emit(initiative=…)"
        )
    return path.initiative_expr

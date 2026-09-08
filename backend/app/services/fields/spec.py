"""What a field *is* — one declaration, read by every surface that names one.

The filter vocabulary is currently written twice: ``_build_task_filter_fields``
on the backend and ``conditions.ts`` on the client, with nothing keeping them in
step. Neither is a description — one compiles a clause, the other draws a
control — so a field's *type*, the operators it answers, and which control fills
it are knowledge no single place holds.

This module is that place. A :class:`FieldSpec` says everything about a field
once:

* how it resolves to SQL — a column, or a callable for the ones needing a
  subquery;
* what kind of value it holds, so a consumer knows how to compare and render it;
* which operators apply, so an unsupported one is refused rather than silently
  producing nothing;
* which control picks a value, which is what lets a filter UI be generic instead
  of carrying a branch per field.

It is a *description*, not a second validator. ``apply_filters`` still owns how a
clause is assembled and ``parse_conditions`` still owns the payload limits;
restating either here would mean maintaining them twice.

Nothing in this module imports a model, so it stays cheap to import from
anywhere and a dataset declaration can live beside the thing it describes.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from enum import Enum
from typing import Any, Callable, Mapping, Optional, Protocol

from app.core.tools import Tool
from app.schemas.query import FilterOp


class FieldType(str, Enum):
    """What a value *is*, for comparison and formatting.

    Coarser than a SQL type on purpose: a consumer needs to know that a due date
    orders and a title does not, never that one is ``timestamptz`` and the other
    ``varchar(200)``.
    """

    text = "text"
    number = "number"
    date = "date"
    boolean = "boolean"
    #: A closed vocabulary the app owns (priority, status category).
    enum = "enum"
    #: A reference to another row — filtered by id, shown by name.
    reference = "reference"


class ControlKind(str, Enum):
    """Which control fills this field.

    A presentation fact, kept here rather than on the client because it belongs
    to the field: that an assignee is chosen from a member picker is true of the
    field, not of any one screen that offers it.
    """

    text = "text"
    number = "number"
    date = "date"
    boolean = "boolean"
    select = "select"
    member = "member"
    tag = "tag"
    project = "project"
    initiative = "initiative"
    task_status = "task_status"
    status_category = "status_category"
    priority = "priority"
    #: Values only a lookup can enumerate (a custom property's options).
    property_value = "property_value"


#: Operator sets, named for what they mean rather than listed at each use.
EQUALITY: frozenset[FilterOp] = frozenset({FilterOp.eq, FilterOp.is_null})
ORDERED: frozenset[FilterOp] = EQUALITY | frozenset(
    {FilterOp.lt, FilterOp.lte, FilterOp.gt, FilterOp.gte}
)
TEXTUAL: frozenset[FilterOp] = EQUALITY | frozenset({FilterOp.ilike})
MEMBERSHIP: frozenset[FilterOp] = EQUALITY | frozenset({FilterOp.in_})


#: What a control offers, by the control it is.
#:
#: Derived rather than listed per field: "a member picker is a multi-select of
#: ids" is true of every member picker, and restating it on each field is the
#: parallel list this module exists to remove. A field's own ``ops`` stays the
#: engine's answer; this is intersected with it, so a control can never offer an
#: operator the engine would refuse.
#:
#: ``project`` is deliberately single-valued: a plain top-level equality on
#: ``project_id`` is the only shape that narrows a request to one project, and
#: the access path reads exactly that shape.
UI_OPS: dict["ControlKind", frozenset[FilterOp]] = {}
UI_MULTIPLE: set["ControlKind"] = set()


@dataclass(frozen=True)
class SortContext:
    """What an ordering needs to know about the request.

    Only the timezone, today — a grouping by "today" has to mean the reader's
    day. Separate from :class:`FieldContext` because a sort genuinely has no
    identity to offer, and inventing one so the types line up is how a resolver
    ends up quietly filtering as user zero.
    """

    tz: Optional[str] = None


@dataclass(frozen=True)
class FieldContext:
    """What a resolver needs that the field itself cannot know.

    Passed per request rather than baked into the declaration, because every one
    of these is a property of *who is asking* — which is why the old builders
    took them as arguments and rebuilt their whole dict on every call.
    """

    guild_id: int
    user_id: int
    #: Custom property definitions by id, for the fields that dispatch on one.
    property_definitions: Mapping[int, Any] = dataclass_field(default_factory=dict)
    #: IANA timezone, for sorts that group by the reader's local day rather than
    #: the server's. Present here too so one context serves a request that both
    #: filters and orders.
    tz: Optional[str] = None


class Resolver(Protocol):
    """A field that needs more than a column comparison to filter.

    Returns a SQLAlchemy clause, or ``None`` to contribute nothing — which is
    how an empty id list says "this narrows nothing" rather than "match nothing".
    """

    def __call__(self, op: FilterOp, value: Any, ctx: FieldContext) -> Any: ...


class SortExpression(Protocol):
    """A field that orders by something other than a plain column."""

    def __call__(self, ctx: SortContext) -> Any: ...


#: What a control offers, by the control it is. Derived rather than listed per
#: field: "a member picker is a multi-select of ids" is true of every member
#: picker, and restating it on each field is the parallel list this module
#: exists to remove.
#:
#: ``project`` is deliberately single-valued. A plain top-level equality on
#: ``project_id`` is the only shape that narrows a request to one project, and
#: the access path reads exactly that shape; an ``in_`` there would quietly take
#: a different branch.


@dataclass(frozen=True)
class FieldSpec:
    """One field, described once."""

    name: str
    type: FieldType
    kind: ControlKind
    ops: frozenset[FilterOp]
    #: The column this field is, when it is one. Mutually exclusive with
    #: ``resolve`` — a field is either a column or a computation, never both.
    column: Optional[Any] = None
    resolve: Optional[Resolver] = None
    #: How this field orders, when it is not simply its column — a grouping
    #: whose expression depends on the reader's timezone, say.
    sort: Optional[SortExpression] = None
    #: Whether a consumer may offer this field for filtering. A column can exist
    #: and still be nobody's business to filter on.
    filterable: bool = True
    #: Whether a consumer may order by it. Off by default: most columns are
    #: filterable and only some are a sensible ordering, and offering a sort
    #: nobody wants is how a field list stops being readable.
    sortable: bool = False
    #: Whether the underlying column admits NULL. Decides whether a control
    #: offers "is empty" at all — asking it of a NOT NULL column is a filter
    #: that can only ever match everything.
    nullable: bool = True
    #: Free-text note for the catalog a client renders.
    description: Optional[str] = None

    def __post_init__(self) -> None:
        if self.column is None and self.resolve is None and self.sort is None:
            raise ValueError(f"field {self.name!r} declares no way to be used")
        if self.column is not None and self.resolve is not None:
            raise ValueError(f"field {self.name!r} is both a column and a computation")
        if self.filterable and self.column is None and self.resolve is None:
            raise ValueError(f"field {self.name!r} is filterable but cannot filter")
        if self.sortable and self.column is None and self.sort is None:
            raise ValueError(f"field {self.name!r} is sortable but cannot sort")


@dataclass(frozen=True)
class Dataset:
    """A queryable thing, and the fields it offers.

    ``tool`` names the tool whose **sharing governs** these rows, which is not
    always the tool they are — a task is governed by its project, the same
    answer ``dac_scope_clause`` reaches for. Naming it lets everything the enum
    already derives be derived rather than restated: the default dataset name,
    and in turn the master switch and resource type the gates read off it. Only
    the field list is genuinely per-dataset.

    ``name_override`` is for a dataset whose name is not the tool's plural —
    ``tasks`` under ``Tool.project`` — and is required when there is no tool.
    """

    model: Any
    fields: tuple[FieldSpec, ...]
    tool: Optional[Tool] = None
    #: Overrides the name derived from ``tool``. Required when there is no tool.
    name_override: Optional[str] = None
    #: Fields kept out of what a client offers, beyond the shared conventions.
    #:
    #: An exclusion list rather than an inclusion one: a new column should show
    #: up in the filter UI by default and be *taken out* on purpose, so the way
    #: to forget a field is to forget to hide it rather than to forget to add
    #: it. Every field stays filterable by a stored definition either way — this
    #: only governs what a control offers.
    hidden: frozenset[str] = frozenset()

    @property
    def name(self) -> str:
        if self.name_override is not None:
            return self.name_override
        if self.tool is not None:
            return self.tool.plural
        raise ValueError("a dataset needs a tool or a name_override")

    @property
    def by_name(self) -> dict[str, FieldSpec]:
        return {spec.name: spec for spec in self.fields}

    @property
    def offered(self) -> tuple[FieldSpec, ...]:
        """The fields a client offers, in the order it lists them.

        Derived: everything filterable, minus the conventions every dataset
        hides and this one's own additions, minus anything whose control has no
        operator to offer. Ordering comes from the control group, so nobody
        maintains a running list as fields are added.
        """
        candidates = [
            spec
            for spec in self.fields
            if spec.filterable
            and spec.name not in HIDDEN_EVERYWHERE
            and spec.name not in self.hidden
            and offered_ops(spec)
        ]
        return tuple(sorted(candidates, key=presentation_order))

    def __post_init__(self) -> None:
        known = self.by_name
        for name in self.hidden:
            if name not in known:
                raise ValueError(f"{self.name}: hidden field {name!r} is not declared")


def column(
    name: str,
    col: Any,
    *,
    type: FieldType,
    kind: ControlKind,
    ops: Optional[frozenset[FilterOp]] = None,
    filterable: bool = True,
    sortable: bool = False,
    nullable: bool = True,
) -> FieldSpec:
    """A field that is a column. ``ops`` defaults to what its type supports."""
    if ops is None:
        ops = {
            FieldType.text: TEXTUAL,
            FieldType.number: ORDERED,
            FieldType.date: ORDERED,
            FieldType.boolean: EQUALITY,
            FieldType.enum: MEMBERSHIP,
            FieldType.reference: MEMBERSHIP,
        }[type]
    return FieldSpec(
        name=name,
        type=type,
        kind=kind,
        ops=ops,
        column=col,
        filterable=filterable,
        sortable=sortable,
        nullable=nullable,
    )


def computed(
    name: str,
    resolver: Callable[..., Any],
    *,
    type: FieldType,
    kind: ControlKind,
    ops: frozenset[FilterOp],
    filterable: bool = True,
    nullable: bool = False,
) -> FieldSpec:
    """A field that needs a subquery, a lookup, or a literal expanded.

    ``ops`` must be exactly what the resolver handles, not what its type could
    in principle support, so that every declared operator produces a clause.
    ``nullable`` says whether "is empty" means something for it — for most
    computed fields it does not.
    """
    return FieldSpec(
        name=name,
        type=type,
        kind=kind,
        ops=ops,
        resolve=resolver,
        filterable=filterable,
        nullable=nullable,
    )


def sort_only(
    name: str,
    expression: SortExpression,
    *,
    type: FieldType,
    kind: ControlKind,
) -> FieldSpec:
    """An ordering that is not a field anybody filters by.

    A derived grouping is the case: it exists to put rows in an order, and
    there is nothing to compare it against.
    """
    return FieldSpec(
        name=name,
        type=type,
        kind=kind,
        ops=frozenset(),
        sort=expression,
        filterable=False,
        sortable=True,
    )


# --- what a control offers ---------------------------------------------------
#
# Populated here rather than at the declaration above because the values need
# ControlKind and the operator sets, and the declaration needs to be readable
# next to the type it belongs to.

_IN = frozenset({FilterOp.in_})
_EQ = frozenset({FilterOp.eq})
_RANGE = frozenset({FilterOp.lt, FilterOp.lte, FilterOp.gt, FilterOp.gte})

UI_OPS.update(
    {
        ControlKind.status_category: _IN,
        ControlKind.task_status: _IN,
        ControlKind.priority: _IN,
        ControlKind.member: _IN,
        ControlKind.tag: _IN,
        ControlKind.initiative: _IN,
        ControlKind.select: _IN,
        ControlKind.project: _EQ,
        ControlKind.date: _RANGE,
        ControlKind.number: _EQ | _RANGE,
        ControlKind.boolean: _EQ,
        ControlKind.text: frozenset({FilterOp.ilike}),
        ControlKind.property_value: _EQ,
    }
)

UI_MULTIPLE.update(
    {
        ControlKind.status_category,
        ControlKind.task_status,
        ControlKind.priority,
        ControlKind.member,
        ControlKind.tag,
        ControlKind.initiative,
        ControlKind.select,
    }
)


def offered_ops(spec: FieldSpec) -> frozenset[FilterOp]:
    """The operators a control offers for this field.

    The control's own set, narrowed to what the engine accepts, plus "is empty"
    only where the column can actually be empty — offering it on a NOT NULL
    column is a filter that can only ever match everything.
    """
    ops = UI_OPS.get(spec.kind, frozenset()) & spec.ops
    if spec.nullable and FilterOp.is_null in spec.ops:
        ops = ops | frozenset({FilterOp.is_null})
    return ops


def offers_multiple(spec: FieldSpec) -> bool:
    return spec.kind in UI_MULTIPLE


#: Columns no dataset offers as a filter, by convention rather than per model.
#:
#: Soft-delete and purge bookkeeping, the surrogate key, the tenant key (a
#: request is already scoped to one guild, so filtering by it narrows nothing),
#: and the drag-ordering float. None of these means anything to somebody
#: building a filter, and every table has them.
HIDDEN_EVERYWHERE: frozenset[str] = frozenset(
    {
        "id",
        "guild_id",
        "position",
        "deleted_at",
        "deleted_by",
        "purge_at",
    }
)


#: Ordering for the fields a client lists, by control group then name. Derived
#: so nobody maintains a running order as fields are added.
_KIND_ORDER: dict["ControlKind", int] = {
    ControlKind.status_category: 0,
    ControlKind.task_status: 1,
    ControlKind.priority: 2,
    ControlKind.member: 3,
    ControlKind.tag: 4,
    ControlKind.project: 5,
    ControlKind.initiative: 6,
    ControlKind.select: 7,
    ControlKind.property_value: 8,
    ControlKind.date: 9,
    ControlKind.boolean: 10,
    ControlKind.number: 11,
    ControlKind.text: 12,
}


def presentation_order(spec: FieldSpec) -> tuple[int, str]:
    return (_KIND_ORDER.get(spec.kind, 99), spec.name)

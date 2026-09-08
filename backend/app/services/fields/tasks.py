"""The task dataset — the fields a task can be filtered by.

Lifted from ``_build_task_filter_fields`` without changing what any of them
answers. The resolvers are the same clauses; what is new is that each field now
also says what it *is*, so a client can draw a control for it and a query
surface can type-check it without either restating this list.

Columns are derived from the model rather than enumerated, which is what the old
builder did and what keeps a new column filterable the day it is added. The
override table below is only for the ones whose control cannot be inferred from
a SQL type — an integer that is a person is not an integer to whoever picks one.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    case,
    func,
    literal,
    text,
)
from sqlmodel import select

from app.core.messages import TaskMessages
from app.core.tools import Tool
from app.models.tenant.project import Project
from app.models.tenant.tag import Tag, TaskTag
from app.models.tenant.task import Task, TaskAssignee, TaskStatus
from app.schemas.query import FilterOp
from app.services.fields.spec import (
    ControlKind,
    Dataset,
    EQUALITY,
    FieldContext,
    FieldSpec,
    FieldType,
    MEMBERSHIP,
    ORDERED,
    SortContext,
    TEXTUAL,
    column,
    computed,
    sort_only,
)
from app.services.tenant import properties as properties_service

#: Columns worth ordering by. Filterability is the default for a column and
#: orderability is not — most columns narrow usefully, few of them make a
#: sensible ordering, and a sort list nobody can read is not a feature.
_SORTABLE = frozenset(
    {
        "position",
        "title",
        "due_date",
        "start_date",
        "priority",
        "created_at",
        "updated_at",
    }
)

#: Task fields a filter control does not offer, beyond the shared conventions.
#:
#: ``initiative_ids`` exists for the cross-guild "my tasks" views, which already
#: know their initiative; a dashboard reads its own and a binding cannot say
#: otherwise. The recurrence columns are a feature's internal state — a JSON
#: rule, the strategy that applies it, and a counter — not something anybody
#: filters a board by.
_HIDDEN = frozenset(
    {
        "initiative_ids",
        "recurrence",
        "recurrence_strategy",
        "recurrence_occurrence_count",
    }
)

#: Controls that a SQL type cannot imply. Everything absent here is inferred.
_CONTROL_OVERRIDES: dict[str, tuple[FieldType, ControlKind]] = {
    "project_id": (FieldType.reference, ControlKind.project),
    "task_status_id": (FieldType.reference, ControlKind.task_status),
    "priority": (FieldType.enum, ControlKind.priority),
    "created_by": (FieldType.reference, ControlKind.member),
    "deleted_by": (FieldType.reference, ControlKind.member),
}


def _infer(col: Any) -> tuple[FieldType, ControlKind]:
    """A column's type and control, where the SQL type is enough to say."""
    sql_type = col.type
    if isinstance(sql_type, Boolean):
        return FieldType.boolean, ControlKind.boolean
    if isinstance(sql_type, (DateTime, Date)):
        return FieldType.date, ControlKind.date
    if isinstance(sql_type, (Integer, Numeric)):
        return FieldType.number, ControlKind.number
    return FieldType.text, ControlKind.text


def _model_columns() -> tuple[FieldSpec, ...]:
    specs = []
    for col in Task.__table__.columns:
        attr = getattr(Task, col.name)
        field_type, control = _CONTROL_OVERRIDES.get(col.name) or _infer(col)
        specs.append(
            column(
                col.name,
                attr,
                type=field_type,
                kind=control,
                sortable=col.name in _SORTABLE,
                nullable=bool(col.nullable),
            )
        )
    return tuple(specs)


# --- the fields a column cannot express ------------------------------------


def _status_category(op: FilterOp, value: Any, ctx: FieldContext) -> Any:
    if not value:
        return None
    subq = select(TaskStatus.id).where(TaskStatus.category.in_(tuple(value)))
    return Task.task_status_id.in_(subq)


def _assignee_ids(op: FilterOp, value: Any, ctx: FieldContext) -> Any:
    # "Unassigned": no row in task_assignees at all. Answered before the
    # emptiness guard below, which is there to skip an empty id list.
    # ``negate`` inverts it, so "has any assignee" comes free.
    if op == FilterOp.is_null:
        has_assignee = Task.id.in_(select(TaskAssignee.task_id))
        return ~has_assignee if value else has_assignee
    if not value:
        return None
    user_ids: list[int] = []
    for aid in value:
        if aid == "me":
            user_ids.append(ctx.user_id)
        else:
            try:
                user_ids.append(int(aid))
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=TaskMessages.INVALID_ASSIGNEE_ID,
                )
    if not user_ids:
        return None
    subq = select(TaskAssignee.task_id).where(TaskAssignee.user_id.in_(tuple(user_ids)))
    return Task.id.in_(subq)


def _tag_ids(op: FilterOp, value: Any, ctx: FieldContext) -> Any:
    if not value:
        return None
    subq = (
        select(TaskTag.task_id)
        .join(Tag, Tag.id == TaskTag.tag_id)
        .where(
            TaskTag.tag_id.in_(tuple(value)),
            Tag.guild_id == ctx.guild_id,
        )
        .distinct()
    )
    return Task.id.in_(subq)


def _initiative_ids(op: FilterOp, value: Any, ctx: FieldContext) -> Any:
    if not value:
        return None
    subq = select(Project.id).where(Project.initiative_id.in_(tuple(value)))
    return Task.project_id.in_(subq)


def _property_values(op: FilterOp, value: Any, ctx: FieldContext) -> Any:
    """Filter tasks by a custom property value.

    ``value`` is a dict of ``{"property_id": int, "value": <any>}``. Compilation
    is delegated to ``build_single_property_clause`` so the typed-column and
    is_empty semantics stay in sync with documents and events.
    """
    if not isinstance(value, dict):
        return None
    try:
        pid = int(value.get("property_id"))
    except (TypeError, ValueError):
        return None
    defn = ctx.property_definitions.get(pid)
    if defn is None:
        # Unknown or cross-guild property — silently skip (defense in depth,
        # consistent with the rest of apply_filters).
        return None
    return properties_service.build_single_property_clause(
        "task", pid, op, value.get("value"), defn
    )


#: What each resolver actually handles. Narrower than the type would suggest,
#: and deliberately so: ``_status_category`` and ``_tag_ids`` build an ``IN``
#: over their value, so ``in_`` is the one operator each of them answers.
_IN_ONLY = frozenset({FilterOp.in_})
_IN_OR_EMPTY = frozenset({FilterOp.in_, FilterOp.is_null})

#: A custom property answers whichever operators its own type supports; the
#: dispatch inside ``build_single_property_clause`` decides, so this one really
#: is as wide as it looks.
_ANY_OP = EQUALITY | MEMBERSHIP | ORDERED | TEXTUAL


def _date_group(ctx: SortContext) -> Any:
    """SQL CASE mirroring the frontend's ``getTaskDateStatus()``.

    Returns a numeric group: 0 overdue, 1 today, 2 this week, 3 this month,
    4 later.

    When the context carries an IANA timezone the expression converts both
    ``now()`` and the task columns into it, so "today" is the *reader's* local
    day rather than the database server's UTC one. That is why this is an
    expression resolved per request rather than a column: the same row belongs
    to a different group depending on who is looking.
    """
    tz = ctx.tz
    if tz:
        tz_sql = literal(tz)
        now = func.now().op("AT TIME ZONE")(tz_sql)
        start = Task.start_date.op("AT TIME ZONE")(tz_sql)
        due = Task.due_date.op("AT TIME ZONE")(tz_sql)
    else:
        now = func.now()
        start = Task.start_date
        due = Task.due_date

    today = func.date_trunc("day", now)
    week_later = now + text("interval '7 days'")
    month_later = now + text("interval '30 days'")

    return case(
        # 0: overdue — due_date is in the past
        (due < now, 0),
        # 1: today — start_date before today, or start/due is today
        (start < today, 1),
        (func.date_trunc("day", start) == today, 1),
        (func.date_trunc("day", due) == today, 1),
        # 2: this week — start or due within 7 days
        (start <= week_later, 2),
        (due <= week_later, 2),
        # 3: this month — start or due within 30 days
        (start <= month_later, 3),
        (due <= month_later, 3),
        # 4: later — everything else
        else_=4,
    )


_COMPUTED: tuple[FieldSpec, ...] = (
    sort_only(
        "date_group",
        _date_group,
        type=FieldType.number,
        kind=ControlKind.number,
    ),
    computed(
        "status_category",
        _status_category,
        type=FieldType.enum,
        kind=ControlKind.status_category,
        ops=_IN_ONLY,
    ),
    computed(
        "assignee_ids",
        _assignee_ids,
        type=FieldType.reference,
        kind=ControlKind.member,
        # The one computed field where "is empty" means something: a task with
        # no row in task_assignees at all.
        ops=_IN_OR_EMPTY,
        nullable=True,
    ),
    computed(
        "tag_ids",
        _tag_ids,
        type=FieldType.reference,
        kind=ControlKind.tag,
        ops=_IN_ONLY,
    ),
    computed(
        "initiative_ids",
        _initiative_ids,
        type=FieldType.reference,
        kind=ControlKind.initiative,
        ops=_IN_ONLY,
    ),
    computed(
        "property_values",
        _property_values,
        type=FieldType.text,
        kind=ControlKind.property_value,
        ops=_ANY_OP,
        nullable=True,
    ),
)


def build() -> Dataset:
    """The dataset, with its model columns resolved.

    Built on call rather than at import so the columns are read once the mappers
    are configured, and so a test can rebuild it.
    """
    return Dataset(
        model=Task,
        tool=Tool.project,
        name_override="tasks",
        fields=_model_columns() + _COMPUTED,
        hidden=_HIDDEN,
    )

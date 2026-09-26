"""Reading tasks: the guild list, the cross-guild ``/me`` lists, the calendar
aggregates and the export snapshots, and the one full load a task response is
built from.

Every list reads the same field registry (``app.services.fields.tasks``) for
what it may filter and sort on, and the guild-scoped readers share one
visibility pipeline (:func:`guild_task_query_builder`), so an export always
matches the list on screen.
"""

from dataclasses import dataclass
from datetime import datetime
from operator import attrgetter
from typing import Any, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, exists, func, or_
from sqlalchemy.orm import joinedload, selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import QueryMessages
from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.core.user_input_validators import resolve_zone
from app.db.blocking import blocking_kinds
from app.db.guild_standing import ActorContext
from app.db.query import (
    apply_filters,
    apply_sorting,
    check_ops,
    clamp_page,
    extract_condition_value,
    iter_leaf_conditions,
    paginate_sequence,
    parse_conditions,
    parse_sort_fields,
)
from app.db.session import require_guild_context, routed_guild_id
from app.models.platform.guild import Guild
from app.models.platform.user import User
from app.models.tenant.comment import Comment
from app.models.tenant.project import Project
from app.models.tenant.property import (
    PropertyDefinition,
    PropertyType,
    TaskPropertyValue,
)
from app.models.tenant.relationship import EntityRelationship
from app.models.tenant.task import Task, TaskAssignee, TaskPriority
from app.schemas.query import FilterCondition, FilterGroup, FilterOp, SortDir
from app.schemas.tenant.task import TaskListRead
from app.services import fields as fields_registry
from app.services import permissions as permissions_service
from app.services.cross_guild import gather_across_guilds, member_guild_ids
from app.services.fields.spec import FieldContext, SortContext
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service
from app.services.tenant import task_checklist as checklist_service


def _date_group_expression(tz: str | None = None):
    """The date-group ordering expression, from the field registry.

    Kept as a helper because two queries select it as a labelled column rather
    than only ordering by it — the cross-guild merge sorts in Python and needs
    the value carried out of SQL.
    """
    return fields_registry.sort_expression("tasks", "date_group", _sort_ctx(tz))


def _sort_ctx(tz: str | None) -> SortContext:
    """Sorting needs only the timezone; identity is filter context."""
    return SortContext(tz=tz)


def _task_sort_fields(tz: str | None = None) -> dict[str, object]:
    """Allowed sort fields for the list endpoint, from the field registry."""
    return fields_registry.sort_fields("tasks", _sort_ctx(tz))


TASK_DEFAULT_SORT = [(Task.position, "asc"), (Task.id, "asc")]


# Attribute sorters for the cross-guild merge. attrgetter is faster than a
# lambda and avoids per-row closure overhead on large result sets. ``priority``
# and ``date_group`` need custom handling (enum order / SQL-carried value) and
# are resolved separately in _sort_global_task_keys.
_GLOBAL_SORT_ATTRGETTERS = {
    "position": attrgetter("position"),
    "title": attrgetter("title"),
    "due_date": attrgetter("due_date"),
    "start_date": attrgetter("start_date"),
    "created_at": attrgetter("created_at"),
    "updated_at": attrgetter("updated_at"),
}

# Native PG enum orders by definition order (low→urgent), not alphabetically;
# replicate that here. TaskPriority is a str-enum, so a plain-string priority
# hashes to the same key.
_PRIORITY_SORT_ORDER = {p: i for i, p in enumerate(TaskPriority)}


def _global_ordering_selectables(tz: str | None = None):
    """The columns the cross-guild ordering pass selects.

    Every sort key the /me task views accept is a plain ``tasks`` column (plus
    the SQL-computed ``date_group``), so the whole matching set can be ordered
    from rows this narrow — no relationships, no annotations. Labelled with the
    sort field names so :func:`_sort_global_task_keys` reads a row by the name
    the caller sorted on.
    """
    return (
        Task.id.label("id"),
        _date_group_expression(tz).label("date_group"),
        Task.position.label("position"),
        Task.title.label("title"),
        Task.due_date.label("due_date"),
        Task.start_date.label("start_date"),
        Task.created_at.label("created_at"),
        Task.updated_at.label("updated_at"),
        Task.priority.label("priority"),
    )


def _sort_global_task_keys(
    items: list[tuple[int, Any]],
    sort_fields: list | None,
) -> list[tuple[int, Any]]:
    """Order the merged cross-guild ordering rows.

    Cross-schema results can't be ordered by a single SQL query, so this is the
    *only* sort for the /me task views (the per-guild queries deliberately skip
    ORDER BY). ``items`` are ``(guild_id, row)`` pairs where ``row`` is a
    :func:`_global_ordering_selectables` row — the guild id travels alongside
    because task ids are unique per schema, not across them.

    Matches the guild-scoped list's ordering conventions: NULLs sort last
    regardless of direction, and ``id`` ascending breaks ties.
    """
    rows = list(items)
    if not sort_fields:
        # Deterministic default when the caller doesn't sort. position is
        # per-guild so it can't truly order across guilds, but the id tiebreaker
        # keeps the merge stable; mirrors the SQL endpoint's position-then-id.
        rows.sort(key=lambda pair: (pair[1].position, pair[1].id))
        return rows

    def _getter(field):
        if field == "date_group":
            return lambda pair: pair[1].date_group
        if field == "priority":
            # None priority → None so the nulls-last partition applies it in
            # both directions (mirrors apply_sorting()'s nulls_last()).
            return lambda pair: (
                _PRIORITY_SORT_ORDER.get(pair[1].priority)
                if pair[1].priority is not None
                else None
            )
        base = _GLOBAL_SORT_ATTRGETTERS.get(field)
        if base is None:
            return None
        return lambda pair: base(pair[1])

    # Stable radix sort: apply the least-significant key first. ``id`` asc is the
    # final tiebreaker, so it sorts first here.
    rows.sort(key=lambda pair: pair[1].id)
    for sf in reversed(sort_fields):
        getter = _getter(sf.field)
        if getter is None:
            # Unknown field: skipped, like apply_sorting() ignoring columns
            # absent from allowed_fields.
            continue
        reverse = sf.dir == SortDir.desc
        non_null = [r for r in rows if getter(r) is not None]
        nulls = [r for r in rows if getter(r) is None]
        non_null.sort(key=getter, reverse=reverse)
        rows = non_null + nulls
    return rows


def _build_task_filter_fields(
    *,
    guild_id: int,
    current_user_id: int | None,
    property_definitions: Optional[dict[int, PropertyDefinition]] = None,
) -> dict:
    """The ``allowed_fields`` mapping for a task filter, from the field registry.

    Every column and every virtual field is declared once in
    ``app.services.fields.tasks`` — the same declaration the filter UI and the
    query surface read — so this is the binding of that declaration to one
    request rather than a catalog of its own.
    """
    return fields_registry.allowed_fields(
        "tasks",
        FieldContext(
            guild_id=guild_id,
            user_id=current_user_id,
            property_definitions=property_definitions or {},
        ),
    )


def _comment_count_expression():
    """A task's comment count, as a column on the row that carries the task.

    For a read that is bounded by round trips rather than by rows — the
    cross-guild lists pay per guild they touch — the count travels with the
    task instead of costing a query of its own. Correlated on ``Task``, so it
    resolves against whichever ``tasks`` the caller's search_path names.
    """
    return (
        select(func.count(Comment.id))
        .where(Comment.task_id == Task.id)
        .correlate(Task)
        .scalar_subquery()
        .label("comment_count")
    )


def _open_blocker_count_expression():
    """How many things are still holding this task up.

    Live outbound ``depends_on`` edges whose far end is still outstanding —
    "outbound" because the source of a dependency is the end that waits.

    What counts as outstanding is per kind and comes from
    :data:`app.db.blocking.OPEN_WHEN`: a task not yet done, an event not yet
    passed, a counter short of its target. A kind with no rule there is not
    counted at all, which is the honest reading — nothing says when a document
    stops blocking. One ``EXISTS`` arm per registered kind, built from the
    registry, so a kind gains a count the day it gains a rule.

    Correlated on ``Task`` like :func:`_comment_count_expression`, so it rides
    along with the row instead of costing a query of its own. RLS does the rest:
    the relationships policy clears both endpoints, so a blocker this reader
    cannot open is not counted at them.
    """
    edge = EntityRelationship
    arms = [
        and_(
            edge.target_type == kind,
            exists(
                select(1)
                .select_from(table)
                .where(table.c["id"] == edge.target_id, open_when)
            ),
        )
        for kind, table, open_when in blocking_kinds()
    ]
    return (
        select(func.count())
        .select_from(edge)
        .where(
            edge.source_type == SearchEntityType.task.value,
            edge.source_id == Task.id,
            edge.relationship_type == RelationshipType.depends_on.value,
            edge.removed_at.is_(None),
            or_(*arms),
        )
        .correlate(Task)
        .scalar_subquery()
        .label("blocked_by_open_count")
    )


async def _annotate_tasks(
    session: AsyncSession,
    tasks: list[Task],
    *,
    comment_counts: dict[int, int] | None = None,
    blocker_counts: dict[int, int] | None = None,
) -> None:
    """Annotate tasks with comment counts, blockers and checklist progress.

    Checklist progress is read from the column the row already carries, so only
    the comment and blocker counts need a query — and passing either in skips
    even that, for a caller that selected them alongside the rows
    (:func:`_comment_count_expression`, :func:`_open_blocker_count_expression`).
    """
    task_ids = [task.id for task in tasks if task.id is not None]
    if not task_ids:
        return

    if comment_counts is None:
        stmt = (
            select(Comment.task_id, func.count(Comment.id))
            .where(Comment.task_id.in_(tuple(task_ids)))
            .group_by(Comment.task_id)
        )
        comment_counts = dict((await session.exec(stmt)).all())

    if blocker_counts is None:
        stmt = select(Task.id, _open_blocker_count_expression()).where(
            Task.id.in_(tuple(task_ids))
        )
        blocker_counts = dict((await session.exec(stmt)).all())

    for task in tasks:
        object.__setattr__(task, "comment_count", comment_counts.get(task.id, 0))
        object.__setattr__(
            task, "blocked_by_open_count", blocker_counts.get(task.id, 0)
        )
        object.__setattr__(
            task, "checklist_progress", checklist_service.progress(task.checklist)
        )


def _annotate_task_properties(tasks: list[Task]) -> None:
    """Annotate tasks with serialized ``PropertySummary`` values.

    Relies on ``task.property_values`` being eager-loaded with the
    ``property_definition`` (and ``value_user`` where relevant) relationship.
    """
    for task in tasks:
        rows = getattr(task, "property_values", []) or []
        summaries = properties_service.summaries_from_rows(rows)
        object.__setattr__(task, "properties", summaries)


def _task_to_list_read(
    task: Task,
    *,
    guild_id: int | None = None,
    guild_name: str | None = None,
) -> TaskListRead:
    """Convert an annotated Task to the lightweight TaskListRead schema.

    Read off the row like ``TaskRead``, so a column the schema gains reaches
    every list with nothing added here. What the row does not carry is filled
    in: the project and initiative names, and ``guild_id`` — the community the
    row was read in, the route's for a guild-scoped list and for a cross-guild
    one the schema each row came from, because rows from several are merged
    after the session has moved on. ``guild_name`` goes with it, for the same
    reason.
    """
    project = task.project
    initiative = project.initiative if project else None
    return TaskListRead.model_validate(task, from_attributes=True).model_copy(
        update={
            "guild_id": guild_id,
            "guild_name": guild_name,
            "project_name": project.name if project else None,
            "initiative_id": initiative.id if initiative else None,
            "initiative_name": initiative.name if initiative else None,
            "initiative_color": initiative.color if initiative else None,
        }
    )


async def list_reads(
    session: AsyncSession, tasks: list[Task], guild_id: int | None
) -> list[TaskListRead]:
    """List rows for tasks loaded with :data:`LIST_ROW_OPTIONS`."""
    await _annotate_tasks(session, tasks)
    await tags_service.annotate_tags(session, tasks)
    _annotate_task_properties(tasks)
    return [_task_to_list_read(task, guild_id=guild_id) for task in tasks]


#: What a list row reads beyond the task itself.
LIST_ROW_OPTIONS = (
    selectinload(Task.project).selectinload(Project.initiative),
    selectinload(Task.assignees),
    selectinload(Task.task_status),
    selectinload(Task.property_values).selectinload(
        TaskPropertyValue.property_definition
    ),
    selectinload(Task.property_values).selectinload(TaskPropertyValue.value_user),
)

#: What an export row reads beyond the task itself.
_EXPORT_ROW_OPTIONS = (
    selectinload(Task.project),
    selectinload(Task.assignees),
    selectinload(Task.task_status),
)


def list_statement(build, q: "TaskListQuery", *options):
    """``build``'s tasks in the order ``q`` asked for, loaded with ``options``."""
    return apply_sorting(
        build(select(Task)).options(*options),
        Task,
        sort_fields=q.sort_fields,
        allowed_fields=_task_sort_fields(q.tz),
        default_sort=TASK_DEFAULT_SORT,
    )


async def load_tasks(session: AsyncSession, task_ids: list[int]) -> list[Task]:
    """Tasks with everything a ``TaskRead`` reads, in board order.

    The many-to-one links are joined onto the row and the counts ride along as
    columns, so the whole response costs the row plus one query per
    collection. Always ``populate_existing``: a caller that just wrote through
    the session reads the rows as they now are rather than as the identity map
    last saw them.
    """
    if not task_ids:
        return []
    statement = (
        select(Task, _comment_count_expression(), _open_blocker_count_expression())
        .where(Task.id.in_(tuple(task_ids)))
        .options(
            joinedload(Task.project).joinedload(Project.initiative),
            joinedload(Task.task_status),
            joinedload(Task.creator),
            selectinload(Task.assignees),
            selectinload(Task.property_values).options(
                selectinload(TaskPropertyValue.property_definition),
                selectinload(TaskPropertyValue.value_user),
            ),
        )
        .order_by(Task.position.asc(), Task.id.asc())
        .execution_options(populate_existing=True)
    )
    rows = (await session.exec(statement)).all()
    tasks = [row[0] for row in rows]
    await _annotate_tasks(
        session,
        tasks,
        comment_counts={row[0].id: row[1] for row in rows},
        blocker_counts={row[0].id: row[2] for row in rows},
    )
    await tags_service.annotate_tags(session, tasks)
    _annotate_task_properties(tasks)
    return tasks


async def load_task(session: AsyncSession, task_id: int) -> Task | None:
    """One task with everything a ``TaskRead`` reads (:func:`load_tasks`)."""
    return next(iter(await load_tasks(session, [task_id])), None)


def _confining_project_id(
    conditions: list[FilterCondition | FilterGroup],
) -> Optional[int]:
    """The single project this request is narrowed to, or ``None``.

    Only a plain top-level equality on one id confines a request to a project.
    ``project_id != 5`` and ``project_id NOT IN []`` both name a value while
    leaving the request spanning every other project in the community, so the
    scope question they ask is the cross-initiative one — and the answer to
    "which rows may this reader see" must not turn on a value the filter is
    about to discard.

    Deliberately stricter than :func:`extract_condition_value`, which reports a
    value for any of those shapes: this one decides access, and the only shape
    that decides it is the one that actually holds for every row returned.
    """
    for cond in conditions:
        if isinstance(cond, FilterGroup) or cond.field != "project_id":
            continue
        if cond.negate or cond.op is not FilterOp.eq:
            return None
        if isinstance(cond.value, (list, tuple, set)):
            return None
        try:
            return int(cond.value)
        except (TypeError, ValueError):
            return None
    return None


async def _allowed_project_ids(
    session: AsyncSession,
    user: User | None,
    context: ActorContext,
    *,
    include_templates: bool = False,
    project_id: Optional[int] = None,
) -> Optional[set[int]]:
    """Project ids whose tasks this request may see.

    The set stays explicitly guild-scoped either way; the sharing gate on top of
    it follows the scope being asked about, the same rule the tool listings
    follow. Confined to one project, the question is the reader's standing in
    the initiative holding it, and a guild admin's reaches all of it. Spanning
    them — the tag browse, the community calendar's task markers — the question
    is what has been shared with the reader, so the answer matches the events
    those markers sit beside.
    """
    conditions = [
        Project.archived_at.is_(None),
    ]
    if project_id is None:
        # Spanning initiatives, the answer is what has been shared with the
        # reader, which is a narrower question than "may I reach it" — so it
        # stays here rather than resting on the table's own policy.
        conditions.append(
            permissions_service.granted_scope_clause(
                Tool.project,
                Project.id,
                user.id if user is not None else None,
                context=context,
            )
        )
    if not include_templates:
        conditions.append(Project.is_template == False)  # noqa: E712
    stmt = select(Project.id).join(Project.initiative).where(*conditions)
    result = await session.exec(stmt)
    return {pid for pid in result.all() if pid is not None}


def _global_task_options():
    """Loaders for the hydration pass of a cross-guild task list.

    project → initiative → guild is a chain of many-to-one links, so it is
    joined onto the row rather than fetched with a query per level: a
    ``selectinload`` there cost three extra round trips per guild the page draws
    from, and this endpoint is bounded by round trips. The collections stay on
    ``selectinload``, which is what it is for.
    """
    return (
        joinedload(Task.project).joinedload(Project.initiative),
        selectinload(Task.assignees),
        selectinload(Task.task_status),
        selectinload(Task.property_values).selectinload(
            TaskPropertyValue.property_definition
        ),
        selectinload(Task.property_values).selectinload(TaskPropertyValue.value_user),
    )


async def _gather_global_task_reads(
    session: AsyncSession,
    current_user: User,
    *,
    build_query,
    guild_ids: Optional[List[int]],
    page: int,
    page_size: int,
    sort_fields: list | None = None,
    tz: str | None = None,
) -> tuple[list[TaskListRead], int, int]:
    """Run a per-guild task query across every guild the user belongs to and
    merge into TaskListReads.

    Two passes, because a single SQL query can't order across guild schemas and
    the ordering has to see the whole matching set before anything can be paged:

    1. **Order.** Each guild returns :func:`_global_ordering_selectables` rows —
       the sort keys and the id, nothing else — *without* ORDER BY, and the
       merged set is sorted once, globally, by :func:`_sort_global_task_keys`
       and then sliced to the requested page.
    2. **Hydrate.** Only the ids on that page are loaded with their
       relationships and annotations, and only from the guilds that actually
       contribute to it. By id alone: the filters are not re-applied, so a
       concurrent edit cannot drop a row the ordering pass already counted.

    The split is what keeps the cost of this endpoint proportional to the page
    rather than to everything the filter matches: a reader with hundreds of
    assigned tasks across half a dozen guilds used to pay the relationship
    loads, comment counts, tag and property annotation for every one of them to
    show twenty.

    ``build_query(guild_id, *selectables)`` receives the guild id so it can
    compile the guild-local filter fields (tag/property subqueries resolve
    against that guild's schema), and what to select.
    """
    target_guilds = await member_guild_ids(
        session, current_user.id, restrict_to=guild_ids
    )
    # Names for the guild column of each row, read once on the user context
    # before the session starts routing into schemas.
    guild_names: dict[int, str] = (
        dict(
            (
                await session.exec(
                    select(Guild.id, Guild.name).where(Guild.id.in_(target_guilds))
                )
            ).all()
        )
        if target_guilds
        else {}
    )

    ordering = _global_ordering_selectables(tz)

    async def _order_keys(
        guild_session: AsyncSession, _guild_id: int
    ) -> list[tuple[int, Any]]:
        rows = (await guild_session.exec(build_query(_guild_id, *ordering))).all()
        return [(_guild_id, row) for row in rows]

    keys = await gather_across_guilds(
        session, current_user.id, target_guilds, _order_keys
    )
    # Sort across ALL guilds before slicing — the per-guild queries return rows
    # unordered, so this is where global ordering is established.
    keys = _sort_global_task_keys(keys, sort_fields)
    total_count = len(keys)
    actual_page = clamp_page(page, page_size, total_count)
    # One slicing rule for every page_size, including the windowed
    # page_size<=0 "fetch all" protocol (bounded response, nothing
    # unreachable — the caller walks pages until has_next is false).
    window = paginate_sequence(keys, actual_page, page_size)
    if not window:
        return [], total_count, actual_page

    # (guild, task) -> where it sits on the page, so the hydrated rows come back
    # in the order the global sort established rather than in guild order.
    placement: dict[tuple[int, int], int] = {}
    wanted: dict[int, list[int]] = {}
    for index, (guild_id, row) in enumerate(window):
        wanted.setdefault(guild_id, []).append(row.id)
        placement[(guild_id, row.id)] = index

    async def _hydrate(
        guild_session: AsyncSession, _guild_id: int
    ) -> list[tuple[int, TaskListRead]]:
        ids = wanted.get(_guild_id)
        if not ids:
            return []
        # By id ALONE — deliberately not through ``build_query``. Re-applying
        # the filters here would let a concurrent edit drop a row the ordering
        # pass already counted: a task that goes done, gets reassigned or is
        # archived between the two statements would stop matching, and the page
        # would come back a row short of the ``total_count`` and ``has_next``
        # computed from the first pass. Access does not rest on those filters —
        # it rests on the guild schema this session is routed into and on
        # ``initiative_access``, and both apply to this statement exactly as
        # they did to the one that chose the ids a moment ago.
        statement = (
            select(
                Task,
                _comment_count_expression(),
                _open_blocker_count_expression(),
            )
            .where(Task.id.in_(tuple(ids)))
            .options(*_global_task_options())
        )
        rows = list((await guild_session.exec(statement)).unique().all())
        tasks = [row[0] for row in rows]
        comment_counts = {row[0].id: row[1] for row in rows}
        blocker_counts = {row[0].id: row[2] for row in rows}
        await _annotate_tasks(
            guild_session,
            tasks,
            comment_counts=comment_counts,
            blocker_counts=blocker_counts,
        )
        await tags_service.annotate_tags(guild_session, tasks)
        _annotate_task_properties(tasks)
        return [
            (
                placement[(_guild_id, task.id)],
                _task_to_list_read(
                    task, guild_id=_guild_id, guild_name=guild_names.get(_guild_id)
                ),
            )
            for task in tasks
        ]

    hydrated = await gather_across_guilds(
        session, current_user.id, sorted(wanted), _hydrate
    )
    hydrated.sort(key=lambda pair: pair[0])
    return [read for _, read in hydrated], total_count, actual_page


async def list_global_tasks(
    session: AsyncSession,
    current_user: User,
    q: "TaskListQuery",
    *,
    created: bool = False,
    include_archived: bool = False,
    page: int = 1,
    page_size: int = 20,
    start_after: datetime | None = None,
    start_before: datetime | None = None,
) -> tuple[list[TaskListRead], int, int]:
    """Tasks assigned to the user — or, ``created``, the ones they created —
    across every guild they belong to.

    ``q``'s conditions are applied per guild via :func:`apply_filters` using the
    same field set as the guild-scoped list, so any Task field — ``due_date``,
    ``title``, ``priority``, ``status_category``, property values, … — filters
    here too. ``start_after``/``start_before`` window the set to tasks whose
    start or due date falls inside — used by the ``/me`` calendar aggregate (the
    window travels as explicit params so a caller never has to encode it in
    ``conditions``).
    """
    base_conditions = [
        Task.created_by == current_user.id
        if created
        else TaskAssignee.user_id == current_user.id,
        Project.archived_at.is_(None),
        Project.is_template.is_(False),
    ]
    if not include_archived:
        base_conditions.append(Task.archived_at.is_(None))
    window = _task_calendar_window_clause(start_after, start_before)
    if window is not None:
        base_conditions.append(window)

    def _build(guild_id: int, *selectables):
        # Defines the filtered set for the ordering pass, which selects the
        # sort keys from it. ORDER BY is omitted — _sort_global_task_keys orders
        # the merged set, which no single schema's query can do.
        stmt = select(*selectables)
        if not created:
            stmt = stmt.join(TaskAssignee, TaskAssignee.task_id == Task.id)
        stmt = stmt.join(Task.project).join(Project.initiative).where(*base_conditions)
        return apply_filters(
            stmt,
            Task,
            q.user_conditions,
            allowed_ops=fields_registry.allowed_ops("tasks"),
            allowed_fields=_build_task_filter_fields(
                guild_id=guild_id,
                current_user_id=current_user.id,
                property_definitions=q.property_definitions,
            ),
        )

    return await _gather_global_task_reads(
        session,
        current_user,
        build_query=_build,
        guild_ids=q.guild_ids,
        page=page,
        page_size=page_size,
        sort_fields=q.sort_fields,
        tz=q.tz,
    )


@dataclass
class TaskListQuery:
    """Parsed task list/filter query params, shared by the guild-scoped list
    and the cross-guild /me aggregates so they stay in lockstep."""

    user_conditions: list
    sort_fields: Optional[list]
    tz: Optional[str]
    # project_id narrows which projects the guild path checks access on; guild_ids
    # restricts the cross-guild fan-out. Every other field filters through
    # ``user_conditions`` via apply_filters, so no other scalar is extracted here.
    project_id: Optional[int]
    guild_ids: Optional[list]
    property_definitions: dict


async def parse_task_list_query(
    session,
    conditions: Optional[str],
    sorting: Optional[str],
    tz: Optional[str],
    *,
    across_guilds_for: User | None = None,
) -> TaskListQuery:
    """Validate + extract task list query params (conditions, sort, tz,
    property-value filters). Raises 400 on malformed input.

    ``across_guilds_for`` is the reader of a cross-guild ``/me`` list, whose
    session runs in the ``public`` search_path and cannot see any guild's
    ``property_definitions`` table; the definitions are then read in each of
    their guilds (:func:`_load_property_definitions_across_guilds`)."""
    try:
        user_conditions = parse_conditions(conditions)
        # Operators are checked here rather than at query-build time so an
        # unsupported one is the same 400 as any other malformed filter.
        check_ops(user_conditions, fields_registry.allowed_ops("tasks"))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueryMessages.INVALID_CONDITIONS,
        )

    try:
        sort_fields = parse_sort_fields(sorting) or None
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueryMessages.INVALID_SORT_FIELDS,
        )

    tz = resolve_zone(tz).key if tz else None

    # Every property_values leaf, wherever it sits, so its definition is loaded
    # and the limit counts what the query actually compiles.
    property_value_leaves = [
        cond
        for cond in iter_leaf_conditions(user_conditions)
        if cond.field == "property_values"
    ]
    if len(property_value_leaves) > properties_service.MAX_PROPERTY_FILTERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueryMessages.INVALID_CONDITIONS,
        )
    property_ids_needed: list[int] = []
    for cond in property_value_leaves:
        if isinstance(cond.value, dict):
            try:
                property_ids_needed.append(int(cond.value.get("property_id")))
            except (TypeError, ValueError):
                continue
    guild_ids = extract_condition_value(user_conditions, "guild_ids")
    if across_guilds_for is not None:
        property_definitions = await _load_property_definitions_across_guilds(
            session, across_guilds_for, property_ids_needed, guild_ids
        )
    else:
        property_definitions = await properties_service.load_definitions_by_ids(
            session, property_ids_needed
        )

    return TaskListQuery(
        user_conditions=user_conditions,
        sort_fields=sort_fields,
        tz=tz,
        project_id=extract_condition_value(user_conditions, "project_id"),
        guild_ids=guild_ids,
        property_definitions=property_definitions,
    )


#: Task filter fields whose values name people by row id.
_PERSON_FILTER_FIELDS = frozenset({"assignee_ids", "created_by"})


def refuse_person_filters(q: TaskListQuery) -> None:
    """Refuse, for an installed app, a filter that names people.

    A filter's values are row ids inside a JSON string, which an app does not
    hold, so the fields that take one are left to people: ``assignee_ids``
    and ``created_by`` (bar asking whether there is one), and a
    person-valued custom property.
    """
    for cond in iter_leaf_conditions(q.user_conditions):
        named = cond.field in _PERSON_FILTER_FIELDS and cond.op is not FilterOp.is_null
        if cond.field == "property_values" and isinstance(cond.value, dict):
            try:
                defn = q.property_definitions.get(int(cond.value.get("property_id")))
            except (TypeError, ValueError):
                defn = None
            named = defn is not None and defn.type is PropertyType.user_reference
        if named:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=QueryMessages.INVALID_CONDITIONS,
            )


async def _load_property_definitions_across_guilds(
    session: AsyncSession,
    current_user: User,
    needed: list[int],
    guild_ids: Optional[list],
) -> dict[int, PropertyDefinition]:
    """Load the property definitions a cross-guild ``/me`` list needs, routing
    into each of the user's guild schemas.

    The ``/me`` session runs in the ``public`` search_path and cannot see any
    guild's ``property_definitions`` table, so the definitions must be loaded
    under the same per-guild routing the aggregate list itself uses. A property
    definition id is unique per guild schema; the compiled filter clause only
    needs the definition's *type* (which typed column to compare), so the first
    guild that resolves an id wins and its type is reused for every guild's
    schema-local ``property_id`` predicate."""
    if not needed:
        return {}

    target_guilds = await member_guild_ids(
        session, current_user.id, restrict_to=guild_ids
    )

    async def _fetch(guild_session, _guild_id: int):
        defs = await properties_service.load_definitions_by_ids(guild_session, needed)
        return list(defs.values())

    definitions = await gather_across_guilds(
        session, current_user.id, target_guilds, _fetch
    )
    merged: dict[int, PropertyDefinition] = {}
    for defn in definitions:
        merged.setdefault(defn.id, defn)
    return merged


async def guild_task_query_builder(
    session,
    current_user: User | None,
    context: ActorContext,
    *,
    q: TaskListQuery,
    include_archived: bool,
):
    """The guild-scoped task visibility pipeline (guild scope, archived
    default, project DAC, filter conditions) as a statement-builder closure.
    Shared by ``list_tasks`` and the tasks export so an export always matches
    the on-screen list. Returns ``None`` when no project is reachable."""
    access_conditions: list = []

    if not include_archived:
        access_conditions.append(Task.archived_at.is_(None))

    allowed_ids = await _allowed_project_ids(
        session,
        current_user,
        context,
        include_templates=q.project_id is not None,
        # Access takes the strict reading, not the one that decides whether
        # templates join the set.
        project_id=_confining_project_id(q.user_conditions),
    )
    if allowed_ids is not None:
        if not allowed_ids:
            return None
        access_conditions.append(Task.project_id.in_(tuple(allowed_ids)))

    filter_fields = _build_task_filter_fields(
        guild_id=context.guild_id,
        current_user_id=current_user.id if current_user is not None else None,
        property_definitions=q.property_definitions,
    )

    def build(stmt):
        stmt = stmt.join(Task.project).join(Project.initiative)
        stmt = stmt.where(*access_conditions)
        return apply_filters(
            stmt,
            Task,
            q.user_conditions,
            allowed_fields=filter_fields,
            allowed_ops=fields_registry.allowed_ops("tasks"),
        )

    return build


async def count_tasks_for_export(
    session,
    current_user: User,
    *,
    conditions: Optional[str] = None,
    sorting: Optional[str] = None,
    tz: Optional[str] = None,
    include_archived: bool = False,
) -> int:
    """Row count for an export snapshot — the cheap pre-render signal for the
    inline-vs-job auto-select and the export size ceiling."""
    q = await parse_task_list_query(session, conditions, sorting, tz)
    build = await guild_task_query_builder(
        session,
        current_user,
        require_guild_context(session),
        q=q,
        include_archived=include_archived,
    )
    if build is None:
        return 0
    count_subq = build(select(Task.id)).subquery()
    return (await session.exec(select(func.count()).select_from(count_subq))).one()


async def query_tasks_for_export(
    session,
    current_user: User,
    *,
    conditions: Optional[str] = None,
    sorting: Optional[str] = None,
    tz: Optional[str] = None,
    include_archived: bool = False,
    max_rows: int,
) -> list[Task]:
    """The tasks export adapter's query seam: the exact ``list_tasks``
    visibility/filter/sort pipeline, unpaginated up to ``max_rows``, with the
    eager loads the export payload needs."""
    q = await parse_task_list_query(session, conditions, sorting, tz)
    build = await guild_task_query_builder(
        session,
        current_user,
        require_guild_context(session),
        q=q,
        include_archived=include_archived,
    )
    if build is None:
        return []
    statement = list_statement(build, q, *_EXPORT_ROW_OPTIONS)
    tasks = list(await session.exec(statement.limit(max_rows)))
    await tags_service.annotate_tags(session, tasks)
    return tasks


async def query_tasks_for_detailed_export(
    session,
    current_user: User,
    *,
    conditions: Optional[str] = None,
    sorting: Optional[str] = None,
    tz: Optional[str] = None,
    include_archived: bool = False,
    max_rows: int,
) -> tuple[list[Task], dict[int, list[Comment]]]:
    """Detailed-report seam: the same ``list_tasks`` visibility/filter/sort
    pipeline as ``query_tasks_for_export``, but with the extra eager loads a
    one-task-per-page report needs (tags) plus each task's comments
    batch-loaded by id. Comments have no ``Task`` relationship, so they are
    fetched separately — under the caller's RLS session, scoped to the same
    initiatives the tasks came from (the tasks are already visibility-filtered,
    so their comments are in reachable initiatives)."""
    q = await parse_task_list_query(session, conditions, sorting, tz)
    build = await guild_task_query_builder(
        session,
        current_user,
        require_guild_context(session),
        q=q,
        include_archived=include_archived,
    )
    if build is None:
        return [], {}
    statement = list_statement(build, q, *_EXPORT_ROW_OPTIONS)
    tasks = list(await session.exec(statement.limit(max_rows)))
    await tags_service.annotate_tags(session, tasks)
    comments = await _load_comments_for_tasks(session, [t.id for t in tasks if t.id])
    return tasks, comments


async def _load_comments_for_tasks(
    session, task_ids: list[int]
) -> dict[int, list[Comment]]:
    """Non-deleted comments for the given tasks, author eager-loaded, grouped
    by task id and ordered oldest-first (reading order for a report)."""
    if not task_ids:
        return {}
    statement = (
        select(Comment)
        .where(
            Comment.task_id.in_(task_ids),
            Comment.deleted_at.is_(None),
        )
        .options(selectinload(Comment.author))
        .order_by(Comment.created_at)
    )
    grouped: dict[int, list[Comment]] = {}
    for comment in await session.exec(statement):
        grouped.setdefault(comment.task_id, []).append(comment)
    return grouped


def _task_calendar_window_clause(
    start_after: Optional[datetime], start_before: Optional[datetime]
):
    """Keep only tasks that sit on a calendar within ``[start_after,
    start_before]`` — i.e. whose ``start_date`` OR ``due_date`` falls in the
    window (a task placed by either endpoint belongs on the calendar).

    Returns ``None`` when neither bound is given (no windowing). This is the
    aggregate's authoritative task window: the named params bound the task leg
    directly, so a caller never has to duplicate the window inside ``conditions``
    (and the cross-guild ``/me`` path can't express it there at all).
    """
    if start_after is None and start_before is None:
        return None
    field_clauses = []
    for field in (Task.start_date, Task.due_date):
        bounds = []
        if start_after is not None:
            bounds.append(field >= start_after)
        if start_before is not None:
            bounds.append(field <= start_before)
        field_clauses.append(and_(*bounds))
    return or_(*field_clauses)


async def query_guild_tasks(
    session: AsyncSession,
    current_user: User,
    guild_context: ActorContext,
    *,
    conditions: Optional[str] = None,
    sorting: Optional[str] = None,
    tz: Optional[str] = None,
    include_archived: bool = False,
    start_after: Optional[datetime] = None,
    start_before: Optional[datetime] = None,
) -> list[TaskListRead]:
    """Fetch every guild task matching the filter (no pagination).

    Shared by the ``calendar-entries`` aggregate, whose date window is bounded so
    the whole matching set is small. Mirrors ``list_tasks`` minus paging: same
    parse → guild query builder → eager loads → sort → annotate → serialize path,
    so access + shaping are identical. ``start_after``/``start_before`` bound the
    result to the calendar window regardless of ``conditions``.
    """
    q = await parse_task_list_query(session, conditions, sorting, tz)
    build = await guild_task_query_builder(
        session,
        current_user,
        guild_context,
        q=q,
        include_archived=include_archived,
    )
    if build is None:
        return []
    statement = list_statement(build, q, *LIST_ROW_OPTIONS)
    window = _task_calendar_window_clause(start_after, start_before)
    if window is not None:
        statement = statement.where(window)
    tasks = list((await session.exec(statement)).all())
    return await list_reads(session, tasks, routed_guild_id(session))


async def query_my_tasks_list(
    session: AsyncSession,
    current_user: User,
    *,
    conditions: Optional[str] = None,
    sorting: Optional[str] = None,
    tz: Optional[str] = None,
    include_archived: bool = False,
    start_after: Optional[datetime] = None,
    start_before: Optional[datetime] = None,
) -> list[TaskListRead]:
    """Fetch every cross-guild assigned task matching the filter (no paging).

    Shared by the ``/me/calendar-entries`` aggregate; mirrors ``list_my_tasks``
    with ``page_size=0`` (the global path's fetch-all).
    ``start_after``/``start_before`` bound the result to the calendar window —
    the global path applies only extracted scalar filters, so the window can
    only be expressed through these params, never through ``conditions``.
    """
    q = await parse_task_list_query(
        session, conditions, sorting, tz, across_guilds_for=current_user
    )
    items, _total, _page = await list_global_tasks(
        session,
        current_user,
        q,
        include_archived=include_archived,
        page=1,
        page_size=0,
        start_after=start_after,
        start_before=start_before,
    )
    return items

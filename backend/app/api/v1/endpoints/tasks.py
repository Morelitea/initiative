from datetime import datetime, timezone
from typing import Annotated, List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import selectinload
from sqlalchemy import case, func, text
from sqlmodel import select, delete

from app.db.query import (
    apply_filters,
    apply_sorting,
    build_paginated_response,
    extract_condition_value,
    paginated_query,
    parse_conditions,
    parse_sort_fields,
)
from app.schemas.query import FilterOp

from app.api.deps import (
    RLSSessionDep,
    SessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
)
from app.db.session import reapply_rls_context
from app.models.project import Project, ProjectPermission, ProjectRolePermission
from app.models.initiative import Initiative, InitiativeMember
from app.models.task import Task, TaskAssignee, TaskPriority, TaskStatus, TaskStatusCategory, Subtask
from app.models.tag import Tag, TaskTag
from app.models.user import User
from app.models.guild import GuildMembership
from app.models.comment import Comment
from pydantic import BaseModel, ValidationError

from app.schemas.task import TaskCreate, TaskListRead, TaskListResponse, TaskMoveRequest, TaskRead, TaskReorderRequest, TaskRecurrence, TaskUpdate
from app.schemas.subtask import (
    SubtaskBatchCreate,
    SubtaskCreate,
    SubtaskRead,
    SubtaskReorderRequest,
    SubtaskUpdate,
    TaskSubtaskProgress,
)
from app.schemas.ai_generation import GenerateSubtasksResponse, GenerateDescriptionResponse
from app.schemas.tag import TagSummary, TagSetRequest
from app.services.realtime import broadcast_event
from app.services import notifications as notifications_service
from app.services import permissions as permissions_service
from app.services.recurrence import get_next_due_date
from app.services import task_statuses as task_statuses_service
from app.services import ai_generation as ai_generation_service
from app.core.messages import ProjectMessages, QueryMessages, TaskMessages, SubtaskMessages

router = APIRouter()


def _date_group_expression():
    """SQL CASE mirroring frontend getTaskDateStatus() logic.

    Returns a numeric group:
      0 = overdue (due_date in the past)
      1 = today (start_date before today OR start/due is today)
      2 = this week (start or due within 7 days)
      3 = this month (start or due within 30 days)
      4 = later (everything else)
    """
    now = func.now()
    today = func.date_trunc("day", now)
    week_later = now + text("interval '7 days'")
    month_later = now + text("interval '30 days'")

    return case(
        # 0: overdue — due_date is in the past
        (Task.due_date < now, 0),
        # 1: today — start_date before today, or start/due is today
        (Task.start_date < today, 1),
        (func.date_trunc("day", Task.start_date) == today, 1),
        (func.date_trunc("day", Task.due_date) == today, 1),
        # 2: this week — start or due within 7 days
        (Task.start_date <= week_later, 2),
        (Task.due_date <= week_later, 2),
        # 3: this month — start or due within 30 days
        (Task.start_date <= month_later, 3),
        (Task.due_date <= month_later, 3),
        # 4: later — everything else
        else_=4,
    )


# Allowed sort fields for the list endpoint
TASK_SORT_FIELDS: dict[str, object] = {
    "sort_order": Task.sort_order,
    "title": Task.title,
    "due_date": Task.due_date,
    "start_date": Task.start_date,
    "priority": Task.priority,
    "created_at": Task.created_at,
    "updated_at": Task.updated_at,
    "date_group": _date_group_expression(),
}


TASK_DEFAULT_SORT = [(Task.sort_order, "asc"), (Task.id, "asc")]


def _build_task_filter_fields(*, guild_id: int, current_user_id: int) -> dict:
    """Build allowed_fields dict from Task model columns plus callable overrides.

    Every column on the Task table is automatically available as a filter
    field (e.g. ``project_id``, ``priority``, ``due_date``, ``title``).
    Virtual fields that require subqueries (``status_category``,
    ``assignee_ids``, ``tag_ids``, ``initiative_ids``) are added as
    callable handlers that receive ``(op, value)`` and return a SA clause.
    """
    # Auto-populate from model columns
    fields: dict = {
        col.name: getattr(Task, col.name)
        for col in Task.__table__.columns
    }

    # Callable overrides for virtual / cross-table fields
    def _status_category_handler(op: FilterOp, value):
        if not value:
            return None
        subq = select(TaskStatus.id).where(
            TaskStatus.category.in_(tuple(value))
        )
        return Task.task_status_id.in_(subq)

    def _assignee_ids_handler(op: FilterOp, value):
        if not value:
            return None
        user_ids = []
        for aid in value:
            if aid == "me":
                user_ids.append(current_user_id)
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
        subq = (
            select(TaskAssignee.task_id)
            .where(TaskAssignee.user_id.in_(tuple(user_ids)))
        )
        return Task.id.in_(subq)

    def _tag_ids_handler(op: FilterOp, value):
        if not value:
            return None
        subq = (
            select(TaskTag.task_id)
            .join(Tag, Tag.id == TaskTag.tag_id)
            .where(
                TaskTag.tag_id.in_(tuple(value)),
                Tag.guild_id == guild_id,
            )
            .distinct()
        )
        return Task.id.in_(subq)

    def _initiative_ids_handler(op: FilterOp, value):
        if not value:
            return None
        subq = select(Project.id).where(
            Project.initiative_id.in_(tuple(value))
        )
        return Task.project_id.in_(subq)

    fields["status_category"] = _status_category_handler
    fields["assignee_ids"] = _assignee_ids_handler
    fields["tag_ids"] = _tag_ids_handler
    fields["initiative_ids"] = _initiative_ids_handler

    return fields





subtasks_router = APIRouter()
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


async def _next_sort_order(session: SessionDep, project_id: int) -> float:
    result = await session.exec(select(func.max(Task.sort_order)).where(Task.project_id == project_id))
    max_value = result.one_or_none()
    return (max_value or 0) + 1


async def _annotate_tasks(session: SessionDep, tasks: list[Task]) -> None:
    """Annotate tasks with comment counts and subtask progress in a single query."""
    task_ids = [task.id for task in tasks if task.id is not None]
    if not task_ids:
        return

    ids_tuple = tuple(task_ids)

    # Single query: LEFT JOIN comments and subtasks aggregations via subqueries
    comment_subq = (
        select(
            Comment.task_id.label("task_id"),
            func.count(Comment.id).label("comment_count"),
        )
        .where(Comment.task_id.in_(ids_tuple))
        .group_by(Comment.task_id)
        .subquery()
    )
    subtask_subq = (
        select(
            Subtask.task_id.label("task_id"),
            func.count(Subtask.id).label("total"),
            func.sum(case((Subtask.is_completed.is_(True), 1), else_=0)).label("completed"),
        )
        .where(Subtask.task_id.in_(ids_tuple))
        .group_by(Subtask.task_id)
        .subquery()
    )

    stmt = (
        select(
            Task.id,
            func.coalesce(comment_subq.c.comment_count, 0),
            subtask_subq.c.total,
            subtask_subq.c.completed,
        )
        .outerjoin(comment_subq, comment_subq.c.task_id == Task.id)
        .outerjoin(subtask_subq, subtask_subq.c.task_id == Task.id)
        .where(Task.id.in_(ids_tuple))
    )
    result = await session.exec(stmt)
    annotations: dict[int, tuple] = {
        row[0]: (row[1], row[2], row[3]) for row in result.all()
    }

    for task in tasks:
        comment_count, sub_total, sub_completed = annotations.get(task.id, (0, None, None))
        object.__setattr__(task, "comment_count", comment_count)
        if sub_total is not None:
            progress = TaskSubtaskProgress(
                completed=int(sub_completed or 0),
                total=int(sub_total),
            )
            object.__setattr__(task, "subtask_progress", progress)
        else:
            object.__setattr__(task, "subtask_progress", None)


def _annotate_task_guild(tasks: list[Task]) -> None:
    for task in tasks:
        project = getattr(task, "project", None)
        initiative = getattr(project, "initiative", None) if project else None
        guild = getattr(initiative, "guild", None) if initiative else None
        object.__setattr__(task, "guild", guild)


def _annotate_task_tags(tasks: list[Task]) -> None:
    """Annotate tasks with their tags extracted from tag_links relationship."""
    for task in tasks:
        tag_links = getattr(task, "tag_links", [])
        tags = [
            TagSummary(id=link.tag.id, name=link.tag.name, color=link.tag.color)
            for link in tag_links
            if link.tag is not None
        ]
        object.__setattr__(task, "tags", tags)


def _task_to_list_read(task: Task) -> TaskListRead:
    """Convert Task model to lightweight TaskListRead schema"""
    from app.schemas.task import TaskAssigneeSummary

    project = getattr(task, "project", None)
    initiative = getattr(project, "initiative", None) if project else None
    guild = getattr(initiative, "guild", None) if initiative else None

    assignees = [
        TaskAssigneeSummary(
            id=assignee.id,
            full_name=assignee.full_name,
            avatar_url=assignee.avatar_url,
            avatar_base64=assignee.avatar_base64,
        )
        for assignee in task.assignees
    ]

    return TaskListRead(
        id=task.id,
        title=task.title,
        description=task.description,
        project_id=task.project_id,
        task_status_id=task.task_status_id,
        task_status=task.task_status,
        priority=task.priority,
        start_date=task.start_date,
        due_date=task.due_date,
        recurrence=task.recurrence,
        recurrence_strategy=task.recurrence_strategy,
        created_at=task.created_at,
        updated_at=task.updated_at,
        sort_order=task.sort_order,
        is_archived=task.is_archived,
        created_by_id=task.created_by_id,
        assignees=assignees,
        recurrence_occurrence_count=task.recurrence_occurrence_count,
        comment_count=getattr(task, "comment_count", 0),
        guild_id=guild.id if guild else None,
        guild_name=guild.name if guild else None,
        project_name=project.name if project else None,
        initiative_id=initiative.id if initiative else None,
        initiative_name=initiative.name if initiative else None,
        initiative_color=initiative.color if initiative else None,
        subtask_progress=getattr(task, "subtask_progress", None),
        tags=getattr(task, "tags", []),
    )


async def _list_subtasks_for_task(session: SessionDep, task_id: int) -> list[Subtask]:
    stmt = (
        select(Subtask)
        .where(Subtask.task_id == task_id)
        .order_by(Subtask.position.asc(), Subtask.id.asc())
    )
    result = await session.exec(stmt)
    return result.all()


async def _clone_subtasks(session: SessionDep, source_task_id: int, target_task_id: int) -> None:
    subtasks = await _list_subtasks_for_task(session, source_task_id)
    if not subtasks:
        return
    clones = [
        Subtask(
            task_id=target_task_id,
            content=subtask.content,
            position=subtask.position,
            is_completed=False,
        )
        for subtask in subtasks
    ]
    session.add_all(clones)


async def _next_subtask_position(session: SessionDep, task_id: int) -> int:
    result = await session.exec(select(func.max(Subtask.position)).where(Subtask.task_id == task_id))
    max_value = result.one_or_none()
    return (max_value or 0) + 1


def _touch_task(task: Task, *, timestamp: datetime | None = None) -> datetime:
    now = timestamp or datetime.now(timezone.utc)
    task.updated_at = now
    return now


async def _touch_project(session: SessionDep, project_id: int, *, timestamp: datetime | None = None) -> datetime:
    """Bump a project's updated_at so task activity surfaces in 'sort by updated'."""
    now = timestamp or datetime.now(timezone.utc)
    result = await session.exec(select(Project).where(Project.id == project_id))
    project = result.one_or_none()
    if project is not None:
        project.updated_at = now
        session.add(project)
    return now


async def _broadcast_task_refresh(session: SessionDep, task_id: int, guild_id: int) -> None:
    task = await _fetch_task(session, task_id, guild_id)
    if task is None:
        return
    await broadcast_event("task", "updated", _task_payload(task))


def _task_payload(task: Task) -> dict:
    return TaskRead.model_validate(task).model_dump(mode="json")


async def _fetch_task(session: SessionDep, task_id: int, guild_id: int) -> Task | None:
    stmt = (
        select(Task)
        .join(Task.project)
        .join(Project.initiative)
        .where(
            Task.id == task_id,
            Initiative.guild_id == guild_id,
        )
        .options(
            selectinload(Task.project)
            .selectinload(Project.initiative)
            .selectinload(Initiative.guild),
            selectinload(Task.assignees),
            selectinload(Task.task_status),
            selectinload(Task.tag_links).selectinload(TaskTag.tag),
        )
    )
    result = await session.exec(stmt)
    task = result.one_or_none()
    if task:
        await _annotate_tasks(session, [task])
        _annotate_task_guild([task])
        _annotate_task_tags([task])
    return task


async def _set_task_assignees(session: SessionDep, task: Task, assignee_ids: list[int] | None) -> None:
    unique_ids = list(dict.fromkeys(assignee_ids or []))

    stmt = select(User).where(User.id.in_(tuple(unique_ids))) if unique_ids else None

    if stmt is not None:
        result = await session.exec(stmt)
        users = result.all()
        if len(users) != len(unique_ids):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.ASSIGNEES_NOT_FOUND)

    delete_stmt = delete(TaskAssignee).where(TaskAssignee.task_id == task.id)
    await session.exec(delete_stmt)

    if unique_ids:
        session.add_all([TaskAssignee(task_id=task.id, user_id=user_id) for user_id in unique_ids])

    await session.flush()
    await session.refresh(task, attribute_names=["assignees"])


async def _advance_recurrence_if_needed(
    session: SessionDep,
    task: Task,
    *,
    previous_status_category: TaskStatusCategory | None,
    now: datetime,
) -> bool:
    current_category = task.task_status.category if task.task_status else None
    if (
        previous_status_category == TaskStatusCategory.done
        or current_category != TaskStatusCategory.done
        or not task.recurrence
        or task.due_date is None
    ):
        return False

    try:
        recurrence = TaskRecurrence.model_validate(task.recurrence)
    except ValidationError:
        return False

    strategy = task.recurrence_strategy or "fixed"
    if strategy == "rolling":
        # For rolling: use completion DATE but preserve original TIME
        base_date = now.replace(
            hour=task.due_date.hour,
            minute=task.due_date.minute,
            second=task.due_date.second,
            microsecond=task.due_date.microsecond,
        )
    else:
        base_date = task.due_date
    next_due = get_next_due_date(
        base_date,
        recurrence,
        completed_occurrences=task.recurrence_occurrence_count,
    )
    if next_due is None:
        task.recurrence = None
        return False

    duration = None
    if task.start_date and task.due_date:
        duration = task.due_date - task.start_date
    new_start = next_due - duration if duration else None

    default_status = await task_statuses_service.get_default_status(session, task.project_id)
    new_task = Task(
        project_id=task.project_id,
        task_status_id=default_status.id,
        title=task.title,
        description=task.description,
        priority=task.priority,
        start_date=new_start,
        due_date=next_due,
        recurrence=recurrence.model_dump(mode="json"),
        recurrence_strategy=strategy,
        sort_order=await _next_sort_order(session, task.project_id),
        recurrence_occurrence_count=task.recurrence_occurrence_count + 1,
        created_by_id=task.created_by_id,
    )
    session.add(new_task)
    await session.flush()
    await _clone_subtasks(session, task.id, new_task.id)
    assignee_ids = [assignee.id for assignee in task.assignees]
    await _set_task_assignees(session, new_task, assignee_ids)
    if task.tag_links:
        session.add_all([
            TaskTag(task_id=new_task.id, tag_id=link.tag_id)
            for link in task.tag_links
        ])
        await session.flush()
    await session.refresh(new_task, attribute_names=["assignees", "tag_links"])
    _annotate_task_tags([new_task])
    await broadcast_event("task", "created", _task_payload(new_task))

    task.recurrence = None
    task.recurrence_strategy = "fixed"
    task.updated_at = now
    session.add(task)
    return True


async def _get_project_with_access(
    session: SessionDep,
    project_id: int,
    user: User,
    *,
    guild_id: int,
    access: str = "read",
) -> Project:
    """Get project with DAC permission check.

    Tasks inherit access from their project's permission levels:
    - read: any permission level (owner, write, read) — user or role-based
    - write: owner or write permission level — user or role-based
    """
    project_stmt = (
        select(Project)
        .join(Project.initiative)
        .where(
            Project.id == project_id,
            Initiative.guild_id == guild_id,
        )
        .options(
            selectinload(Project.permissions),
            selectinload(Project.role_permissions),
            selectinload(Project.initiative)
            .selectinload(Initiative.memberships)
            .selectinload(InitiativeMember.user),
        )
    )
    project_result = await session.exec(project_stmt)
    project = project_result.one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ProjectMessages.NOT_FOUND)
    if project.is_archived and access == "write":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=ProjectMessages.IS_ARCHIVED)

    # Ensure permission is loaded (may need fallback query)
    permission = permissions_service.user_permission_from_project(project, user.id)
    if not permission:
        stmt = select(ProjectPermission).where(
            ProjectPermission.project_id == project.id,
            ProjectPermission.user_id == user.id,
        )
        result = await session.exec(stmt)
        permission = result.one_or_none()
        if permission:
            project.permissions.append(permission)

    permissions_service.require_project_access(project, user, access=access)

    return project


async def _ensure_can_manage(
    session: SessionDep,
    project_id: int,
    user: User,
    *,
    guild_id: int,
) -> Project:
    project = await _get_project_with_access(
        session,
        project_id,
        user,
        guild_id=guild_id,
        access="write",
    )
    return project


async def _allowed_project_ids(
    session: SessionDep,
    user: User,
    guild_id: int,
    *,
    include_templates: bool = False,
) -> Optional[set[int]]:
    """Get project IDs where user has explicit or role-based permission.

    Returns set of project IDs where user has any permission level.
    """
    # User-specific permissions
    user_conditions = [
        ProjectPermission.user_id == user.id,
        Initiative.guild_id == guild_id,
        Project.is_archived == False,  # noqa: E712
    ]
    if not include_templates:
        user_conditions.append(Project.is_template == False)  # noqa: E712
    user_perm_subq = (
        select(ProjectPermission.project_id)
        .join(Project)
        .join(Project.initiative)
        .where(*user_conditions)
    )
    # Role-based permissions
    role_conditions = [
        Initiative.guild_id == guild_id,
        Project.is_archived == False,  # noqa: E712
    ]
    if not include_templates:
        role_conditions.append(Project.is_template == False)  # noqa: E712
    role_perm_subq = (
        select(ProjectRolePermission.project_id)
        .join(Project, Project.id == ProjectRolePermission.project_id)
        .join(Project.initiative)
        .join(
            InitiativeMember,
            (InitiativeMember.role_id == ProjectRolePermission.initiative_role_id)
            & (InitiativeMember.user_id == user.id),
        )
        .where(*role_conditions)
    )
    combined = user_perm_subq.union(role_perm_subq)
    permission_ids_result = await session.execute(combined)
    return {row[0] for row in permission_ids_result.all() if row[0] is not None}


async def _list_global_tasks(
    session: SessionDep,
    current_user: User,
    *,
    project_id: Optional[int],
    priorities: Optional[List[TaskPriority]],
    status_category: Optional[List[TaskStatusCategory]],
    initiative_ids: Optional[List[int]],
    guild_ids: Optional[List[int]],
    include_archived: bool = False,
    page: int = 1,
    page_size: int = 20,
    sort_fields: list | None = None,
) -> tuple[list[Task], int, int]:
    conditions = [
        TaskAssignee.user_id == current_user.id,
        GuildMembership.user_id == current_user.id,
        Project.is_archived.is_(False),
        Project.is_template.is_(False),
    ]
    if not include_archived:
        conditions.append(Task.is_archived.is_(False))
    if project_id is not None:
        conditions.append(Task.project_id == project_id)
    if priorities:
        conditions.append(Task.priority.in_(tuple(priorities)))
    if initiative_ids:
        conditions.append(Project.initiative_id.in_(tuple(initiative_ids)))
    if guild_ids:
        conditions.append(Initiative.guild_id.in_(tuple(guild_ids)))

    # Build base join chain
    def _base_query(stmt):
        stmt = (
            stmt
            .join(TaskAssignee, TaskAssignee.task_id == Task.id)
            .join(Task.project)
            .join(Project.initiative)
            .join(Initiative.guild)
            .join(GuildMembership, GuildMembership.guild_id == Initiative.guild_id)
        )
        if status_category:
            stmt = stmt.join(TaskStatus, Task.task_status_id == TaskStatus.id).where(
                TaskStatus.category.in_(tuple(status_category))
            )
        return stmt.where(*conditions)

    count_subq = _base_query(select(Task.id)).subquery()
    count_stmt = select(func.count()).select_from(count_subq)

    statement = _base_query(select(Task)).options(
        selectinload(Task.project)
        .selectinload(Project.initiative)
        .selectinload(Initiative.guild),
        selectinload(Task.assignees),
        selectinload(Task.task_status),
        selectinload(Task.tag_links).selectinload(TaskTag.tag),
    )
    statement = apply_sorting(statement, Task, sort_fields=sort_fields, allowed_fields=TASK_SORT_FIELDS, default_sort=TASK_DEFAULT_SORT)

    return await paginated_query(session, statement, count_stmt, page, page_size)


async def _list_global_created_tasks(
    session: SessionDep,
    current_user: User,
    *,
    project_id: Optional[int],
    priorities: Optional[List[TaskPriority]],
    status_category: Optional[List[TaskStatusCategory]],
    initiative_ids: Optional[List[int]],
    guild_ids: Optional[List[int]],
    include_archived: bool = False,
    page: int = 1,
    page_size: int = 20,
    sort_fields: list | None = None,
) -> tuple[list[Task], int, int]:
    """List tasks created by the current user across all guilds they belong to."""
    conditions = [
        Task.created_by_id == current_user.id,
        GuildMembership.user_id == current_user.id,
        Project.is_archived.is_(False),
        Project.is_template.is_(False),
    ]
    if not include_archived:
        conditions.append(Task.is_archived.is_(False))
    if project_id is not None:
        conditions.append(Task.project_id == project_id)
    if priorities:
        conditions.append(Task.priority.in_(tuple(priorities)))
    if initiative_ids:
        conditions.append(Project.initiative_id.in_(tuple(initiative_ids)))
    if guild_ids:
        conditions.append(Initiative.guild_id.in_(tuple(guild_ids)))

    def _base_query(stmt):
        stmt = (
            stmt
            .join(Task.project)
            .join(Project.initiative)
            .join(Initiative.guild)
            .join(GuildMembership, GuildMembership.guild_id == Initiative.guild_id)
        )
        if status_category:
            stmt = stmt.join(TaskStatus, Task.task_status_id == TaskStatus.id).where(
                TaskStatus.category.in_(tuple(status_category))
            )
        return stmt.where(*conditions)

    count_subq = _base_query(select(Task.id)).subquery()
    count_stmt = select(func.count()).select_from(count_subq)

    statement = _base_query(select(Task)).options(
        selectinload(Task.project)
        .selectinload(Project.initiative)
        .selectinload(Initiative.guild),
        selectinload(Task.assignees),
        selectinload(Task.task_status),
        selectinload(Task.tag_links).selectinload(TaskTag.tag),
    )
    statement = apply_sorting(statement, Task, sort_fields=sort_fields, allowed_fields=TASK_SORT_FIELDS, default_sort=TASK_DEFAULT_SORT)

    return await paginated_query(session, statement, count_stmt, page, page_size)


@router.get("/", response_model=TaskListResponse)
async def list_tasks(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    scope: Annotated[Literal["global", "global_created"] | None, Query()] = None,
    conditions: Optional[str] = Query(
        default=None,
        description=(
            'JSON list of filter conditions. Each object: '
            '{"field": "<column>", "op": "<operator>", "value": <val>}. '
            "Any Task column is valid plus virtual fields: "
            "status_category, assignee_ids, tag_ids, initiative_ids."
        ),
    ),
    include_archived: bool = Query(default=False, description="Include archived tasks"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=0, le=100),
    sorting: Optional[str] = Query(
        default=None,
        description='JSON list of sort fields: [{"field": "due_date", "dir": "desc"}]',
    ),
) -> TaskListResponse:
    try:
        user_conditions = parse_conditions(conditions)
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

    # Extract values needed by global paths and access control
    project_id = extract_condition_value(user_conditions, "project_id")
    priorities = extract_condition_value(user_conditions, "priority")
    status_category = extract_condition_value(user_conditions, "status_category")
    initiative_ids = extract_condition_value(user_conditions, "initiative_ids")
    guild_ids = extract_condition_value(user_conditions, "guild_ids")

    if scope == "global":
        tasks, total_count, actual_page = await _list_global_tasks(
            session,
            current_user,
            project_id=project_id,
            priorities=priorities,
            status_category=status_category,
            initiative_ids=initiative_ids,
            guild_ids=guild_ids,
            include_archived=include_archived,
            page=page,
            page_size=page_size,
            sort_fields=sort_fields,
        )
        await _annotate_tasks(session, tasks)
        _annotate_task_tags(tasks)
        items = [_task_to_list_read(task) for task in tasks]
        return TaskListResponse(**build_paginated_response(
            items=items, total_count=total_count, page=actual_page,
            page_size=page_size, sorting=sorting,
        ))

    elif scope == "global_created":
        tasks, total_count, actual_page = await _list_global_created_tasks(
            session,
            current_user,
            project_id=project_id,
            priorities=priorities,
            status_category=status_category,
            initiative_ids=initiative_ids,
            guild_ids=guild_ids,
            include_archived=include_archived,
            page=page,
            page_size=page_size,
            sort_fields=sort_fields,
        )
        await _annotate_tasks(session, tasks)
        _annotate_task_tags(tasks)
        items = [_task_to_list_read(task) for task in tasks]
        return TaskListResponse(**build_paginated_response(
            items=items, total_count=total_count, page=actual_page,
            page_size=page_size, sorting=sorting,
        ))

    # Non-global (guild-scoped) path
    access_conditions = [Initiative.guild_id == guild_context.guild_id]

    if not include_archived:
        access_conditions.append(Task.is_archived.is_(False))

    allowed_ids = await _allowed_project_ids(
        session,
        current_user,
        guild_context.guild_id,
        include_templates=project_id is not None,
    )
    if allowed_ids is not None:
        if not allowed_ids:
            return TaskListResponse(**build_paginated_response(
                items=[], total_count=0, page=1,
                page_size=page_size, sorting=sorting,
            ))
        access_conditions.append(Task.project_id.in_(tuple(allowed_ids)))

    filter_fields = _build_task_filter_fields(
        guild_id=guild_context.guild_id,
        current_user_id=current_user.id,
    )

    def _build_non_global_query(stmt):
        stmt = stmt.join(Task.project).join(Project.initiative)
        stmt = stmt.where(*access_conditions)
        stmt = apply_filters(stmt, Task, user_conditions, allowed_fields=filter_fields)
        return stmt

    count_subq = _build_non_global_query(select(Task.id)).subquery()
    count_stmt = select(func.count()).select_from(count_subq)

    statement = _build_non_global_query(select(Task)).options(
        selectinload(Task.project)
        .selectinload(Project.initiative)
        .selectinload(Initiative.guild),
        selectinload(Task.assignees),
        selectinload(Task.task_status),
        selectinload(Task.tag_links).selectinload(TaskTag.tag),
    )
    statement = apply_sorting(statement, Task, sort_fields=sort_fields, allowed_fields=TASK_SORT_FIELDS, default_sort=TASK_DEFAULT_SORT)

    tasks, total_count, actual_page = await paginated_query(session, statement, count_stmt, page, page_size)
    await _annotate_tasks(session, tasks)
    _annotate_task_tags(tasks)
    items = [_task_to_list_read(task) for task in tasks]
    return TaskListResponse(**build_paginated_response(
        items=items, total_count=total_count, page=actual_page,
        page_size=page_size, sorting=sorting,
    ))


@router.post("/", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_in: TaskCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Task:
    project = await _get_project_with_access(
        session,
        task_in.project_id,
        current_user,
        guild_id=guild_context.guild_id,
        access="write",
    )

    sort_order = await _next_sort_order(session, task_in.project_id)
    await task_statuses_service.ensure_default_statuses(session, project.id)
    selected_status = None
    if task_in.task_status_id is not None:
        selected_status = await task_statuses_service.get_project_status(
            session,
            status_id=task_in.task_status_id,
            project_id=project.id,
        )
        if selected_status is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=TaskMessages.STATUS_NOT_FOUND)
    else:
        selected_status = await task_statuses_service.get_default_status(session, project.id)

    task_data = task_in.dict(exclude={"assignee_ids", "task_status_id"})

    # Serialize recurrence to JSON if present
    if task_data.get("recurrence") is not None:
        if isinstance(task_data["recurrence"], TaskRecurrence):
            task_data["recurrence"] = task_data["recurrence"].model_dump(mode="json")
        elif isinstance(task_data["recurrence"], dict):
            # Already a dict, convert to model and back to ensure proper serialization
            recurrence_obj = TaskRecurrence.model_validate(task_data["recurrence"])
            task_data["recurrence"] = recurrence_obj.model_dump(mode="json")

    task = Task(**task_data, sort_order=sort_order, task_status_id=selected_status.id, created_by_id=current_user.id)
    session.add(task)
    await session.flush()
    await _set_task_assignees(session, task, task_in.assignee_ids)
    if project and task.assignees:
        for assignee in task.assignees:
            await notifications_service.enqueue_task_assignment_event(
                session,
                task=task,
                assignee=assignee,
                assigned_by=current_user,
                project_name=project.name,
                guild_id=guild_context.guild_id,
            )
    await _touch_project(session, task_in.project_id)
    await session.commit()
    await reapply_rls_context(session)
    task = await _fetch_task(session, task.id, guild_context.guild_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=TaskMessages.MISSING_AFTER_CREATE)
    await broadcast_event("task", "created", _task_payload(task))
    return task


@router.get("/{task_id}", response_model=TaskRead)
async def read_task(
    task_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Task:
    task = await _fetch_task(session, task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_FOUND)

    await _get_project_with_access(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
        access="read",
    )
    return task


@router.patch("/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: int,
    task_in: TaskUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Task:
    task = await _fetch_task(session, task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_FOUND)

    project = await _get_project_with_access(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
        access="write",
    )

    update_data = task_in.dict(exclude_unset=True)
    assignee_ids = update_data.pop("assignee_ids", None)
    previous_status_category = task.task_status.category if task.task_status else None
    new_status_id = update_data.pop("task_status_id", None)

    if new_status_id is not None and new_status_id != task.task_status_id:
        selected_status = await task_statuses_service.get_project_status(
            session,
            status_id=new_status_id,
            project_id=task.project_id,
        )
        if selected_status is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=TaskMessages.STATUS_NOT_FOUND)
        task.task_status_id = selected_status.id
        task.task_status = selected_status

    for field, value in update_data.items():
        if field == "recurrence":
            if value is None:
                task.recurrence_occurrence_count = 0
                setattr(task, field, None)
                task.recurrence_strategy = "fixed"
                continue
            if isinstance(value, TaskRecurrence):
                value = value.model_dump(mode="json")
            elif isinstance(value, dict):
                # Already a dict, convert to model and back to ensure proper serialization
                recurrence_obj = TaskRecurrence.model_validate(value)
                value = recurrence_obj.model_dump(mode="json")
        if field == "recurrence_strategy" and value is None:
            continue
        setattr(task, field, value)
    now = datetime.now(timezone.utc)
    task.updated_at = now

    new_assignees: list[User] = []
    if assignee_ids is not None:
        existing_assignee_ids = {assignee.id for assignee in task.assignees}
        await _set_task_assignees(session, task, assignee_ids)
        new_assignees = [assignee for assignee in task.assignees if assignee.id not in existing_assignee_ids]

    await _advance_recurrence_if_needed(
        session,
        task,
        previous_status_category=previous_status_category,
        now=now,
    )

    if new_assignees and project:
        for assignee in new_assignees:
            await notifications_service.enqueue_task_assignment_event(
                session,
                task=task,
                assignee=assignee,
                assigned_by=current_user,
                project_name=project.name,
                guild_id=guild_context.guild_id,
            )
    await _touch_project(session, task.project_id, timestamp=now)
    session.add(task)
    await session.commit()
    await reapply_rls_context(session)
    task = await _fetch_task(session, task.id, guild_context.guild_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=TaskMessages.MISSING_AFTER_UPDATE)
    await broadcast_event("task", "updated", _task_payload(task))
    return task


@router.post("/{task_id}/move", response_model=TaskRead)
async def move_task(
    task_id: int,
    move_in: TaskMoveRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Task:
    task = await _fetch_task(session, task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_FOUND)

    if task.project_id == move_in.target_project_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=TaskMessages.ALREADY_IN_PROJECT)

    await _ensure_can_manage(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
    )

    target_project = await _get_project_with_access(
        session,
        move_in.target_project_id,
        current_user,
        guild_id=guild_context.guild_id,
        access="write",
    )
    if target_project.is_template:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=TaskMessages.CANNOT_MOVE_TO_TEMPLATE)

    default_status = await task_statuses_service.get_default_status(session, target_project.id)
    now = datetime.now(timezone.utc)
    source_project_id = task.project_id
    task.project_id = target_project.id
    task.task_status_id = default_status.id
    task.task_status = default_status
    task.sort_order = 0
    task.updated_at = now
    session.add(task)
    await _touch_project(session, source_project_id, timestamp=now)
    await _touch_project(session, target_project.id, timestamp=now)
    await session.commit()
    await reapply_rls_context(session)

    updated_task = await _fetch_task(session, task.id, guild_context.guild_id)
    if updated_task is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=TaskMessages.MISSING_AFTER_MOVE)
    await broadcast_event("task", "updated", _task_payload(updated_task))
    return updated_task


@router.post("/{task_id}/duplicate", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def duplicate_task(
    task_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Task:
    # Fetch the original task with its subtasks and tags
    task_stmt = (
        select(Task)
        .options(
            selectinload(Task.assignees),
            selectinload(Task.tag_links),
        )
        .join(Task.project)
        .join(Project.initiative)
        .where(
            Task.id == task_id,
            Initiative.guild_id == guild_context.guild_id,
        )
    )
    task_result = await session.exec(task_stmt)
    original_task = task_result.one_or_none()
    if not original_task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_FOUND)

    await _ensure_can_manage(
        session,
        original_task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
    )

    # Fetch subtasks
    subtasks_stmt = select(Subtask).where(Subtask.task_id == task_id).order_by(Subtask.position)
    subtasks_result = await session.exec(subtasks_stmt)
    original_subtasks = list(subtasks_result.all())

    # Get next sort order for the new task
    sort_order = await _next_sort_order(session, original_task.project_id)

    # Create the new task with the same properties
    new_task = Task(
        title=f"{original_task.title} (copy)",
        description=original_task.description,
        project_id=original_task.project_id,
        task_status_id=original_task.task_status_id,
        priority=original_task.priority,
        start_date=original_task.start_date,
        due_date=original_task.due_date,
        recurrence=original_task.recurrence,
        recurrence_strategy=original_task.recurrence_strategy,
        sort_order=sort_order,
        created_by_id=current_user.id,
    )
    session.add(new_task)
    await session.flush()

    # Copy assignees
    assignee_ids = [assignee.id for assignee in original_task.assignees]
    await _set_task_assignees(session, new_task, assignee_ids)

    # Copy subtasks
    for original_subtask in original_subtasks:
        new_subtask = Subtask(
            task_id=new_task.id,
            content=original_subtask.content,
            is_completed=False,  # Reset completion status
            position=original_subtask.position,
        )
        session.add(new_subtask)

    # Copy tags
    if original_task.tag_links:
        session.add_all([
            TaskTag(task_id=new_task.id, tag_id=link.tag_id)
            for link in original_task.tag_links
        ])

    await _touch_project(session, original_task.project_id)
    await session.commit()
    await reapply_rls_context(session)

    # Fetch with all relationships for the response
    task_with_relations = await _fetch_task(session, new_task.id, guild_context.guild_id)
    if not task_with_relations:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.DUPLICATE_NOT_FOUND)

    return task_with_relations


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    task_stmt = (
        select(Task)
        .join(Task.project)
        .join(Project.initiative)
        .where(
            Task.id == task_id,
            Initiative.guild_id == guild_context.guild_id,
        )
    )
    task_result = await session.exec(task_stmt)
    task = task_result.one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_FOUND)

    await _ensure_can_manage(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
    )

    project_id = task.project_id
    await session.delete(task)
    await _touch_project(session, project_id)
    await session.commit()
    await broadcast_event("task", "deleted", {"id": task_id, "project_id": project_id})


@router.post("/reorder", response_model=List[TaskRead])
async def reorder_tasks(
    reorder_in: TaskReorderRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[Task]:
    if not reorder_in.items:
        return []

    await _ensure_can_manage(
        session,
        reorder_in.project_id,
        current_user,
        guild_id=guild_context.guild_id,
    )

    task_ids = [item.id for item in reorder_in.items]
    tasks_stmt = (
        select(Task)
        .join(Task.project)
        .join(Project.initiative)
        .where(
            Task.id.in_(tuple(task_ids)),
            Initiative.guild_id == guild_context.guild_id,
        )
        .options(selectinload(Task.assignees), selectinload(Task.task_status))
    )
    tasks_result = await session.exec(tasks_stmt)
    tasks = tasks_result.all()
    task_map = {task.id: task for task in tasks}

    missing_ids = set(task_ids) - set(task_map.keys())
    if missing_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_FOUND)

    now = datetime.now(timezone.utc)
    status_cache: dict[int, TaskStatus] = {}
    for item in reorder_in.items:
        task = task_map[item.id]
        previous_status_category = task.task_status.category if task.task_status else None
        if task.project_id != reorder_in.project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=TaskMessages.PROJECT_MISMATCH)

        if item.task_status_id != task.task_status_id:
            status_obj = status_cache.get(item.task_status_id)
            if status_obj is None:
                status_obj = await task_statuses_service.get_project_status(
                    session,
                    status_id=item.task_status_id,
                    project_id=reorder_in.project_id,
                )
                if status_obj is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=TaskMessages.STATUS_NOT_FOUND,
                    )
                status_cache[item.task_status_id] = status_obj
            task.task_status_id = status_obj.id
            task.task_status = status_obj

        task.sort_order = item.sort_order
        task.updated_at = now
        session.add(task)
        await _advance_recurrence_if_needed(
            session,
            task,
            previous_status_category=previous_status_category,
            now=now,
        )

    await _touch_project(session, reorder_in.project_id, timestamp=now)
    await session.commit()
    await reapply_rls_context(session)

    refreshed_stmt = (
        select(Task)
        .options(
            selectinload(Task.project)
            .selectinload(Project.initiative)
            .selectinload(Initiative.guild),
            selectinload(Task.assignees),
            selectinload(Task.task_status),
        )
        .where(Task.project_id == reorder_in.project_id)
        .order_by(Task.sort_order.asc(), Task.id.asc())
    )
    refreshed_result = await session.exec(refreshed_stmt)
    tasks = refreshed_result.all()
    await _annotate_tasks(session, tasks)
    _annotate_task_guild(tasks)
    await broadcast_event("task", "reordered", {"project_id": reorder_in.project_id})
    return tasks


class ArchiveDoneResponse(BaseModel):
    archived_count: int


@router.post("/archive-done", response_model=ArchiveDoneResponse)
async def archive_done_tasks(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    project_id: int = Query(..., description="Project to archive done tasks from"),
    task_status_id: Optional[int] = Query(default=None, description="Specific done status to archive (optional)"),
) -> ArchiveDoneResponse:
    """Archive all tasks in 'done' status category for a project."""
    await _ensure_can_manage(
        session,
        project_id,
        current_user,
        guild_id=guild_context.guild_id,
    )

    # Build the query to find done tasks
    statement = (
        select(Task)
        .join(Task.task_status)
        .where(
            Task.project_id == project_id,
            Task.is_archived.is_(False),
            TaskStatus.category == TaskStatusCategory.done,
        )
    )

    # Optionally filter by specific status
    if task_status_id is not None:
        statement = statement.where(Task.task_status_id == task_status_id)

    result = await session.exec(statement)
    tasks = result.all()

    if not tasks:
        return ArchiveDoneResponse(archived_count=0)

    now = datetime.now(timezone.utc)
    for task in tasks:
        task.is_archived = True
        task.updated_at = now
        session.add(task)

    await _touch_project(session, project_id, timestamp=now)
    await session.commit()
    await broadcast_event("task", "archived", {"project_id": project_id, "count": len(tasks)})
    return ArchiveDoneResponse(archived_count=len(tasks))


@router.get("/{task_id}/subtasks", response_model=List[SubtaskRead])
async def list_subtasks(
    task_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[Subtask]:
    task = await _fetch_task(session, task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_FOUND)

    await _get_project_with_access(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
        access="read",
    )
    return await _list_subtasks_for_task(session, task.id)


@router.post("/{task_id}/subtasks", response_model=SubtaskRead, status_code=status.HTTP_201_CREATED)
async def create_subtask(
    task_id: int,
    subtask_in: SubtaskCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Subtask:
    task = await _fetch_task(session, task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_FOUND)

    await _ensure_can_manage(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
    )

    content = subtask_in.content.strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=SubtaskMessages.CONTENT_EMPTY)

    position = await _next_subtask_position(session, task.id)
    subtask = Subtask(
        task_id=task.id,
        content=content,
        position=position,
    )
    now = datetime.now(timezone.utc)
    subtask.updated_at = now
    _touch_task(task, timestamp=now)
    await _touch_project(session, task.project_id, timestamp=now)
    session.add(subtask)
    session.add(task)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(subtask)
    await _broadcast_task_refresh(session, task.id, guild_context.guild_id)
    return subtask


@router.post("/{task_id}/subtasks/batch", response_model=List[SubtaskRead])
async def create_subtasks_batch(
    task_id: int,
    subtask_batch: SubtaskBatchCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[Subtask]:
    """Create multiple subtasks at once."""
    task = await _fetch_task(session, task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_FOUND)

    await _ensure_can_manage(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
    )

    # Get current max position
    existing = await _list_subtasks_for_task(session, task.id)
    position = max((s.position for s in existing), default=-1) + 1

    now = datetime.now(timezone.utc)
    created_subtasks = []

    for content in subtask_batch.contents:
        content = content.strip()
        if not content or len(content) > 2000:
            continue  # Skip empty or too-long content

        subtask = Subtask(
            task_id=task.id,
            content=content,
            position=position,
            updated_at=now,
        )
        session.add(subtask)
        created_subtasks.append(subtask)
        position += 1

    if created_subtasks:
        _touch_task(task, timestamp=now)
        await _touch_project(session, task.project_id, timestamp=now)
        session.add(task)
        await session.commit()
        await reapply_rls_context(session)
        for subtask in created_subtasks:
            await session.refresh(subtask)
        await _broadcast_task_refresh(session, task.id, guild_context.guild_id)

    return created_subtasks


@router.put("/{task_id}/subtasks/order", response_model=List[SubtaskRead])
async def reorder_subtasks(
    task_id: int,
    reorder_in: SubtaskReorderRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[Subtask]:
    task = await _fetch_task(session, task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_FOUND)

    await _ensure_can_manage(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
    )

    if not reorder_in.items:
        return await _list_subtasks_for_task(session, task.id)

    subtask_ids = [item.id for item in reorder_in.items]
    stmt = select(Subtask).where(
        Subtask.task_id == task.id,
        Subtask.id.in_(tuple(subtask_ids)),
    )
    result = await session.exec(stmt)
    subtasks = result.all()
    subtask_map = {subtask.id: subtask for subtask in subtasks}
    if len(subtask_map) != len(subtask_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SubtaskMessages.NOT_FOUND_FOR_TASK)

    now = datetime.now(timezone.utc)
    for item in reorder_in.items:
        subtask = subtask_map[item.id]
        subtask.position = item.position
        subtask.updated_at = now
        session.add(subtask)
    _touch_task(task, timestamp=now)
    await _touch_project(session, task.project_id, timestamp=now)
    session.add(task)
    await session.commit()
    await reapply_rls_context(session)
    await _broadcast_task_refresh(session, task.id, guild_context.guild_id)
    return await _list_subtasks_for_task(session, task.id)


@subtasks_router.patch("/subtasks/{subtask_id}", response_model=SubtaskRead)
async def update_subtask(
    subtask_id: int,
    subtask_in: SubtaskUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Subtask:
    subtask = await session.get(Subtask, subtask_id)
    if not subtask:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SubtaskMessages.NOT_FOUND)

    task = await _fetch_task(session, subtask.task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_FOUND)

    await _ensure_can_manage(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
    )

    update_data = subtask_in.model_dump(exclude_unset=True)
    if not update_data:
        return subtask

    if "content" in update_data and update_data["content"] is not None:
        content_value = update_data["content"].strip()
        if not content_value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=SubtaskMessages.CONTENT_EMPTY)
        subtask.content = content_value

    if "is_completed" in update_data and update_data["is_completed"] is not None:
        subtask.is_completed = bool(update_data["is_completed"])

    now = datetime.now(timezone.utc)
    subtask.updated_at = now
    _touch_task(task, timestamp=now)
    await _touch_project(session, task.project_id, timestamp=now)
    session.add(subtask)
    session.add(task)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(subtask)
    await _broadcast_task_refresh(session, task.id, guild_context.guild_id)
    return subtask


@subtasks_router.delete("/subtasks/{subtask_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subtask(
    subtask_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    subtask = await session.get(Subtask, subtask_id)
    if not subtask:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=SubtaskMessages.NOT_FOUND)

    task = await _fetch_task(session, subtask.task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_FOUND)

    await _ensure_can_manage(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
    )

    await session.delete(subtask)
    now = _touch_task(task)
    await _touch_project(session, task.project_id, timestamp=now)
    session.add(task)
    await session.commit()
    await reapply_rls_context(session)
    await _broadcast_task_refresh(session, task.id, guild_context.guild_id)
    return None


# AI Generation endpoints
@router.post("/{task_id}/ai/subtasks", response_model=GenerateSubtasksResponse)
async def generate_task_subtasks(
    task_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> GenerateSubtasksResponse:
    """Generate AI-powered subtask suggestions for a task."""
    task = await _fetch_task(session, task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_FOUND)

    # Check write access and get project with initiative
    project = await _get_project_with_access(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
        access="write",
    )

    try:
        subtasks = await ai_generation_service.generate_subtasks(
            session,
            current_user,
            guild_context.guild_id,
            task,
            initiative_name=project.initiative.name if project.initiative else None,
            project_name=project.name,
        )
        return GenerateSubtasksResponse(subtasks=subtasks)
    except ai_generation_service.AIGenerationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{task_id}/ai/description", response_model=GenerateDescriptionResponse)
async def generate_task_description(
    task_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> GenerateDescriptionResponse:
    """Generate AI-powered description for a task."""
    task = await _fetch_task(session, task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_FOUND)

    # Check write access and get project with initiative
    project = await _get_project_with_access(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
        access="write",
    )

    try:
        description = await ai_generation_service.generate_description(
            session,
            current_user,
            guild_context.guild_id,
            task,
            initiative_name=project.initiative.name if project.initiative else None,
            project_name=project.name,
        )
        return GenerateDescriptionResponse(description=description)
    except ai_generation_service.AIGenerationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put("/{task_id}/tags", response_model=TaskRead)
async def set_task_tags(
    task_id: int,
    tags_in: TagSetRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Task:
    """Set the tags for a task. Replaces all existing tags with the provided list."""
    task = await _fetch_task(session, task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_FOUND)

    await _ensure_can_manage(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
    )

    # Validate that all tag IDs belong to this guild
    unique_tag_ids = list(dict.fromkeys(tags_in.tag_ids))
    if unique_tag_ids:
        stmt = select(Tag).where(
            Tag.id.in_(tuple(unique_tag_ids)),
            Tag.guild_id == guild_context.guild_id,
        )
        result = await session.exec(stmt)
        tags = result.all()
        if len(tags) != len(unique_tag_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=TaskMessages.TAGS_NOT_FOUND,
            )

    # Delete existing task tags
    delete_stmt = delete(TaskTag).where(TaskTag.task_id == task.id)
    await session.exec(delete_stmt)

    # Add new task tags
    task_id_to_update = task.id
    if unique_tag_ids:
        session.add_all([
            TaskTag(task_id=task_id_to_update, tag_id=tag_id)
            for tag_id in unique_tag_ids
        ])

    # Update timestamp via a lightweight select (avoids stale relationship objects)
    ts_stmt = select(Task).where(Task.id == task_id_to_update)
    ts_result = await session.exec(ts_stmt)
    ts_task = ts_result.one()
    now = datetime.now(timezone.utc)
    ts_task.updated_at = now
    await _touch_project(session, ts_task.project_id, timestamp=now)
    await session.commit()
    await reapply_rls_context(session)

    # Single fetch with all relationships for the response
    task = await _fetch_task(session, task_id_to_update, guild_context.guild_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=TaskMessages.MISSING_AFTER_UPDATE)
    await broadcast_event("task", "updated", _task_payload(task))
    return task

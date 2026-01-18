from datetime import datetime, timezone
from typing import Annotated, List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import selectinload
from sqlalchemy import case, func
from sqlmodel import select, delete

from app.api.deps import (
    SessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
)
from app.models.project import Project, ProjectPermission
from app.models.initiative import Initiative, InitiativeMember, InitiativeRole
from app.models.task import Task, TaskAssignee, TaskPriority, TaskStatus, TaskStatusCategory, Subtask
from app.models.user import User
from app.models.guild import GuildRole, GuildMembership
from app.models.comment import Comment
from pydantic import BaseModel, ValidationError

from app.schemas.task import TaskCreate, TaskListRead, TaskMoveRequest, TaskRead, TaskReorderRequest, TaskRecurrence, TaskUpdate
from app.schemas.subtask import (
    SubtaskCreate,
    SubtaskRead,
    SubtaskReorderRequest,
    SubtaskUpdate,
    TaskSubtaskProgress,
)
from app.services.realtime import broadcast_event
from app.services import notifications as notifications_service
from app.services.recurrence import get_next_due_date
from app.services import task_statuses as task_statuses_service

router = APIRouter()
subtasks_router = APIRouter()
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


async def _next_sort_order(session: SessionDep, project_id: int) -> float:
    result = await session.exec(select(func.max(Task.sort_order)).where(Task.project_id == project_id))
    max_value = result.one_or_none()
    return (max_value or 0) + 1


async def _annotate_task_comment_counts(session: SessionDep, tasks: list[Task]) -> None:
    task_ids = [task.id for task in tasks if task.id is not None]
    if not task_ids:
        return
    stmt = (
        select(Comment.task_id, func.count(Comment.id))
        .where(Comment.task_id.in_(tuple(task_ids)))
        .group_by(Comment.task_id)
    )
    result = await session.exec(stmt)
    counts = dict(result.all())
    for task in tasks:
        object.__setattr__(task, "comment_count", counts.get(task.id, 0))


async def _annotate_task_subtask_progress(session: SessionDep, tasks: list[Task]) -> None:
    task_ids = [task.id for task in tasks if task.id is not None]
    if not task_ids:
        return
    stmt = (
        select(
            Subtask.task_id,
            func.count(Subtask.id).label("total"),
            func.sum(
                case(
                    (Subtask.is_completed.is_(True), 1),
                    else_=0,
                )
            ).label("completed"),
        )
        .where(Subtask.task_id.in_(tuple(task_ids)))
        .group_by(Subtask.task_id)
    )
    result = await session.exec(stmt)
    counts = {task_id: {"total": total, "completed": completed or 0} for task_id, total, completed in result.all()}
    for task in tasks:
        progress_data = counts.get(task.id)
        if not progress_data:
            object.__setattr__(task, "subtask_progress", None)
            continue
        progress = TaskSubtaskProgress(
            completed=int(progress_data["completed"]),
            total=int(progress_data["total"]),
        )
        object.__setattr__(task, "subtask_progress", progress)


def _annotate_task_guild(tasks: list[Task]) -> None:
    for task in tasks:
        project = getattr(task, "project", None)
        initiative = getattr(project, "initiative", None) if project else None
        guild = getattr(initiative, "guild", None) if initiative else None
        object.__setattr__(task, "guild", guild)


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
        )
    )
    result = await session.exec(stmt)
    task = result.one_or_none()
    if task:
        await _annotate_task_comment_counts(session, [task])
        await _annotate_task_subtask_progress(session, [task])
        _annotate_task_guild([task])
    return task


async def _set_task_assignees(session: SessionDep, task: Task, assignee_ids: list[int] | None) -> None:
    unique_ids = list(dict.fromkeys(assignee_ids or []))

    stmt = select(User).where(User.id.in_(tuple(unique_ids))) if unique_ids else None

    if stmt is not None:
        result = await session.exec(stmt)
        users = result.all()
        if len(users) != len(unique_ids):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One or more assignees not found")

    delete_stmt = delete(TaskAssignee).where(TaskAssignee.task_id == task.id)
    await session.exec(delete_stmt)

    if unique_ids:
        session.add_all([TaskAssignee(task_id=task.id, user_id=user_id) for user_id in unique_ids])

    await session.flush()
    await session.refresh(task, attribute_names=["assignees"])


def _permission_from_project(project: Project, user_id: int) -> ProjectPermission | None:
    permissions = getattr(project, "permissions", None)
    if not permissions:
        return None
    for permission in permissions:
        if permission.user_id == user_id:
            return permission
    return None


def _membership_from_project(project: Project, user_id: int) -> InitiativeMember | None:
    initiative = getattr(project, "initiative", None)
    if not initiative:
        return None
    memberships = getattr(initiative, "memberships", None)
    if not memberships:
        return None
    for membership in memberships:
        if membership.user_id == user_id:
            return membership
    return None


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
    base_date = task.due_date if strategy == "fixed" else now
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
    )
    session.add(new_task)
    await session.flush()
    await _clone_subtasks(session, task.id, new_task.id)
    assignee_ids = [assignee.id for assignee in task.assignees]
    await _set_task_assignees(session, new_task, assignee_ids)
    await session.refresh(new_task, attribute_names=["assignees"])
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
    guild_role: GuildRole | None = None,
) -> Project:
    project_stmt = (
        select(Project)
        .join(Project.initiative)
        .where(
            Project.id == project_id,
            Initiative.guild_id == guild_id,
        )
        .options(
            selectinload(Project.permissions),
            selectinload(Project.initiative)
            .selectinload(Initiative.memberships)
            .selectinload(InitiativeMember.user),
        )
    )
    project_result = await session.exec(project_stmt)
    project = project_result.one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.is_archived and access == "write":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project is archived")

    if guild_role == GuildRole.admin:
        return project

    permission = _permission_from_project(project, user.id)
    if not permission:
        stmt = select(ProjectPermission).where(
            ProjectPermission.project_id == project.id,
            ProjectPermission.user_id == user.id,
        )
        result = await session.exec(stmt)
        permission = result.one_or_none()
        if permission:
            project.permissions.append(permission)

    membership = _membership_from_project(project, user.id)
    if not membership and project.initiative_id:
        initiative_stmt = select(InitiativeMember).where(
            InitiativeMember.initiative_id == project.initiative_id,
            InitiativeMember.user_id == user.id,
        )
        initiative_result = await session.exec(initiative_stmt)
        membership = initiative_result.one_or_none()
        if membership and project.initiative:
            project.initiative.memberships.append(membership)

    is_owner = project.owner_id == user.id
    is_pm = membership and membership.role == InitiativeRole.project_manager

    if access == "read":
        if is_owner or membership or permission:
            return project
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not part of this project's initiative")

    has_write = (
        is_owner
        or is_pm
        or permission is not None
        or bool(project.members_can_write and membership)
    )
    if not has_write:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions for this project")

    return project


async def _ensure_can_manage(
    session: SessionDep,
    project_id: int,
    user: User,
    *,
    guild_id: int,
    guild_role: GuildRole | None = None,
) -> Project:
    project = await _get_project_with_access(
        session,
        project_id,
        user,
        guild_id=guild_id,
        access="write",
        guild_role=guild_role,
    )
    return project


async def _allowed_project_ids(
    session: SessionDep,
    user: User,
    guild_id: int,
    *,
    is_guild_admin: bool,
) -> Optional[set[int]]:
    if is_guild_admin:
        return None

    initiative_ids_result = await session.exec(
        select(InitiativeMember.initiative_id)
        .join(Initiative)
        .where(
            InitiativeMember.user_id == user.id,
            Initiative.guild_id == guild_id,
        )
    )
    initiative_ids = {row for row in initiative_ids_result.all() if row is not None}

    permission_ids_result = await session.exec(
        select(ProjectPermission.project_id)
        .join(Project)
        .join(Project.initiative)
        .where(
            ProjectPermission.user_id == user.id,
            Initiative.guild_id == guild_id,
        )
    )
    permission_ids = {row for row in permission_ids_result.all() if row is not None}

    project_result = await session.exec(
        select(Project.id, Project.owner_id, Project.initiative_id, Project.is_archived, Project.is_template)
        .join(Project.initiative)
        .where(Initiative.guild_id == guild_id)
    )
    ids: set[int] = set()
    for project_id, owner_id, initiative_id, is_archived, is_template in project_result.all():
        if is_archived or is_template:
            continue
        if owner_id == user.id:
            ids.add(project_id)
            continue
        if initiative_id in initiative_ids:
            ids.add(project_id)
            continue
        if project_id in permission_ids:
            ids.add(project_id)
    return ids


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
) -> list[Task]:
    statement = (
        select(Task)
        .join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .join(Task.project)
        .join(Project.initiative)
        .join(Initiative.guild)
        .join(GuildMembership, GuildMembership.guild_id == Initiative.guild_id)
        .where(
            TaskAssignee.user_id == current_user.id,
            GuildMembership.user_id == current_user.id,
            Project.is_archived.is_(False),
            Project.is_template.is_(False),
        )
        .options(
            selectinload(Task.project)
            .selectinload(Project.initiative)
            .selectinload(Initiative.guild),
            selectinload(Task.assignees),
            selectinload(Task.task_status),
        )
        .order_by(Task.sort_order.asc(), Task.id.asc())
    )
    if not include_archived:
        statement = statement.where(Task.is_archived.is_(False))

    if project_id is not None:
        statement = statement.where(Task.project_id == project_id)

    if priorities:
        statement = statement.where(Task.priority.in_(tuple(priorities)))

    if status_category:
        statement = statement.join(TaskStatus, Task.task_status_id == TaskStatus.id).where(TaskStatus.category.in_(tuple(status_category)))

    if initiative_ids:
        statement = statement.where(Project.initiative_id.in_(tuple(initiative_ids)))

    if guild_ids:
        statement = statement.where(Initiative.guild_id.in_(tuple(guild_ids)))

    result = await session.exec(statement)
    return result.all()


@router.get("/", response_model=List[TaskListRead])
async def list_tasks(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    project_id: Optional[int] = Query(default=None),
    scope: Annotated[Literal["global"] | None, Query()] = None,
    assignee_ids: Optional[List[str]] = Query(default=None),
    task_status_ids: Optional[List[int]] = Query(default=None),
    priorities: Optional[List[TaskPriority]] = Query(default=None),
    status_category: Optional[List[TaskStatusCategory]] = Query(default=None),
    initiative_ids: Optional[List[int]] = Query(default=None),
    guild_ids: Optional[List[int]] = Query(default=None),
    include_archived: bool = Query(default=False, description="Include archived tasks"),
) -> List[TaskListRead]:
    if scope == "global":
        tasks = await _list_global_tasks(
            session,
            current_user,
            project_id=project_id,
            priorities=priorities,
            status_category=status_category,
            initiative_ids=initiative_ids,
            guild_ids=guild_ids,
            include_archived=include_archived,
        )
        await _annotate_task_comment_counts(session, tasks)
        await _annotate_task_subtask_progress(session, tasks)
        return [_task_to_list_read(task) for task in tasks]

    statement = (
        select(Task)
        .join(Task.project)
        .join(Project.initiative)
        .where(Initiative.guild_id == guild_context.guild_id)
        .options(
            selectinload(Task.project)
            .selectinload(Project.initiative)
            .selectinload(Initiative.guild),
            selectinload(Task.assignees),
            selectinload(Task.task_status),
        )
        .order_by(Task.sort_order.asc(), Task.id.asc())
    )

    allowed_ids = await _allowed_project_ids(
        session,
        current_user,
        guild_context.guild_id,
        is_guild_admin=guild_context.role == GuildRole.admin,
    )
    if allowed_ids is not None:
        if not allowed_ids:
            return []
        statement = statement.where(Task.project_id.in_(tuple(allowed_ids)))

    if not include_archived:
        statement = statement.where(Task.is_archived.is_(False))

    if project_id is not None:
        statement = statement.where(Task.project_id == project_id)

    if assignee_ids:
        user_ids = []
        for assignee_id in assignee_ids:
            if assignee_id == "me":
                user_ids.append(current_user.id)
            else:
                try:
                    user_ids.append(int(assignee_id))
                except ValueError:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid assignee_id: {assignee_id}")
        if user_ids:
            statement = statement.join(TaskAssignee, TaskAssignee.task_id == Task.id).where(
                TaskAssignee.user_id.in_(tuple(user_ids))
            )

    if task_status_ids:
        statement = statement.where(Task.task_status_id.in_(tuple(task_status_ids)))

    if priorities:
        statement = statement.where(Task.priority.in_(tuple(priorities)))

    if status_category:
        statement = statement.join(TaskStatus, Task.task_status_id == TaskStatus.id).where(TaskStatus.category.in_(tuple(status_category)))

    if initiative_ids:
        statement = statement.where(Project.initiative_id.in_(tuple(initiative_ids)))

    if guild_ids:
        statement = statement.where(Initiative.guild_id.in_(tuple(guild_ids)))

    result = await session.exec(statement)
    tasks = result.all()
    await _annotate_task_comment_counts(session, tasks)
    await _annotate_task_subtask_progress(session, tasks)
    return [_task_to_list_read(task) for task in tasks]


@router.post("/", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_in: TaskCreate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Task:
    project = await _get_project_with_access(
        session,
        task_in.project_id,
        current_user,
        guild_id=guild_context.guild_id,
        access="write",
        guild_role=guild_context.role,
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
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task status not found for project")
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

    task = Task(**task_data, sort_order=sort_order, task_status_id=selected_status.id)
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
    await session.commit()
    task = await _fetch_task(session, task.id, guild_context.guild_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Task not found after creation")
    await broadcast_event("task", "created", _task_payload(task))
    return task


@router.get("/{task_id}", response_model=TaskRead)
async def read_task(
    task_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Task:
    task = await _fetch_task(session, task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    await _get_project_with_access(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
        access="read",
        guild_role=guild_context.role,
    )
    return task


@router.patch("/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: int,
    task_in: TaskUpdate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Task:
    task = await _fetch_task(session, task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    project = await _get_project_with_access(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
        access="write",
        guild_role=guild_context.role,
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
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task status not found for project")
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
    session.add(task)
    await session.commit()
    task = await _fetch_task(session, task.id, guild_context.guild_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Task missing after update")
    await broadcast_event("task", "updated", _task_payload(task))
    return task


@router.post("/{task_id}/move", response_model=TaskRead)
async def move_task(
    task_id: int,
    move_in: TaskMoveRequest,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Task:
    task = await _fetch_task(session, task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    if task.project_id == move_in.target_project_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task already belongs to this project")

    await _ensure_can_manage(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
        guild_role=guild_context.role,
    )

    target_project = await _get_project_with_access(
        session,
        move_in.target_project_id,
        current_user,
        guild_id=guild_context.guild_id,
        access="write",
        guild_role=guild_context.role,
    )
    if target_project.is_template:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot move task to a template project")

    default_status = await task_statuses_service.get_default_status(session, target_project.id)
    now = datetime.now(timezone.utc)
    task.project_id = target_project.id
    task.task_status_id = default_status.id
    task.task_status = default_status
    task.sort_order = 0
    task.updated_at = now
    session.add(task)
    await session.commit()

    updated_task = await _fetch_task(session, task.id, guild_context.guild_id)
    if updated_task is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Task missing after move")
    await broadcast_event("task", "updated", _task_payload(updated_task))
    return updated_task


@router.post("/{task_id}/duplicate", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def duplicate_task(
    task_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Task:
    # Fetch the original task with its subtasks
    task_stmt = (
        select(Task)
        .options(selectinload(Task.assignees))
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    await _ensure_can_manage(
        session,
        original_task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
        guild_role=guild_context.role,
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

    await session.commit()
    await session.refresh(new_task)

    # Annotate and return the task
    task_with_relations = await _fetch_task(session, new_task.id, guild_context.guild_id)
    if not task_with_relations:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Duplicated task not found")

    return task_with_relations


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    session: SessionDep,
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    await _ensure_can_manage(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
        guild_role=guild_context.role,
    )

    await session.delete(task)
    await session.commit()
    await broadcast_event("task", "deleted", {"id": task_id, "project_id": task.project_id})


@router.post("/reorder", response_model=List[TaskRead])
async def reorder_tasks(
    reorder_in: TaskReorderRequest,
    session: SessionDep,
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
        guild_role=guild_context.role,
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    now = datetime.now(timezone.utc)
    status_cache: dict[int, TaskStatus] = {}
    for item in reorder_in.items:
        task = task_map[item.id]
        previous_status_category = task.task_status.category if task.task_status else None
        if task.project_id != reorder_in.project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task project mismatch")

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
                        detail="Task status not found for project",
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

    await session.commit()

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
    await _annotate_task_comment_counts(session, tasks)
    await _annotate_task_subtask_progress(session, tasks)
    _annotate_task_guild(tasks)
    await broadcast_event("task", "reordered", {"project_id": reorder_in.project_id})
    return tasks


class ArchiveDoneResponse(BaseModel):
    archived_count: int


@router.post("/archive-done", response_model=ArchiveDoneResponse)
async def archive_done_tasks(
    session: SessionDep,
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
        guild_role=guild_context.role,
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

    await session.commit()
    await broadcast_event("task", "archived", {"project_id": project_id, "count": len(tasks)})
    return ArchiveDoneResponse(archived_count=len(tasks))


@router.get("/{task_id}/subtasks", response_model=List[SubtaskRead])
async def list_subtasks(
    task_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[Subtask]:
    task = await _fetch_task(session, task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    await _get_project_with_access(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
        access="read",
        guild_role=guild_context.role,
    )
    return await _list_subtasks_for_task(session, task.id)


@router.post("/{task_id}/subtasks", response_model=SubtaskRead, status_code=status.HTTP_201_CREATED)
async def create_subtask(
    task_id: int,
    subtask_in: SubtaskCreate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Subtask:
    task = await _fetch_task(session, task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    await _ensure_can_manage(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
        guild_role=guild_context.role,
    )

    content = subtask_in.content.strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Content cannot be empty")

    position = await _next_subtask_position(session, task.id)
    subtask = Subtask(
        task_id=task.id,
        content=content,
        position=position,
    )
    now = datetime.now(timezone.utc)
    subtask.updated_at = now
    _touch_task(task, timestamp=now)
    session.add(subtask)
    session.add(task)
    await session.commit()
    await session.refresh(subtask)
    await _broadcast_task_refresh(session, task.id, guild_context.guild_id)
    return subtask


@router.put("/{task_id}/subtasks/order", response_model=List[SubtaskRead])
async def reorder_subtasks(
    task_id: int,
    reorder_in: SubtaskReorderRequest,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[Subtask]:
    task = await _fetch_task(session, task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    await _ensure_can_manage(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
        guild_role=guild_context.role,
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subtask not found for this task")

    now = datetime.now(timezone.utc)
    for item in reorder_in.items:
        subtask = subtask_map[item.id]
        subtask.position = item.position
        subtask.updated_at = now
        session.add(subtask)
    _touch_task(task, timestamp=now)
    session.add(task)
    await session.commit()
    await _broadcast_task_refresh(session, task.id, guild_context.guild_id)
    return await _list_subtasks_for_task(session, task.id)


@subtasks_router.patch("/subtasks/{subtask_id}", response_model=SubtaskRead)
async def update_subtask(
    subtask_id: int,
    subtask_in: SubtaskUpdate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Subtask:
    subtask = await session.get(Subtask, subtask_id)
    if not subtask:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subtask not found")

    task = await _fetch_task(session, subtask.task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    await _ensure_can_manage(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
        guild_role=guild_context.role,
    )

    update_data = subtask_in.model_dump(exclude_unset=True)
    if not update_data:
        return subtask

    if "content" in update_data and update_data["content"] is not None:
        content_value = update_data["content"].strip()
        if not content_value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Content cannot be empty")
        subtask.content = content_value

    if "is_completed" in update_data and update_data["is_completed"] is not None:
        subtask.is_completed = bool(update_data["is_completed"])

    now = datetime.now(timezone.utc)
    subtask.updated_at = now
    _touch_task(task, timestamp=now)
    session.add(subtask)
    session.add(task)
    await session.commit()
    await session.refresh(subtask)
    await _broadcast_task_refresh(session, task.id, guild_context.guild_id)
    return subtask


@subtasks_router.delete("/subtasks/{subtask_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subtask(
    subtask_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    subtask = await session.get(Subtask, subtask_id)
    if not subtask:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subtask not found")

    task = await _fetch_task(session, subtask.task_id, guild_context.guild_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    await _ensure_can_manage(
        session,
        task.project_id,
        current_user,
        guild_id=guild_context.guild_id,
        guild_role=guild_context.role,
    )

    await session.delete(subtask)
    _touch_task(task)
    session.add(task)
    await session.commit()
    await _broadcast_task_refresh(session, task.id, guild_context.guild_id)
    return None

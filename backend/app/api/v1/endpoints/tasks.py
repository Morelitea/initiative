from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from sqlmodel import select, delete

from app.api.deps import SessionDep, get_current_active_user
from app.models.project import Project, ProjectPermission
from app.models.initiative import Initiative, InitiativeMember, InitiativeRole
from app.models.task import Task, TaskAssignee, TaskStatus
from app.models.user import User, UserRole
from pydantic import ValidationError

from app.schemas.task import TaskCreate, TaskRead, TaskReorderRequest, TaskRecurrence, TaskUpdate
from app.services.realtime import broadcast_event
from app.services import notifications as notifications_service
from app.services.recurrence import get_next_due_date

router = APIRouter()


async def _next_sort_order(session: SessionDep, project_id: int) -> float:
    result = await session.exec(select(func.max(Task.sort_order)).where(Task.project_id == project_id))
    max_value = result.one_or_none()
    return (max_value or 0) + 1


def _task_payload(task: Task) -> dict:
    return TaskRead.model_validate(task).model_dump(mode="json")


async def _fetch_task(session: SessionDep, task_id: int) -> Task | None:
    stmt = select(Task).options(selectinload(Task.assignees)).where(Task.id == task_id)
    result = await session.exec(stmt)
    return result.one_or_none()


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
    previous_status: TaskStatus,
    now: datetime,
) -> bool:
    if (
        previous_status == TaskStatus.done
        or task.status != TaskStatus.done
        or not task.recurrence
        or task.due_date is None
    ):
        return False

    try:
        recurrence = TaskRecurrence.model_validate(task.recurrence)
    except ValidationError:
        return False

    next_due = get_next_due_date(
        task.due_date,
        recurrence,
        completed_occurrences=task.recurrence_occurrence_count,
    )
    if next_due is None:
        return False

    task.status = TaskStatus.backlog
    task.due_date = next_due
    task.sort_order = await _next_sort_order(session, task.project_id)
    task.recurrence_occurrence_count = task.recurrence_occurrence_count + 1
    task.updated_at = now
    session.add(task)
    return True


async def _get_project_with_access(
    session: SessionDep,
    project_id: int,
    user: User,
    *,
    access: str = "read",
) -> Project:
    project_stmt = (
        select(Project)
        .where(Project.id == project_id)
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

    if user.role == UserRole.admin:
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
) -> Project:
    project = await _get_project_with_access(session, project_id, user, access="write")
    return project


async def _allowed_project_ids(session: SessionDep, user: User) -> Optional[set[int]]:
    if user.role == UserRole.admin:
        return None

    initiative_ids_result = await session.exec(
        select(InitiativeMember.initiative_id).where(InitiativeMember.user_id == user.id)
    )
    initiative_ids = {row for row in initiative_ids_result.all() if row is not None}

    permission_ids_result = await session.exec(
        select(ProjectPermission.project_id).where(ProjectPermission.user_id == user.id)
    )
    permission_ids = {row for row in permission_ids_result.all() if row is not None}

    project_result = await session.exec(select(Project.id, Project.owner_id, Project.initiative_id, Project.is_archived))
    ids: set[int] = set()
    for project_id, owner_id, initiative_id, is_archived in project_result.all():
        if is_archived:
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


@router.get("/", response_model=List[TaskRead])
async def list_tasks(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    project_id: Optional[int] = Query(default=None),
) -> List[Task]:
    statement = (
        select(Task)
        .options(selectinload(Task.project), selectinload(Task.assignees))
        .order_by(Task.sort_order.asc(), Task.id.asc())
    )

    allowed_ids = await _allowed_project_ids(session, current_user)
    if allowed_ids is not None:
        if not allowed_ids:
            return []
        statement = statement.where(Task.project_id.in_(tuple(allowed_ids)))

    if project_id is not None:
        statement = statement.where(Task.project_id == project_id)

    result = await session.exec(statement)
    return result.all()


@router.post("/", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_in: TaskCreate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Task:
    project = await _get_project_with_access(session, task_in.project_id, current_user, access="write")

    sort_order = await _next_sort_order(session, task_in.project_id)
    task_data = task_in.dict(exclude={"assignee_ids"})
    task = Task(**task_data, sort_order=sort_order)
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
            )
    await session.commit()
    task = await _fetch_task(session, task.id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Task not found after creation")
    await broadcast_event("task", "created", _task_payload(task))
    return task


@router.get("/{task_id}", response_model=TaskRead)
async def read_task(
    task_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Task:
    task = await _fetch_task(session, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    await _get_project_with_access(session, task.project_id, current_user, access="read")
    return task


@router.patch("/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: int,
    task_in: TaskUpdate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Task:
    task = await _fetch_task(session, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    project = await _get_project_with_access(session, task.project_id, current_user, access="write")

    update_data = task_in.dict(exclude_unset=True)
    assignee_ids = update_data.pop("assignee_ids", None)
    previous_status = task.status
    status_changed = False
    for field, value in update_data.items():
        if field == "status" and value is not None and value != task.status:
            status_changed = True
        if field == "recurrence":
            if value is None:
                task.recurrence_occurrence_count = 0
                setattr(task, field, None)
                continue
            if isinstance(value, TaskRecurrence):
                value = value.model_dump(mode="json")
        setattr(task, field, value)
    now = datetime.now(timezone.utc)
    task.updated_at = now

    if status_changed:
        task.sort_order = await _next_sort_order(session, task.project_id)

    new_assignees: list[User] = []
    if assignee_ids is not None:
        existing_assignee_ids = {assignee.id for assignee in task.assignees}
        await _set_task_assignees(session, task, assignee_ids)
        new_assignees = [assignee for assignee in task.assignees if assignee.id not in existing_assignee_ids]

    await _advance_recurrence_if_needed(session, task, previous_status=previous_status, now=now)

    if new_assignees and project:
        for assignee in new_assignees:
            await notifications_service.enqueue_task_assignment_event(
                session,
                task=task,
                assignee=assignee,
                assigned_by=current_user,
                project_name=project.name,
            )
    session.add(task)
    await session.commit()
    task = await _fetch_task(session, task.id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Task missing after update")
    await broadcast_event("task", "updated", _task_payload(task))
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    task_stmt = select(Task).where(Task.id == task_id)
    task_result = await session.exec(task_stmt)
    task = task_result.one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    await _ensure_can_manage(session, task.project_id, current_user)

    await session.delete(task)
    await session.commit()
    await broadcast_event("task", "deleted", {"id": task_id, "project_id": task.project_id})


@router.post("/reorder", response_model=List[TaskRead])
async def reorder_tasks(
    reorder_in: TaskReorderRequest,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> List[Task]:
    if not reorder_in.items:
        return []

    await _ensure_can_manage(session, reorder_in.project_id, current_user)

    task_ids = [item.id for item in reorder_in.items]
    tasks_stmt = select(Task).options(selectinload(Task.assignees)).where(Task.id.in_(tuple(task_ids)))
    tasks_result = await session.exec(tasks_stmt)
    tasks = tasks_result.all()
    task_map = {task.id: task for task in tasks}

    missing_ids = set(task_ids) - set(task_map.keys())
    if missing_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    now = datetime.now(timezone.utc)
    for item in reorder_in.items:
        task = task_map[item.id]
        previous_status = task.status
        if task.project_id != reorder_in.project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task project mismatch")
        task.status = item.status
        task.sort_order = item.sort_order
        task.updated_at = now
        session.add(task)
        await _advance_recurrence_if_needed(session, task, previous_status=previous_status, now=now)

    await session.commit()

    refreshed_stmt = (
        select(Task)
        .options(selectinload(Task.assignees))
        .where(Task.project_id == reorder_in.project_id)
        .order_by(Task.sort_order.asc(), Task.id.asc())
    )
    refreshed_result = await session.exec(refreshed_stmt)
    tasks = refreshed_result.all()
    await broadcast_event("task", "reordered", {"project_id": reorder_in.project_id})
    return tasks

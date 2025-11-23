from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from sqlmodel import select, delete

from app.api.deps import SessionDep, get_current_active_user
from app.models.project import Project, ProjectMember, ProjectRole
from app.models.team import TeamMember
from app.models.task import Task, TaskAssignee
from app.models.user import User, UserRole
from app.schemas.task import TaskCreate, TaskRead, TaskReorderRequest, TaskUpdate
from app.services.realtime import broadcast_event
from app.services import project_access

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


async def _get_project_and_membership(
    session: SessionDep,
    project_id: int,
    user: User,
    *,
    access: str = "read",
) -> tuple[Project, ProjectMember | None]:
    project_stmt = select(Project).where(Project.id == project_id)
    project_result = await session.exec(project_stmt)
    project = project_result.one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.is_archived and access == "write":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project is archived")

    if user.role == UserRole.admin or project.owner_id == user.id:
        membership = ProjectMember(project_id=project_id, user_id=user.id, role=ProjectRole.admin)
        return project, membership

    membership_stmt = select(ProjectMember).where(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == user.id,
    )
    membership_result = await session.exec(membership_stmt)
    membership = membership_result.one_or_none()

    allowed_roles = (
        project_access.write_roles_set(project) if access == "write" else project_access.read_roles_set(project)
    )
    user_project_role = project_access.user_role_to_project_role(user.role)
    team_member = False
    if project.team_id:
        team_stmt = select(TeamMember).where(TeamMember.team_id == project.team_id, TeamMember.user_id == user.id)
        team_member = (await session.exec(team_stmt)).one_or_none() is not None
        if not team_member and user.role != UserRole.admin and project.owner_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not part of this project's team")

    has_global_access = user_project_role.value in allowed_roles
    has_membership_access = membership and membership.role.value in allowed_roles

    if not membership:
        if has_global_access:
            if project.team_id and not team_member and user.role != UserRole.admin and project.owner_id != user.id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not part of this project's team")
            return project, None
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not part of this project")

    if not has_membership_access and not has_global_access:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions for this project")

    return project, membership


async def _ensure_can_manage(
    session: SessionDep,
    project_id: int,
    user: User,
) -> Project:
    project, _ = await _get_project_and_membership(session, project_id, user, access="write")
    return project


async def _allowed_project_ids(session: SessionDep, user: User) -> Optional[set[int]]:
    if user.role == UserRole.admin:
        return None

    membership_result = await session.exec(select(ProjectMember).where(ProjectMember.user_id == user.id))
    memberships = membership_result.all()
    membership_map = {membership.project_id: membership.role for membership in memberships}
    user_project_role = project_access.user_role_to_project_role(user.role)
    team_ids_result = await session.exec(select(TeamMember.team_id).where(TeamMember.user_id == user.id))
    team_ids = set(team_ids_result.all())

    project_result = await session.exec(select(Project))
    ids: set[int] = set()
    for project in project_result.all():
        if project.is_archived:
            continue
        if project.owner_id == user.id:
            ids.add(project.id)
            continue
        if project.team_id and project.team_id not in team_ids and user.role != UserRole.admin:
            continue
        allowed_roles = project_access.read_roles_set(project)
        membership_role = membership_map.get(project.id)
        if membership_role and membership_role.value in allowed_roles:
            ids.add(project.id)
            continue
        if user_project_role.value in allowed_roles:
            ids.add(project.id)
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
    await _ensure_can_manage(session, task_in.project_id, current_user)

    sort_order = await _next_sort_order(session, task_in.project_id)
    task_data = task_in.dict(exclude={"assignee_ids"})
    task = Task(**task_data, sort_order=sort_order)
    session.add(task)
    await session.flush()
    await _set_task_assignees(session, task, task_in.assignee_ids)
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

    await _get_project_and_membership(session, task.project_id, current_user, access="read")
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

    await _ensure_can_manage(session, task.project_id, current_user)

    update_data = task_in.dict(exclude_unset=True)
    assignee_ids = update_data.pop("assignee_ids", None)
    status_changed = False
    for field, value in update_data.items():
        if field == "status" and value is not None and value != task.status:
            status_changed = True
        setattr(task, field, value)
    task.updated_at = datetime.now(timezone.utc)

    if status_changed:
        task.sort_order = await _next_sort_order(session, task.project_id)

    if assignee_ids is not None:
        await _set_task_assignees(session, task, assignee_ids)

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
        if task.project_id != reorder_in.project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task project mismatch")
        task.status = item.status
        task.sort_order = item.sort_order
        task.updated_at = now
        session.add(task)

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

from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlmodel import select, delete, update

from app.api.deps import GuildContext, RLSSessionDep, SessionDep, get_current_active_user, get_guild_membership
from app.db.session import reapply_rls_context
from app.api.v1.endpoints.tasks import _get_project_with_access, _ensure_can_manage
from app.models.task import Task, TaskStatus, TaskStatusCategory
from app.models.user import User
from app.schemas.task_status import (
    TaskStatusCreate,
    TaskStatusDeleteRequest,
    TaskStatusReorderRequest,
    TaskStatusRead,
    TaskStatusUpdate,
)
from app.services import task_statuses as task_statuses_service

router = APIRouter(prefix="/projects/{project_id}/task-statuses", tags=["task-statuses"])

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


def _sorted(statuses: List[TaskStatus]) -> List[TaskStatus]:
    return sorted(statuses, key=lambda status: (status.position, status.id or 0))


def _resequence(statuses: List[TaskStatus]) -> None:
    for index, item in enumerate(statuses):
        item.position = index


def _ensure_default(statuses: List[TaskStatus]) -> None:
    if any(status.is_default for status in statuses):
        return
    for status_obj in statuses:
        if status_obj.category == TaskStatusCategory.backlog:
            status_obj.is_default = True
            return
    if statuses:
        statuses[0].is_default = True


async def _load_status_or_404(session: SessionDep, project_id: int, status_id: int) -> TaskStatus:
    stmt = select(TaskStatus).where(TaskStatus.project_id == project_id, TaskStatus.id == status_id)
    result = await session.exec(stmt)
    status_obj = result.one_or_none()
    if status_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task status not found")
    return status_obj


async def _ensure_category_not_last(
    session: SessionDep,
    *,
    project_id: int,
    target: TaskStatus,
) -> None:
    if target.category not in {TaskStatusCategory.backlog, TaskStatusCategory.done}:
        return
    stmt = (
        select(func.count(TaskStatus.id))
        .where(TaskStatus.project_id == project_id, TaskStatus.category == target.category)
    )
    result = await session.exec(stmt)
    count = result.one()
    if count <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove the final status for this category",
        )


@router.get("/", response_model=List[TaskStatusRead])
async def list_task_statuses(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[TaskStatus]:
    await _get_project_with_access(
        session,
        project_id,
        current_user,
        guild_id=guild_context.guild_id,
        access="read",
    )
    return await task_statuses_service.list_statuses(session, project_id)


@router.post("/", response_model=TaskStatusRead, status_code=status.HTTP_201_CREATED)
async def create_task_status(
    project_id: int,
    status_in: TaskStatusCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> TaskStatus:
    project = await _ensure_can_manage(
        session,
        project_id,
        current_user,
        guild_id=guild_context.guild_id,
    )

    statuses = await task_statuses_service.list_statuses(session, project.id)
    insert_at = status_in.position if status_in.position is not None else len(statuses)
    insert_at = max(0, min(insert_at, len(statuses)))
    new_status = TaskStatus(
        project_id=project.id,
        name=status_in.name,
        category=status_in.category,
        is_default=status_in.is_default,
        position=insert_at,
    )
    statuses.insert(insert_at, new_status)
    if status_in.is_default:
        for status_obj in statuses:
            if status_obj is not new_status:
                status_obj.is_default = False
    _resequence(statuses)
    _ensure_default(statuses)
    session.add(new_status)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(new_status)
    return new_status


@router.patch("/{status_id}", response_model=TaskStatusRead)
async def update_task_status(
    project_id: int,
    status_id: int,
    status_in: TaskStatusUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> TaskStatus:
    await _ensure_can_manage(
        session,
        project_id,
        current_user,
        guild_id=guild_context.guild_id,
    )

    target = await _load_status_or_404(session, project_id, status_id)
    statuses = await task_statuses_service.list_statuses(session, project_id)
    update_data = status_in.model_dump(exclude_unset=True)

    new_category = update_data.get("category")
    if new_category and new_category != target.category:
        await _ensure_category_not_last(session, project_id=project_id, target=target)
        target.category = new_category
    if "name" in update_data and update_data["name"] is not None:
        target.name = update_data["name"]

    if update_data.get("is_default"):
        for status_obj in statuses:
            status_obj.is_default = status_obj.id == target.id
    elif update_data.get("is_default") is False:
        target.is_default = False

    if update_data.get("position") is not None:
        current_list = [status for status in statuses if status.id != target.id]
        insert_at = max(0, min(update_data["position"], len(current_list)))
        current_list.insert(insert_at, target)
        _resequence(current_list)
        _ensure_default(current_list)
    else:
        _resequence(statuses)
        _ensure_default(statuses)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(target)
    return target


@router.post("/reorder", response_model=List[TaskStatusRead])
async def reorder_task_statuses(
    project_id: int,
    reorder_in: TaskStatusReorderRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[TaskStatus]:
    project = await _ensure_can_manage(
        session,
        project_id,
        current_user,
        guild_id=guild_context.guild_id,
    )


    if not reorder_in.items:
        return await task_statuses_service.list_statuses(session, project.id)

    statuses = await task_statuses_service.list_statuses(session, project.id)
    status_map = {status.id: status for status in statuses}
    seen: set[int] = set()
    ordered: list[TaskStatus] = []
    for item in sorted(reorder_in.items, key=lambda entry: entry.position):
        if item.id in seen:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Duplicate status id")
        status_obj = status_map.get(item.id)
        if status_obj is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task status not found")
        ordered.append(status_obj)
        seen.add(item.id)
    remaining = [status for status in statuses if status.id not in seen]
    combined = ordered + remaining
    _resequence(combined)
    await session.commit()
    await reapply_rls_context(session)
    return await task_statuses_service.list_statuses(session, project.id)


@router.delete("/{status_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_status(
    project_id: int,
    status_id: int,
    delete_in: TaskStatusDeleteRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    await _ensure_can_manage(
        session,
        project_id,
        current_user,
        guild_id=guild_context.guild_id,
    )

    target = await _load_status_or_404(session, project_id, status_id)
    await _ensure_category_not_last(session, project_id=project_id, target=target)

    stmt = select(func.count(Task.id)).where(Task.task_status_id == target.id)
    result = await session.exec(stmt)
    task_count = result.one() or 0

    fallback_obj: TaskStatus | None = None
    if task_count:
        if delete_in.fallback_status_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fallback status required")
        if delete_in.fallback_status_id == target.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fallback status must differ")
        fallback_obj = await _load_status_or_404(session, project_id, delete_in.fallback_status_id)
        if fallback_obj.category != target.category:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Fallback status must share the same category",
            )
        await session.exec(
            update(Task)
            .where(Task.task_status_id == target.id)
            .values(task_status_id=fallback_obj.id)
        )

    await session.exec(delete(TaskStatus).where(TaskStatus.id == target.id))
    remaining = await task_statuses_service.list_statuses(session, project_id)
    _resequence(remaining)
    _ensure_default(remaining)
    await session.commit()

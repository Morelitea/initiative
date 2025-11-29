from __future__ import annotations

from typing import Iterable, Sequence

from sqlmodel import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.task import TaskStatus, TaskStatusCategory

DEFAULT_TASK_STATUSES: Sequence[dict] = (
    {
        "name": "Backlog",
        "category": TaskStatusCategory.backlog,
        "position": 0,
        "is_default": True,
    },
    {
        "name": "In Progress",
        "category": TaskStatusCategory.in_progress,
        "position": 1,
        "is_default": False,
    },
    {
        "name": "Blocked",
        "category": TaskStatusCategory.todo,
        "position": 2,
        "is_default": False,
    },
    {
        "name": "Done",
        "category": TaskStatusCategory.done,
        "position": 3,
        "is_default": False,
    },
)


def _sorted(statuses: Iterable[TaskStatus]) -> list[TaskStatus]:
    return sorted(statuses, key=lambda status: (status.position, status.id or 0))


async def list_statuses(session: AsyncSession, project_id: int) -> list[TaskStatus]:
    stmt = (
        select(TaskStatus)
        .where(TaskStatus.project_id == project_id)
        .order_by(TaskStatus.position.asc(), TaskStatus.id.asc())
    )
    result = await session.exec(stmt)
    return result.all()


async def ensure_default_statuses(session: AsyncSession, project_id: int) -> list[TaskStatus]:
    existing = await list_statuses(session, project_id)
    if existing:
        return _sorted(existing)

    created: list[TaskStatus] = []
    for payload in DEFAULT_TASK_STATUSES:
        status = TaskStatus(project_id=project_id, **payload)
        session.add(status)
        created.append(status)
    await session.flush()
    return _sorted(created)


async def get_default_status(session: AsyncSession, project_id: int) -> TaskStatus:
    statuses = await ensure_default_statuses(session, project_id)
    for status in statuses:
        if status.is_default:
            return status
    backlog = next((status for status in statuses if status.category == TaskStatusCategory.backlog), None)
    if backlog is not None:
        return backlog
    return statuses[0]


async def get_project_status(session: AsyncSession, status_id: int, project_id: int) -> TaskStatus | None:
    stmt = select(TaskStatus).where(TaskStatus.id == status_id, TaskStatus.project_id == project_id)
    result = await session.exec(stmt)
    return result.one_or_none()


async def clone_statuses(
    session: AsyncSession,
    *,
    source_project_id: int,
    target_project_id: int,
) -> dict[int, int]:
    stmt = (
        select(TaskStatus)
        .where(TaskStatus.project_id == source_project_id)
        .order_by(TaskStatus.position.asc(), TaskStatus.id.asc())
    )
    result = await session.exec(stmt)
    source_statuses = result.all()
    if not source_statuses:
        return {}

    await session.exec(delete(TaskStatus).where(TaskStatus.project_id == target_project_id))
    await session.flush()

    mapping: dict[int, int] = {}
    for source_status in source_statuses:
        clone = TaskStatus(
            project_id=target_project_id,
            name=source_status.name,
            position=source_status.position,
            category=source_status.category,
            is_default=source_status.is_default,
        )
        session.add(clone)
        await session.flush()
        mapping[source_status.id] = clone.id
    return mapping

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from sqlalchemy import func
from sqlmodel import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.tenant.project import Project
from app.models.tenant.task import TaskStatus, TaskStatusCategory
from app.schemas.tenant.task_status import InitiativeTaskStatusRead
from app.services import permissions as permissions_service

CATEGORY_DEFAULTS: dict[TaskStatusCategory, tuple[str, str]] = {
    TaskStatusCategory.backlog: ("#94A3B8", "circle-dashed"),
    TaskStatusCategory.todo: ("#FBBF24", "circle-pause"),
    TaskStatusCategory.in_progress: ("#60A5FA", "circle-play"),
    TaskStatusCategory.done: ("#34D399", "circle-check"),
}


def defaults_for_category(category: TaskStatusCategory) -> tuple[str, str]:
    return CATEGORY_DEFAULTS[category]


def _seeded(
    name: str, category: TaskStatusCategory, position: int, *, is_default: bool = False
) -> dict:
    color, icon = CATEGORY_DEFAULTS[category]
    return {
        "name": name,
        "category": category,
        "position": position,
        "is_default": is_default,
        "color": color,
        "icon": icon,
    }


DEFAULT_TASK_STATUSES: Sequence[dict] = (
    _seeded("Backlog", TaskStatusCategory.backlog, 0, is_default=True),
    _seeded("In Progress", TaskStatusCategory.in_progress, 1),
    _seeded("Blocked", TaskStatusCategory.todo, 2),
    _seeded("Done", TaskStatusCategory.done, 3),
)


def _sorted(statuses: Iterable[TaskStatus]) -> list[TaskStatus]:
    return sorted(statuses, key=lambda status: (status.position, status.id or 0))


async def list_statuses(session: AsyncSession, project_id: int) -> Sequence[TaskStatus]:
    stmt = (
        select(TaskStatus)
        .where(TaskStatus.project_id == project_id)
        .order_by(TaskStatus.position.asc(), TaskStatus.id.asc())
    )
    result = await session.exec(stmt)
    return result.all()


async def ensure_default_statuses(
    session: AsyncSession, project_id: int
) -> list[TaskStatus]:
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
    backlog = next(
        (
            status
            for status in statuses
            if status.category == TaskStatusCategory.backlog
        ),
        None,
    )
    if backlog is not None:
        return backlog
    return statuses[0]


async def get_project_status(
    session: AsyncSession, status_id: int, project_id: int
) -> TaskStatus | None:
    stmt = select(TaskStatus).where(
        TaskStatus.id == status_id, TaskStatus.project_id == project_id
    )
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

    await session.exec(
        delete(TaskStatus).where(TaskStatus.project_id == target_project_id)
    )
    await session.flush()

    mapping: dict[int, int] = {}
    for source_status in source_statuses:
        clone = TaskStatus(
            project_id=target_project_id,
            name=source_status.name,
            position=source_status.position,
            category=source_status.category,
            is_default=source_status.is_default,
            color=source_status.color,
            icon=source_status.icon,
        )
        session.add(clone)
        await session.flush()
        mapping[source_status.id] = clone.id  # ty: ignore[invalid-assignment] — persisted row, id is set
    return mapping


@dataclass
class _StatusGroup:
    """One ``(name, category)`` column being collected across projects."""

    color: str
    icon: str
    project_ids: set[int] = field(default_factory=set)


async def list_initiative_statuses(
    session: AsyncSession,
    *,
    initiative_id: int,
    user_id: int,
    guild_id: int,
) -> list[InitiativeTaskStatusRead]:
    """The distinct status columns across an initiative's readable projects.

    Visibility is the project listing's own rule — ``dac_scope_clause`` narrows
    the scan to the projects this request may read — so both the columns and
    the counts describe the caller's view of the initiative. Archived projects
    and templates stay out, matching the default project list.
    """
    project_conditions = [
        Project.initiative_id == initiative_id,
        Project.is_archived.is_(False),
        Project.is_template.is_(False),
        permissions_service.dac_scope_clause(
            Tool.project, Project.id, user_id, guild_id=guild_id
        ),
    ]

    total_stmt = select(func.count()).select_from(Project).where(*project_conditions)
    projects_total = int((await session.exec(total_stmt)).one())
    if not projects_total:
        return []

    rows_stmt = (
        select(
            TaskStatus.name,
            TaskStatus.category,
            TaskStatus.color,
            TaskStatus.icon,
            TaskStatus.project_id,
        )
        .join(Project, Project.id == TaskStatus.project_id)
        .where(*project_conditions)
        .order_by(TaskStatus.position.asc(), TaskStatus.name.asc(), TaskStatus.id.asc())
    )
    rows = (await session.exec(rows_stmt)).all()

    # Board order: the scan is ordered by position, so a column first seen at
    # position 1 is grouped — and emitted — before one first seen at position 2.
    grouped: dict[tuple[str, TaskStatusCategory], _StatusGroup] = {}
    for name, category, color, icon, project_id in rows:
        group = grouped.get((name, category))
        if group is None:
            group = _StatusGroup(color=color, icon=icon)
            grouped[(name, category)] = group
        group.project_ids.add(project_id)

    return [
        InitiativeTaskStatusRead(
            name=name,
            category=category,
            color=group.color,
            icon=group.icon,
            project_count=len(group.project_ids),
            projects_total=projects_total,
        )
        for (name, category), group in grouped.items()
    ]

"""Build a self-contained JSON export for a single project.

The output is a :class:`ProjectExportEnvelope` that references tags, task
statuses, properties, and users by string keys (name / email) rather than
integer IDs so it can be imported on a different Initiative instance.

Out of scope (see plan): comments, documents, attachments, project-role
permissions, favorites, recents, queues. Those would extend the schema
under a future ``schema_version`` bump.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.core.version import get_version
from app.models.project import Project
from app.models.property import PropertyType, TaskPropertyValue
from app.models.tag import ProjectTag, TaskTag
from app.models.task import Task, TaskStatus
from app.schemas.project_export import (
    SCHEMA_VERSION,
    ProjectExportEnvelope,
    ProjectExportProject,
    ProjectExportPropertyDefinition,
    ProjectExportPropertyValue,
    ProjectExportSubtask,
    ProjectExportTag,
    ProjectExportTask,
    ProjectExportTaskStatus,
)


async def build_project_export(
    session: AsyncSession,
    project_id: int,
    *,
    exported_by_email: Optional[str] = None,
    source_instance_url: Optional[str] = None,
) -> ProjectExportEnvelope:
    """Eager-load the project graph and serialize it to an envelope.

    The caller is responsible for permission checks before invoking this.
    """
    stmt = (
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.task_statuses),
            selectinload(Project.tag_links).selectinload(ProjectTag.tag),
            selectinload(Project.tasks).selectinload(Task.task_status),
            selectinload(Project.tasks).selectinload(Task.assignees),
            selectinload(Project.tasks).selectinload(Task.subtasks),
            selectinload(Project.tasks).selectinload(Task.tag_links).selectinload(TaskTag.tag),
            selectinload(Project.tasks)
            .selectinload(Task.property_values)
            .selectinload(TaskPropertyValue.property_definition),
            selectinload(Project.tasks)
            .selectinload(Task.property_values)
            .selectinload(TaskPropertyValue.value_user),
        )
    )
    project = (await session.exec(stmt)).one()

    # Project-level tag set
    project_tags: list[ProjectExportTag] = []
    seen_tag_names: set[str] = set()
    for link in project.tag_links or []:
        tag = link.tag
        if tag is None or tag.name in seen_tag_names:
            continue
        seen_tag_names.add(tag.name)
        project_tags.append(ProjectExportTag(name=tag.name, color=tag.color))

    # Per-project task statuses
    statuses_sorted = sorted(project.task_statuses or [], key=lambda s: s.position)
    statuses = [
        ProjectExportTaskStatus(
            name=s.name,
            category=s.category,
            position=s.position,
            color=s.color,
            icon=s.icon,
            is_default=s.is_default,
        )
        for s in statuses_sorted
    ]

    # Tasks (and gather property-definition references along the way)
    tasks: list[ProjectExportTask] = []
    referenced_property_ids: dict[int, _PropDefSnapshot] = {}
    tasks_sorted = sorted(project.tasks or [], key=lambda t: (t.sort_order, t.id or 0))
    for task in tasks_sorted:
        property_values: list[ProjectExportPropertyValue] = []
        for pv in task.property_values or []:
            pd = pv.property_definition
            if pd is None:
                continue
            referenced_property_ids[pd.id] = _PropDefSnapshot(
                name=pd.name,
                type=pd.type,
                position=pd.position,
                color=pd.color,
                options=pd.options,
            )
            property_values.append(_serialize_property_value(pv, pd.type))

        subtasks_sorted = sorted(task.subtasks or [], key=lambda s: s.position)
        subtasks = [
            ProjectExportSubtask(
                content=s.content,
                is_completed=s.is_completed,
                position=s.position,
            )
            for s in subtasks_sorted
        ]

        tag_names = []
        seen_task_tags: set[str] = set()
        for link in task.tag_links or []:
            if link.tag and link.tag.name not in seen_task_tags:
                seen_task_tags.add(link.tag.name)
                tag_names.append(link.tag.name)

        assignee_emails = [u.email for u in (task.assignees or []) if u.email]

        status_name = (
            task.task_status.name
            if task.task_status is not None
            else _fallback_status_name(statuses_sorted)
        )

        tasks.append(
            ProjectExportTask(
                title=task.title,
                description=task.description,
                priority=task.priority,
                start_date=task.start_date,
                due_date=task.due_date,
                recurrence=task.recurrence,
                recurrence_strategy=task.recurrence_strategy,
                recurrence_occurrence_count=task.recurrence_occurrence_count,
                sort_order=task.sort_order,
                is_archived=task.is_archived,
                status_name=status_name,
                tag_names=tag_names,
                assignee_emails=assignee_emails,
                subtasks=subtasks,
                property_values=property_values,
            )
        )

    property_definitions = [
        ProjectExportPropertyDefinition(
            name=snap.name,
            type=snap.type,
            position=snap.position,
            color=snap.color,
            options=snap.options,
        )
        for snap in referenced_property_ids.values()
    ]

    return ProjectExportEnvelope(
        schema_version=SCHEMA_VERSION,
        app_version=get_version(),
        exported_at=datetime.now(timezone.utc),
        exported_by_email=exported_by_email,
        source_instance_url=source_instance_url,
        project=ProjectExportProject(
            name=project.name,
            icon=project.icon,
            description=project.description,
            is_template=project.is_template,
            is_archived=project.is_archived,
        ),
        tags=project_tags,
        task_statuses=statuses,
        property_definitions=property_definitions,
        tasks=tasks,
    )


def _fallback_status_name(statuses_sorted: list[TaskStatus]) -> str:
    """Pick a status name to associate with a task whose status row is
    missing (defensive — shouldn't happen in normal operation)."""
    for s in statuses_sorted:
        if s.is_default:
            return s.name
    return statuses_sorted[0].name if statuses_sorted else "Backlog"


def _serialize_property_value(
    pv: TaskPropertyValue,
    prop_type: PropertyType,
) -> ProjectExportPropertyValue:
    """Encode a typed property value into the export's flat shape."""
    base = ProjectExportPropertyValue(
        property_name=pv.property_definition.name,
        property_type=prop_type,
    )
    if prop_type == PropertyType.text or prop_type == PropertyType.url or prop_type == PropertyType.select:
        base.value_text = pv.value_text
    elif prop_type == PropertyType.number:
        base.value_number = float(pv.value_number) if pv.value_number is not None else None
    elif prop_type == PropertyType.checkbox:
        base.value_boolean = pv.value_boolean
    elif prop_type == PropertyType.date:
        base.value_text = pv.value_date.isoformat() if pv.value_date else None
    elif prop_type == PropertyType.datetime:
        base.value_text = pv.value_datetime.isoformat() if pv.value_datetime else None
    elif prop_type == PropertyType.multi_select:
        base.value_json = pv.value_json
    elif prop_type == PropertyType.user_reference:
        if pv.value_user is not None:
            base.value_email = pv.value_user.email
    return base


class _PropDefSnapshot:
    """Lightweight value object for collecting referenced property
    definitions without importing the SQLModel class into the envelope."""

    __slots__ = ("name", "type", "position", "color", "options")

    def __init__(
        self,
        *,
        name: str,
        type: PropertyType,
        position: float,
        color: Optional[str],
        options: Optional[list[dict]],
    ) -> None:
        self.name = name
        self.type = type
        self.position = position
        self.color = color
        self.options = options

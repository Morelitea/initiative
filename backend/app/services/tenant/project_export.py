"""Build a self-contained JSON export for a single project.

The output is a :class:`ProjectExportEnvelope` that references tags, task
statuses, properties, and users by string keys (name / handle) rather than
integer IDs so it can be imported on a different Initiative instance.

Tasks carry what was said on them and what they point at: comments (as
text plus the author's handle and display name — never an id), and the edges
between tasks, named by ``external_ref`` so the far end resolves after both
ends have been restored. Both are optional fields, so an older reader that
does not know them ignores them and the version does not move.

Out of scope (see plan): documents, attachments, project-role permissions,
favorites, recents, queues. Those would extend the schema under a future
``schema_version`` bump.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.core.relationships import RelationshipType, decode_node_id, node_id
from app.core.search import SearchEntityType
from app.core.user_display import display_name, handle_of
from app.core.version import get_version
from app.models.tenant.comment import Comment
from app.models.tenant.relationship import EntityRelationship
from app.models.tenant.project import Project
from app.models.tenant.property import PropertyType, TaskPropertyValue
from app.models.tenant.task import Task, TaskStatus
from app.schemas.tenant.project_export import (
    SCHEMA_VERSION,
    ProjectExportComment,
    ProjectExportEnvelope,
    ProjectExportProject,
    ProjectExportPropertyDefinition,
    ProjectExportPropertyValue,
    ProjectExportChecklistItem,
    ProjectExportTag,
    ProjectExportTask,
    ProjectExportTaskLink,
    ProjectExportTaskStatus,
)
from app.services.tenant import tags as tags_service


async def build_project_export(
    session: AsyncSession,
    project_id: int,
    *,
    exported_by_handle: Optional[str] = None,
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
            selectinload(Project.tasks).selectinload(Task.task_status),
            selectinload(Project.tasks).selectinload(Task.assignees),
            selectinload(Project.tasks)
            .selectinload(Task.property_values)
            .selectinload(TaskPropertyValue.property_definition),
            selectinload(Project.tasks)
            .selectinload(Task.property_values)
            .selectinload(TaskPropertyValue.value_user),
        )
    )
    project = (await session.exec(stmt)).one()
    await tags_service.annotate_tags(session, [project])
    await tags_service.annotate_tags(session, project.tasks or [])

    task_ids = [task.id for task in (project.tasks or []) if task.id is not None]
    comments_by_task = await _load_comments(session, task_ids)
    links_by_task = await _load_links(session, task_ids)

    # Project-level tag set
    project_tags: list[ProjectExportTag] = []
    seen_tag_names: set[str] = set()
    for tag in project.tags or []:
        if tag.name in seen_tag_names:
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
    tasks_sorted = sorted(project.tasks or [], key=lambda t: (t.position, t.id or 0))
    for task in tasks_sorted:
        property_values: list[ProjectExportPropertyValue] = []
        for pv in task.property_values or []:
            pd = pv.property_definition
            if pd is None:
                continue
            referenced_property_ids[pd.id] = _PropDefSnapshot(  # ty: ignore[invalid-assignment] — persisted row, id is set
                name=pd.name,
                type=pd.type,
                position=pd.position,
                color=pd.color,
                options=pd.options,
            )
            property_values.append(_serialize_property_value(pv, pd.type))

        checklist = [
            ProjectExportChecklistItem(
                text=item.get("text", ""), done=bool(item.get("done"))
            )
            for item in (task.checklist or [])
            if item.get("text")
        ]

        task_tags: list[ProjectExportTag] = []
        seen_task_tags: set[str] = set()
        for tag in task.tags or []:
            if tag.name not in seen_task_tags:
                seen_task_tags.add(tag.name)
                task_tags.append(ProjectExportTag(name=tag.name, color=tag.color))

        assignee_handles = [handle_of(u) for u in (task.assignees or [])]

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
                position=task.position,
                archived_at=task.archived_at,
                completed_at=task.completed_at,
                status_name=status_name,
                tags=task_tags,
                assignee_handles=assignee_handles,
                checklist=checklist,
                property_values=property_values,
                created_at=task.created_at,
                updated_at=task.updated_at,
                external_ref=task_ref(task.id),
                links=links_by_task.get(task.id, []),
                comments=comments_by_task.get(task.id, []),
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
        exported_by_handle=exported_by_handle,
        source_instance_url=source_instance_url,
        project=ProjectExportProject(
            name=project.name,
            icon=project.icon,
            description=project.description,
            is_template=project.is_template,
            archived_at=project.archived_at,
            start_date=project.start_date,
            end_date=project.end_date,
        ),
        tags=project_tags,
        task_statuses=statuses,
        property_definitions=property_definitions,
        tasks=tasks,
    )


#: Edge kinds a task envelope carries. ``tagged_with`` is already the task's
#: ``tags`` and ``references`` is derived from bodies on save rather than
#: asserted, so neither is something a restore should re-assert from here.
_EXPORTED_LINK_TYPES: tuple[RelationshipType, ...] = (
    RelationshipType.depends_on,
    RelationshipType.part_of,
    RelationshipType.related_to,
    RelationshipType.attached,
)

#: Far ends worth naming: the kinds whose importer registers a ref, so a link
#: to one can actually be resolved on the other side. A link to anything else
#: would be written only to be counted as unresolved.
_LINKABLE_TARGETS: frozenset[SearchEntityType] = frozenset(
    {SearchEntityType.task, SearchEntityType.calendar_event}
)


def task_ref(task_id: int | None) -> str | None:
    """The name a task answers to across one import.

    Derived from the source id rather than stored, because it has to be the
    same string wherever the task is named — a project envelope writing its
    own tasks, and another project's envelope pointing at one of them in the
    same backup.
    """
    return f"task:{task_id}" if task_id is not None else None


def _entity_ref(kind: SearchEntityType, entity_id: int) -> str:
    return f"{kind.value}:{entity_id}"


async def _load_comments(
    session: AsyncSession, task_ids: list[int]
) -> dict[int, list[ProjectExportComment]]:
    """What was said on each of these tasks, oldest first.

    Authors cross as a handle and a display name and never as an id — the
    rule every envelope follows for people. Trashed comments do not cross at
    all: a restore is not where somebody's deleted words come back.
    """
    if not task_ids:
        return {}
    rows = (
        await session.exec(
            select(Comment)
            .where(
                Comment.task_id.in_(task_ids),
                Comment.deleted_at.is_(None),
            )
            .options(selectinload(Comment.author))
            .order_by(Comment.created_at.asc(), Comment.id.asc())
        )
    ).all()
    by_task: dict[int, list[ProjectExportComment]] = {}
    for row in rows:
        author = getattr(row, "author", None)
        by_task.setdefault(row.task_id, []).append(
            ProjectExportComment(
                author_handle=handle_of(author) if author is not None else None,
                author_name=display_name(author) if author is not None else None,
                body=row.content,
                created_at=row.created_at,
                external_ref=f"comment:{row.id}",
                reply_to_ref=(
                    f"comment:{row.parent_comment_id}"
                    if row.parent_comment_id is not None
                    else None
                ),
            )
        )
    return by_task


async def _load_links(
    session: AsyncSession, task_ids: list[int]
) -> dict[int, list[ProjectExportTaskLink]]:
    """The edges these tasks assert, from the task's side.

    Only edges *stored* with one of these tasks as the source are read, so an
    edge is written once rather than from both ends — a symmetric one is
    stored in node order, and the importer re-orders it on the way back in.

    Refs, not ids: the far end may be in another envelope of the same backup
    (a task in a different project, a sprint on a calendar), which resolves
    once everything has been applied, or outside it entirely, which is
    counted. Both are ordinary, and neither is knowable from here.
    """
    if not task_ids:
        return {}
    source_nodes = [node_id(SearchEntityType.task, task_id) for task_id in task_ids]
    rows = (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.source_node.in_(source_nodes),
                EntityRelationship.relationship_type.in_(
                    [t.value for t in _EXPORTED_LINK_TYPES]
                ),
                EntityRelationship.removed_at.is_(None),
            )
        )
    ).all()
    by_task: dict[int, list[ProjectExportTaskLink]] = {}
    for row in rows:
        try:
            target_kind, target_id = decode_node_id(row.target_node)
        except ValueError:
            # A kind this build has no code for: nothing here can name it.
            continue
        if target_kind not in _LINKABLE_TARGETS:
            continue
        by_task.setdefault(row.source_id, []).append(
            ProjectExportTaskLink(
                type=RelationshipType(row.relationship_type),
                target_external_ref=_entity_ref(target_kind, target_id),
            )
        )
    return by_task


async def list_project_ids_for_export(
    session,
    current_user,
    guild_id: int,
    *,
    initiative_ids: list[int],
) -> list[int]:
    """Ids of every project the user may include in an aggregate export —
    DAC-visible (a request that reaches the whole guild sees all). The aggregate
    export includes read-accessible projects by design; the per-project seams
    still enforce their own access level per entity."""
    from sqlmodel import select

    from app.models.tenant.project import Project

    if not initiative_ids:
        return []
    conditions = [
        Project.initiative_id.in_(initiative_ids),
    ]
    statement = select(Project.id).where(*conditions).order_by(Project.id.asc())
    return list(await session.exec(statement))


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
    if (
        prop_type == PropertyType.text
        or prop_type == PropertyType.url
        or prop_type == PropertyType.select
    ):
        base.value_text = pv.value_text
    elif prop_type == PropertyType.number:
        base.value_number = (
            float(pv.value_number) if pv.value_number is not None else None
        )
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
            base.value_handle = handle_of(pv.value_user)
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

from copy import deepcopy
from datetime import datetime, timezone
from typing import Annotated, List, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload, undefer
from sqlmodel import select, delete

from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    IncludeDeletedDep,
    RLSSessionDep,
    SessionDep,
    UserSessionDep,
    app_scope,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
)
from app.core.audit_events import AuditEventType
from app.core.messages import ChecklistMessages, TaskMessages
from app.db.query import build_paginated_response, paginated_query
from app.db.session import routed_guild_id
from app.models.platform.user import User
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant.project import Project
from app.models.tenant.property import TaskPropertyValue
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
from app.schemas.ai_generation import (
    GenerateChecklistResponse,
    GenerateDescriptionResponse,
)
from app.schemas.tenant.property import PropertyValuesSetRequest
from app.schemas.tenant.tag import TagSetRequest
from app.schemas.tenant.task import (
    ChecklistItem,
    ChecklistItemToggle,
    TaskCreate,
    TaskListResponse,
    TaskMoveRequest,
    TaskRead,
    TaskReorderRequest,
    TaskRecurrence,
    TaskUpdate,
)
from app.services import ai_generation as ai_generation_service
from app.services import audit as audit_service
from app.services import notifications as notifications_service
from app.services.ai_settings import resolve_ai_settings
from app.services.tenant import attachments as attachments_service
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service
from app.services.tenant import task_checklist as checklist_service
from app.services.tenant import task_creation as task_creation_service
from app.services.tenant import task_description as task_description_service
from app.services.tenant import task_queries
from app.services.tenant import task_statuses as task_statuses_service
from app.services.tenant.soft_delete import trash
from app.services.tenant.task_completion import sync_completed_at

router = APIRouter(route_class=ActorRoute)

#: The routes an installed app may call. A task is the project's, so it
#: answers to the projects scopes.
ProjectsRead = Annotated[ActorContext, Depends(app_scope("projects:read"))]
ProjectsWrite = Annotated[ActorContext, Depends(app_scope("projects:write"))]


# Cross-guild "my tasks" aggregates (My Tasks / Created Tasks pages). Mounted
# under /api/v1/me; user-scoped (no guild context), routes per member guild
# itself via gather_across_guilds.
me_router = APIRouter()
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


# Positions are stored as NUMERIC(20, 10); two stored values differ by at least
# 1e-10. When repeated midpoint inserts squeeze neighbors closer than this, the
# next midpoint can no longer fit between them, so we renumber the whole group.
_MIN_POSITION_GAP = 1e-9


async def _rebalance_if_needed(
    session: SessionDep, project_id: int, moved_positions: dict[int, float]
) -> dict[int, float]:
    """Renumber a project's tasks to evenly spaced integers when two positions have
    collided to within ``_MIN_POSITION_GAP`` (precision exhaustion from repeated
    drag-reorder midpoint inserts).

    Positions are a single project-wide ordering (the list view sorts by them and
    kanban columns are filtered slices of that order), so the rebalance spans the
    whole project rather than a single status group.

    A collision can only be introduced next to a task we just moved, so the common
    case (no exhaustion) is settled with a cheap existence query per moved task
    instead of loading the whole project. Only on a near-collision do we scan and
    renumber.

    Sets only ``position`` on the touched tasks — never ``updated_at`` — so tasks
    that were merely renumbered (not explicitly moved) don't churn. Returns a map
    of task id -> new position for every task it changed (empty when no rebalance
    was necessary).
    """
    # The session runs with autoflush off, so push the just-applied positions to
    # the DB before the neighbor check evaluates them in SQL (otherwise it reads
    # stale values and reports phantom collisions).
    await session.flush()

    collision = False
    for moved_id, position in moved_positions.items():
        neighbor = await session.exec(
            select(Task.id)
            .where(
                Task.project_id == project_id,
                Task.id != moved_id,
                func.abs(Task.position - position) < _MIN_POSITION_GAP,
            )
            .limit(1)
        )
        if neighbor.first() is not None:
            collision = True
            break
    if not collision:
        return {}

    stmt = (
        select(Task)
        .where(Task.project_id == project_id)
        .order_by(Task.position.asc(), Task.id.asc())
    )
    result = await session.exec(stmt)
    ordered = result.all()

    changed: dict[int, float] = {}
    for index, task in enumerate(ordered, start=1):
        new_position = float(index)
        if task.position != new_position:
            task.position = new_position
            session.add(task)
            changed[task.id] = new_position  # ty: ignore[invalid-assignment] — persisted row, id is set
    return changed


def _touch_project(project: Project, now: datetime) -> None:
    """Bump a project's updated_at so task activity surfaces in 'sort by updated'."""
    project.updated_at = now


#: A task has no sharing of its own: it is reached through its project, at the
#: project's level. Which tool that is comes from the registry entry the
#: ``tasks`` policy is rendered from, so the routes and the policy cannot
#: disagree about a task's parent.
_GOVERNING = resource_access.governing_tool("tasks")


async def _load_for_change(
    session: SessionDep, task_id: int, user: User | None, context: ActorContext
) -> Task:
    """The task with what changing it reads — its project and initiative, its
    status and its assignees — refused unless the request may edit the project.

    What only a response reads (counts, tags, properties, the creator) is left
    to :func:`task_queries.load_task` once the change has landed.
    """
    statement = (
        select(Task)
        .where(Task.id == task_id)
        .options(
            joinedload(Task.project).options(
                joinedload(Project.initiative), undefer(Project.actions)
            ),
            joinedload(Task.task_status),
            selectinload(Task.assignees),
        )
    )
    task = (await session.exec(statement)).one_or_none()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_FOUND
        )
    resource_access.authorize(
        _GOVERNING, task.project, user, context=context, access="write"
    )
    return task


async def _response(session: SessionDep, task_id: int, missing: str) -> Task:
    """The task as a ``TaskRead`` reads it, after a change has committed."""
    task = await task_queries.load_task(session, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=missing
        )
    return task


@me_router.get("/tasks", response_model=TaskListResponse)
async def list_my_tasks(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    conditions: Optional[str] = Query(default=None),
    include_archived: bool = Query(default=False, description="Include archived tasks"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=0, le=100),
    sorting: Optional[str] = Query(default=None),
    tz: Optional[str] = Query(default=None),
) -> TaskListResponse:
    """Tasks assigned to the current user across every guild they belong to.

    An optional ``guild_ids`` conditions entry narrows to a subset of guilds.
    """
    q = await task_queries.parse_task_list_query(
        session, conditions, sorting, tz, across_guilds_for=current_user
    )
    items, total_count, actual_page = await task_queries.list_global_tasks(
        session,
        current_user,
        q,
        include_archived=include_archived,
        page=page,
        page_size=page_size,
    )
    return TaskListResponse(
        **build_paginated_response(
            items=items,
            total_count=total_count,
            page=actual_page,
            page_size=page_size,
            sorting=sorting,
        )
    )


@me_router.get("/tasks/created", response_model=TaskListResponse)
async def list_my_created_tasks(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    conditions: Optional[str] = Query(default=None),
    include_archived: bool = Query(default=False, description="Include archived tasks"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=0, le=100),
    sorting: Optional[str] = Query(default=None),
    tz: Optional[str] = Query(default=None),
) -> TaskListResponse:
    """Tasks created by the current user across every guild they belong to."""
    q = await task_queries.parse_task_list_query(
        session, conditions, sorting, tz, across_guilds_for=current_user
    )
    items, total_count, actual_page = await task_queries.list_global_tasks(
        session,
        current_user,
        q,
        created=True,
        include_archived=include_archived,
        page=page,
        page_size=page_size,
    )
    return TaskListResponse(
        **build_paginated_response(
            items=items,
            total_count=total_count,
            page=actual_page,
            page_size=page_size,
            sorting=sorting,
        )
    )


@router.get("/", response_model=TaskListResponse)
async def list_tasks(
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsRead,
    conditions: Optional[str] = Query(
        default=None,
        description=(
            "JSON list of filter conditions, AND-ed together. Each object: "
            '{"field": "<column>", "op": "<operator>", "value": <val>}. '
            "Any Task column is valid plus virtual fields: "
            "status_category, assignee_ids, tag_ids, initiative_ids. "
            'An object with a "conditions" key is an AND/OR group: '
            '{"logic": "or", "conditions": [...]}.'
        ),
    ),
    include_archived: bool = Query(default=False, description="Include archived tasks"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=0, le=100),
    sorting: Optional[str] = Query(
        default=None,
        description='JSON list of sort fields: [{"field": "due_date", "dir": "desc"}]',
    ),
    tz: Optional[str] = Query(
        default=None,
        description="IANA timezone name (e.g. America/Los_Angeles) for date_group calculation",
    ),
) -> TaskListResponse:
    q = await task_queries.parse_task_list_query(session, conditions, sorting, tz)
    if current_user is None:
        task_queries.refuse_person_filters(q)

    # Guild-scoped list. Cross-guild "my tasks" aggregates live under
    # /me/tasks and /me/tasks/created (see list_my_tasks above).
    build = await task_queries.guild_task_query_builder(
        session,
        current_user,
        guild_context,
        q=q,
        include_archived=include_archived,
    )
    if build is None:
        return TaskListResponse(
            **build_paginated_response(
                items=[],
                total_count=0,
                page=1,
                page_size=page_size,
                sorting=sorting,
            )
        )

    count_stmt = select(func.count()).select_from(build(select(Task.id)).subquery())
    statement = task_queries.list_statement(build, q, *task_queries.LIST_ROW_OPTIONS)
    tasks, total_count, actual_page = await paginated_query(
        session, statement, count_stmt, page, page_size
    )
    items = await task_queries.list_reads(session, tasks, routed_guild_id(session))
    return TaskListResponse(
        **build_paginated_response(
            items=items,
            total_count=total_count,
            page=actual_page,
            page_size=page_size,
            sorting=sorting,
        )
    )


@router.post("/", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_in: TaskCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsWrite,
) -> Task:
    project = await resource_access.load_authorized(
        session,
        _GOVERNING,
        task_in.project_id,
        current_user,
        guild_context,
        access="write",
    )

    task_data = task_in.model_dump(
        exclude={
            "assignee_ids",
            "task_status_id",
            "tag_ids",
            "property_values",
            "checklist",
        }
    )

    # Serialize recurrence to JSON if present
    if task_data.get("recurrence") is not None:
        if isinstance(task_data["recurrence"], TaskRecurrence):
            task_data["recurrence"] = task_data["recurrence"].model_dump(mode="json")
        elif isinstance(task_data["recurrence"], dict):
            # Already a dict, convert to model and back to ensure proper serialization
            recurrence_obj = TaskRecurrence.model_validate(task_data["recurrence"])
            task_data["recurrence"] = recurrence_obj.model_dump(mode="json")

    task_data.pop("project_id", None)
    task = await task_creation_service.create_task_row(
        session,
        project=project,
        task_status_id=task_in.task_status_id,
        **task_data,
        created_by=guild_context.user_id,
        checklist=checklist_service.normalize(task_in.checklist),
    )
    await task_creation_service.set_task_assignees(
        session, task, task_in.assignee_ids, project=project
    )
    if task.assignees:
        assigned_by = await notifications_service.author_of(
            session, guild_context, current_user
        )
        await notifications_service.notify_assigned(
            session,
            task,
            [assignee.id for assignee in task.assignees],
            assigned_by=assigned_by,
            project_name=project.name,
        )

    # Attach tags and custom properties in the same transaction. Both services
    # mutate the session without committing; a raised HTTPException (invalid
    # tag/property) rolls back so no orphan task is persisted.
    try:
        if task_in.tag_ids:
            await tags_service.set_entity_tags(
                session,
                tags_service.TAG_LINKS["task"],
                guild_id=guild_context.guild_id,
                entity_id=task.id,
                tag_ids=task_in.tag_ids,
            )
        if task_in.property_values:
            await properties_service.set_task_property_values(
                session,
                task,
                await properties_service.property_values_by_row_id(
                    session, task_in.property_values
                ),
                project.initiative_id,
            )
    except HTTPException:
        await session.rollback()
        raise

    if task.description:
        await task_description_service.description_saved(
            session,
            task,
            previous=None,
            author=current_user,
        )

    _touch_project(project, datetime.now(timezone.utc))
    await session.commit()
    return await _response(session, task.id, TaskMessages.MISSING_AFTER_CREATE)


@router.get("/{task_id}", response_model=TaskRead)
async def read_task(
    task_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsRead,
    include_deleted: IncludeDeletedDep = False,
) -> Task:
    task = await task_queries.load_task(session, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_FOUND
        )
    resource_access.authorize(
        _GOVERNING, task.project, current_user, context=guild_context
    )
    return task


@router.patch("/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: int,
    task_in: TaskUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsWrite,
) -> Task:
    task = await _load_for_change(session, task_id, current_user, guild_context)
    project = task.project

    update_data = task_in.model_dump(exclude_unset=True)
    assignee_ids = update_data.pop("assignee_ids", None)
    tag_ids = update_data.pop("tag_ids", None)
    property_values = update_data.pop("property_values", None)
    checklist_sent = update_data.pop("checklist", None) is not None
    previous_description = task.description
    previous_status_category = task.task_status.category if task.task_status else None
    new_status_id = update_data.pop("task_status_id", None)

    if new_status_id is not None and new_status_id != task.task_status_id:
        selected_status = await task_statuses_service.get_project_status(
            session,
            status_id=new_status_id,
            project_id=task.project_id,
        )
        if selected_status is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=TaskMessages.STATUS_NOT_FOUND,
            )
        task.task_status_id = selected_status.id  # ty: ignore[invalid-assignment] — persisted row, id is set
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
    if checklist_sent:
        task.checklist = checklist_service.normalize(
            task_in.checklist or [], existing=task.checklist
        )
    now = datetime.now(timezone.utc)
    task.updated_at = now
    sync_completed_at(
        task, task.task_status.category if task.task_status else None, now=now
    )

    new_assignees: list[MemberProfile] = []
    if assignee_ids is not None:
        existing_assignee_ids = {assignee.id for assignee in task.assignees}
        await task_creation_service.set_task_assignees(
            session, task, assignee_ids, project=project
        )
        new_assignees = [
            assignee
            for assignee in task.assignees
            if assignee.id not in existing_assignee_ids
        ]

    await task_creation_service.advance_recurrence_if_needed(
        session,
        task,
        previous_status_category=previous_status_category,
        now=now,
        # An installed app has no zone of its own; a rolling recurrence it
        # completes counts days in UTC.
        user_timezone=current_user.timezone if current_user is not None else None,
    )

    if new_assignees:
        assigned_by = await notifications_service.author_of(
            session, guild_context, current_user
        )
        await notifications_service.notify_assigned(
            session,
            task,
            [assignee.id for assignee in new_assignees],
            assigned_by=assigned_by,
            project_name=project.name,
        )

    # Replace tags/properties when the client sent them (PATCH semantics:
    # absent/None = leave unchanged; a list = replace-all). Both services
    # mutate the session without committing; roll back on validation errors.
    try:
        if tag_ids is not None:
            await tags_service.set_entity_tags(
                session,
                tags_service.TAG_LINKS["task"],
                guild_id=guild_context.guild_id,
                entity_id=task.id,
                tag_ids=tag_ids,
            )
        if property_values is not None:
            await properties_service.set_task_property_values(
                session,
                task,
                await properties_service.property_values_by_row_id(
                    session, task_in.property_values or []
                ),
                project.initiative_id,
            )
    except HTTPException:
        await session.rollback()
        raise

    released_images: set[str] = set()
    if task.description != previous_description:
        await task_description_service.description_saved(
            session,
            task,
            previous=previous_description,
            author=current_user,
        )
        # An installed app does not manage the community's uploads; a picture
        # its edit took out of the description stays for a person to clear.
        if current_user is not None:
            released_images = await attachments_service.release_pasted_images(
                session,
                attachments_service.upload_urls_in_markdown(previous_description)
                - attachments_service.upload_urls_in_markdown(task.description),
                leaving={Task: {task.id}},
            )

    _touch_project(project, now)
    await session.commit()
    # A picture taken out of the description goes once the edit has landed.
    attachments_service.delete_blobs(guild_context.guild_id, released_images)
    return await _response(session, task.id, TaskMessages.MISSING_AFTER_UPDATE)


@router.post("/{task_id}/move", response_model=TaskRead)
async def move_task(
    task_id: int,
    move_in: TaskMoveRequest,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsWrite,
) -> Task:
    task = await _load_for_change(session, task_id, current_user, guild_context)
    if task.project_id == move_in.target_project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=TaskMessages.ALREADY_IN_PROJECT,
        )

    target_project = await resource_access.load_authorized(
        session,
        _GOVERNING,
        move_in.target_project_id,
        current_user,
        guild_context,
        access="write",
    )
    if target_project.is_template:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=TaskMessages.CANNOT_MOVE_TO_TEMPLATE,
        )

    default_status = await task_statuses_service.get_default_status(
        session, target_project.id
    )
    now = datetime.now(timezone.utc)
    source_project = task.project
    task.project_id = target_project.id
    task.task_status_id = default_status.id  # ty: ignore[invalid-assignment] — persisted row, id is set
    task.task_status = default_status
    task.position = 0
    task.updated_at = now
    sync_completed_at(task, default_status.category, now=now)
    session.add(task)

    # If the move crosses initiative boundaries, drop property values —
    # their definitions belong to the old initiative and can't resolve in
    # the new one.
    if source_project.initiative_id != target_project.initiative_id:
        await session.exec(
            delete(TaskPropertyValue).where(TaskPropertyValue.task_id == task.id)
        )
    # Only those who can open the destination stay assigned.
    await task_creation_service.set_task_assignees(
        session,
        task,
        [assignee.id for assignee in task.assignees],
        project=target_project,
        carried=True,
    )

    _touch_project(source_project, now)
    _touch_project(target_project, now)
    await session.commit()
    return await _response(session, task.id, TaskMessages.MISSING_AFTER_MOVE)


@router.post(
    "/{task_id}/duplicate", response_model=TaskRead, status_code=status.HTTP_201_CREATED
)
async def duplicate_task(
    task_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Task:
    original_task = await _load_for_change(
        session, task_id, current_user, guild_context
    )
    project = original_task.project
    position = await task_creation_service.next_position(session, project.id)

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
        position=position,
        created_by=current_user.id,
        checklist=checklist_service.cloned(original_task.checklist),
    )
    # The copy keeps the source's status, so a duplicated done task is complete
    # from the moment it exists — stamped now, not inherited: the copy was not
    # the thing that finished when the original did.
    sync_completed_at(
        new_task,
        original_task.task_status.category if original_task.task_status else None,
        now=datetime.now(timezone.utc),
    )
    session.add(new_task)
    await session.flush()

    # Copy assignees
    assignee_ids = [assignee.id for assignee in original_task.assignees]
    await task_creation_service.set_task_assignees(
        session, new_task, assignee_ids, project=project, carried=True
    )

    # Copy tags (active only — links to trashed tags are not carried forward)
    await tags_service.copy_entity_tags(
        session,
        tags_service.TAG_LINKS["task"],
        source_id=original_task.id,
        target_id=new_task.id,
    )

    # Copy property values — duplicate stays in the same project and
    # therefore the same initiative, so definitions always resolve.
    source_values_stmt = select(TaskPropertyValue).where(
        TaskPropertyValue.task_id == original_task.id
    )
    source_values_result = await session.exec(source_values_stmt)
    source_values = source_values_result.all()
    if source_values:
        session.add_all(
            [
                TaskPropertyValue(
                    task_id=new_task.id,
                    property_id=row.property_id,
                    value_text=row.value_text,
                    value_number=row.value_number,
                    value_boolean=row.value_boolean,
                    value_date=row.value_date,
                    value_datetime=row.value_datetime,
                    value_user_id=row.value_user_id,
                    value_json=deepcopy(row.value_json)
                    if row.value_json is not None
                    else None,
                )
                for row in source_values
            ]
        )

    if new_task.description:
        await task_description_service.record_references(
            session, new_task, author_id=current_user.id
        )

    _touch_project(project, datetime.now(timezone.utc))
    await session.commit()
    return await _response(session, new_task.id, TaskMessages.DUPLICATE_NOT_FOUND)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    task = await _load_for_change(session, task_id, current_user, guild_context)
    project = task.project
    await trash(session, task, deleted_by_user_id=current_user.id)
    _touch_project(project, datetime.now(timezone.utc))
    await session.commit()


@router.post("/reorder", response_model=List[TaskRead])
async def reorder_tasks(
    reorder_in: TaskReorderRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Sequence[Task]:
    if not reorder_in.items:
        return []

    project = await resource_access.load_authorized(
        session,
        _GOVERNING,
        reorder_in.project_id,
        current_user,
        guild_context,
        access="write",
    )

    task_ids = [item.id for item in reorder_in.items]
    tasks_stmt = (
        select(Task)
        .where(Task.id.in_(tuple(task_ids)))
        .options(selectinload(Task.assignees), selectinload(Task.task_status))
    )
    tasks_result = await session.exec(tasks_stmt)
    tasks = tasks_result.all()
    task_map = {task.id: task for task in tasks}

    missing_ids = set(task_ids) - set(task_map.keys())
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_FOUND
        )

    now = datetime.now(timezone.utc)
    status_cache: dict[int, TaskStatus] = {}
    for item in reorder_in.items:
        task = task_map[item.id]
        previous_status_category = (
            task.task_status.category if task.task_status else None
        )
        if task.project_id != reorder_in.project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=TaskMessages.PROJECT_MISMATCH,
            )

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
            task.task_status_id = status_obj.id  # ty: ignore[invalid-assignment] — persisted row, id is set
            task.task_status = status_obj

        task.position = item.position
        task.updated_at = now
        sync_completed_at(
            task, task.task_status.category if task.task_status else None, now=now
        )
        session.add(task)
        await task_creation_service.advance_recurrence_if_needed(
            session,
            task,
            previous_status_category=previous_status_category,
            now=now,
            user_timezone=current_user.timezone,
        )

    # Renumber the project's tasks if any moved task collided with a neighbor;
    # collects ids the rebalance touched so they're returned to the client
    # alongside the explicitly-moved tasks (rebalanced tasks keep updated_at).
    moved_positions = {item.id: item.position for item in reorder_in.items}
    rebalanced_ids = set(
        await _rebalance_if_needed(session, reorder_in.project_id, moved_positions)
    )

    _touch_project(project, now)
    await session.commit()
    return await task_queries.load_tasks(session, list(set(task_ids) | rebalanced_ids))


class ArchiveDoneResponse(BaseModel):
    archived_count: int


@router.post("/archive-done", response_model=ArchiveDoneResponse)
async def archive_done_tasks(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    project_id: int = Query(..., description="Project to archive done tasks from"),
    task_status_id: Optional[int] = Query(
        default=None, description="Specific done status to archive (optional)"
    ),
) -> ArchiveDoneResponse:
    """Archive all tasks in 'done' status category for a project."""
    project = await resource_access.load_authorized(
        session, _GOVERNING, project_id, current_user, guild_context, access="write"
    )

    # Build the query to find done tasks
    statement = (
        select(Task)
        .join(Task.task_status)
        .where(
            Task.project_id == project_id,
            Task.archived_at.is_(None),
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
        task.archived_at = now
        task.updated_at = now
        session.add(task)

    _touch_project(project, now)
    await session.commit()
    return ArchiveDoneResponse(archived_count=len(tasks))


@router.patch(
    "/{task_id}/checklist/{item_id}",
    response_model=List[ChecklistItem],
)
async def toggle_checklist_item(
    task_id: int,
    item_id: str,
    toggle_in: ChecklistItemToggle,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsWrite,
) -> List[ChecklistItem]:
    """Tick or untick one checklist item.

    Adding, renaming, reordering and deleting go through ``PATCH /tasks/{id}``
    with the whole list. A tick gets its own route because it is the write
    several people make to the same task at once: it names one item and rewrites
    only that item, so two ticks on different items both land.
    """
    task = await _load_for_change(session, task_id, current_user, guild_context)
    now = datetime.now(timezone.utc)
    result = await session.exec(
        checklist_service.toggle_statement(),
        params=checklist_service.toggle_params(
            task_id=task.id,
            item_id=item_id,
            done=toggle_in.done,
            now=now,
        ),
    )
    row = result.one_or_none()
    if row is None:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ChecklistMessages.ITEM_NOT_FOUND,
        )

    _touch_project(task.project, now)
    await session.commit()
    # The statement wrote behind the ORM's back, so the loaded row is stale.
    session.expire(task)
    return checklist_service.read(row[0])


async def _record_ai_request(
    session: SessionDep,
    *,
    user: User,
    guild_id: int,
    purpose: str,
    task_id: int,
    initiative_id: Optional[int],
) -> None:
    """Write down that a task is about to be sent to an AI provider.

    Which task, which connection and which provider — never any of the text.
    Committed before the request goes out, since the disclosure does not wait
    on the reply. A configuration that sends nothing records nothing.
    """
    resolved = await resolve_ai_settings(session, user, guild_id)
    if not resolved.enabled or resolved.provider is None:
        return
    await audit_service.record(
        session,
        event_type=AuditEventType.AI_REQUEST_SENT,
        actor_user_id=user.id,
        guild_id=guild_id,
        target_type="task",
        target_id=task_id,
        detail={
            "purpose": purpose,
            "initiative_id": initiative_id,
            "scope": resolved.scope.value if resolved.scope else None,
            "connection_id": resolved.connection_id,
            "provider": resolved.provider.value,
        },
    )
    await session.commit()


# AI Generation endpoints
@router.post("/{task_id}/ai/checklist", response_model=GenerateChecklistResponse)
async def generate_task_checklist(
    task_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> GenerateChecklistResponse:
    """Suggest checklist steps for a task."""
    task = await _load_for_change(session, task_id, current_user, guild_context)
    project = task.project

    await _record_ai_request(
        session,
        user=current_user,
        guild_id=guild_context.guild_id,
        purpose="checklist",
        task_id=task.id,
        initiative_id=project.initiative_id,
    )

    try:
        items = await ai_generation_service.generate_checklist(
            session,
            current_user,
            guild_context.guild_id,
            task,
            initiative_name=project.initiative.name if project.initiative else None,
            project_name=project.name,
        )
        return GenerateChecklistResponse(items=items)
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
    task = await _load_for_change(session, task_id, current_user, guild_context)
    project = task.project

    await _record_ai_request(
        session,
        user=current_user,
        guild_id=guild_context.guild_id,
        purpose="description",
        task_id=task.id,
        initiative_id=project.initiative_id,
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
    task = await _load_for_change(session, task_id, current_user, guild_context)
    await tags_service.set_entity_tags(
        session,
        tags_service.TAG_LINKS["task"],
        guild_id=guild_context.guild_id,
        entity_id=task.id,
        tag_ids=tags_in.tag_ids,
    )
    now = datetime.now(timezone.utc)
    task.updated_at = now
    _touch_project(task.project, now)
    await session.commit()
    return await _response(session, task.id, TaskMessages.MISSING_AFTER_UPDATE)


@router.put("/{task_id}/properties", response_model=TaskRead)
async def set_task_properties(
    task_id: int,
    payload: PropertyValuesSetRequest,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsWrite,
) -> Task:
    """Replace the custom property values on a task.

    Requires write access (same permission gate as PUT /tags). Validates
    each value against its definition's type and options server-side. An
    installed app names the person a person-valued property holds by its
    reference for them.
    """
    task = await _load_for_change(session, task_id, current_user, guild_context)
    try:
        await properties_service.set_task_property_values(
            session,
            task,
            await properties_service.property_values_by_row_id(session, payload.values),
            task.project.initiative_id,
        )
    except HTTPException:
        await session.rollback()
        raise
    now = datetime.now(timezone.utc)
    task.updated_at = now
    _touch_project(task.project, now)
    await session.commit()
    return await _response(session, task.id, TaskMessages.MISSING_AFTER_UPDATE)

from datetime import datetime, timezone
from typing import Annotated, List, Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, update as sa_update
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api import resource_access
from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    SessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import QueueMessages, TagMessages, TaskMessages
from app.core.tools import Tool
from app.models.tenant.tag import Tag, TaskTag, ProjectTag, DocumentTag
from app.models.tenant.task import Task
from app.models.tenant.project import Project
from app.models.tenant.document import Document
from app.models.tenant.queue import QueueItem
from app.models.platform.user import User
from app.services import permissions as permissions_service
from app.services.platform import guilds as guilds_service
from app.services.realtime import broadcast_event
from app.services.tenant import tags as tags_service
from app.services.tenant.soft_delete import soft_delete_entity
from app.schemas.tenant.tag import (
    TagBulkEditRequest,
    TagBulkEditResponse,
    TagCreate,
    TagRead,
    TagUpdate,
    TaggedEntitiesResponse,
    TaggedTaskSummary,
    TaggedProjectSummary,
    TaggedDocumentSummary,
)

# The tag dictionary is a guild-wide folksonomy BY DESIGN: every guild member
# (initiative membership not required) may list, create, rename, recolor, and
# trash tags, so the only gate here is guild membership. Hard purge alone is
# admin-gated (the RESTRICTIVE RLS policy on ``tags``). Pinned by
# ``test_any_guild_member_can_manage_the_tag_dictionary``.
router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


async def _get_tag_or_404(session: SessionDep, tag_id: int, guild_id: int) -> Tag:
    """Fetch a tag by ID, ensuring it belongs to the specified guild."""
    stmt = select(Tag).where(Tag.id == tag_id, Tag.guild_id == guild_id)
    result = await session.exec(stmt)
    tag = result.one_or_none()
    if tag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=TagMessages.NOT_FOUND
        )
    return tag


async def _check_duplicate_name(
    session: SessionDep,
    guild_id: int,
    name: str,
    exclude_tag_id: int | None = None,
) -> None:
    """Check for case-insensitive duplicate tag name within guild."""
    stmt = select(Tag).where(
        Tag.guild_id == guild_id,
        func.lower(Tag.name) == name.lower().strip(),
    )
    if exclude_tag_id is not None:
        stmt = stmt.where(Tag.id != exclude_tag_id)
    result = await session.exec(stmt)
    if result.one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=TagMessages.NAME_ALREADY_EXISTS,
        )


@router.get("/", response_model=List[TagRead])
async def list_tags(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Sequence[Tag]:
    """List all tags in the current guild."""
    stmt = (
        select(Tag)
        .where(Tag.guild_id == guild_context.guild_id)
        .order_by(Tag.name.asc())
    )
    result = await session.exec(stmt)
    return result.all()


@router.post("/", response_model=TagRead, status_code=status.HTTP_201_CREATED)
async def create_tag(
    tag_in: TagCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Tag:
    """Create a new tag in the current guild."""
    await _check_duplicate_name(session, guild_context.guild_id, tag_in.name)

    tag = Tag(
        guild_id=guild_context.guild_id,
        name=tag_in.name.strip(),
        color=tag_in.color,
    )
    session.add(tag)
    await session.commit()
    await session.refresh(tag)
    return tag


@router.post("/bulk", response_model=TagBulkEditResponse)
async def bulk_edit_tags(
    payload: TagBulkEditRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> TagBulkEditResponse:
    """Add and/or remove tags across many entities of one type, atomically.

    Every target is authorized with the same write gate its own set-tags
    endpoint uses (tasks/queue items via their parent project/queue, tools via
    the unified resource-access registry). Nothing is applied unless every
    target passes — one transaction, and for tasks one realtime signal per
    affected project instead of one per task.
    """
    target = payload.target_type.value
    spec = tags_service.TAG_LINKS[target]
    add_ids = await tags_service.validate_guild_tag_ids(
        session, guild_context.guild_id, payload.add_tag_ids
    )
    remove_ids = list(dict.fromkeys(payload.remove_tag_ids))
    target_ids = list(dict.fromkeys(payload.target_ids))

    affected_project_ids: set[int] = set()
    if target == "task":
        rows = (
            await session.exec(
                select(Task.id, Task.project_id).where(Task.id.in_(target_ids))
            )
        ).all()
        if len(rows) != len(target_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_FOUND
            )
        affected_project_ids = {project_id for _, project_id in rows}
        for project_id in affected_project_ids:
            await resource_access.load_authorized(
                session,
                Tool.project,
                project_id,
                current_user,
                guild_context,
                access="write",
            )
    elif target == "queue_item":
        rows = (
            await session.exec(
                select(QueueItem.id, QueueItem.queue_id).where(
                    QueueItem.id.in_(target_ids)
                )
            )
        ).all()
        if len(rows) != len(target_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=QueueMessages.ITEM_NOT_FOUND,
            )
        for queue_id in {queue_id for _, queue_id in rows}:
            await resource_access.load_authorized(
                session,
                Tool.queue,
                queue_id,
                current_user,
                guild_context,
                access="write",
            )
    else:
        for target_id in target_ids:
            await resource_access.load_authorized(
                session,
                Tool(target),
                target_id,
                current_user,
                guild_context,
                access="write",
            )

    await tags_service.bulk_edit_tags(
        session,
        spec,
        entity_ids=target_ids,
        add_tag_ids=add_ids,
        remove_tag_ids=remove_ids,
    )
    if affected_project_ids:
        await session.exec(
            sa_update(Project)
            .where(Project.id.in_(affected_project_ids))
            .values(updated_at=datetime.now(timezone.utc))
        )
    await session.commit()

    for project_id in affected_project_ids:
        initiative_id = (
            await session.exec(
                select(Project.initiative_id).where(Project.id == project_id)
            )
        ).one_or_none()
        if initiative_id is not None:
            await broadcast_event(
                guild_context.guild_id,
                initiative_id,
                "task",
                "updated",
                {"project_id": project_id},
            )

    return TagBulkEditResponse(updated_count=len(target_ids))


@router.get("/{tag_id}", response_model=TagRead)
async def get_tag(
    tag_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Tag:
    """Get a specific tag by ID."""
    return await _get_tag_or_404(session, tag_id, guild_context.guild_id)


@router.patch("/{tag_id}", response_model=TagRead)
async def update_tag(
    tag_id: int,
    tag_in: TagUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Tag:
    """Update a tag's name or color."""
    tag = await _get_tag_or_404(session, tag_id, guild_context.guild_id)

    update_data = tag_in.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"] is not None:
        await _check_duplicate_name(
            session,
            guild_context.guild_id,
            update_data["name"],
            exclude_tag_id=tag.id,
        )
        tag.name = update_data["name"].strip()

    if "color" in update_data and update_data["color"] is not None:
        tag.color = update_data["color"]

    tag.updated_at = datetime.now(timezone.utc)
    session.add(tag)
    await session.commit()
    await session.refresh(tag)
    return tag


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Soft-delete a tag. The tag moves to the guild's trash; junction rows
    stay in place (reads hide them via the soft-delete filter) and fall with
    the tag's ORM relationship cascade on hard purge."""
    tag = await _get_tag_or_404(session, tag_id, guild_context.guild_id)
    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    await soft_delete_entity(
        session,
        tag,
        deleted_by_user_id=current_user.id,
        retention_days=retention_days,
    )
    await session.commit()


@router.get("/{tag_id}/entities", response_model=TaggedEntitiesResponse)
async def get_tag_entities(
    tag_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> TaggedEntitiesResponse:
    """Get all entities (tasks, projects, documents) with this tag.

    Only returns entities the user has permission to access.
    """
    tag = await _get_tag_or_404(session, tag_id, guild_context.guild_id)

    # Build project access subquery (user + role)
    project_access_subq = permissions_service.visible_project_ids_subquery(
        current_user.id
    )

    # Get tasks with this tag that user can access
    tasks_stmt = (
        select(Task)
        .join(TaskTag, TaskTag.task_id == Task.id)
        .where(
            TaskTag.tag_id == tag.id,
            Task.project_id.in_(project_access_subq),
        )
        .options(selectinload(Task.project))
    )
    tasks_result = await session.exec(tasks_stmt)
    tasks = tasks_result.all()
    task_summaries = [
        TaggedTaskSummary(
            id=task.id,
            title=task.title,
            project_id=task.project_id,
            project_name=task.project.name if task.project else None,
        )
        for task in tasks
    ]

    # Get projects with this tag that user can access
    projects_stmt = (
        select(Project)
        .join(ProjectTag, ProjectTag.project_id == Project.id)
        .where(
            ProjectTag.tag_id == tag.id,
            Project.id.in_(project_access_subq),
        )
        .options(selectinload(Project.initiative))
    )
    projects_result = await session.exec(projects_stmt)
    projects = projects_result.all()
    project_summaries = [
        TaggedProjectSummary(
            id=project.id,
            name=project.name,
            initiative_id=project.initiative_id,
            initiative_name=project.initiative.name if project.initiative else None,
        )
        for project in projects
    ]

    # Build document access subquery (user + role)
    doc_access_subq = permissions_service.visible_document_ids_subquery(current_user.id)

    # Get documents with this tag that user can access
    documents_stmt = (
        select(Document)
        .join(DocumentTag, DocumentTag.document_id == Document.id)
        .where(
            DocumentTag.tag_id == tag.id,
            Document.id.in_(doc_access_subq),
        )
        .options(selectinload(Document.initiative))
    )
    documents_result = await session.exec(documents_stmt)
    documents = documents_result.all()
    document_summaries = [
        TaggedDocumentSummary(
            id=doc.id,
            title=doc.title,
            initiative_id=doc.initiative_id,
            initiative_name=doc.initiative.name if doc.initiative else None,
        )
        for doc in documents
    ]

    return TaggedEntitiesResponse(
        tasks=task_summaries,
        projects=project_summaries,
        documents=document_summaries,
    )

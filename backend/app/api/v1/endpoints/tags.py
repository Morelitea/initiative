from datetime import datetime, timezone
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import GuildContext, SessionDep, get_current_active_user, get_guild_membership
from app.models.tag import Tag, TaskTag, ProjectTag, DocumentTag
from app.models.task import Task
from app.models.project import Project, ProjectPermission
from app.models.document import Document, DocumentPermission
from app.models.user import User
from app.schemas.tag import (
    TagCreate,
    TagRead,
    TagUpdate,
    TaggedEntitiesResponse,
    TaggedTaskSummary,
    TaggedProjectSummary,
    TaggedDocumentSummary,
)

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


async def _get_tag_or_404(session: SessionDep, tag_id: int, guild_id: int) -> Tag:
    """Fetch a tag by ID, ensuring it belongs to the specified guild."""
    stmt = select(Tag).where(Tag.id == tag_id, Tag.guild_id == guild_id)
    result = await session.exec(stmt)
    tag = result.one_or_none()
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
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
            detail="A tag with this name already exists",
        )


@router.get("/", response_model=List[TagRead])
async def list_tags(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[Tag]:
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
    session: SessionDep,
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


@router.get("/{tag_id}", response_model=TagRead)
async def get_tag(
    tag_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Tag:
    """Get a specific tag by ID."""
    return await _get_tag_or_404(session, tag_id, guild_context.guild_id)


@router.patch("/{tag_id}", response_model=TagRead)
async def update_tag(
    tag_id: int,
    tag_in: TagUpdate,
    session: SessionDep,
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
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Delete a tag. This cascades to remove the tag from all entities."""
    tag = await _get_tag_or_404(session, tag_id, guild_context.guild_id)
    await session.delete(tag)
    await session.commit()


@router.get("/{tag_id}/entities", response_model=TaggedEntitiesResponse)
async def get_tag_entities(
    tag_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> TaggedEntitiesResponse:
    """Get all entities (tasks, projects, documents) with this tag.

    Only returns entities the user has permission to access.
    """
    tag = await _get_tag_or_404(session, tag_id, guild_context.guild_id)

    # Get tasks with this tag that user can access
    tasks_stmt = (
        select(Task)
        .join(TaskTag, TaskTag.task_id == Task.id)
        .join(Task.project)
        .join(ProjectPermission, ProjectPermission.project_id == Project.id)
        .where(
            TaskTag.tag_id == tag.id,
            ProjectPermission.user_id == current_user.id,
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
        .join(ProjectPermission, ProjectPermission.project_id == Project.id)
        .where(
            ProjectTag.tag_id == tag.id,
            ProjectPermission.user_id == current_user.id,
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

    # Get documents with this tag that user can access
    documents_stmt = (
        select(Document)
        .join(DocumentTag, DocumentTag.document_id == Document.id)
        .join(DocumentPermission, DocumentPermission.document_id == Document.id)
        .where(
            DocumentTag.tag_id == tag.id,
            DocumentPermission.user_id == current_user.id,
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

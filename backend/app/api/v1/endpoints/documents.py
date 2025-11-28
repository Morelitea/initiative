from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import (
    SessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
)
from app.models.document import Document, ProjectDocument
from app.models.initiative import Initiative, InitiativeMember, InitiativeRole
from app.models.user import User
from app.models.guild import GuildRole
from app.schemas.document import (
    DocumentCreate,
    DocumentRead,
    DocumentSummary,
    DocumentUpdate,
    serialize_document,
    serialize_document_summary,
)
from app.services import attachments as attachments_service
from app.services import documents as documents_service
from app.services import initiatives as initiatives_service

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


async def _get_initiative_or_404(
    session: SessionDep,
    *,
    initiative_id: int,
    guild_id: int,
) -> Initiative:
    stmt = select(Initiative).where(
        Initiative.id == initiative_id,
        Initiative.guild_id == guild_id,
    )
    result = await session.exec(stmt)
    initiative = result.one_or_none()
    if not initiative:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Initiative not found")
    return initiative


async def _get_document_or_404(
    session: SessionDep,
    *,
    document_id: int,
    guild_id: int,
) -> Document:
    document = await documents_service.get_document(
        session,
        document_id=document_id,
        guild_id=guild_id,
    )
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


async def _require_initiative_access(
    session: SessionDep,
    *,
    initiative_id: int,
    user: User,
    guild_role: GuildRole,
    require_manager: bool = False,
) -> None:
    if guild_role == GuildRole.admin:
        return
    membership = await initiatives_service.get_initiative_membership(
        session,
        initiative_id=initiative_id,
        user_id=user.id,
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Initiative membership required")
    if require_manager and membership.role != InitiativeRole.project_manager:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Initiative manager role required")


@router.get("/", response_model=List[DocumentSummary])
async def list_documents(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(default=None),
) -> List[DocumentSummary]:
    stmt = (
        select(Document)
        .join(Document.initiative)
        .where(Initiative.guild_id == guild_context.guild_id)
        .options(
            selectinload(Document.initiative).selectinload(Initiative.memberships).selectinload(InitiativeMember.user),
            selectinload(Document.project_links).selectinload(ProjectDocument.project),
        )
        .order_by(Document.updated_at.desc(), Document.id.desc())
    )
    if initiative_id is not None:
        await _get_initiative_or_404(session, initiative_id=initiative_id, guild_id=guild_context.guild_id)
        stmt = stmt.where(Document.initiative_id == initiative_id)

    if search:
        normalized = search.strip().lower()
        if normalized:
            stmt = stmt.where(func.lower(Document.title).contains(normalized))

    if guild_context.role != GuildRole.admin:
        stmt = (
            stmt.join(
                InitiativeMember,
                (InitiativeMember.initiative_id == Document.initiative_id)
                & (InitiativeMember.user_id == current_user.id),
            )
            .distinct()
        )

    result = await session.exec(stmt)
    documents = result.all()
    return [serialize_document_summary(document) for document in documents]


@router.post("/", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def create_document(
    document_in: DocumentCreate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DocumentRead:
    initiative = await _get_initiative_or_404(
        session,
        initiative_id=document_in.initiative_id,
        guild_id=guild_context.guild_id,
    )
    await _require_initiative_access(
        session,
        initiative_id=initiative.id,
        user=current_user,
        guild_role=guild_context.role,
        require_manager=True,
    )
    title = document_in.title.strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document title is required")

    document = Document(
        title=title,
        initiative_id=initiative.id,
        content=documents_service.normalize_document_content(document_in.content),
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
        featured_image_url=document_in.featured_image_url,
    )
    session.add(document)
    await session.commit()

    hydrated = await _get_document_or_404(session, document_id=document.id, guild_id=guild_context.guild_id)
    return serialize_document(hydrated)


@router.get("/{document_id}", response_model=DocumentRead)
async def read_document(
    document_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DocumentRead:
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    await _require_initiative_access(
        session,
        initiative_id=document.initiative_id,
        user=current_user,
        guild_role=guild_context.role,
        require_manager=False,
    )
    return serialize_document(document)


@router.patch("/{document_id}", response_model=DocumentRead)
async def update_document(
    document_id: int,
    document_in: DocumentUpdate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DocumentRead:
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    await _require_initiative_access(
        session,
        initiative_id=document.initiative_id,
        user=current_user,
        guild_role=guild_context.role,
        require_manager=True,
    )
    updated = False
    update_data = document_in.model_dump(exclude_unset=True)
    removed_upload_urls: set[str] = set()
    previous_content_urls = attachments_service.extract_upload_urls(document.content)
    previous_featured_url = document.featured_image_url

    if "title" in update_data:
        title = (update_data["title"] or "").strip()
        if not title:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document title is required")
        document.title = title
        updated = True

    if "content" in update_data:
        document.content = documents_service.normalize_document_content(update_data["content"])
        new_content_urls = attachments_service.extract_upload_urls(document.content)
        removed_upload_urls.update(previous_content_urls - new_content_urls)
        updated = True

    if "featured_image_url" in update_data:
        document.featured_image_url = update_data["featured_image_url"]
        if previous_featured_url and previous_featured_url != document.featured_image_url:
            removed_upload_urls.add(previous_featured_url)
        updated = True

    if updated:
        document.updated_at = datetime.now(timezone.utc)
        document.updated_by_id = current_user.id
        session.add(document)
        await session.commit()
    hydrated = await _get_document_or_404(session, document_id=document.id, guild_id=guild_context.guild_id)
    attachments_service.delete_uploads_by_urls(removed_upload_urls)
    return serialize_document(hydrated)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    await _require_initiative_access(
        session,
        initiative_id=document.initiative_id,
        user=current_user,
        guild_role=guild_context.role,
        require_manager=True,
    )
    removed_upload_urls = attachments_service.extract_upload_urls(document.content)
    if document.featured_image_url:
        removed_upload_urls.add(document.featured_image_url)
    await session.delete(document)
    await session.commit()
    attachments_service.delete_uploads_by_urls(removed_upload_urls)

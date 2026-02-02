from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, inspect
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import (
    SessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
)
from app.models.document import Document, DocumentPermission, DocumentPermissionLevel, DocumentType, ProjectDocument
from app.models.initiative import Initiative, InitiativeMember, InitiativeRole
from app.models.user import User
from app.models.guild import GuildRole
from app.schemas.document import (
    DocumentCreate,
    DocumentCopyRequest,
    DocumentDuplicateRequest,
    DocumentPermissionBulkCreate,
    DocumentPermissionBulkDelete,
    DocumentPermissionCreate,
    DocumentPermissionRead,
    DocumentPermissionUpdate,
    DocumentRead,
    DocumentSummary,
    DocumentUpdate,
    serialize_document,
    serialize_document_summary,
)
from app.schemas.ai_generation import GenerateDocumentSummaryResponse
from app.services import attachments as attachments_service
from app.services import documents as documents_service
from app.services import initiatives as initiatives_service
from app.services import notifications as notifications_service
from app.services.ai_generation import AIGenerationError, generate_document_summary

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


def _require_document_write_access(
    document: Document,
    user: User,
) -> None:
    """Check if user has write access to a document.

    Pure DAC: Access is only granted through explicit DocumentPermission.
    Write access requires either 'write' or 'owner' permission level.
    """
    permissions = getattr(document, "permissions", None) or []
    if any(
        permission.user_id == user.id
        and permission.level in (DocumentPermissionLevel.write, DocumentPermissionLevel.owner)
        for permission in permissions
    ):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Document write access required")


def _get_loaded_permissions(document: Document) -> list[DocumentPermission]:
    """Get permissions from document, asserting they were eagerly loaded."""
    state = inspect(document)
    if "permissions" not in state.dict or state.attrs.permissions.loaded_value is None:
        raise RuntimeError(
            f"Document {document.id} permissions not loaded. "
            "Use selectinload(Document.permissions) in query."
        )
    return document.permissions or []


def _require_document_access(
    document: Document,
    user: User,
    *,
    access: str = "read",
    require_owner: bool = False,
) -> None:
    """Check if user has required access to a document.

    Pure DAC: Access is only granted through explicit DocumentPermission.
    - owner permission = full access (can manage permissions, delete, etc.)
    - write permission = can edit document content
    - read permission = can view document
    """
    # Check explicit permission
    permission = next((p for p in _get_loaded_permissions(document) if p.user_id == user.id), None)

    if require_owner:
        if not permission or permission.level != DocumentPermissionLevel.owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Document owner permission required",
            )
        return

    if not permission:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have access to this document")

    if access == "write" and permission.level == DocumentPermissionLevel.read:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Write access required")


def _get_document_permission(document: Document, user_id: int) -> DocumentPermission | None:
    """Get a user's permission for a document from the loaded permissions."""
    return next((p for p in _get_loaded_permissions(document) if p.user_id == user_id), None)


@router.get("/", response_model=List[DocumentSummary])
async def list_documents(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(default=None),
) -> List[DocumentSummary]:
    """List documents visible to the current user.

    Pure DAC: Only documents with explicit DocumentPermission are visible.
    """
    # Subquery: documents where user has explicit permission
    has_permission_subq = (
        select(DocumentPermission.document_id)
        .where(DocumentPermission.user_id == current_user.id)
        .scalar_subquery()
    )

    stmt = (
        select(Document)
        .join(Document.initiative)
        .where(
            Initiative.guild_id == guild_context.guild_id,
            Document.id.in_(has_permission_subq),
        )
        .options(
            selectinload(Document.initiative).selectinload(Initiative.memberships).selectinload(InitiativeMember.user),
            selectinload(Document.project_links).selectinload(ProjectDocument.project),
            selectinload(Document.permissions),
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

    result = await session.exec(stmt)
    documents = result.unique().all()

    await documents_service.annotate_comment_counts(session, documents)
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
        guild_id=guild_context.guild_id,
        content=documents_service.normalize_document_content(document_in.content),
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
        featured_image_url=document_in.featured_image_url,
        is_template=document_in.is_template,
    )
    session.add(document)
    await session.flush()

    # Add owner permission for the creator
    owner_permission = DocumentPermission(
        document_id=document.id,
        user_id=current_user.id,
        level=DocumentPermissionLevel.owner,
        guild_id=guild_context.guild_id,
    )
    session.add(owner_permission)
    await session.commit()

    hydrated = await _get_document_or_404(session, document_id=document.id, guild_id=guild_context.guild_id)
    return serialize_document(hydrated)


@router.post("/upload", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document_file(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    title: str = Form(...),
    initiative_id: int = Form(...),
    file: UploadFile = File(...),
) -> DocumentRead:
    """Upload a file document (PDF, DOCX, etc.)."""
    initiative = await _get_initiative_or_404(
        session,
        initiative_id=initiative_id,
        guild_id=guild_context.guild_id,
    )
    await _require_initiative_access(
        session,
        initiative_id=initiative.id,
        user=current_user,
        guild_role=guild_context.role,
        require_manager=True,
    )
    title = title.strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document title is required")

    # Read and validate file content
    contents = await file.read()
    try:
        mime_type, extension = attachments_service.validate_document_file(
            content=contents,
            filename=file.filename,
            content_type=file.content_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Save file to uploads directory
    file_url = attachments_service.save_document_file(contents, extension)

    # Create document record
    document = Document(
        title=title,
        initiative_id=initiative.id,
        guild_id=guild_context.guild_id,
        content={},  # File documents have empty content
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
        document_type=DocumentType.file,
        file_url=file_url,
        file_content_type=mime_type,
        file_size=len(contents),
        original_filename=file.filename,
    )
    session.add(document)
    await session.flush()

    # Add owner permission for the creator
    owner_permission = DocumentPermission(
        document_id=document.id,
        user_id=current_user.id,
        level=DocumentPermissionLevel.owner,
        guild_id=guild_context.guild_id,
    )
    session.add(owner_permission)
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
    _require_document_access(document, current_user, access="read")
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
    _require_document_write_access(document, current_user)
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

    if "is_template" in update_data:
        document.is_template = bool(update_data["is_template"])
        updated = True

    if updated:
        document.updated_at = datetime.now(timezone.utc)
        document.updated_by_id = current_user.id
        session.add(document)
        await session.commit()
    hydrated = await _get_document_or_404(session, document_id=document.id, guild_id=guild_context.guild_id)
    attachments_service.delete_uploads_by_urls(removed_upload_urls)
    return serialize_document(hydrated)


@router.post("/{document_id}/duplicate", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def duplicate_document(
    document_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    payload: DocumentDuplicateRequest | None = Body(default=None),
) -> DocumentRead:
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    _require_document_access(document, current_user, access="write")
    payload = payload or DocumentDuplicateRequest()
    title = (payload.title or f"{document.title} (Copy)").strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document title is required")

    duplicated = await documents_service.duplicate_document(
        session,
        source=document,
        target_initiative_id=document.initiative_id,
        title=title,
        user_id=current_user.id,
        guild_id=guild_context.guild_id,
    )
    hydrated = await _get_document_or_404(session, document_id=duplicated.id, guild_id=guild_context.guild_id)
    return serialize_document(hydrated)


@router.post("/{document_id}/copy", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def copy_document(
    document_id: int,
    payload: DocumentCopyRequest,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DocumentRead:
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    # Copy requires write permission for source document
    _require_document_access(document, current_user, access="write")
    target_initiative = await _get_initiative_or_404(
        session,
        initiative_id=payload.target_initiative_id,
        guild_id=guild_context.guild_id,
    )
    # Also require initiative PM in target initiative
    await _require_initiative_access(
        session,
        initiative_id=target_initiative.id,
        user=current_user,
        guild_role=guild_context.role,
        require_manager=True,
    )
    title = (payload.title or document.title).strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document title is required")

    duplicated = await documents_service.duplicate_document(
        session,
        source=document,
        target_initiative_id=target_initiative.id,
        title=title,
        user_id=current_user.id,
        guild_id=guild_context.guild_id,
    )
    hydrated = await _get_document_or_404(session, document_id=duplicated.id, guild_id=guild_context.guild_id)
    return serialize_document(hydrated)


@router.post("/{document_id}/members", response_model=DocumentPermissionRead, status_code=status.HTTP_201_CREATED)
async def add_document_member(
    document_id: int,
    member_in: DocumentPermissionCreate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DocumentPermission:
    """Add a member to a document with specified permission level."""
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    _require_document_access(document, current_user, access="write")
    if member_in.level == DocumentPermissionLevel.owner:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot assign owner permission")

    # Verify user is an initiative member
    initiative_membership = await initiatives_service.get_initiative_membership(
        session,
        initiative_id=document.initiative_id,
        user_id=member_in.user_id,
    )
    if not initiative_membership:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User must be an initiative member")

    # Check if user already has a permission
    existing = _get_document_permission(document, member_in.user_id)
    if existing:
        if existing.level == DocumentPermissionLevel.owner:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot modify owner's permission")
        existing.level = member_in.level
        session.add(existing)
        await session.commit()
        await session.refresh(existing)
        return existing

    permission = DocumentPermission(
        document_id=document_id,
        user_id=member_in.user_id,
        level=member_in.level,
        guild_id=guild_context.guild_id,
    )
    session.add(permission)
    await session.commit()
    await session.refresh(permission)
    return permission


@router.post("/{document_id}/members/bulk", response_model=List[DocumentPermissionRead], status_code=status.HTTP_201_CREATED)
async def add_document_members_bulk(
    document_id: int,
    bulk_in: DocumentPermissionBulkCreate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[DocumentPermission]:
    """Add multiple members to a document with the same permission level."""
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    _require_document_access(document, current_user, access="write")
    if bulk_in.level == DocumentPermissionLevel.owner:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot assign owner permission")

    if not bulk_in.user_ids:
        return []

    # Get all initiative members in one query
    initiative_members_result = await session.exec(
        select(InitiativeMember.user_id).where(
            InitiativeMember.initiative_id == document.initiative_id,
            InitiativeMember.user_id.in_(bulk_in.user_ids),
        )
    )
    valid_member_ids = set(initiative_members_result.all())

    # Get existing permissions
    existing_user_ids = {p.user_id for p in (document.permissions or [])}
    owner_ids = {p.user_id for p in (document.permissions or []) if p.level == DocumentPermissionLevel.owner}

    created_permissions: List[DocumentPermission] = []
    for user_id in bulk_in.user_ids:
        # Skip invalid users (not initiative members)
        if user_id not in valid_member_ids:
            continue
        # Skip owners - cannot modify their permission
        if user_id in owner_ids:
            continue
        # Update existing permission
        if user_id in existing_user_ids:
            existing = next((p for p in document.permissions if p.user_id == user_id), None)
            if existing and existing.level != DocumentPermissionLevel.owner:
                existing.level = bulk_in.level
                session.add(existing)
                created_permissions.append(existing)
            continue
        # Create new permission
        permission = DocumentPermission(
            document_id=document_id,
            user_id=user_id,
            level=bulk_in.level,
            guild_id=guild_context.guild_id,
        )
        session.add(permission)
        created_permissions.append(permission)

    await session.commit()
    for permission in created_permissions:
        await session.refresh(permission)
    return created_permissions


@router.post("/{document_id}/members/bulk-delete", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document_members_bulk(
    document_id: int,
    bulk_in: DocumentPermissionBulkDelete,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Remove multiple members from a document."""
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    _require_document_access(document, current_user, access="write")

    if not bulk_in.user_ids:
        return

    # Get owner IDs to exclude from deletion
    owner_ids = {p.user_id for p in (document.permissions or []) if p.level == DocumentPermissionLevel.owner}

    for user_id in bulk_in.user_ids:
        # Skip owners - cannot remove them
        if user_id in owner_ids:
            continue
        permission = _get_document_permission(document, user_id)
        if permission:
            await session.delete(permission)

    await session.commit()


@router.patch("/{document_id}/members/{user_id}", response_model=DocumentPermissionRead)
async def update_document_member(
    document_id: int,
    user_id: int,
    update_in: DocumentPermissionUpdate,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DocumentPermission:
    """Update a document member's permission level."""
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    _require_document_access(document, current_user, access="write")
    if update_in.level == DocumentPermissionLevel.owner:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot assign owner permission")

    permission = _get_document_permission(document, user_id)
    if not permission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")
    if permission.level == DocumentPermissionLevel.owner:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot modify owner's permission")

    permission.level = update_in.level
    session.add(permission)
    await session.commit()
    await session.refresh(permission)
    return permission


@router.delete("/{document_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document_member(
    document_id: int,
    user_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Remove a member's permission from a document."""
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    _require_document_access(document, current_user, access="write")
    permission = _get_document_permission(document, user_id)
    if not permission:
        return
    if permission.level == DocumentPermissionLevel.owner:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove the document owner")
    await session.delete(permission)
    await session.commit()


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    _require_document_access(document, current_user, require_owner=True)
    removed_upload_urls = attachments_service.extract_upload_urls(document.content)
    if document.featured_image_url:
        removed_upload_urls.add(document.featured_image_url)
    # For file documents, also delete the uploaded file
    if document.file_url:
        removed_upload_urls.add(document.file_url)
    await session.delete(document)
    await session.commit()
    attachments_service.delete_uploads_by_urls(removed_upload_urls)


@router.post("/{document_id}/mentions", status_code=status.HTTP_204_NO_CONTENT)
async def notify_mentions(
    document_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    mentioned_user_ids: List[int] = Body(..., embed=True),
) -> None:
    """Notify users that they were mentioned in a document."""
    if not mentioned_user_ids:
        return
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    _require_document_write_access(document, current_user)
    initiative = document.initiative
    if not initiative:
        initiative = await _get_initiative_or_404(
            session, initiative_id=document.initiative_id, guild_id=guild_context.guild_id
        )
    memberships = getattr(initiative, "memberships", []) or []
    member_map = {membership.user_id: membership.user for membership in memberships if membership.user}
    for user_id in mentioned_user_ids:
        mentioned_user = member_map.get(user_id)
        if not mentioned_user:
            continue
        await notifications_service.notify_document_mention(
            session,
            mentioned_user=mentioned_user,
            mentioned_by=current_user,
            document_id=document.id,
            document_title=document.title,
            guild_id=guild_context.guild_id,
        )
    await session.commit()


@router.post("/{document_id}/ai/summary", response_model=GenerateDocumentSummaryResponse)
async def generate_summary(
    document_id: int,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> GenerateDocumentSummaryResponse:
    """Generate an AI summary of a document.

    Requires read access to the document. Only works for native documents
    (not file uploads like PDFs).
    """
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    _require_document_access(document, current_user, access="read")

    # Only allow summarization of native documents with content
    if document.document_type and document.document_type.value == "file":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="AI summarization is only available for native documents, not file uploads",
        )

    try:
        summary = await generate_document_summary(
            session=session,
            user=current_user,
            guild_id=guild_context.guild_id,
            document_content=document.content,
            document_title=document.title,
        )
        return GenerateDocumentSummaryResponse(summary=summary)
    except AIGenerationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

from datetime import datetime, timezone
from typing import Annotated, List, Literal, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import delete as sa_delete, exists, func
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import (
    RLSSessionDep,
    SessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
)
from app.core.messages import DocumentMessages, InitiativeMessages
from app.db.session import reapply_rls_context
from app.models.document import Document, DocumentPermission, DocumentPermissionLevel, DocumentRolePermission, DocumentType, ProjectDocument
from app.models.upload import Upload
from app.models.initiative import Initiative, InitiativeMember, InitiativeRoleModel, PermissionKey
from app.models.tag import Tag, DocumentTag
from app.models.user import User
from app.models.guild import GuildMembership, GuildRole
from app.schemas.document import (
    DocumentAutocomplete,
    DocumentBacklink,
    DocumentCountsResponse,
    DocumentCreate,
    DocumentCopyRequest,
    DocumentDuplicateRequest,
    DocumentListResponse,
    DocumentPermissionBulkCreate,
    DocumentPermissionBulkDelete,
    DocumentPermissionCreate,
    DocumentPermissionRead,
    DocumentPermissionUpdate,
    DocumentRead,
    DocumentRolePermissionCreate,
    DocumentRolePermissionRead,
    DocumentRolePermissionUpdate,
    DocumentUpdate,
    serialize_document,
    serialize_document_summary,
)
from app.schemas.ai_generation import GenerateDocumentSummaryResponse
from app.schemas.tag import TagSetRequest
from app.services import attachments as attachments_service
from app.services import documents as documents_service
from app.services import initiatives as initiatives_service
from app.services import notifications as notifications_service
from app.services import permissions as permissions_service
from app.services import rls as rls_service
from app.services.ai_generation import AIGenerationError, generate_document_summary

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]

DOCUMENT_SORT_FIELDS = {
    "title": Document.title,
    "updated_at": Document.updated_at,
    "created_at": Document.created_at,
}


def _apply_document_sort(statement, sort_by: Optional[str], sort_dir: Optional[str]):
    col = DOCUMENT_SORT_FIELDS.get(sort_by) if sort_by else None
    if col is not None:
        order = col.desc() if sort_dir == "desc" else col.asc()
        statement = statement.order_by(order.nulls_last(), Document.id.desc())
    else:
        statement = statement.order_by(Document.updated_at.desc(), Document.id.desc())
    return statement


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=InitiativeMessages.NOT_FOUND)
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=DocumentMessages.NOT_FOUND)
    return document


async def _require_initiative_access(
    session: SessionDep,
    *,
    initiative_id: int,
    user: User,
    guild_role: GuildRole,
    require_manager: bool = False,
    permission_key: PermissionKey | None = None,
) -> None:
    """Check that user has access to an initiative.

    Args:
        session: Database session
        initiative_id: Initiative to check access for
        user: User to check
        guild_role: User's guild role (admins bypass checks)
        require_manager: If True, require manager-level role (legacy, use permission_key instead)
        permission_key: Specific permission to check (e.g., PermissionKey.create_docs)
    """
    if rls_service.is_guild_admin(guild_role):
        return
    membership = await initiatives_service.get_initiative_membership(
        session,
        initiative_id=initiative_id,
        user_id=user.id,
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=DocumentMessages.INITIATIVE_MEMBERSHIP_REQUIRED)

    # Check specific permission if requested
    if permission_key is not None:
        has_perm = await rls_service.check_initiative_permission(
            session,
            initiative_id=initiative_id,
            user=user,
            permission_key=permission_key,
        )
        if not has_perm:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=DocumentMessages.PERMISSION_REQUIRED,
            )
        return

    # Legacy manager check
    if require_manager:
        is_manager = await rls_service.is_initiative_manager(
            session,
            initiative_id=initiative_id,
            user=user,
        )
        if not is_manager:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=DocumentMessages.MANAGER_REQUIRED)


def _compute_my_doc_permission_level(
    document: Document,
    user_id: int,
) -> str | None:
    """Compute the effective permission level for a user on a document."""
    return permissions_service.compute_document_permission(document, user_id)


def _require_document_write_access(
    document: Document,
    user: User,
) -> None:
    """Check if user has write access to a document."""
    permissions_service.require_document_access(document, user, access="write")


def _require_document_access(
    document: Document,
    user: User,
    *,
    access: str = "read",
    require_owner: bool = False,
) -> None:
    """Check if user has required access to a document."""
    permissions_service.require_document_access(
        document, user, access=access, require_owner=require_owner,
    )


def _get_document_permission(document: Document, user_id: int) -> DocumentPermission | None:
    """Get a user's permission for a document from the loaded permissions."""
    return permissions_service.get_document_permission(document, user_id)


def _build_visible_docs_filters(
    guild_id: int,
    user_id: int,
    *,
    initiative_id: Optional[int] = None,
    search: Optional[str] = None,
    tag_ids: Optional[List[int]] = None,
    untagged: Optional[bool] = None,
):
    """Build common WHERE conditions for visible-document queries."""
    has_permission_subq = permissions_service.visible_document_ids_subquery(user_id)

    conditions = [
        Initiative.guild_id == guild_id,
        Document.id.in_(has_permission_subq),
    ]

    if initiative_id is not None:
        conditions.append(Document.initiative_id == initiative_id)

    if search:
        normalized = search.strip().lower()
        if normalized:
            conditions.append(func.lower(Document.title).contains(normalized))

    if tag_ids:
        tag_subquery = (
            select(DocumentTag.document_id)
            .join(Tag, Tag.id == DocumentTag.tag_id)
            .where(
                DocumentTag.tag_id.in_(tuple(tag_ids)),
                Tag.guild_id == guild_id,
            )
            .distinct()
        )
        conditions.append(Document.id.in_(tag_subquery))

    if untagged:
        tagged_subquery = (
            select(DocumentTag.document_id)
            .where(DocumentTag.document_id == Document.id)
            .correlate(Document)
        )
        conditions.append(~exists(tagged_subquery))

    return conditions


async def _list_global_documents(
    session: SessionDep,
    current_user: User,
    *,
    guild_ids: Optional[List[int]] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: Optional[str] = None,
    sort_dir: Optional[str] = None,
) -> tuple[list[Document], int]:
    """List documents created by the current user across all guilds they belong to."""
    conditions = [
        GuildMembership.user_id == current_user.id,
        Document.created_by_id == current_user.id,
    ]
    if guild_ids:
        conditions.append(Initiative.guild_id.in_(tuple(guild_ids)))
    if search:
        normalized = search.strip().lower()
        if normalized:
            conditions.append(func.lower(Document.title).contains(normalized))

    def _base_query(stmt):
        return (
            stmt
            .join(Document.initiative)
            .join(Initiative.guild)
            .join(GuildMembership, GuildMembership.guild_id == Initiative.guild_id)
            .where(*conditions)
        )

    # Count query
    count_subq = _base_query(select(Document.id)).subquery()
    count_stmt = select(func.count()).select_from(count_subq)
    total_count = (await session.exec(count_stmt)).one()

    # Data query with eager loading
    statement = _base_query(select(Document)).options(
        selectinload(Document.initiative).selectinload(Initiative.guild),
        selectinload(Document.initiative).selectinload(Initiative.memberships).options(
            selectinload(InitiativeMember.user),
            selectinload(InitiativeMember.role_ref).selectinload(InitiativeRoleModel.permissions),
        ),
        selectinload(Document.project_links).selectinload(ProjectDocument.project),
        selectinload(Document.permissions),
        selectinload(Document.role_permissions).selectinload(DocumentRolePermission.role),
        selectinload(Document.tag_links).selectinload(DocumentTag.tag),
    )
    statement = _apply_document_sort(statement, sort_by, sort_dir)

    if page_size > 0:
        statement = statement.offset((page - 1) * page_size).limit(page_size)

    result = await session.exec(statement)
    return result.unique().all(), total_count


@router.get("/counts", response_model=DocumentCountsResponse)
async def get_document_counts(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(default=None),
) -> DocumentCountsResponse:
    """Get per-tag document counts for visible documents.

    Lightweight endpoint for the tag tree sidebar. Does NOT accept tag_ids
    because counts should reflect all tags.
    """
    if initiative_id is not None:
        await _get_initiative_or_404(session, initiative_id=initiative_id, guild_id=guild_context.guild_id)

    conditions = _build_visible_docs_filters(
        guild_context.guild_id,
        current_user.id,
        initiative_id=initiative_id,
        search=search,
    )

    # Subquery: IDs of visible documents
    visible_docs_subq = (
        select(Document.id)
        .join(Document.initiative)
        .where(*conditions)
        .subquery()
    )

    # Total count
    total_stmt = select(func.count()).select_from(visible_docs_subq)
    total_count = (await session.exec(total_stmt)).one()

    # Per-tag counts (join Tag to enforce guild scoping)
    tag_count_stmt = (
        select(DocumentTag.tag_id, func.count(DocumentTag.document_id))
        .join(Tag, Tag.id == DocumentTag.tag_id)
        .where(
            DocumentTag.document_id.in_(select(visible_docs_subq.c.id)),
            Tag.guild_id == guild_context.guild_id,
        )
        .group_by(DocumentTag.tag_id)
    )
    tag_rows = (await session.exec(tag_count_stmt)).all()
    tag_counts = {tag_id: count for tag_id, count in tag_rows}

    # Untagged count
    untagged_stmt = (
        select(func.count())
        .select_from(visible_docs_subq)
        .where(
            ~select(DocumentTag.document_id)
            .where(DocumentTag.document_id == visible_docs_subq.c.id)
            .correlate(visible_docs_subq)
            .exists()
        )
    )
    untagged_count = (await session.exec(untagged_stmt)).one()

    return DocumentCountsResponse(
        total_count=total_count,
        untagged_count=untagged_count,
        tag_counts=tag_counts,
    )


@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    scope: Annotated[Literal["global"] | None, Query()] = None,
    guild_ids: Optional[List[int]] = Query(default=None),
    search: Optional[str] = Query(default=None),
    tag_ids: Optional[List[int]] = Query(default=None, description="Filter by tag IDs"),
    untagged: Optional[bool] = Query(default=None, description="Filter to documents with no tags"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=0, le=100),
    sort_by: Optional[str] = Query(default=None),
    sort_dir: Optional[str] = Query(default=None),
) -> DocumentListResponse:
    """List documents visible to the current user.

    DAC: Documents with explicit DocumentPermission or role-based permission.

    Pagination: page_size=0 returns all documents (no pagination).

    When scope=global, returns documents created by the current user across
    all guilds they belong to. Optionally filter by guild_ids.
    """
    if scope == "global":
        documents, total_count = await _list_global_documents(
            session,
            current_user,
            guild_ids=guild_ids,
            search=search,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        await documents_service.annotate_comment_counts(session, documents)
        items = [
            serialize_document_summary(
                document,
                my_permission_level=_compute_my_doc_permission_level(
                    document, current_user.id,
                ),
            )
            for document in documents
        ]
        if page_size > 0:
            has_next = page * page_size < total_count
        else:
            has_next = False
            page = 1
        return DocumentListResponse(
            items=items,
            total_count=total_count,
            page=page,
            page_size=page_size,
            has_next=has_next,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )

    if initiative_id is not None:
        await _get_initiative_or_404(session, initiative_id=initiative_id, guild_id=guild_context.guild_id)

    conditions = _build_visible_docs_filters(
        guild_context.guild_id,
        current_user.id,
        initiative_id=initiative_id,
        search=search,
        tag_ids=tag_ids,
        untagged=untagged,
    )

    # Count query
    count_subq = (
        select(Document.id)
        .join(Document.initiative)
        .where(*conditions)
        .subquery()
    )
    count_stmt = select(func.count()).select_from(count_subq)
    total_count = (await session.exec(count_stmt)).one()

    # Data query with eager loading
    stmt = (
        select(Document)
        .join(Document.initiative)
        .where(*conditions)
        .options(
            selectinload(Document.initiative).selectinload(Initiative.memberships).options(
                selectinload(InitiativeMember.user),
                selectinload(InitiativeMember.role_ref).selectinload(InitiativeRoleModel.permissions),
            ),
            selectinload(Document.project_links).selectinload(ProjectDocument.project),
            selectinload(Document.permissions),
            selectinload(Document.role_permissions).selectinload(DocumentRolePermission.role),
            selectinload(Document.tag_links).selectinload(DocumentTag.tag),
        )
    )
    stmt = _apply_document_sort(stmt, sort_by, sort_dir)

    if page_size > 0:
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    result = await session.exec(stmt)
    documents = result.unique().all()

    await documents_service.annotate_comment_counts(session, documents)
    items = [
        serialize_document_summary(
            document,
            my_permission_level=_compute_my_doc_permission_level(
                document, current_user.id,
            ),
        )
        for document in documents
    ]

    if page_size > 0:
        has_next = page * page_size < total_count
    else:
        # page_size=0 means "all rows, no pagination"
        has_next = False
        page = 1

    return DocumentListResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=has_next,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@router.get("/autocomplete", response_model=List[DocumentAutocomplete])
async def autocomplete_documents(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    initiative_id: int = Query(...),
    q: str = Query(..., min_length=1),
    limit: int = Query(default=10, le=20),
) -> List[DocumentAutocomplete]:
    """Search documents by title within an initiative for autocomplete/wikilinks.

    Returns lightweight document info (id, title, updated_at) for typeahead.
    Only returns documents the user has permission to access.
    """
    await _get_initiative_or_404(session, initiative_id=initiative_id, guild_id=guild_context.guild_id)

    has_permission_subq = permissions_service.visible_document_ids_subquery(current_user.id)

    normalized = q.strip().lower()
    stmt = (
        select(Document)
        .join(Document.initiative)
        .where(
            Document.initiative_id == initiative_id,
            Initiative.guild_id == guild_context.guild_id,
            Document.id.in_(has_permission_subq),
            func.lower(Document.title).contains(normalized),
        )
        .order_by(Document.updated_at.desc())
        .limit(limit)
    )

    result = await session.exec(stmt)
    documents = result.all()

    return [
        DocumentAutocomplete(
            id=doc.id,
            title=doc.title,
            updated_at=doc.updated_at,
        )
        for doc in documents
    ]


async def _check_duplicate_title(
    session: SessionDep,
    *,
    initiative_id: int,
    title: str,
    exclude_document_id: int | None = None,
) -> None:
    """Check if a document with the same title already exists in the initiative.

    Raises 400 if a duplicate is found.
    """
    normalized_title = title.strip().lower()
    stmt = select(Document).where(
        Document.initiative_id == initiative_id,
        func.lower(Document.title) == normalized_title,
    )
    if exclude_document_id is not None:
        stmt = stmt.where(Document.id != exclude_document_id)

    result = await session.exec(stmt)
    existing = result.first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.TITLE_ALREADY_EXISTS,
        )


@router.post("/", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def create_document(
    document_in: DocumentCreate,
    session: RLSSessionDep,
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
        permission_key=PermissionKey.create_docs,
    )
    title = document_in.title.strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=DocumentMessages.TITLE_REQUIRED)

    # Check for duplicate title in initiative
    await _check_duplicate_title(session, initiative_id=initiative.id, title=title)

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

    # Process optional role permissions from request
    if document_in.role_permissions:
        # Validate each role belongs to this initiative
        role_ids = {rp.initiative_role_id for rp in document_in.role_permissions if rp.level != DocumentPermissionLevel.owner}
        valid_role_ids: set[int] = set()
        if role_ids:
            result = await session.exec(
                select(InitiativeRoleModel.id).where(
                    InitiativeRoleModel.id.in_(role_ids),
                    InitiativeRoleModel.initiative_id == initiative.id,
                )
            )
            valid_role_ids = set(result.all())
        for rp in document_in.role_permissions:
            if rp.initiative_role_id not in valid_role_ids or rp.level == DocumentPermissionLevel.owner:
                continue
            session.add(DocumentRolePermission(
                document_id=document.id,
                initiative_role_id=rp.initiative_role_id,
                guild_id=guild_context.guild_id,
                level=rp.level,
            ))

    # Process optional user permissions (batch-validate initiative membership)
    if document_in.user_permissions:
        requested = {up.user_id for up in document_in.user_permissions if up.user_id != current_user.id}
        valid_ids: set[int] = set()
        if requested:
            result = await session.exec(
                select(InitiativeMember.user_id).where(
                    InitiativeMember.initiative_id == initiative.id,
                    InitiativeMember.user_id.in_(requested),
                )
            )
            valid_ids = set(result.all())
        for up in document_in.user_permissions:
            if up.user_id in valid_ids and up.level != DocumentPermissionLevel.owner:
                session.add(DocumentPermission(
                    document_id=document.id,
                    user_id=up.user_id,
                    level=up.level,
                    guild_id=guild_context.guild_id,
                ))

    # Sync wikilinks to document_links table
    await documents_service.sync_document_links(
        session,
        document_id=document.id,
        content=document.content,
        guild_id=guild_context.guild_id,
    )

    await session.commit()
    await reapply_rls_context(session)

    hydrated = await _get_document_or_404(session, document_id=document.id, guild_id=guild_context.guild_id)
    return serialize_document(
        hydrated,
        my_permission_level=_compute_my_doc_permission_level(
            hydrated, current_user.id,
        ),
    )


@router.post("/upload", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document_file(
    session: RLSSessionDep,
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
        permission_key=PermissionKey.create_docs,
    )
    title = title.strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=DocumentMessages.TITLE_REQUIRED)

    # Check for duplicate title in initiative
    await _check_duplicate_title(session, initiative_id=initiative.id, title=title)

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

    # Track the upload in the uploads table for guild-scoped access control
    upload_record = Upload(
        filename=file_url.split("/")[-1],
        guild_id=guild_context.guild_id,
        uploader_user_id=current_user.id,
        size_bytes=len(contents),
    )
    session.add(upload_record)

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
    await reapply_rls_context(session)

    hydrated = await _get_document_or_404(session, document_id=document.id, guild_id=guild_context.guild_id)
    return serialize_document(
        hydrated,
        my_permission_level=_compute_my_doc_permission_level(
            hydrated, current_user.id,
        ),
    )


@router.get("/{document_id}", response_model=DocumentRead)
async def read_document(
    document_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DocumentRead:
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    _require_document_access(document, current_user, access="read")
    return serialize_document(
        document,
        my_permission_level=_compute_my_doc_permission_level(
            document, current_user.id,
        ),
    )


@router.get("/{document_id}/backlinks", response_model=List[DocumentBacklink])
async def get_backlinks(
    document_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[DocumentBacklink]:
    """Get documents that link to this document via wikilinks.

    Only returns documents the current user has permission to access.
    """
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    _require_document_access(document, current_user, access="read")

    backlinks = await documents_service.get_backlinks(
        session,
        document_id=document_id,
        user_id=current_user.id,
    )

    return [
        DocumentBacklink(
            id=doc.id,
            title=doc.title,
            updated_at=doc.updated_at,
        )
        for doc in backlinks
    ]


@router.patch("/{document_id}", response_model=DocumentRead)
async def update_document(
    document_id: int,
    document_in: DocumentUpdate,
    session: RLSSessionDep,
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
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=DocumentMessages.TITLE_REQUIRED)
        # Check for duplicate title in initiative (exclude current document)
        await _check_duplicate_title(
            session,
            initiative_id=document.initiative_id,
            title=title,
            exclude_document_id=document.id,
        )
        document.title = title
        updated = True

    content_updated = False
    if "content" in update_data:
        document.content = documents_service.normalize_document_content(update_data["content"])
        new_content_urls = attachments_service.extract_upload_urls(document.content)
        removed_upload_urls.update(previous_content_urls - new_content_urls)
        content_updated = True
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
        # Sync wikilinks if content was updated
        if content_updated:
            await documents_service.sync_document_links(
                session,
                document_id=document.id,
                content=document.content,
                guild_id=guild_context.guild_id,
            )
        await session.commit()
        await reapply_rls_context(session)
    hydrated = await _get_document_or_404(session, document_id=document.id, guild_id=guild_context.guild_id)
    attachments_service.delete_uploads_by_urls(removed_upload_urls)
    return serialize_document(
        hydrated,
        my_permission_level=_compute_my_doc_permission_level(
            hydrated, current_user.id,
        ),
    )


@router.post("/{document_id}/duplicate", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def duplicate_document(
    document_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    payload: DocumentDuplicateRequest | None = Body(default=None),
) -> DocumentRead:
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    _require_document_access(document, current_user, access="write")
    payload = payload or DocumentDuplicateRequest()
    title = (payload.title or f"{document.title} (Copy)").strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=DocumentMessages.TITLE_REQUIRED)

    duplicated = await documents_service.duplicate_document(
        session,
        source=document,
        target_initiative_id=document.initiative_id,
        title=title,
        user_id=current_user.id,
        guild_id=guild_context.guild_id,
    )
    hydrated = await _get_document_or_404(session, document_id=duplicated.id, guild_id=guild_context.guild_id)
    return serialize_document(
        hydrated,
        my_permission_level=_compute_my_doc_permission_level(
            hydrated, current_user.id,
        ),
    )


@router.post("/{document_id}/copy", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def copy_document(
    document_id: int,
    payload: DocumentCopyRequest,
    session: RLSSessionDep,
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
    # Also require create_docs permission in target initiative
    await _require_initiative_access(
        session,
        initiative_id=target_initiative.id,
        user=current_user,
        guild_role=guild_context.role,
        permission_key=PermissionKey.create_docs,
    )
    title = (payload.title or document.title).strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=DocumentMessages.TITLE_REQUIRED)

    duplicated = await documents_service.duplicate_document(
        session,
        source=document,
        target_initiative_id=target_initiative.id,
        title=title,
        user_id=current_user.id,
        guild_id=guild_context.guild_id,
    )
    hydrated = await _get_document_or_404(session, document_id=duplicated.id, guild_id=guild_context.guild_id)
    return serialize_document(
        hydrated,
        my_permission_level=_compute_my_doc_permission_level(
            hydrated, current_user.id,
        ),
    )


@router.post("/{document_id}/members", response_model=DocumentPermissionRead, status_code=status.HTTP_201_CREATED)
async def add_document_member(
    document_id: int,
    member_in: DocumentPermissionCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DocumentPermission:
    """Add a member to a document with specified permission level."""
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    _require_document_access(document, current_user, access="write")
    if member_in.level == DocumentPermissionLevel.owner:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=DocumentMessages.CANNOT_ASSIGN_OWNER)

    # Verify user is an initiative member
    initiative_membership = await initiatives_service.get_initiative_membership(
        session,
        initiative_id=document.initiative_id,
        user_id=member_in.user_id,
    )
    if not initiative_membership:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=DocumentMessages.USER_MUST_BE_MEMBER)

    # Check if user already has a permission
    existing = _get_document_permission(document, member_in.user_id)
    if existing:
        if existing.level == DocumentPermissionLevel.owner:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=DocumentMessages.CANNOT_MODIFY_OWNER)
        existing.level = member_in.level
        session.add(existing)
        await session.commit()
        await reapply_rls_context(session)
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
    await reapply_rls_context(session)
    await session.refresh(permission)
    return permission


@router.post("/{document_id}/members/bulk", response_model=List[DocumentPermissionRead], status_code=status.HTTP_201_CREATED)
async def add_document_members_bulk(
    document_id: int,
    bulk_in: DocumentPermissionBulkCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[DocumentPermission]:
    """Add multiple members to a document with the same permission level."""
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    _require_document_access(document, current_user, access="write")
    if bulk_in.level == DocumentPermissionLevel.owner:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=DocumentMessages.CANNOT_ASSIGN_OWNER)

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
    await reapply_rls_context(session)
    for permission in created_permissions:
        await session.refresh(permission)
    return created_permissions


@router.post("/{document_id}/members/bulk-delete", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document_members_bulk(
    document_id: int,
    bulk_in: DocumentPermissionBulkDelete,
    session: RLSSessionDep,
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
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DocumentPermission:
    """Update a document member's permission level."""
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    _require_document_access(document, current_user, access="write")
    if update_in.level == DocumentPermissionLevel.owner:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=DocumentMessages.CANNOT_ASSIGN_OWNER)

    permission = _get_document_permission(document, user_id)
    if not permission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=DocumentMessages.PERMISSION_NOT_FOUND)
    if permission.level == DocumentPermissionLevel.owner:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=DocumentMessages.CANNOT_MODIFY_OWNER)

    permission.level = update_in.level
    session.add(permission)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(permission)
    return permission


@router.delete("/{document_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document_member(
    document_id: int,
    user_id: int,
    session: RLSSessionDep,
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=DocumentMessages.CANNOT_REMOVE_OWNER)
    await session.delete(permission)
    await session.commit()


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: int,
    session: RLSSessionDep,
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
    # Unresolve any wikilinks pointing to this document before deletion
    await documents_service.unresolve_wikilinks_to_document(session, deleted_document_id=document_id)
    await session.delete(document)
    await session.commit()
    attachments_service.delete_uploads_by_urls(removed_upload_urls)


@router.post("/{document_id}/mentions", status_code=status.HTTP_204_NO_CONTENT)
async def notify_mentions(
    document_id: int,
    session: RLSSessionDep,
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
    session: RLSSessionDep,
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
    if document.document_type == DocumentType.file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.AI_NATIVE_ONLY,
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


@router.put("/{document_id}/tags", response_model=DocumentRead)
async def set_document_tags(
    document_id: int,
    tags_in: TagSetRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DocumentRead:
    """Set tags on a document. Replaces all existing tags with the provided list."""
    document = await _get_document_or_404(
        session, document_id=document_id, guild_id=guild_context.guild_id
    )
    _require_document_access(document, current_user, access="write")

    # Validate all tags belong to this guild
    if tags_in.tag_ids:
        tags_stmt = select(Tag).where(
            Tag.id.in_(tags_in.tag_ids),
            Tag.guild_id == guild_context.guild_id,
        )
        tags_result = await session.exec(tags_stmt)
        valid_tags = tags_result.all()
        valid_tag_ids = {t.id for t in valid_tags}

        invalid_ids = set(tags_in.tag_ids) - valid_tag_ids
        if invalid_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=DocumentMessages.INVALID_TAG_IDS,
            )

    # Remove existing tags
    delete_stmt = sa_delete(DocumentTag).where(DocumentTag.document_id == document_id)
    await session.exec(delete_stmt)

    # Add new tags
    for tag_id in tags_in.tag_ids:
        document_tag = DocumentTag(
            document_id=document_id,
            tag_id=tag_id,
        )
        session.add(document_tag)

    # Fetch fresh document to avoid issues with deleted relationship objects
    doc_stmt = (
        select(Document)
        .where(Document.id == document_id)
        .options(
            selectinload(Document.initiative),
            selectinload(Document.permissions),
            selectinload(Document.role_permissions).selectinload(DocumentRolePermission.role),
            selectinload(Document.tag_links).selectinload(DocumentTag.tag),
        )
    )
    result = await session.exec(doc_stmt)
    doc = result.one()
    doc.updated_at = datetime.now(timezone.utc)
    await session.commit()

    return serialize_document(
        doc,
        my_permission_level=_compute_my_doc_permission_level(
            doc, current_user.id,
        ),
    )


# ── Role-based permission CRUD ───────────────────────────────────


@router.post("/{document_id}/role-permissions", response_model=DocumentRolePermissionRead, status_code=status.HTTP_201_CREATED)
async def add_document_role_permission(
    document_id: int,
    role_perm_in: DocumentRolePermissionCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DocumentRolePermissionRead:
    """Add a role-based permission to a document."""
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    _require_document_access(document, current_user, access="write")

    if role_perm_in.level == DocumentPermissionLevel.owner:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=DocumentMessages.CANNOT_ASSIGN_OWNER_TO_ROLE)

    # Validate the role belongs to the same initiative as the document
    stmt = select(InitiativeRoleModel).where(InitiativeRoleModel.id == role_perm_in.initiative_role_id)
    result = await session.exec(stmt)
    role = result.one_or_none()
    if not role or role.initiative_id != document.initiative_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=DocumentMessages.ROLE_WRONG_INITIATIVE)

    # Check if already exists
    existing_stmt = select(DocumentRolePermission).where(
        DocumentRolePermission.document_id == document_id,
        DocumentRolePermission.initiative_role_id == role_perm_in.initiative_role_id,
    )
    existing_result = await session.exec(existing_stmt)
    existing = existing_result.one_or_none()
    if existing:
        existing.level = role_perm_in.level
        session.add(existing)
        await session.commit()
        await reapply_rls_context(session)
        await session.refresh(existing)
        return DocumentRolePermissionRead(
            initiative_role_id=existing.initiative_role_id,
            role_name=role.name,
            role_display_name=role.display_name,
            level=existing.level,
            created_at=existing.created_at,
        )

    role_perm = DocumentRolePermission(
        document_id=document_id,
        initiative_role_id=role_perm_in.initiative_role_id,
        level=role_perm_in.level,
        guild_id=guild_context.guild_id,
    )
    session.add(role_perm)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(role_perm)
    return DocumentRolePermissionRead(
        initiative_role_id=role_perm.initiative_role_id,
        role_name=role.name,
        role_display_name=role.display_name,
        level=role_perm.level,
        created_at=role_perm.created_at,
    )


@router.patch("/{document_id}/role-permissions/{role_id}", response_model=DocumentRolePermissionRead)
async def update_document_role_permission(
    document_id: int,
    role_id: int,
    update_in: DocumentRolePermissionUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DocumentRolePermissionRead:
    """Update a role-based permission level on a document."""
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    _require_document_access(document, current_user, access="write")

    if update_in.level == DocumentPermissionLevel.owner:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=DocumentMessages.CANNOT_ASSIGN_OWNER_TO_ROLE)

    stmt = select(DocumentRolePermission).where(
        DocumentRolePermission.document_id == document_id,
        DocumentRolePermission.initiative_role_id == role_id,
    )
    result = await session.exec(stmt)
    role_perm = result.one_or_none()
    if not role_perm:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=DocumentMessages.ROLE_PERMISSION_NOT_FOUND)

    role_perm.level = update_in.level
    session.add(role_perm)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(role_perm)

    # Get role info
    role_stmt = select(InitiativeRoleModel).where(InitiativeRoleModel.id == role_id)
    role_result = await session.exec(role_stmt)
    role = role_result.one_or_none()
    return DocumentRolePermissionRead(
        initiative_role_id=role_perm.initiative_role_id,
        role_name=role.name if role else "",
        role_display_name=role.display_name if role else "",
        level=role_perm.level,
        created_at=role_perm.created_at,
    )


@router.delete("/{document_id}/role-permissions/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document_role_permission(
    document_id: int,
    role_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Remove a role-based permission from a document."""
    document = await _get_document_or_404(session, document_id=document_id, guild_id=guild_context.guild_id)
    _require_document_access(document, current_user, access="write")

    stmt = select(DocumentRolePermission).where(
        DocumentRolePermission.document_id == document_id,
        DocumentRolePermission.initiative_role_id == role_id,
    )
    result = await session.exec(stmt)
    role_perm = result.one_or_none()
    if not role_perm:
        return
    await session.delete(role_perm)
    await session.commit()

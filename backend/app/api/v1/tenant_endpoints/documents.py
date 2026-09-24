import logging
from datetime import datetime, timezone
from typing import Annotated, List, Optional, Sequence

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from sqlalchemy import delete as sa_delete, func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload, undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.relationships import Related, RelationshipType
from app.core.search import SearchEntityType
from app.models.tenant.project import Project
from app.services.tenant import archive as archive_service
from app.services.tenant import content_references
from app.services.tenant import relationships
from app.services.tenant.relationships import Endpoint
from app.api.deps import (
    IncludeDeletedDep,
    RLSSessionDep,
    SessionDep,
    UploadUserDep,
    addressed_guild_id,
    establish_guild_access,
    get_current_active_user,
    get_guild_membership,
    GuildAccessError,
    GuildContext,
)
from app.core.messages import (
    AttachmentMessages,
    DocumentMessages,
    InitiativeMessages,
)
from app.core.rate_limit import limiter
from app.db.session import require_guild_context
from app.models.tenant.document import (
    Document,
    DocumentFileVersion,
    DocumentType,
)
from app.models.tenant.upload import Upload
from app.models.tenant.initiative import (
    Initiative,
    PermissionKey,
)
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.models.platform.user import User
from app.schemas.tenant.document import (
    DocumentCopyRequest,
    DocumentCountsResponse,
    DocumentCreate,
    DocumentDuplicateRequest,
    DocumentFileVersionRead,
    DocumentRead,
    DocumentSummary,
    DocumentUpdate,
    serialize_document,
    serialize_document_file_version,
    serialize_document_file_versions,
    serialize_document_summary,
    SpreadsheetImportRead,
)
from app.schemas.ai_generation import GenerateDocumentSummaryResponse
from app.schemas.tenant.property import PropertyValuesSetRequest
from app.services.tenant import attachments as attachments_service
from app.services import storage_config
from app.services.storage import build_upload_response, get_guild_storage
from app.api import resource_access
from app.core.tools import Tool
from app.services.tenant import documents as documents_service
from app.services.tenant import initiatives as initiatives_service
from app.services.tenant import tags as tags_service
from app.services.tenant import tool_listing
from app.services import notifications as notifications_service
from app.services.platform import accounts as accounts_service
from app.services import permissions as permissions_service
from app.services import reachability
from app.services.tenant import properties as properties_service
from app.services import rls as rls_service
from app.services import audit as audit_service
from app.services.ai_generation import AIGenerationError, generate_document_summary
from app.services.ai_settings import resolve_ai_settings
from app.services.tenant import spreadsheet_import
from app.services.tenant.collaboration import collaboration_manager

logger = logging.getLogger(__name__)


async def attached_projects(
    session: AsyncSession, documents: Sequence[Document]
) -> dict[int, list[Related]]:
    """Which projects each of these documents is attached to.

    One call for the whole page. The list endpoints below serialise documents in
    a comprehension, so anything per-document here would be a query per row on
    the busiest read in the tool.
    """
    return await relationships.related_for_many(
        session,
        SearchEntityType.document,
        [d.id for d in documents if d.id is not None],
        relationship_type=RelationshipType.attached,
        other_kind=SearchEntityType.project,
        model=Project,
    )


router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]

# Upper bound on the ``ids`` filter, matching the page_size ceiling: the
# filter exists to hydrate one page worth of known documents, not to smuggle
# an unbounded IN list into the query.
MAX_DOCUMENT_IDS = 100


async def get_initiative_or_404(
    session: SessionDep,
    *,
    initiative_id: int,
    guild_id: int,
) -> Initiative:
    stmt = select(Initiative).where(
        Initiative.id == initiative_id,
    )
    result = await session.exec(stmt)
    initiative = result.one_or_none()
    if not initiative:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=InitiativeMessages.NOT_FOUND
        )
    return initiative


async def _get_document_or_404(
    session: SessionDep,
    *,
    document_id: int,
    guild_id: int,
    populate_existing: bool = False,
    user_id: int,
) -> Document:
    """Load a document with everything a ``DocumentRead`` reads, or refuse.

    The eager loads are the registry's (``documents.get_document_hydrated`` —
    the same ones ``resource_access.load_authorized(..., hydrated=True)``
    takes), so a document reaches a response the same way whichever door it
    came through. For the re-read a write answers with, where the row has
    already been authorized.
    """
    document = await documents_service.get_document_hydrated(
        session, document_id, populate_existing=populate_existing
    )
    if not document:
        raise await reachability.missing_or_denied(
            "documents",
            document_id,
            user_id,
            guild_id,
            not_found=Tool.document.not_found_code,
            denied=Tool.document.no_access_code,
        )
    return document


async def _require_initiative_access(
    session: SessionDep,
    *,
    initiative_id: int,
    user: User,
    guild_context: GuildContext,
    require_manager: bool = False,
    permission_key: PermissionKey | None = None,
) -> None:
    """Check that user has access to an initiative.

    Args:
        session: Database session
        initiative_id: Initiative to check access for
        user: User to check
        guild_context: the reader's standing (an admin passes)
        require_manager: If True, require manager-level role (legacy, use permission_key instead)
        permission_key: Specific permission to check (e.g., PermissionKey.create_documents)
    """
    if guild_context.is_admin:
        return
    membership = await initiatives_service.get_initiative_membership(
        session,
        initiative_id=initiative_id,
        user_id=user.id,
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DocumentMessages.INITIATIVE_MEMBERSHIP_REQUIRED,
        )

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
                detail=Tool.document.role_permission_code,
            )
        return

    # Legacy manager check
    if require_manager:
        is_manager = await rls_service.is_initiative_manager(
            session,
            initiative_id=initiative_id,
        )
        if not is_manager:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=InitiativeMessages.MANAGER_REQUIRED,
            )


def _file_download_response(
    *,
    guild_id: int,
    file_url: str,
    content_type: str | None,
    original_filename: str | None,
    inline: bool,
) -> Response:
    """Build a hardened download response for a stored upload blob.

    Shared by the current-document download and the per-version download so
    the path-traversal guard and SVG/HTML stored-XSS hardening can't drift
    between the two endpoints. Serves through the guild's storage backend
    (local FileResponse or S3 streaming proxy) via :func:`build_upload_response`.
    """
    filename = file_url.split("/")[-1]
    blob = get_guild_storage(guild_id).open_readable(filename)
    if blob is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    headers: dict[str, str] = {"X-Content-Type-Options": "nosniff"}
    ext = (original_filename or filename).rsplit(".", 1)[-1].lower()
    normalized_type = (content_type or "").lower()
    if (
        ext in ("svg", "html", "htm")
        or "svg" in normalized_type
        or "html" in normalized_type
    ):
        if inline:
            # Disable scripts (stored-XSS hardening) but allow the file to be
            # framed by the same-origin in-app document viewer. X-Frame-Options
            # set here overrides the SecurityHeadersMiddleware global DENY (it
            # uses setdefault); frame-ancestors 'self' is the CSP equivalent.
            headers["Content-Security-Policy"] = (
                "script-src 'none'; frame-ancestors 'self'"
            )
            headers["X-Frame-Options"] = "SAMEORIGIN"
        else:
            # Non-inline downloads are sent as attachments; keep the strict
            # script-src and let the global X-Frame-Options: DENY stand.
            headers["Content-Security-Policy"] = "script-src 'none'"

    if inline:
        return build_upload_response(blob, media_type=content_type, headers=headers)
    return build_upload_response(
        blob, filename=original_filename or filename, headers=headers
    )


def visible_document_conditions(
    context: GuildContext,
    user_id: int,
    *,
    initiative_id: Optional[int] = None,
    ids: Optional[List[int]] = None,
    search: Optional[str] = None,
    tag_ids: Optional[List[int]] = None,
    untagged: Optional[bool] = None,
    is_template: Optional[bool] = None,
    document_type: Optional[DocumentType] = None,
):
    """WHERE conditions for visible-document queries — the list and the tag
    counts beside it, so the sidebar's numbers match the rows under them.

    The guild, the documents switch, sharing, the search box and the tag filter
    are the shared set (:func:`tool_listing.base_conditions`); the rest are the
    document list's own. The archive answer is the caller's, since the tag
    counts take their own ``archived`` parameter.
    """
    conditions = tool_listing.base_conditions(
        Tool.document,
        Document,
        Initiative.documents_enabled,
        user_id,
        context=context,
        initiative_id=initiative_id,
        search=search,
        tag_ids=tag_ids,
    )

    if ids is not None:
        conditions.append(Document.id.in_(tuple(ids)))

    if is_template is not None:
        conditions.append(Document.is_template == is_template)

    if document_type is not None:
        conditions.append(Document.document_type == document_type)

    if untagged:
        conditions.append(
            tags_service.untagged_clause(
                tags_service.TOOL_TAG_LINKS[Tool.document], Document.id
            )
        )

    return conditions


async def serialize_document_page(
    session: AsyncSession, user: User, documents: list[Document]
) -> list[DocumentSummary]:
    """Serialize one page of documents — the rows a document list answers with.

    Everything a card shows beyond the row itself (its tags, its comment count,
    the projects it is attached to) is a grouped query over the whole page, run
    once here rather than per row. The order is already settled by the caller
    and is preserved.

    Both document lists run this: the guild-wide one through
    ``tool_lists.TOOL_LISTS``, and the cross-guild ``/me/documents`` through
    ``me_tools.MY_TOOL_LISTS``.
    """
    await tags_service.annotate_tags(session, documents)
    await documents_service.annotate_comment_counts(session, documents)
    attached = await attached_projects(session, documents)
    context = require_guild_context(session)
    return [
        serialize_document_summary(
            document,
            context=context,
            user_id=user.id,
            projects=attached.get(document.id, []),
        )
        for document in documents
    ]


@router.get("/counts", response_model=DocumentCountsResponse)
async def get_document_counts(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(default=None),
    is_template: Optional[bool] = Query(
        default=None, description="Filter to template (or non-template) documents"
    ),
    document_type: Optional[DocumentType] = Query(
        default=None, description="Filter by document type"
    ),
    archived: Optional[bool] = Query(
        default=None, description=archive_service.ARCHIVED_QUERY_DESCRIPTION
    ),
) -> DocumentCountsResponse:
    """Get per-tag document counts for visible documents.

    Lightweight endpoint for the tag tree sidebar. Does NOT accept tag_ids
    because counts should reflect all tags. The remaining filters mirror the
    list endpoint so the sidebar counts match the list beside it.
    """
    if initiative_id is not None:
        await get_initiative_or_404(
            session, initiative_id=initiative_id, guild_id=guild_context.guild_id
        )

    conditions = visible_document_conditions(
        guild_context,
        current_user.id,
        initiative_id=initiative_id,
        search=search,
        is_template=is_template,
        document_type=document_type,
    )
    conditions.append(archive_service.archive_filter_clause(Document, archived))

    # Subquery: IDs of visible documents
    visible_docs_subq = select(Document.id).where(*conditions).subquery()

    # Total count
    total_stmt = select(func.count()).select_from(visible_docs_subq)
    total_count = (await session.exec(total_stmt)).one()

    # Per-tag counts. Guild scoping needs no clause of its own — a tag of
    # another guild lives in another schema, which this query cannot reach.
    spec = tags_service.TOOL_TAG_LINKS[Tool.document]
    tag_rows = (
        await session.exec(
            tags_service.tag_counts_for(spec, select(visible_docs_subq.c.id))
        )
    ).all()
    tag_counts = {tag_id: count for tag_id, count in tag_rows}

    # Untagged count
    untagged_stmt = (
        select(func.count())
        .select_from(visible_docs_subq)
        .where(tags_service.untagged_clause(spec, visible_docs_subq.c.id))
    )
    untagged_count = (await session.exec(untagged_stmt)).one()

    return DocumentCountsResponse(
        total_count=total_count,
        untagged_count=untagged_count,
        tag_counts=tag_counts,
    )


async def _check_duplicate_name(
    session: SessionDep,
    *,
    initiative_id: int,
    name: str,
    exclude_document_id: int | None = None,
) -> None:
    """Check if a document with the same name already exists in the initiative.

    Raises 400 if a duplicate is found.
    """
    normalized_name = name.strip().lower()
    stmt = select(Document).where(
        Document.initiative_id == initiative_id,
        func.lower(Document.name) == normalized_name,
    )
    if exclude_document_id is not None:
        stmt = stmt.where(Document.id != exclude_document_id)

    result = await session.exec(stmt)
    existing = result.first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.NAME_ALREADY_EXISTS,
        )


@router.post("/", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def create_document(
    document_in: DocumentCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DocumentRead:
    initiative = await get_initiative_or_404(
        session,
        initiative_id=document_in.initiative_id,
        guild_id=guild_context.guild_id,
    )
    resource_access.require_tool_enabled(Tool.document, initiative)
    await _require_initiative_access(
        session,
        initiative_id=initiative.id,
        user=current_user,
        guild_context=guild_context,
        permission_key=PermissionKey.create_documents,
    )
    name = document_in.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.NAME_REQUIRED,
        )

    # Check for duplicate name in initiative
    await _check_duplicate_name(session, initiative_id=initiative.id, name=name)

    requested_type = DocumentType(document_in.document_type)

    try:
        normalized_content = documents_service.normalize_document_content(
            document_in.content,
            document_type=requested_type,
        )
    except documents_service.DocumentContentError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code
        ) from exc

    document = Document(
        name=name,
        initiative_id=initiative.id,
        document_type=requested_type,
        content=normalized_content,
        created_by=current_user.id,
        featured_image_url=document_in.featured_image_url,
        is_template=document_in.is_template,
    )
    session.add(document)
    await session.flush()

    # Add owner permission for the creator
    owner_permission = ResourceGrant(
        resource_type="document",
        resource_id=document.id,
        user_id=current_user.id,
        role_id=None,
        level=ResourceAccessLevel.owner,
        initiative_id=document.initiative_id,
    )
    session.add(owner_permission)

    # Apply the initial sharing exactly the way edits do — one grant list, one
    # code path (defaults to Viewer for all members, set on DocumentCreate.grants).
    await permissions_service.replace_resource_grants(
        session,
        resource_type="document",
        resource_id=document.id,
        guild_id=guild_context.guild_id,
        initiative_id=document.initiative_id,
        owner_id=current_user.id,
        grants=document_in.grants,
        actor_user_id=current_user.id,
    )

    # What the new body points at becomes `references` edges.
    await content_references.sync_for_entity(
        session,
        Endpoint(SearchEntityType.document, document.id),
        body=document.content,
        author_id=current_user.id,
    )

    await session.commit()

    hydrated = await _get_document_or_404(
        session,
        document_id=document.id,
        guild_id=guild_context.guild_id,
        user_id=current_user.id,
    )
    return serialize_document(
        hydrated,
        user_id=current_user.id,
        context=guild_context,
    )


@router.post(
    "/upload", response_model=DocumentRead, status_code=status.HTTP_201_CREATED
)
async def upload_document_file(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    name: str = Form(...),
    initiative_id: int = Form(...),
    file: UploadFile = File(...),
) -> DocumentRead:
    """Upload a file document (PDF, DOCX, etc.)."""
    initiative = await get_initiative_or_404(
        session,
        initiative_id=initiative_id,
        guild_id=guild_context.guild_id,
    )
    resource_access.require_tool_enabled(Tool.document, initiative)
    await _require_initiative_access(
        session,
        initiative_id=initiative.id,
        user=current_user,
        guild_context=guild_context,
        permission_key=PermissionKey.create_documents,
    )
    name = name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.NAME_REQUIRED,
        )

    # Pick up a backend/credential change saved in another worker before writing.
    await storage_config.ensure_storage_config_fresh(session)

    # Check for duplicate name in initiative
    await _check_duplicate_name(session, initiative_id=initiative.id, name=name)

    # Read the body with a hard cap so an over-limit upload is rejected before
    # the whole payload is buffered into memory (memory-exhaustion DoS guard).
    try:
        contents = await attachments_service.read_upload_bounded(
            file, attachments_service.MAX_DOCUMENT_FILE_SIZE
        )
    except attachments_service.FileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=DocumentMessages.FILE_TOO_LARGE,
        )
    try:
        mime_type, extension = attachments_service.validate_document_file(
            content=contents,
            filename=file.filename,
            content_type=file.content_type,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.INVALID_FILE,
        )

    try:
        await attachments_service.enforce_storage_quota(
            session, guild_id=guild_context.guild_id, incoming_bytes=len(contents)
        )
    except attachments_service.StorageQuotaExceededError:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=AttachmentMessages.STORAGE_QUOTA_EXCEEDED,
        )

    file_url = await attachments_service.store_upload(
        session,
        guild_id=guild_context.guild_id,
        filename=attachments_service.new_upload_filename(extension),
        data=contents,
        content_type=mime_type,
        created_by=current_user.id,
    )

    # Create document record. A picture is its own featured image, set here so
    # it is written with the row: the uploader's owner grant is only added
    # below, so a later UPDATE in this transaction is not theirs to make yet.
    document = Document(
        name=name,
        initiative_id=initiative.id,
        content={},  # File documents have empty content
        created_by=current_user.id,
        document_type=DocumentType.file,
        file_url=file_url,
        file_content_type=mime_type,
        file_size=len(contents),
        original_filename=file.filename,
        featured_image_url=(
            file_url if mime_type and mime_type.startswith("image/") else None
        ),
    )
    session.add(document)
    await session.flush()

    # Add owner permission for the creator
    session.add(
        ResourceGrant(
            resource_type="document",
            resource_id=document.id,
            user_id=current_user.id,
            role_id=None,
            level=ResourceAccessLevel.owner,
            initiative_id=document.initiative_id,
        )
    )
    # File uploads default to Viewer for all members, like native docs.
    session.add(
        ResourceGrant(
            resource_type="document",
            resource_id=document.id,
            user_id=None,
            role_id=None,
            all_initiative_members=True,
            level=ResourceAccessLevel.read,
            initiative_id=document.initiative_id,
        )
    )
    # The grants land before the version row: writing a version is the
    # document owner's to do, and the uploader is its owner only once the
    # grant exists.
    await session.flush()

    # Record the initial version (v1). The documents row mirrors this version's
    # file fields; subsequent uploads add higher-numbered versions.
    session.add(
        DocumentFileVersion(
            document_id=document.id,
            version_number=1,
            file_url=file_url,
            file_content_type=mime_type,
            file_size=len(contents),
            original_filename=file.filename,
            created_by=current_user.id,
        )
    )
    await session.commit()

    hydrated = await _get_document_or_404(
        session,
        document_id=document.id,
        guild_id=guild_context.guild_id,
        user_id=current_user.id,
    )
    return serialize_document(
        hydrated,
        user_id=current_user.id,
        context=guild_context,
    )


def _normalize_mime(mime: str | None) -> str:
    """Normalize a MIME type for version type-match comparison."""
    normalized = (mime or "").lower().strip()
    if normalized == "image/jpg":
        return "image/jpeg"
    return normalized


@router.post(
    "/{document_id}/versions",
    response_model=DocumentFileVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document_version(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    document_id: int,
    file: UploadFile = File(...),
) -> DocumentFileVersionRead:
    """Upload a new version of a file document. Requires write access."""
    document = await resource_access.load_authorized(
        session,
        Tool.document,
        document_id,
        current_user,
        guild_context,
        access="write",
        hydrated=True,
    )
    if document.document_type != DocumentType.file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.NOT_A_FILE_DOCUMENT,
        )

    # Pick up a backend/credential change saved in another worker before writing.
    await storage_config.ensure_storage_config_fresh(session)

    # Read the body with a hard cap so an over-limit upload is rejected before
    # the whole payload is buffered into memory (memory-exhaustion DoS guard).
    try:
        contents = await attachments_service.read_upload_bounded(
            file, attachments_service.MAX_DOCUMENT_FILE_SIZE
        )
    except attachments_service.FileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=DocumentMessages.FILE_TOO_LARGE,
        )
    try:
        mime_type, extension = attachments_service.validate_document_file(
            content=contents,
            filename=file.filename,
            content_type=file.content_type,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.INVALID_FILE,
        )

    # A new version must keep the document's original file type. Skip the
    # check when the stored type is NULL so legacy documents without a
    # recorded content type aren't permanently locked out of new versions
    # (``_normalize_mime(None)`` returns ``""`` and would always mismatch).
    if document.file_content_type is not None and _normalize_mime(
        mime_type
    ) != _normalize_mime(document.file_content_type):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.VERSION_TYPE_MISMATCH,
        )

    try:
        await attachments_service.enforce_storage_quota(
            session, guild_id=guild_context.guild_id, incoming_bytes=len(contents)
        )
    except attachments_service.StorageQuotaExceededError:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=AttachmentMessages.STORAGE_QUOTA_EXCEEDED,
        )

    file_url = await attachments_service.store_upload(
        session,
        guild_id=guild_context.guild_id,
        filename=attachments_service.new_upload_filename(extension),
        data=contents,
        content_type=mime_type,
        created_by=current_user.id,
    )

    max_version = await session.scalar(
        select(func.max(DocumentFileVersion.version_number)).where(
            DocumentFileVersion.document_id == document_id
        )
    )
    next_version = (max_version or 0) + 1

    version = DocumentFileVersion(
        document_id=document_id,
        version_number=next_version,
        file_url=file_url,
        file_content_type=mime_type,
        file_size=len(contents),
        original_filename=file.filename,
        created_by=current_user.id,
    )
    session.add(version)

    # Mirror the new (now current) version onto the document row so the
    # existing download endpoint and viewer serve the latest file.
    document.file_url = file_url
    document.file_content_type = mime_type
    document.file_size = len(contents)
    document.original_filename = file.filename
    document.updated_at = datetime.now(timezone.utc)
    if mime_type and mime_type.startswith("image/"):
        document.featured_image_url = file_url

    try:
        await session.commit()
    except IntegrityError:
        # The (document_id, version_number) unique constraint rejected this row:
        # a concurrent upload claimed the same next version number between our
        # MAX() read and this commit. Roll back, drop the orphaned blob, and ask
        # the caller to retry rather than surfacing a 500.
        await session.rollback()
        attachments_service.delete_upload_by_url(file_url)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DocumentMessages.VERSION_CONFLICT,
        )
    await session.refresh(version)
    return serialize_document_file_version(version, is_current=True)


@router.get("/{document_id}/versions", response_model=List[DocumentFileVersionRead])
async def list_document_versions(
    document_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[DocumentFileVersionRead]:
    """List all stored versions of a file document, newest first. Read access."""
    document = await resource_access.load_authorized(
        session,
        Tool.document,
        document_id,
        current_user,
        guild_context,
        access="read",
        hydrated=True,
    )
    if document.document_type != DocumentType.file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.NOT_A_FILE_DOCUMENT,
        )

    result = await session.exec(
        select(DocumentFileVersion)
        .where(DocumentFileVersion.document_id == document_id)
        .order_by(DocumentFileVersion.version_number.desc())
    )
    versions = result.all()
    return serialize_document_file_versions(list(versions))


@router.delete(
    "/{document_id}/versions/{version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document_version(
    document_id: int,
    version_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Delete a version of a file document. Owner only. Deleting the current
    version promotes the previous one; deleting the last version is blocked."""
    document = await resource_access.load_authorized(
        session,
        Tool.document,
        document_id,
        current_user,
        guild_context,
        require_owner=True,
        hydrated=True,
    )
    if document.document_type != DocumentType.file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.NOT_A_FILE_DOCUMENT,
        )

    # Serialize concurrent deletes against the same document by taking a
    # row-level lock on the document row. Without it, two owner DELETEs that
    # both observe ``len(versions) >= 2`` can both pass the "last version"
    # guard and race to delete different rows — leaving zero versions, and
    # (in the worst case) ``document.file_url`` pointing at a blob that the
    # second request also deleted. Holding the lock until commit means the
    # second request re-reads the version list after the first one finishes.
    await session.exec(
        select(Document).where(Document.id == document_id).with_for_update()
    )

    result = await session.exec(
        select(DocumentFileVersion)
        .where(DocumentFileVersion.document_id == document_id)
        .order_by(DocumentFileVersion.version_number.desc())
    )
    versions = list(result.all())
    if len(versions) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.CANNOT_DELETE_LAST_VERSION,
        )

    target = next((v for v in versions if v.id == version_id), None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=DocumentMessages.VERSION_NOT_FOUND,
        )

    is_current = target.version_number == versions[0].version_number
    deleted_url = target.file_url

    await session.delete(target)
    await session.flush()

    # Remove the upload-tracking row + filesystem blob for this version.
    filename = deleted_url.split("/")[-1]
    await session.exec(sa_delete(Upload).where(Upload.filename == filename))

    if is_current:
        # Promote the next-highest version to current by mirroring its file
        # fields onto the document row.
        promoted = next((v for v in versions if v.id != version_id), None)
        if promoted is not None:
            document.file_url = promoted.file_url
            document.file_content_type = promoted.file_content_type
            document.file_size = promoted.file_size
            document.original_filename = promoted.original_filename
            document.updated_at = datetime.now(timezone.utc)
            # Keep featured image coherent when it referenced the deleted blob.
            if document.featured_image_url == deleted_url:
                if (promoted.file_content_type or "").startswith("image/"):
                    document.featured_image_url = promoted.file_url
                else:
                    document.featured_image_url = None

    await session.commit()

    # Delete the blob after the row is gone so a failed commit doesn't orphan files.
    attachments_service.delete_upload_by_url(deleted_url)


@router.get("/{document_id}", response_model=DocumentRead)
async def read_document(
    document_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    include_deleted: IncludeDeletedDep = False,
    include_content: Annotated[
        bool,
        Query(
            description=(
                "Include the document body. Pass false for the metadata alone —"
                " a document's body is the largest thing this API returns, and a"
                " caller reacting to a change (a name, a tag, a property) does"
                " not need it. Everything else is unchanged."
            )
        ),
    ] = True,
) -> DocumentRead:
    document = await resource_access.load_authorized(
        session,
        Tool.document,
        document_id,
        current_user,
        guild_context,
        access="read",
        hydrated=True,
    )
    return serialize_document(
        document,
        user_id=current_user.id,
        include_content=include_content,
        context=guild_context,
    )


@router.patch("/{document_id}", response_model=DocumentRead)
async def update_document(
    document_id: int,
    document_in: DocumentUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DocumentRead:
    document = await resource_access.load_authorized(
        session,
        Tool.document,
        document_id,
        current_user,
        guild_context,
        access="write",
        hydrated=True,
    )
    updated = False
    update_data = document_in.model_dump(exclude_unset=True)
    removed_upload_urls: set[str] = set()
    previous_content_urls = attachments_service.extract_upload_urls(document.content)
    previous_featured_url = document.featured_image_url

    if "name" in update_data:
        name = (update_data["name"] or "").strip()
        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=DocumentMessages.NAME_REQUIRED,
            )
        # Check for duplicate name in initiative (exclude current document)
        await _check_duplicate_name(
            session,
            initiative_id=document.initiative_id,
            name=name,
            exclude_document_id=document.id,
        )
        document.name = name
        updated = True

    content_updated = False
    # A document with a live collaboration room has that room as the writer of
    # both its views — it saves ``content`` and ``yjs_state`` from one snapshot,
    # on an interval and at teardown. Everything else in the patch (the name,
    # the featured image) is unrelated to that and still applies.
    if "content" in update_data and collaboration_manager.has_active_collaborators(
        guild_context.guild_id, SearchEntityType.document.value, document.id
    ):
        # An editor inside the session reports its content to the room over its
        # own socket, which is what ties a rendering to the state it was made
        # from. A rendering arriving here belongs to a tab outside the session,
        # whose view of the document the session has moved on from — and a
        # request carries no connection, so one of an account's tabs cannot be
        # told from another here. It is refused rather than taken and reported
        # as saved; reconnecting is what gets that tab's work in, and the
        # handshake carries it.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DocumentMessages.LIVE_SESSION_OWNS_CONTENT,
        )
    if "content" in update_data:
        try:
            document.content = documents_service.normalize_document_content(
                update_data["content"],
                document_type=document.document_type,
            )
        except documents_service.DocumentContentError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code
            ) from exc
        new_content_urls = attachments_service.extract_upload_urls(document.content)
        removed_upload_urls.update(previous_content_urls - new_content_urls)
        # Reaching here means no room is live, so this edit is the newest
        # thing about the document and any stored Yjs state predates it. It is
        # cleared so the next collaborative session bootstraps from this
        # content rather than from state that never saw it.
        document.yjs_state = None
        content_updated = True
        updated = True

    if "featured_image_url" in update_data:
        document.featured_image_url = update_data["featured_image_url"]
        if (
            previous_featured_url
            and previous_featured_url != document.featured_image_url
        ):
            removed_upload_urls.add(previous_featured_url)
        updated = True

    if "is_template" in update_data:
        document.is_template = bool(update_data["is_template"])
        updated = True

    if updated:
        document.updated_at = datetime.now(timezone.utc)
        session.add(document)
        if content_updated:
            await content_references.sync_for_entity(
                session,
                Endpoint(SearchEntityType.document, document.id),
                body=document.content,
                author_id=current_user.id,
            )
        if removed_upload_urls:
            filenames = [url.split("/")[-1] for url in removed_upload_urls]
            await session.exec(sa_delete(Upload).where(Upload.filename.in_(filenames)))
        await session.commit()
        # Invalidate any in-memory collaboration room so the next session
        # loads fresh state from the database. If a room has active
        # collaborators their in-memory state wins until they disconnect.
        if content_updated:
            await collaboration_manager.invalidate_room_if_empty(
                guild_context.guild_id, SearchEntityType.document.value, document.id
            )
    hydrated = await _get_document_or_404(
        session,
        document_id=document.id,
        guild_id=guild_context.guild_id,
        user_id=current_user.id,
    )
    attachments_service.delete_uploads_by_urls(removed_upload_urls)
    return serialize_document(
        hydrated,
        user_id=current_user.id,
        context=guild_context,
    )


@router.post(
    "/{document_id}/duplicate",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_document(
    document_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    payload: DocumentDuplicateRequest | None = Body(default=None),
) -> DocumentRead:
    document = await resource_access.load_authorized(
        session,
        Tool.document,
        document_id,
        current_user,
        guild_context,
        access="write",
        hydrated=True,
    )
    payload = payload or DocumentDuplicateRequest()
    name = (payload.name or f"{document.name} (Copy)").strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.NAME_REQUIRED,
        )

    try:
        duplicated = await documents_service.duplicate_document(
            session,
            source=document,
            target_initiative_id=document.initiative_id,
            name=name,
            user_id=current_user.id,
            guild_id=guild_context.guild_id,
        )
    except attachments_service.StorageQuotaExceededError:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=AttachmentMessages.STORAGE_QUOTA_EXCEEDED,
        )
    hydrated = await _get_document_or_404(
        session,
        document_id=duplicated.id,
        guild_id=guild_context.guild_id,
        user_id=current_user.id,
    )
    return serialize_document(
        hydrated,
        user_id=current_user.id,
        context=guild_context,
    )


@router.post(
    "/{document_id}/copy",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def copy_document(
    document_id: int,
    payload: DocumentCopyRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DocumentRead:
    document = await resource_access.load_authorized(
        session,
        Tool.document,
        document_id,
        current_user,
        guild_context,
        hydrated=True,
    )
    # Templates are starter content meant to be copied — read on the source is
    # enough. Copying anything else asks for write on it, so a copy is never a
    # quiet fork of somebody else's work.
    if not document.is_template:
        resource_access.authorize(
            Tool.document,
            document,
            current_user,
            access="write",
            context=guild_context,
        )
    target_initiative = await get_initiative_or_404(
        session,
        initiative_id=payload.target_initiative_id,
        guild_id=guild_context.guild_id,
    )
    # Also require create_documents permission in target initiative
    resource_access.require_tool_enabled(Tool.document, target_initiative)
    await _require_initiative_access(
        session,
        initiative_id=target_initiative.id,
        user=current_user,
        guild_context=guild_context,
        permission_key=PermissionKey.create_documents,
    )
    name = (payload.name or document.name).strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.NAME_REQUIRED,
        )

    try:
        duplicated = await documents_service.duplicate_document(
            session,
            source=document,
            target_initiative_id=target_initiative.id,
            name=name,
            user_id=current_user.id,
            guild_id=guild_context.guild_id,
        )
    except attachments_service.StorageQuotaExceededError:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=AttachmentMessages.STORAGE_QUOTA_EXCEEDED,
        )
    hydrated = await _get_document_or_404(
        session,
        document_id=duplicated.id,
        guild_id=guild_context.guild_id,
        user_id=current_user.id,
    )
    return serialize_document(
        hydrated,
        user_id=current_user.id,
        context=guild_context,
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Soft-delete a document. Upload rows + filesystem blobs survive so a
    restored document keeps its images and file body. Wikilinks pointing at
    this document continue to reference the row but resolve to nothing
    (the active-row filter hides it). Both URL-orphan cleanup for native
    docs and the 1:1 Upload cleanup for file-type docs run later, at
    hard-purge time, via ``purge_document_uploads``."""
    from app.services.platform import guilds as guilds_service
    from app.services.tenant.soft_delete import soft_delete_entity

    document = await resource_access.load_authorized(
        session,
        Tool.document,
        document_id,
        current_user,
        guild_context,
        require_owner=True,
        hydrated=True,
    )
    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    await soft_delete_entity(
        session,
        document,
        deleted_by_user_id=current_user.id,
        retention_days=retention_days,
    )
    await session.commit()


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
    document = await resource_access.load_authorized(
        session,
        Tool.document,
        document_id,
        current_user,
        guild_context,
        access="write",
        hydrated=True,
    )
    memberships = await initiatives_service.initiative_roster(
        session, document.initiative_id
    )
    member_ids = {
        membership.user_id for membership in memberships if membership.user_id
    }
    # Who to tell is a question about their account, so it is asked where an
    # account may be read.
    recipients = await accounts_service.load(
        (user_id for user_id in mentioned_user_ids if user_id in member_ids),
        excluding_ignorers_of=current_user.id,
    )
    for user_id in mentioned_user_ids:
        mentioned_user = recipients.get(user_id)
        if not mentioned_user:
            continue
        await notifications_service.notify_document_mention(
            session,
            mentioned_user=mentioned_user,
            mentioned_by=current_user,
            document_id=document.id,
            document_name=document.name,
            guild_id=guild_context.guild_id,
            initiative_id=document.initiative_id,
        )
    await session.commit()


@router.post(
    "/{document_id}/ai/summary", response_model=GenerateDocumentSummaryResponse
)
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
    document = await resource_access.load_authorized(
        session,
        Tool.document,
        document_id,
        current_user,
        guild_context,
        access="read",
        hydrated=True,
    )

    # Only allow summarization of native documents with content
    if document.document_type == DocumentType.file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.AI_NATIVE_ONLY,
        )

    # Written down before the request goes out, since the disclosure does not
    # wait on the reply: which document, which connection, which provider, and
    # none of the text. A configuration that sends nothing records nothing.
    resolved = await resolve_ai_settings(session, current_user, guild_context.guild_id)
    if resolved.enabled and resolved.provider is not None:
        await audit_service.record(
            session,
            event_type=AuditEventType.AI_REQUEST_SENT,
            actor_user_id=current_user.id,
            guild_id=guild_context.guild_id,
            target_type="document",
            target_id=document.id,
            detail={
                "purpose": "summary",
                "initiative_id": document.initiative_id,
                "scope": resolved.scope.value if resolved.scope else None,
                "connection_id": resolved.connection_id,
                "provider": resolved.provider.value,
            },
        )
        await session.commit()

    try:
        summary = await generate_document_summary(
            session=session,
            user=current_user,
            guild_id=guild_context.guild_id,
            document_content=document.content,
            document_name=document.name,
        )
        return GenerateDocumentSummaryResponse(summary=summary)
    except AIGenerationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put("/{document_id}/properties", response_model=DocumentRead)
async def set_document_properties(
    document_id: int,
    payload: PropertyValuesSetRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DocumentRead:
    """Replace the custom property values on a document.

    Requires document write access. Values are validated server-side against
    each property definition's type and options.
    """
    document = await resource_access.load_authorized(
        session,
        Tool.document,
        document_id,
        current_user,
        guild_context,
        access="write",
        hydrated=True,
    )

    try:
        await properties_service.set_document_property_values(
            session,
            document,
            payload.values,
            document.initiative_id,
        )
    except HTTPException:
        await session.rollback()
        raise

    # Bump updated_at via a lightweight select to avoid touching the
    # relationship collections after the DELETE in the service layer.
    ts_stmt = select(Document).where(Document.id == document_id)
    ts_result = await session.exec(ts_stmt)
    ts_doc = ts_result.one()
    ts_doc.updated_at = datetime.now(timezone.utc)
    await session.commit()

    # populate_existing=True forces selectinload to refresh the cached
    # document's property_values collection. Without it, expire_on_commit
    # =False keeps the stale (pre-replace-all) collection in the identity
    # map and the response serializes as if no values were set.
    refreshed = await _get_document_or_404(
        session,
        document_id=document_id,
        guild_id=guild_context.guild_id,
        populate_existing=True,
        user_id=current_user.id,
    )
    return serialize_document(
        refreshed,
        user_id=current_user.id,
        context=guild_context,
    )


async def read_after_write(
    session: RLSSessionDep,
    document_id: int,
    user: User,
    guild_context: GuildContext,
) -> DocumentRead:
    """The document a write answers with: re-read after the commit, serialized.

    Registered in ``tool_lists.TOOL_LISTS`` so the shared sharing route
    (``tool_grants.py``) answers in this tool's own shape.
    """
    hydrated = await _get_document_or_404(
        session,
        document_id=document_id,
        guild_id=guild_context.guild_id,
        user_id=user.id,
    )
    return serialize_document(hydrated, user_id=user.id, context=guild_context)


def _download_document_options():
    """Eager loads the download's access check reads off the document."""
    return (
        selectinload(Document.initiative),
        undefer(Document.access_level),
        selectinload(Document.grants).selectinload(ResourceGrant.role),
    )


async def _load_download_document(
    session: AsyncSession, current_user, guild_id: int, document_id: int
):
    """Load a file ``Document`` by id from the path-addressed guild schema,
    with the eager loads the access check needs.

    Downloads are served via iframe/window.open, which can't send headers, so
    the guild rides in the ``/g/{guild_id}`` path segment and names exactly the
    schema to read. Access is re-validated here (membership or live PAM grant).
    Leaves the session routed into the guild so a follow-up version query runs
    in the same schema.

    Returns ``(document, context)`` — the standing the seam computed for this
    reader in that community — or ``(None, None)`` when there's no access, no
    schema, or no such document in the addressed guild. All of those are an
    indistinguishable 404 to the caller, so existence is never confirmed across
    guilds.
    """
    from app.db.schema_provisioning import guild_schema_name

    # Guard the SET ROLE sink: if the guild schema/role isn't provisioned,
    # establish_guild_access would fault rather than 404. The catalog answers
    # this for any login.
    schema_exists = (
        await session.exec(
            text("SELECT 1 FROM pg_namespace WHERE nspname = :ns"),
            params={"ns": guild_schema_name(int(guild_id))},
        )
    ).first()
    if schema_exists is None:
        return None, None

    # Route into the guild through the single entry point — same resolution and
    # applied context (membership / live PAM / break-glass, then SET ROLE +
    # standing) as REST and the realtime sockets, on the request login, so the
    # row arrives with the level this reader holds on it.
    try:
        ctx = await establish_guild_access(session, current_user, int(guild_id))
    except GuildAccessError:
        return None, None

    doc = (
        await session.exec(
            select(Document)
            .where(Document.id == document_id)
            .options(*_download_document_options())
        )
    ).one_or_none()
    return doc, ctx


@router.get("/{document_id}/download", include_in_schema=False)
@limiter.limit("30/minute")
async def download_document_file(
    request: Request,
    guild_id: int,
    document_id: int,
    current_user: UploadUserDep,
    # SessionDep (not RLSSessionDep) because the loader routes the session
    # into the path-addressed guild's schema itself after validating access.
    session: SessionDep,
    inline: bool = False,
) -> Response:
    """Download a file-type document — requires read permission on the document."""
    # These two routes resolve the guild themselves rather than through
    # ``get_guild_membership``, so they ask the same question it does.
    guild_id = addressed_guild_id(request, guild_id)
    document, context = await _load_download_document(
        session, current_user, guild_id, document_id
    )
    if document is None:
        raise await reachability.missing_or_denied(
            "documents",
            document_id,
            int(current_user.id),
            int(guild_id),
            not_found=Tool.document.not_found_code,
            denied=Tool.document.no_access_code,
        )
    if document.document_type != DocumentType.file or document.file_url is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=Tool.document.not_found_code
        )

    resource_access.authorize(
        Tool.document, document, current_user, access="read", context=context
    )

    logger.info(
        "document_download document_id=%d user=%d inline=%s",
        document_id,
        current_user.id,
        inline,
    )
    return _file_download_response(
        guild_id=guild_id,
        file_url=document.file_url,
        content_type=document.file_content_type,
        original_filename=document.original_filename,
        inline=inline,
    )


@router.get("/{document_id}/versions/{version_id}/download", include_in_schema=False)
@limiter.limit("30/minute")
async def download_document_file_version(
    request: Request,
    guild_id: int,
    document_id: int,
    version_id: int,
    current_user: UploadUserDep,
    # Same rationale as download_document_file: the loader validates access
    # and routes the session into the path-addressed guild's schema.
    session: SessionDep,
    inline: bool = False,
) -> Response:
    """Download a specific stored version of a file document — read permission."""
    guild_id = addressed_guild_id(request, guild_id)
    document, context = await _load_download_document(
        session, current_user, guild_id, document_id
    )
    if document is None:
        raise await reachability.missing_or_denied(
            "documents",
            document_id,
            int(current_user.id),
            int(guild_id),
            not_found=Tool.document.not_found_code,
            denied=Tool.document.no_access_code,
        )
    if document.document_type != DocumentType.file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=Tool.document.not_found_code
        )

    resource_access.authorize(
        Tool.document, document, current_user, access="read", context=context
    )

    version_result = await session.exec(
        select(DocumentFileVersion).where(
            DocumentFileVersion.id == version_id,
            DocumentFileVersion.document_id == document_id,
        )
    )
    version = version_result.one_or_none()
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=DocumentMessages.VERSION_NOT_FOUND,
        )

    logger.info(
        "document_version_download document_id=%d version_id=%d user=%d inline=%s",
        document_id,
        version_id,
        current_user.id,
        inline,
    )
    return _file_download_response(
        guild_id=guild_id,
        file_url=version.file_url,
        content_type=version.file_content_type,
        original_filename=version.original_filename,
        inline=inline,
    )


@router.post(
    "/{document_id}/spreadsheet/import",
    response_model=SpreadsheetImportRead,
)
async def import_spreadsheet_file(
    document_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    file: UploadFile = File(...),
) -> SpreadsheetImportRead:
    """Read a CSV/XLSX file into sheets, for the caller to add to this workbook.

    The document is the permission scope rather than the destination — nothing
    here writes to it. The sheets go back to the editor, which adds them to the
    live document in a single transaction, so the whole import is one thing to
    undo and peers receive it as one change.

    Parsing is server-side for the same reason rendering is: the workbook
    libraries are here, and the result goes through the same normalizer a
    created spreadsheet does, so an imported sheet is the same kind of object
    as any other.
    """
    document = await resource_access.load_authorized(
        session,
        Tool.document,
        document_id,
        current_user,
        guild_context,
        access="write",
        hydrated=True,
    )
    if document.document_type != DocumentType.spreadsheet:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.SPREADSHEET_INVALID_PAYLOAD,
        )

    # Bounded read, so an over-sized file is refused before it is buffered.
    try:
        contents = await attachments_service.read_upload_bounded(
            file, attachments_service.MAX_DOCUMENT_FILE_SIZE
        )
    except attachments_service.FileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=DocumentMessages.FILE_TOO_LARGE,
        )

    try:
        sheets = spreadsheet_import.parse_spreadsheet_file(
            file.filename or "", contents
        )
    except documents_service.DocumentContentError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code
        ) from exc

    return SpreadsheetImportRead(sheets=sheets)

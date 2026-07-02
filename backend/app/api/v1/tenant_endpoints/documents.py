import logging
from datetime import datetime, timezone
from typing import Annotated, List, Optional

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
from sqlalchemy import delete as sa_delete, exists, func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    RLSSessionDep,
    SessionDep,
    UploadUserDep,
    UserSessionDep,
    establish_guild_access,
    get_current_active_user,
    get_guild_membership,
    GuildAccessError,
    GuildContext,
)
from app.db.query import unbounded_page_limit
from app.core.messages import (
    AttachmentMessages,
    DocumentMessages,
    InitiativeMessages,
    QueryMessages,
)
from app.core.pam_context import has_active_grant
from app.core.rate_limit import limiter
from app.db.session import get_admin_session, reapply_rls_context
from app.services.cross_guild import gather_across_guilds, member_guild_ids
from app.models.tenant.document import (
    Document,
    DocumentFileVersion,
    DocumentType,
    ProjectDocument,
)
from app.models.tenant.upload import Upload
from app.models.tenant.initiative import (
    Initiative,
    InitiativeMember,
    InitiativeRoleModel,
    PermissionKey,
)
from app.models.tenant.property import DocumentPropertyValue
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.models.tenant.tag import Tag, DocumentTag
from app.models.platform.user import User
from app.models.platform.guild import GuildRole
from app.schemas.tenant.document import (
    DocumentAutocomplete,
    DocumentBacklink,
    DocumentCountsResponse,
    DocumentCreate,
    DocumentCopyRequest,
    DocumentDuplicateRequest,
    DocumentListResponse,
    DocumentSummary,
    DocumentRead,
    DocumentFileVersionRead,
    DocumentUpdate,
    serialize_document,
    serialize_document_file_version,
    serialize_document_file_versions,
    serialize_document_summary,
)
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.schemas.ai_generation import GenerateDocumentSummaryResponse
from app.schemas.tenant.property import PropertyValuesSetRequest
from app.schemas.tenant.tag import TagSetRequest
from app.services import attachments as attachments_service
from app.services.storage import build_upload_response, get_guild_storage
from app.api import resource_access
from app.core.tools import Tool
from app.services.tenant import documents as documents_service
from app.services.tenant import initiatives as initiatives_service
from app.services import notifications as notifications_service
from app.services import permissions as permissions_service
from app.services.tenant import properties as properties_service
from app.services.tenant import recent_views as recent_views_service
from app.services import rls as rls_service
from app.schemas.tenant.recent_view import RecentViewWrite
from app.services.ai_generation import AIGenerationError, generate_document_summary
from app.services.collaboration import collaboration_manager

logger = logging.getLogger(__name__)

router = APIRouter()
# Cross-guild "my documents" aggregate (My Documents page). Mounted under
# /api/v1/me; user-scoped, routes per member guild via gather_across_guilds.
me_router = APIRouter()

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


def _grant_for_user(document: Document, user_id: int) -> ResourceGrant | None:
    """Find a user's (non-role) document grant from the loaded grants."""
    return next(
        (
            g
            for g in (document.grants or [])
            if g.user_id == user_id and g.role_id is None
        ),
        None,
    )


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
) -> Document:
    document = await documents_service.get_document(
        session,
        document_id=document_id,
        guild_id=guild_id,
        populate_existing=populate_existing,
    )
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=DocumentMessages.NOT_FOUND
        )
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
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=DocumentMessages.MANAGER_REQUIRED,
            )


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
    manage_access: bool = False,
    guild_role: GuildRole | str | None = None,
) -> None:
    """Authorize a document via the shared engine. ``manage_access=True`` (member/
    permission ops) additionally rejects PAM grantees — a grant never manages
    access."""
    resource_access.authorize(
        Tool.document,
        document,
        user,
        access=access,
        require_owner=require_owner,
        manage_access=manage_access,
        guild_role=guild_role,
    )


def _get_document_permission(document: Document, user_id: int) -> ResourceGrant | None:
    """Get a user's permission grant for a document from the loaded grants."""
    return _grant_for_user(document, user_id)


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
    # A guild admin (full access to all guild data) or a live PAM grant sees all
    # of the guild's documents in one bulk, guild-scoped query; otherwise narrow
    # to documents the user has explicit/role permission for. Guild scope + RLS
    # apply either way.
    conditions = [Initiative.guild_id == guild_id]
    if not has_active_grant(
        guild_id
    ) and not permissions_service.is_request_guild_admin(guild_id):
        conditions.append(
            Document.id.in_(permissions_service.visible_document_ids_subquery(user_id))
        )

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


async def _apply_property_filters(
    session: SessionDep,
    conditions: list,
) -> list:
    """Return SA WHERE clauses for parsed property filter conditions.

    Thin adapter over the shared
    :func:`properties_service.build_property_filter_clauses` helper —
    loads the definitions visible under the caller's RLS, then delegates
    the per-condition compilation so documents, tasks, and events all
    share one source of truth for typed-column + is_empty semantics.
    """
    if not conditions:
        return []
    defs = await properties_service.load_definitions_by_ids(
        session,
        [c.property_id for c in conditions],
    )
    return properties_service.build_property_filter_clauses(
        "document", conditions, defs
    )


def _sort_global_document_summaries(
    items: list[DocumentSummary], sort_by: Optional[str], sort_dir: Optional[str]
) -> list[DocumentSummary]:
    """Order the merged cross-guild summaries, mirroring _apply_document_sort
    (``id`` desc tiebreak applied as a separate stable pass)."""
    items.sort(key=lambda d: d.id, reverse=True)
    if sort_by == "title":
        items.sort(key=lambda d: (d.title or "").lower(), reverse=sort_dir == "desc")
    elif sort_by == "updated_at":
        items.sort(key=lambda d: d.updated_at, reverse=sort_dir == "desc")
    elif sort_by == "created_at":
        items.sort(key=lambda d: d.created_at, reverse=sort_dir == "desc")
    else:
        items.sort(key=lambda d: d.updated_at, reverse=True)
    return items


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
) -> tuple[list[DocumentSummary], int]:
    """List documents the user created across every guild they belong to.

    Visits each guild's schema in turn and merges. Per-schema ids collide, so
    items are distinguished by (guild_id, id) via the nested initiative.
    """
    target_guilds = await member_guild_ids(
        session, current_user.id, restrict_to=guild_ids
    )
    conditions = [Document.created_by_id == current_user.id]
    if search:
        normalized = search.strip().lower()
        if normalized:
            conditions.append(func.lower(Document.title).contains(normalized))

    async def _fetch(
        guild_session: AsyncSession, _guild_id: int
    ) -> list[DocumentSummary]:
        statement = (
            select(Document)
            .where(*conditions)
            .options(
                selectinload(Document.initiative).selectinload(Initiative.guild),
                selectinload(Document.initiative)
                .selectinload(Initiative.memberships)
                .options(
                    selectinload(InitiativeMember.user),
                    selectinload(InitiativeMember.role_ref).selectinload(
                        InitiativeRoleModel.permissions
                    ),
                ),
                selectinload(Document.project_links).selectinload(
                    ProjectDocument.project
                ),
                selectinload(Document.grants).selectinload(ResourceGrant.role),
                selectinload(Document.tag_links).selectinload(DocumentTag.tag),
                selectinload(Document.property_values).selectinload(
                    DocumentPropertyValue.property_definition
                ),
                selectinload(Document.property_values).selectinload(
                    DocumentPropertyValue.value_user
                ),
            )
        )
        documents = list((await guild_session.exec(statement)).unique().all())
        await documents_service.annotate_comment_counts(guild_session, documents)
        return [
            serialize_document_summary(
                document,
                my_permission_level=_compute_my_doc_permission_level(
                    document, current_user.id
                ),
            )
            for document in documents
        ]

    items = await gather_across_guilds(session, current_user.id, target_guilds, _fetch)
    items = _sort_global_document_summaries(items, sort_by, sort_dir)
    total_count = len(items)
    if page_size > 0:
        start = (page - 1) * page_size
        items = items[start : start + page_size]
    else:
        # "all rows" is still capped server-side (SEC-14): never return an
        # unbounded merged list across every guild.
        items = items[: unbounded_page_limit()]
    return items, total_count


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
        await _get_initiative_or_404(
            session, initiative_id=initiative_id, guild_id=guild_context.guild_id
        )

    conditions = _build_visible_docs_filters(
        guild_context.guild_id,
        current_user.id,
        initiative_id=initiative_id,
        search=search,
    )

    # Subquery: IDs of visible documents
    visible_docs_subq = (
        select(Document.id).join(Document.initiative).where(*conditions).subquery()
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


@me_router.get("/documents", response_model=DocumentListResponse)
async def list_my_documents(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_ids: Optional[List[int]] = Query(default=None),
    search: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=0, le=100),
    sort_by: Optional[str] = Query(default=None),
    sort_dir: Optional[str] = Query(default=None),
) -> DocumentListResponse:
    """Documents created by the current user across every guild they belong to.

    An optional ``guild_ids`` filter narrows to a subset of guilds.
    """
    items, total_count = await _list_global_documents(
        session,
        current_user,
        guild_ids=guild_ids,
        search=search,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    if page_size > 0:
        has_next = page * page_size < total_count
    else:
        # "All rows" is still capped (SEC-14): report truncation.
        has_next = len(items) < total_count
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


@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(default=None),
    tag_ids: Optional[List[int]] = Query(default=None, description="Filter by tag IDs"),
    untagged: Optional[bool] = Query(
        default=None, description="Filter to documents with no tags"
    ),
    property_filters: Optional[str] = Query(
        default=None,
        description=(
            "JSON-encoded list of property-value filters, e.g. "
            '`[{"property_id": 12, "op": "eq", "value": "live"}]`. '
            "Maximum 5 conditions per request."
        ),
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=0, le=100),
    sort_by: Optional[str] = Query(default=None),
    sort_dir: Optional[str] = Query(default=None),
) -> DocumentListResponse:
    """List documents in the active guild visible to the current user.

    DAC: Documents with explicit DocumentPermission or role-based permission.

    Pagination: page_size=0 returns all documents (no pagination).

    Cross-guild "my documents" lives under /me/documents (see list_my_documents).
    """

    if initiative_id is not None:
        await _get_initiative_or_404(
            session, initiative_id=initiative_id, guild_id=guild_context.guild_id
        )

    conditions = _build_visible_docs_filters(
        guild_context.guild_id,
        current_user.id,
        initiative_id=initiative_id,
        search=search,
        tag_ids=tag_ids,
        untagged=untagged,
    )

    # Parse + apply property filters (capped at MAX_PROPERTY_FILTERS).
    try:
        parsed_property_filters = properties_service.parse_property_filters(
            property_filters
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueryMessages.INVALID_CONDITIONS,
        )
    property_clauses = await _apply_property_filters(session, parsed_property_filters)
    conditions.extend(property_clauses)

    # Count query
    count_subq = (
        select(Document.id).join(Document.initiative).where(*conditions).subquery()
    )
    count_stmt = select(func.count()).select_from(count_subq)
    total_count = (await session.exec(count_stmt)).one()

    # Data query with eager loading
    stmt = (
        select(Document)
        .join(Document.initiative)
        .where(*conditions)
        .options(
            selectinload(Document.initiative)
            .selectinload(Initiative.memberships)
            .options(
                selectinload(InitiativeMember.user),
                selectinload(InitiativeMember.role_ref).selectinload(
                    InitiativeRoleModel.permissions
                ),
            ),
            selectinload(Document.project_links).selectinload(ProjectDocument.project),
            selectinload(Document.grants).selectinload(ResourceGrant.role),
            selectinload(Document.tag_links).selectinload(DocumentTag.tag),
            selectinload(Document.property_values).selectinload(
                DocumentPropertyValue.property_definition
            ),
            selectinload(Document.property_values).selectinload(
                DocumentPropertyValue.value_user
            ),
        )
    )
    stmt = _apply_document_sort(stmt, sort_by, sort_dir)

    if page_size > 0:
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    else:
        # "all rows" is still capped server-side (SEC-14) so the query can't
        # dump an entire guild's document table in one response.
        stmt = stmt.limit(unbounded_page_limit())

    result = await session.exec(stmt)
    documents = result.unique().all()

    await documents_service.annotate_comment_counts(session, documents)
    items = [
        serialize_document_summary(
            document,
            my_permission_level=_compute_my_doc_permission_level(
                document,
                current_user.id,
            ),
        )
        for document in documents
    ]

    if page_size > 0:
        has_next = page * page_size < total_count
    else:
        # page_size=0 means "all rows" — but still capped at
        # unbounded_page_limit() (SEC-14). Surface a truncated result via
        # has_next so the SPA can tell data is missing.
        has_next = len(items) < total_count
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
    await _get_initiative_or_404(
        session, initiative_id=initiative_id, guild_id=guild_context.guild_id
    )

    has_permission_subq = permissions_service.visible_document_ids_subquery(
        current_user.id
    )

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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.TITLE_REQUIRED,
        )

    # Check for duplicate title in initiative
    await _check_duplicate_title(session, initiative_id=initiative.id, title=title)

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
        title=title,
        initiative_id=initiative.id,
        guild_id=guild_context.guild_id,
        document_type=requested_type,
        content=normalized_content,
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
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
        guild_id=guild_context.guild_id,
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
    )

    # Sync wikilinks to document_links table
    await documents_service.sync_document_links(
        session,
        document_id=document.id,
        content=document.content,
        guild_id=guild_context.guild_id,
    )

    await session.commit()
    await reapply_rls_context(session)

    hydrated = await _get_document_or_404(
        session, document_id=document.id, guild_id=guild_context.guild_id
    )
    return serialize_document(
        hydrated,
        my_permission_level=_compute_my_doc_permission_level(
            hydrated,
            current_user.id,
        ),
    )


@router.post(
    "/upload", response_model=DocumentRead, status_code=status.HTTP_201_CREATED
)
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.TITLE_REQUIRED,
        )

    # Check for duplicate title in initiative
    await _check_duplicate_title(session, initiative_id=initiative.id, title=title)

    # Read the body with a hard cap so an over-limit upload is rejected before
    # the whole payload is buffered into memory (memory-exhaustion DoS guard).
    try:
        contents = await attachments_service.read_upload_bounded(
            file, attachments_service.MAX_DOCUMENT_FILE_SIZE
        )
    except attachments_service.FileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
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

    # Save file to uploads directory
    file_url = attachments_service.save_document_file(
        contents, extension, guild_context.guild_id, content_type=mime_type
    )

    # Track the upload in the uploads table for guild-scoped access control
    upload_record = Upload(
        filename=file_url.split("/")[-1],
        guild_id=guild_context.guild_id,
        uploader_user_id=current_user.id,
        size_bytes=len(contents),
        content_type=mime_type,
        content_hash=attachments_service.compute_content_hash(contents),
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
    owner_permission = ResourceGrant(
        resource_type="document",
        resource_id=document.id,
        user_id=current_user.id,
        role_id=None,
        level=ResourceAccessLevel.owner,
        guild_id=guild_context.guild_id,
        initiative_id=document.initiative_id,
    )
    # Record the initial version (v1). The documents row mirrors this version's
    # file fields; subsequent uploads add higher-numbered versions.
    initial_version = DocumentFileVersion(
        document_id=document.id,
        guild_id=guild_context.guild_id,
        version_number=1,
        file_url=file_url,
        file_content_type=mime_type,
        file_size=len(contents),
        original_filename=file.filename,
        uploaded_by_id=current_user.id,
    )
    # Auto-set featured image for image uploads (before commit so we avoid expired attrs)
    if mime_type and mime_type.startswith("image/"):
        document.featured_image_url = file_url

    session.add(owner_permission)
    session.add(initial_version)
    # File uploads default to Viewer for all members, like native docs.
    session.add(
        ResourceGrant(
            resource_type="document",
            resource_id=document.id,
            user_id=None,
            role_id=None,
            all_initiative_members=True,
            level=ResourceAccessLevel.read,
            guild_id=guild_context.guild_id,
            initiative_id=document.initiative_id,
        )
    )
    await session.commit()
    await reapply_rls_context(session)

    hydrated = await _get_document_or_404(
        session, document_id=document.id, guild_id=guild_context.guild_id
    )
    return serialize_document(
        hydrated,
        my_permission_level=_compute_my_doc_permission_level(
            hydrated,
            current_user.id,
        ),
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
    document = await _get_document_or_404(
        session, document_id=document_id, guild_id=guild_context.guild_id
    )
    if document.document_type != DocumentType.file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.NOT_A_FILE_DOCUMENT,
        )
    _require_document_access(document, current_user, access="write")

    # Read the body with a hard cap so an over-limit upload is rejected before
    # the whole payload is buffered into memory (memory-exhaustion DoS guard).
    try:
        contents = await attachments_service.read_upload_bounded(
            file, attachments_service.MAX_DOCUMENT_FILE_SIZE
        )
    except attachments_service.FileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
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

    file_url = attachments_service.save_document_file(
        contents, extension, guild_context.guild_id, content_type=mime_type
    )

    # Track the new blob in the uploads table for guild-scoped access control.
    upload_record = Upload(
        filename=file_url.split("/")[-1],
        guild_id=guild_context.guild_id,
        uploader_user_id=current_user.id,
        size_bytes=len(contents),
        content_type=mime_type,
        content_hash=attachments_service.compute_content_hash(contents),
    )
    session.add(upload_record)

    max_version = await session.scalar(
        select(func.max(DocumentFileVersion.version_number)).where(
            DocumentFileVersion.document_id == document_id
        )
    )
    next_version = (max_version or 0) + 1

    version = DocumentFileVersion(
        document_id=document_id,
        guild_id=guild_context.guild_id,
        version_number=next_version,
        file_url=file_url,
        file_content_type=mime_type,
        file_size=len(contents),
        original_filename=file.filename,
        uploaded_by_id=current_user.id,
    )
    session.add(version)

    # Mirror the new (now current) version onto the document row so the
    # existing download endpoint and viewer serve the latest file.
    document.file_url = file_url
    document.file_content_type = mime_type
    document.file_size = len(contents)
    document.original_filename = file.filename
    document.updated_by_id = current_user.id
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
        await reapply_rls_context(session)
        attachments_service.delete_upload_by_url(file_url)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DocumentMessages.VERSION_CONFLICT,
        )
    await reapply_rls_context(session)
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
    document = await _get_document_or_404(
        session, document_id=document_id, guild_id=guild_context.guild_id
    )
    if document.document_type != DocumentType.file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.NOT_A_FILE_DOCUMENT,
        )
    _require_document_access(document, current_user, access="read")

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
    document = await _get_document_or_404(
        session, document_id=document_id, guild_id=guild_context.guild_id
    )
    if document.document_type != DocumentType.file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.NOT_A_FILE_DOCUMENT,
        )
    _require_document_access(document, current_user, require_owner=True)

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
            document.updated_by_id = current_user.id
            document.updated_at = datetime.now(timezone.utc)
            # Keep featured image coherent when it referenced the deleted blob.
            if document.featured_image_url == deleted_url:
                if (promoted.file_content_type or "").startswith("image/"):
                    document.featured_image_url = promoted.file_url
                else:
                    document.featured_image_url = None

    await session.commit()
    await reapply_rls_context(session)

    # Delete the blob after the row is gone so a failed commit doesn't orphan files.
    attachments_service.delete_upload_by_url(deleted_url)


@router.get("/{document_id}", response_model=DocumentRead)
async def read_document(
    document_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DocumentRead:
    document = await _get_document_or_404(
        session, document_id=document_id, guild_id=guild_context.guild_id
    )
    _require_document_access(document, current_user, access="read")
    return serialize_document(
        document,
        my_permission_level=_compute_my_doc_permission_level(
            document,
            current_user.id,
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
    document = await _get_document_or_404(
        session, document_id=document_id, guild_id=guild_context.guild_id
    )
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
    document = await _get_document_or_404(
        session, document_id=document_id, guild_id=guild_context.guild_id
    )
    _require_document_write_access(document, current_user)
    updated = False
    update_data = document_in.model_dump(exclude_unset=True)
    removed_upload_urls: set[str] = set()
    previous_content_urls = attachments_service.extract_upload_urls(document.content)
    previous_featured_url = document.featured_image_url

    if "title" in update_data:
        title = (update_data["title"] or "").strip()
        if not title:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=DocumentMessages.TITLE_REQUIRED,
            )
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
        # Clear yjs_state ONLY if there is no active collaboration room.
        # Rationale: when users are actively collaborating, the in-memory
        # room is the source of truth for Yjs state, and its full snapshot
        # will be written back to yjs_state on the last disconnect via
        # persist_room. Clearing yjs_state here while a room is active
        # creates a data-loss window: if the REST PATCH lands right before
        # all users disconnect, and the disconnect's persist_room fails or
        # races with cleanup, yjs_state stays None and the next session
        # bootstraps from the (potentially stale) PATCHed content column,
        # losing any edits that were made between the PATCH and disconnect.
        #
        # Clearing only when the room is inactive still solves PR #347's
        # original problem: non-collab edits need to override any stale
        # pre-existing yjs_state the next time the user re-enables collab.
        if not collaboration_manager.has_active_collaborators(document.id):
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
        if removed_upload_urls:
            filenames = [url.split("/")[-1] for url in removed_upload_urls]
            await session.exec(sa_delete(Upload).where(Upload.filename.in_(filenames)))
        await session.commit()
        await reapply_rls_context(session)
        # Invalidate any in-memory collaboration room so the next session
        # loads fresh state from the database. If a room has active
        # collaborators their in-memory state wins until they disconnect.
        if content_updated:
            await collaboration_manager.invalidate_room_if_empty(document.id)
    hydrated = await _get_document_or_404(
        session, document_id=document.id, guild_id=guild_context.guild_id
    )
    attachments_service.delete_uploads_by_urls(removed_upload_urls)
    return serialize_document(
        hydrated,
        my_permission_level=_compute_my_doc_permission_level(
            hydrated,
            current_user.id,
        ),
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
    document = await _get_document_or_404(
        session, document_id=document_id, guild_id=guild_context.guild_id
    )
    _require_document_access(document, current_user, access="write")
    payload = payload or DocumentDuplicateRequest()
    title = (payload.title or f"{document.title} (Copy)").strip()
    if not title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.TITLE_REQUIRED,
        )

    try:
        duplicated = await documents_service.duplicate_document(
            session,
            source=document,
            target_initiative_id=document.initiative_id,
            title=title,
            user_id=current_user.id,
            guild_id=guild_context.guild_id,
        )
    except attachments_service.StorageQuotaExceededError:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=AttachmentMessages.STORAGE_QUOTA_EXCEEDED,
        )
    hydrated = await _get_document_or_404(
        session, document_id=duplicated.id, guild_id=guild_context.guild_id
    )
    return serialize_document(
        hydrated,
        my_permission_level=_compute_my_doc_permission_level(
            hydrated,
            current_user.id,
        ),
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
    document = await _get_document_or_404(
        session, document_id=document_id, guild_id=guild_context.guild_id
    )
    # Templates are starter content meant to be copied — read on the source is enough.
    # Non-templates still require write to prevent silent fork-and-edit of someone else's work.
    required_access = "read" if document.is_template else "write"
    _require_document_access(document, current_user, access=required_access)
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.TITLE_REQUIRED,
        )

    try:
        duplicated = await documents_service.duplicate_document(
            session,
            source=document,
            target_initiative_id=target_initiative.id,
            title=title,
            user_id=current_user.id,
            guild_id=guild_context.guild_id,
        )
    except attachments_service.StorageQuotaExceededError:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=AttachmentMessages.STORAGE_QUOTA_EXCEEDED,
        )
    hydrated = await _get_document_or_404(
        session, document_id=duplicated.id, guild_id=guild_context.guild_id
    )
    return serialize_document(
        hydrated,
        my_permission_level=_compute_my_doc_permission_level(
            hydrated,
            current_user.id,
        ),
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

    document = await _get_document_or_404(
        session, document_id=document_id, guild_id=guild_context.guild_id
    )
    _require_document_access(document, current_user, require_owner=True)
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
    document = await _get_document_or_404(
        session, document_id=document_id, guild_id=guild_context.guild_id
    )
    _require_document_write_access(document, current_user)
    initiative = document.initiative
    if not initiative:
        initiative = await _get_initiative_or_404(
            session,
            initiative_id=document.initiative_id,
            guild_id=guild_context.guild_id,
        )
    memberships = getattr(initiative, "memberships", []) or []
    member_map = {
        membership.user_id: membership.user
        for membership in memberships
        if membership.user
    }
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
    document = await _get_document_or_404(
        session, document_id=document_id, guild_id=guild_context.guild_id
    )
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
            selectinload(Document.grants).selectinload(ResourceGrant.role),
            selectinload(Document.tag_links).selectinload(DocumentTag.tag),
            selectinload(Document.property_values).selectinload(
                DocumentPropertyValue.property_definition
            ),
            selectinload(Document.property_values).selectinload(
                DocumentPropertyValue.value_user
            ),
        )
    )
    result = await session.exec(doc_stmt)
    doc = result.one()
    doc.updated_at = datetime.now(timezone.utc)
    await session.commit()

    return serialize_document(
        doc,
        my_permission_level=_compute_my_doc_permission_level(
            doc,
            current_user.id,
        ),
    )


@router.put("/{document_id}/properties", response_model=DocumentRead)
async def set_document_properties(
    document_id: int,
    payload: PropertyValuesSetRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DocumentRead:
    """Replace the custom property values on a document.

    Requires document write access (same gate as PUT /tags). Values are
    validated server-side against each property definition's type and
    options.
    """
    document = await _get_document_or_404(
        session, document_id=document_id, guild_id=guild_context.guild_id
    )
    _require_document_access(document, current_user, access="write")

    try:
        await properties_service.set_document_property_values(
            session,
            document,
            payload.values,
            document.initiative_id,
        )
    except HTTPException:
        await session.rollback()
        await reapply_rls_context(session)
        raise

    # Bump updated_at via a lightweight select to avoid touching the
    # relationship collections after the DELETE in the service layer.
    ts_stmt = select(Document).where(Document.id == document_id)
    ts_result = await session.exec(ts_stmt)
    ts_doc = ts_result.one()
    ts_doc.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await reapply_rls_context(session)

    # populate_existing=True forces selectinload to refresh the cached
    # document's property_values collection. Without it, expire_on_commit
    # =False keeps the stale (pre-replace-all) collection in the identity
    # map and the response serializes as if no values were set.
    refreshed = await _get_document_or_404(
        session,
        document_id=document_id,
        guild_id=guild_context.guild_id,
        populate_existing=True,
    )
    return serialize_document(
        refreshed,
        my_permission_level=_compute_my_doc_permission_level(
            refreshed,
            current_user.id,
        ),
    )


@router.put("/{document_id}/grants", response_model=DocumentRead)
async def set_document_grants(
    document_id: int,
    grants: list[ResourceGrantSchema],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DocumentRead:
    """Replace the document's entire sharing state in one call — the body is the
    full list of grants (all-initiative-members / per-user / per-role). Every
    non-owner grant is rebuilt from it; the owner is always preserved.
    """
    await resource_access.set_resource_grants(
        session, Tool.document, document_id, current_user, guild_context, grants
    )
    hydrated = await _get_document_or_404(
        session, document_id=document_id, guild_id=guild_context.guild_id
    )
    return serialize_document(
        hydrated,
        my_permission_level=_compute_my_doc_permission_level(hydrated, current_user.id),
    )


def _download_document_options():
    """Eager loads needed by ``_require_document_access`` on a download."""
    return (
        selectinload(Document.initiative)
        .selectinload(Initiative.memberships)
        .options(
            selectinload(InitiativeMember.user),
            selectinload(InitiativeMember.role_ref).selectinload(
                InitiativeRoleModel.permissions
            ),
        ),
        selectinload(Document.grants).selectinload(ResourceGrant.role),
    )


async def _load_download_document(
    session: AsyncSession, current_user, guild_id: int, document_id: int
):
    """Load a file ``Document`` by id from the path-addressed guild schema,
    with the eager loads the access check needs.

    Downloads are served via iframe/window.open, which can't send headers, so
    the guild rides in the ``/g/{guild_id}`` path segment and names exactly the
    schema to read. Access is re-validated here (membership or live PAM grant);
    the frozen ``public`` backup is never read. Leaves the session routed into
    the guild so a follow-up version query runs in the same schema.

    Returns ``(document, guild_role)`` — role ``None`` for PAM grantees — or
    ``(None, None)`` when there's no access, no schema, or no such document in
    the addressed guild. All of those are an indistinguishable 404 to the
    caller, so existence is never confirmed across guilds.
    """
    from app.db.schema_provisioning import guild_schema_name

    # Guard the SET ROLE sink: if the guild schema/role isn't provisioned,
    # establish_guild_access would fault rather than 404. (The session is the
    # BYPASSRLS admin engine, so this lookup runs regardless of context.)
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
    # active_role/grant, no ambient bypass) as REST and the realtime
    # sockets. Fine-grained read permission is then enforced by
    # require_document_access against the context this established.
    try:
        ctx = await establish_guild_access(session, current_user, int(guild_id))
    except GuildAccessError:
        return None, None

    doc = (
        await session.exec(
            select(Document)
            .where(Document.id == document_id, Document.guild_id == guild_id)
            .options(*_download_document_options())
        )
    ).one_or_none()
    # A real member threads their guild role into the access check's guild-admin
    # leg; a PAM/break-glass grantee gets ``None`` here — their reach is the
    # scoped grant / admin role already in the established context, not a guild
    # role on the row.
    guild_role = None if ctx.is_pam else ctx.role
    return doc, guild_role


@router.get("/{document_id}/download", include_in_schema=False)
@limiter.limit("30/minute")
async def download_document_file(
    request: Request,
    guild_id: int,
    document_id: int,
    current_user: UploadUserDep,
    # AdminSessionDep (not RLSSessionDep) because the loader routes the
    # session into the path-addressed guild's schema itself after validating
    # access.
    session: Annotated[AsyncSession, Depends(get_admin_session)],
    inline: bool = False,
) -> Response:
    """Download a file-type document — requires read permission on the document."""
    document, guild_role = await _load_download_document(
        session, current_user, guild_id, document_id
    )
    if (
        document is None
        or document.document_type != DocumentType.file
        or document.file_url is None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=DocumentMessages.NOT_FOUND
        )

    # ``guild_role`` feeds the initiative-scope gate's guild-admin leg — the
    # routed session has no request role context of its own here.
    _require_document_access(
        document, current_user, access="read", guild_role=guild_role
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
    # and routes the admin session into the path-addressed guild's schema.
    session: Annotated[AsyncSession, Depends(get_admin_session)],
    inline: bool = False,
) -> Response:
    """Download a specific stored version of a file document — read permission."""
    document, guild_role = await _load_download_document(
        session, current_user, guild_id, document_id
    )
    if document is None or document.document_type != DocumentType.file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=DocumentMessages.NOT_FOUND
        )

    _require_document_access(
        document, current_user, access="read", guild_role=guild_role
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


@router.post("/{document_id}/view", response_model=RecentViewWrite)
async def record_document_view(
    document_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> RecentViewWrite:
    """Record a recent-view for the layout tabs bar."""
    document = await _get_document_or_404(
        session, document_id=document_id, guild_id=guild_context.guild_id
    )
    _require_document_access(document, current_user, access="read")
    record = await recent_views_service.record_view(
        session,
        user_id=current_user.id,
        entity_type="document",
        entity_id=document.id,
        persist=not guild_context.is_pam,
        limit=current_user.recent_tabs_limit,
    )
    return RecentViewWrite(
        entity_type="document",
        entity_id=document.id,
        last_viewed_at=record.last_viewed_at,
    )


@router.delete("/{document_id}/view", status_code=status.HTTP_204_NO_CONTENT)
async def clear_document_view(
    document_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    document = await _get_document_or_404(
        session, document_id=document_id, guild_id=guild_context.guild_id
    )
    _require_document_access(document, current_user, access="read")
    await recent_views_service.clear_view(
        session,
        user_id=current_user.id,
        entity_type="document",
        entity_id=document.id,
    )

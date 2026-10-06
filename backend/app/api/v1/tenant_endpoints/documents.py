import asyncio
import logging
from datetime import datetime, timezone
from typing import Annotated, Any, List, Optional

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
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.search import SearchEntityType
from app.services.permissions import Action
from app.services.tenant import content_references
from app.services.tenant.relationships import Endpoint
from app.api.actor_route import ActorRoute
from app.api.deps import (
    CommunityIdPath,
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    IncludeDeletedDep,
    RLSSessionDep,
    plugin_scope,
    SessionDep,
    UploadUserDep,
    establish_guild_access,
    get_current_active_user,
    GuildAccessError,
    GuildContext,
    GuildContextDep,
)
from app.core.messages import (
    AttachmentMessages,
    DocumentMessages,
)
from app.core.rate_limit import limiter
from app.db.session import require_actor_context
from app.models.tenant.document import (
    Document,
    DocumentFileVersion,
    DocumentType,
)
from app.models.platform.notification import NotificationType
from app.models.platform.user import User
from app.schemas.tenant.document import (
    DocumentCreate,
    DocumentFileVersionRead,
    DocumentRead,
    DocumentSummary,
    DocumentUpdate,
    serialize_document,
    serialize_document_summary,
    SpreadsheetImportRead,
)
from app.schemas.tenant.resource_grant import initiative_readable
from app.schemas.ai_generation import GenerateDocumentSummaryResponse
from app.services.tenant import attachments as attachments_service
from app.services.tenant import file_versions
from app.services import storage_config
from app.services.storage import build_upload_response, get_guild_storage
from app.api import resource_access
from app.core.tools import Tool
from app.services.tenant import body_states
from app.services.tenant import comments as comments_service
from app.services.tenant import documents as documents_service
from app.services.tenant import ownership as ownership_service
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service
from app.services.tenant.names import ensure_name_free
from app.services.tenant import tool_listing
from app.services import notifications as notifications_service
from app.services import reachability
from app.services import audit as audit_service
from app.services.ai_generation import AIGenerationError, generate_document_summary
from app.services.ai_settings import resolve_ai_settings
from app.services.tenant import spreadsheet_import
from app.services.tenant.collaboration import (
    collaboration_manager,
    content_version,
    versioned,
    written_into,
)

logger = logging.getLogger(__name__)


router = APIRouter(route_class=ActorRoute)

#: The routes an installed plug-in may call, under the documents scopes.
DocumentsRead = Annotated[ActorContext, Depends(plugin_scope("documents:read"))]
DocumentsWrite = Annotated[ActorContext, Depends(plugin_scope("documents:write"))]


def _file_download_response(
    *, guild_id: int, version: DocumentFileVersion, inline: bool
) -> Response:
    """Build a hardened download response for one version's stored file.

    Shared by the current-document download and the per-version download so
    the filename checks and SVG/HTML response hardening can't drift
    between the two endpoints. Serves through the guild's storage backend
    (local FileResponse or S3 streaming proxy) via :func:`build_upload_response`.
    """
    content_type = version.file_content_type
    original_filename = version.original_filename
    filename = version.file_url.split("/")[-1]
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
            # Shown as a static page: sandboxed, with no scripts and no forms,
            # and framed only by the in-app document viewer on this origin.
            # X-Frame-Options set here overrides the SecurityHeadersMiddleware
            # global DENY (it uses setdefault); frame-ancestors 'self' is the
            # CSP equivalent.
            headers["Content-Security-Policy"] = (
                "sandbox; script-src 'none'; form-action 'none'; frame-ancestors 'self'"
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
    context: ActorContext,
    user_id: int | None,
    *,
    initiative_id: Optional[int] = None,
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
        user_id,
        context=context,
        initiative_id=initiative_id,
        search=search,
        tag_ids=tag_ids,
    )

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
    session: AsyncSession, user_id: int | None, documents: list[Document]
) -> list[DocumentSummary]:
    """Serialize one page of documents — the rows a document list answers with.

    Everything a card shows beyond the row itself (its tags, its comment count)
    is a grouped query over the whole page, run
    once here rather than per row. The order is already settled by the caller
    and is preserved.

    Both document lists run this: the guild-wide one through
    ``tool_lists.TOOL_LISTS``, and the cross-guild ``/me/documents`` through
    ``me_tools.MY_TOOL_LISTS``.
    """
    await tags_service.annotate_tags(session, documents)
    await properties_service.annotate_properties(session, documents)
    await comments_service.annotate_comment_counts(
        session, documents, column="document_id"
    )
    await ownership_service.annotate_owner_plugins(session, documents)
    context = require_actor_context(session)
    return [
        serialize_document_summary(document, context=context, user_id=user_id)
        for document in documents
    ]


@router.post("/", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def create_document(
    document_in: DocumentCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: DocumentsWrite,
) -> DocumentRead:
    resource_access.refuse_plugin_sharing(guild_context, document_in, "grants")
    initiative = await resource_access.prepare_create(
        session, Tool.document, document_in.initiative_id, current_user, guild_context
    )
    name = document_in.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.NAME_REQUIRED,
        )

    await ensure_name_free(
        session,
        Document.name,
        name,
        Document.initiative_id == initiative.id,
        detail=DocumentMessages.NAME_ALREADY_EXISTS,
    )

    try:
        normalized_content = documents_service.normalize_document_content(
            document_in.content,
            document_type=document_in.document_type,
        )
    except documents_service.DocumentContentError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code
        ) from exc

    document = Document(
        name=name,
        initiative_id=initiative.id,
        document_type=document_in.document_type,
        content=normalized_content,
        created_by=guild_context.user_id,
        featured_image_url=document_in.featured_image_url,
        is_template=document_in.is_template,
    )
    session.add(document)
    await session.flush()

    await resource_access.grant_initial_sharing(
        session,
        guild_context,
        Tool.document,
        user=current_user,
        resource_id=document.id,
        initiative_id=initiative.id,
        payload=document_in,
        grants=document_in.grants,
    )

    # What the new body points at becomes `references` edges.
    await content_references.sync_for_entity(
        session,
        Endpoint(SearchEntityType.document, document.id),
        body=document.content,
        author_id=guild_context.user_id,
    )
    await attachments_service.claim_uploads(session, document)

    await properties_service.write_on_create(session, document, document_in.properties)
    await session.commit()
    return await read_after_write(session, document.id, current_user, guild_context)


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
    initiative = await resource_access.prepare_create(
        session, Tool.document, initiative_id, current_user, guild_context
    )
    name = name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.NAME_REQUIRED,
        )
    await ensure_name_free(
        session,
        Document.name,
        name,
        Document.initiative_id == initiative.id,
        detail=DocumentMessages.NAME_ALREADY_EXISTS,
    )
    stored = await _store_file(
        session, guild_context, file, initiative_id=initiative.id
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
        featured_image_url=_featured(stored["file_url"], stored["file_content_type"]),
    )
    session.add(document)
    await session.flush()

    await resource_access.grant_initial_sharing(
        session,
        guild_context,
        Tool.document,
        user=current_user,
        resource_id=document.id,
        initiative_id=initiative.id,
        payload=None,
        grants=initiative_readable(),
    )
    # The grants land before the version row: writing a version is the
    # document owner's to do, and the uploader is its owner only once the
    # grant exists.
    await session.flush()

    version = await file_versions.add_version(
        session, document, created_by=current_user.id, **stored
    )
    await file_versions.commit_version(session, guild_context.guild_id, version)
    return await read_after_write(session, document.id, current_user, guild_context)


def _normalize_mime(mime: str | None) -> str:
    """Normalize a MIME type for version type-match comparison."""
    normalized = (mime or "").lower().strip()
    if normalized == "image/jpg":
        return "image/jpeg"
    return normalized


def _featured(file_url: str, content_type: str | None) -> str | None:
    """A picture is its own featured image; any other file shows none."""
    return file_url if (content_type or "").startswith("image/") else None


async def _store_file(
    session: AsyncSession,
    guild_context: GuildContext,
    file: UploadFile,
    *,
    initiative_id: int,
    keep_type: str | None = None,
) -> dict[str, Any]:
    """Read an uploaded file, check it and store it, and return the version
    columns it was stored as. ``keep_type`` refuses a file of another type."""
    guild_id = guild_context.guild_id
    # Pick up a backend/credential change saved in another worker before writing.
    await storage_config.ensure_storage_config_fresh(session)
    # Read the body with a hard cap so an over-limit upload is rejected before
    # the whole payload is buffered into memory.
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
    if keep_type is not None and _normalize_mime(mime_type) != _normalize_mime(
        keep_type
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.VERSION_TYPE_MISMATCH,
        )
    try:
        await attachments_service.enforce_storage_quota(
            session, guild_id=guild_id, incoming_bytes=len(contents)
        )
    except attachments_service.StorageQuotaExceededError:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=AttachmentMessages.STORAGE_QUOTA_EXCEEDED,
        )
    file_url = await attachments_service.store_upload(
        session,
        guild_id=guild_id,
        filename=attachments_service.new_upload_filename(extension),
        data=contents,
        content_type=mime_type,
        created_by=guild_context.user_id,
        initiative_id=initiative_id,
    )
    return {
        "file_url": file_url,
        "file_content_type": mime_type,
        "file_size": len(contents),
        "original_filename": file.filename,
    }


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
        session, Tool.document, document_id, current_user, guild_context, access="write"
    )
    if document.document_type != DocumentType.file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.NOT_A_FILE_DOCUMENT,
        )
    # A new version keeps the document's file type.
    current = document.current_version
    stored = await _store_file(
        session,
        guild_context,
        file,
        initiative_id=document.initiative_id,
        keep_type=current.file_content_type if current is not None else None,
    )
    version = await file_versions.add_version(
        session, document, created_by=current_user.id, **stored
    )
    featured = _featured(version.file_url, version.file_content_type)
    if featured is not None:
        document.featured_image_url = featured
    await file_versions.commit_version(
        session,
        guild_context.guild_id,
        version,
        conflict=DocumentMessages.VERSION_CONFLICT,
    )
    return file_versions.read(DocumentFileVersionRead, version, document)


@router.get("/{document_id}/versions", response_model=List[DocumentFileVersionRead])
async def list_document_versions(
    document_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[DocumentFileVersionRead]:
    """List all stored versions of a file document, newest first. Read access."""
    document = await resource_access.load_authorized(
        session, Tool.document, document_id, current_user, guild_context
    )
    if document.document_type != DocumentType.file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.NOT_A_FILE_DOCUMENT,
        )

    return [
        file_versions.read(DocumentFileVersionRead, version, document)
        for version in await file_versions.versions_newest_first(session, document)
    ]


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
        action=Action.delete,
    )
    if document.document_type != DocumentType.file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.NOT_A_FILE_DOCUMENT,
        )
    deleted = await file_versions.delete_version(
        session, document, version_id, DocumentMessages
    )
    # A featured image that was the deleted file follows the current one.
    current = document.current_version
    if current is not None and document.featured_image_url == deleted.file_url:
        document.featured_image_url = _featured(
            current.file_url, current.file_content_type
        )
    await session.commit()
    await file_versions.release_files(guild_context.guild_id, deleted)


@router.get("/{document_id}", response_model=DocumentRead)
async def read_document(
    document_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: DocumentsRead,
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
    read = serialize_document(
        document,
        user_id=guild_context.user_id,
        include_content=include_content,
        context=guild_context,
    )
    if not include_content:
        return read
    return await versioned(
        read, guild_context.guild_id, SearchEntityType.document.value
    )


@router.patch("/{document_id}", response_model=DocumentRead)
async def update_document(
    document_id: int,
    document_in: DocumentUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: DocumentsWrite,
) -> DocumentRead:
    document = await resource_access.load_authorized(
        session, Tool.document, document_id, current_user, guild_context, access="write"
    )
    updated = False
    update_data = document_in.model_dump(exclude_unset=True)
    removed_upload_urls: set[str] = set()
    released: set[str] = set()
    previous_featured_url = document.featured_image_url

    if "name" in update_data:
        name = (update_data["name"] or "").strip()
        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=DocumentMessages.NAME_REQUIRED,
            )
        await ensure_name_free(
            session,
            Document.name,
            name,
            Document.initiative_id == document.initiative_id,
            Document.id != document.id,
            detail=DocumentMessages.NAME_ALREADY_EXISTS,
        )
        document.name = name
        updated = True

    content_updated = False
    room = (
        collaboration_manager.live_room(
            guild_context.guild_id, SearchEntityType.document.value, document.id
        )
        if "content" in update_data
        else None
    )
    version = update_data.get("content_version")
    if room is not None and (version is None or not room.renders_content):
        # A live room is the writer of both of the document's views. A body
        # that names no version may describe one the session has moved on
        # from, and a body the browser renders is reconciled by its editors,
        # so either is refused rather than taken and reported as saved.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=DocumentMessages.LIVE_SESSION_OWNS_CONTENT,
        )
    if room is not None:
        # The writer read what the session holds now: the change goes into
        # it, reaches the open editors, and is saved with their edits.
        try:
            live_content = documents_service.normalize_document_content(
                update_data["content"], document_type=document.document_type
            )
        except documents_service.DocumentContentError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code
            ) from exc
        if not await room.write(live_content, version, user_id=guild_context.user_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=DocumentMessages.CONTENT_CHANGED,
            )
        updated = True
    elif "content" in update_data:
        # Locked until this write commits, so a write naming the same version
        # reads this one's content.
        await session.refresh(document, ["content"], with_for_update=True)
        if version is not None and content_version(document.content) != version:
            # The writer says which content it changed. Anything since would
            # be undone by writing this whole body over it, so the write is
            # refused and the writer reads again.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=DocumentMessages.CONTENT_CHANGED,
            )
        previous_content_urls = attachments_service.extract_upload_urls(
            document.content
        )
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
        # No room is live, so this edit is the newest thing about the
        # document. Its stored Yjs state has it written in, so the next
        # session opens on it with its history.
        body = body_states.for_kind(document.document_type)
        if body is not None:
            await session.refresh(document, ["yjs_state"])
            document.yjs_state = await written_into(
                body, document.yjs_state, document.content
            )
        else:
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
                author_id=guild_context.user_id,
            )
        await attachments_service.claim_uploads(session, document)
        # What the edit took out goes once nothing else shows it. An installed
        # plug-in does not manage the community's uploads; what its edit let go of
        # stays for a person to clear.
        await session.commit()
        if current_user is not None and removed_upload_urls:
            released = await attachments_service.release_unshown(
                guild_context.guild_id, removed_upload_urls
            )
        # Invalidate any in-memory collaboration room so the next session
        # loads fresh state from the database. If a room has active
        # collaborators their in-memory state wins until they disconnect.
        if content_updated:
            await collaboration_manager.invalidate_room_if_empty(
                guild_context.guild_id, SearchEntityType.document.value, document.id
            )
    attachments_service.delete_blobs(guild_context.guild_id, released)
    return await read_after_write(session, document.id, current_user, guild_context)


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
        session, Tool.document, document_id, current_user, guild_context, access="write"
    )
    name = notifications_service.actor_name(current_user)
    await notifications_service.notify(
        session,
        NotificationType.mention,
        mentioned_user_ids,
        about=(Tool.document.value, document.id),
        key="mention.document",
        values={"actor": name, "document": document.name},
        data={
            "entity_type": Tool.document.value,
            "entity_id": document.id,
            "mentioned_by_name": name,
            "mentioned_by_id": current_user.id,
        },
        actor=current_user,
        # The editor reports mentions as it saves: an unread line absorbs the
        # next report rather than mailing again.
        rollup_key=f"document-body:{document.id}",
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

    Requires read access to the document. Only works for native (editor)
    documents.
    """
    document = await resource_access.load_authorized(
        session, Tool.document, document_id, current_user, guild_context
    )
    if document.document_type != DocumentType.native:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DocumentMessages.AI_NATIVE_ONLY,
        )
    await session.refresh(document, ["content"])

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
        raise HTTPException(status_code=e.status_code, detail=e.code)


async def read_after_write(
    session: RLSSessionDep,
    document_id: int,
    user: Optional[User],
    guild_context: ActorContext,
    *,
    populate_existing: bool = False,
) -> DocumentRead:
    """The document a write answers with: re-read after the commit with
    everything a ``DocumentRead`` reads, and serialized. ``populate_existing``
    refreshes a copy already in the session.

    Registered in ``tool_lists.TOOL_LISTS`` so the shared sharing route
    (``tool_grants.py``) answers in this tool's own shape.
    """
    document = await documents_service.get_document_hydrated(
        session, document_id, populate_existing=populate_existing
    )
    if not document:
        raise await reachability.missing_or_denied(
            "documents",
            document_id,
            guild_context.user_id,
            guild_context.guild_id,
            not_found=Tool.document.not_found_code,
            denied=Tool.document.no_access_code,
        )
    return await versioned(
        serialize_document(
            document, user_id=guild_context.user_id, context=guild_context
        ),
        guild_context.guild_id,
        SearchEntityType.document.value,
    )


async def _load_download_document(
    session: AsyncSession, current_user, guild_id: int, document_id: int
):
    """Load a file ``Document`` by id from the path-addressed guild schema,
    with the eager loads the access check needs.

    Downloads are served via iframe/window.open, which can't send headers, so
    the guild rides in the ``/c/{community_id}`` path segment and names exactly the
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

    # If the guild schema/role isn't provisioned, establish_guild_access would
    # fault rather than 404. The catalog answers
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

    return await documents_service.get_document_for_grants(session, document_id), ctx


@router.get("/{document_id}/download", include_in_schema=False)
@limiter.limit("30/minute")
async def download_document_file(
    request: Request,
    guild_id: CommunityIdPath,
    document_id: int,
    current_user: UploadUserDep,
    # SessionDep (not RLSSessionDep) because the loader routes the session
    # into the path-addressed guild's schema itself after validating access.
    session: SessionDep,
    inline: bool = False,
) -> Response:
    """Download a file-type document — requires read permission on the document."""
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
    version = document.current_version
    if document.document_type != DocumentType.file or version is None:
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
    return _file_download_response(guild_id=guild_id, version=version, inline=inline)


@router.get("/{document_id}/versions/{version_id}/download", include_in_schema=False)
@limiter.limit("30/minute")
async def download_document_file_version(
    request: Request,
    guild_id: CommunityIdPath,
    document_id: int,
    version_id: int,
    current_user: UploadUserDep,
    # Same rationale as download_document_file: the loader validates access
    # and routes the session into the path-addressed guild's schema.
    session: SessionDep,
    inline: bool = False,
) -> Response:
    """Download a specific stored version of a file document — read permission."""
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
    return _file_download_response(guild_id=guild_id, version=version, inline=inline)


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
        session, Tool.document, document_id, current_user, guild_context, access="write"
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
        # Parsing a workbook is CPU work, so it runs off the event loop.
        sheets = await asyncio.to_thread(
            spreadsheet_import.parse_spreadsheet_file, file.filename or "", contents
        )
    except documents_service.DocumentContentError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code
        ) from exc

    return SpreadsheetImportRead(sheets=sheets)

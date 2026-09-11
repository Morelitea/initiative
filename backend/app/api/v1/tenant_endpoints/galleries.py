"""Gallery endpoints — a collection of pictures in an initiative.

Creation is gated at the initiative level (galleries_enabled + create_galleries);
everything after that flows from the gallery's resource-grant DAC
(``resource_grants`` + ``PUT /{id}/grants``), like every other tool.

Two things here are the gallery's own rather than the generic tool shape:

* **Pictures are content, not tools.** A picture is reached only through its
  gallery — ``/galleries/{id}/images/…`` — and adding, replacing or removing
  one asks for **write** access on the gallery, the way editing a task asks
  for write on its project. Deleting a stored *version* asks for the owner,
  because it destroys history rather than editing the present.
* **The picture list scrolls.** It pages in forties and takes an ``until``
  anchor, so the client fetches ahead of the reader and a timeline rail can
  jump a long gallery to a month without paging through everything since —
  the same arrangement a board has.

Uploads are validated from their bytes alone: the format and pixel size are
read from the header and the client's ``Content-Type`` is not consulted. Only
after that does anything decode a pixel — to make the thumbnail, boxed so a
picture that cannot be thumbnailed is still stored.
"""

import logging
from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import delete as sa_delete, func
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api import resource_access
from app.api.deps import (
    GuildContext,
    IncludeDeletedDep,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import (
    AttachmentMessages,
    CommonMessages,
    GalleryMessages,
    InitiativeMessages,
)
from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.gallery import Gallery, GalleryImage, GalleryImageVersion
from app.models.tenant.initiative import Initiative
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.models.tenant.upload import Upload
from app.schemas.tenant.gallery import (
    GalleryCreate,
    GalleryImageBulkDelete,
    GalleryImageBulkDeleteResponse,
    GalleryImageListResponse,
    GalleryImageRead,
    GalleryImageUpdate,
    GalleryImageVersionRead,
    GalleryListResponse,
    GalleryRead,
    GalleryUpdate,
    serialize_gallery,
    serialize_gallery_image,
    serialize_gallery_image_version,
    serialize_gallery_image_versions,
    serialize_gallery_summary,
)
from app.schemas.tenant.initiative import InitiativeGroupedCountsResponse
from app.schemas.tenant.recent_view import RecentViewWrite
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.schemas.tenant.timeline import TimelineResponse
from app.services import permissions as permissions_service
from app.services import storage_config
from app.services.tenant import archive as archive_service
from app.services.tenant import attachments as attachments_service
from app.services.tenant import comments as comments_service
from app.services.tenant import galleries as galleries_service
from app.services.tenant import recent_views as recent_views_service
from app.services.tenant import search as search_service
from app.services.tenant import tags as tags_service
from app.services.tenant import timeline as timeline_service
from app.services.tenant import tool_listing

logger = logging.getLogger(__name__)

#: Which commit failures prove nothing was written.
#:
#: A constraint the server rejected is definitive: the transaction is gone,
#: and the blobs written for it are bytes nothing will ever reference. A lost
#: connection is not — Postgres may have committed and failed to say so — and
#: the two must not be treated alike, because they fail in opposite
#: directions. A blob left behind is waste somebody can sweep up; a blob
#: deleted out from under a committed row is a picture that is broken
#: forever.
_DEFINITIVELY_NOT_COMMITTED = (IntegrityError, DataError)


def _discard_orphans(urls: list[str], failure: BaseException) -> None:
    """Take back blobs a failed commit left behind — but only where the
    failure proves they are orphans. Anything ambiguous keeps its bytes and
    says so, so the waste is findable rather than the picture missing."""
    urls = [url for url in urls if url]
    if not urls:
        return
    if isinstance(failure, _DEFINITIVELY_NOT_COMMITTED):
        attachments_service.delete_uploads_by_urls(urls)
        return
    logger.warning(
        "Left %d uploaded blob(s) in place after an inconclusive commit "
        "failure (%s); they are orphaned only if the transaction did not "
        "land: %s",
        len(urls),
        type(failure).__name__,
        ", ".join(urls),
    )


#: How many pictures one page carries. A picture is a thumbnail and a few
#: fields, so this is generous — the point is that the grid fetches the next
#: page as somebody nears the bottom, not that anyone pages by hand.
IMAGE_PAGE_SIZE = 40
MAX_IMAGE_PAGE_SIZE = 200

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_initiative_for_gallery(
    session: RLSSessionDep,
    initiative_id: int,
) -> Initiative:
    stmt = (
        select(Initiative)
        .where(Initiative.id == initiative_id)
        .options(
            selectinload(Initiative.memberships),
            selectinload(Initiative.roles),
        )
    )
    initiative = (await session.exec(stmt)).one_or_none()
    if not initiative:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.NOT_FOUND,
        )
    return initiative


async def _refetch_gallery(
    session: RLSSessionDep, gallery_id: int, *, user_id: int
) -> Gallery:
    gallery = await galleries_service.get_gallery(
        session, gallery_id, populate_existing=True
    )
    if not gallery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GalleryMessages.NOT_FOUND,
        )
    await _annotate(session, [gallery])
    return gallery


async def _annotate(session: RLSSessionDep, galleries: list) -> None:
    """Everything a gallery row carries beyond its columns, one grouped query
    each for the page."""
    await tags_service.annotate_tags(session, galleries)
    await comments_service.annotate_comment_counts(
        session, galleries, column="gallery_id"
    )
    await galleries_service.annotate_image_counts(session, galleries)
    await galleries_service.annotate_covers(session, galleries)


async def _refetch_image(
    session: RLSSessionDep, gallery_id: int, image_id: int
) -> GalleryImage:
    image = await galleries_service.get_image(
        session, gallery_id, image_id, populate_existing=True
    )
    if image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GalleryMessages.IMAGE_NOT_FOUND,
        )
    await galleries_service.annotate_version_counts(session, [image])
    return image


async def _load_image(
    session: RLSSessionDep,
    gallery_id: int,
    image_id: int,
    current_user: User,
    guild_context: GuildContext,
    *,
    access: str = "read",
    require_owner: bool = False,
) -> tuple[Gallery, GalleryImage]:
    """The gallery, authorized at ``access``, and one of its pictures.

    Authorization is the gallery's: a picture is the gallery's content, and
    reaching one means reaching the other.
    """
    gallery = await resource_access.load_authorized(
        session,
        Tool.gallery,
        gallery_id,
        current_user,
        guild_context,
        access=access,
        require_owner=require_owner,
    )
    image = await galleries_service.get_image(session, gallery.id, image_id)
    if image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GalleryMessages.IMAGE_NOT_FOUND,
        )
    return gallery, image


async def _read_picture(
    session: RLSSessionDep,
    guild_context: GuildContext,
    file: UploadFile,
) -> tuple[bytes, str, str, int, int, galleries_service.Thumbnail | None]:
    """Read and validate an upload, then render its thumbnail.

    Returns the picture's bytes, content type, extension and pixel size, and
    the thumbnail (``None`` where one was not made). The size is Pillow's
    where a thumbnail was made — it has applied the EXIF orientation the
    header check cannot see — and the header's otherwise.
    """
    try:
        contents = await attachments_service.read_upload_bounded(
            file, galleries_service.MAX_IMAGE_BYTES
        )
    except attachments_service.FileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=GalleryMessages.IMAGE_TOO_LARGE,
        )
    try:
        header, extension = galleries_service.validate_image(contents)
    except galleries_service.EmptyImageError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GalleryMessages.IMAGE_EMPTY,
        )
    except galleries_service.InvalidImageError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GalleryMessages.INVALID_IMAGE,
        )

    # The second half of the gate: a header says what a file claims, and the
    # decode says whether it is one. A refusal here is the same 400 a bad
    # header gets — the caller sent something that is not a picture.
    try:
        thumbnail = galleries_service.render_thumbnail(contents)
    except galleries_service.InvalidImageError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GalleryMessages.INVALID_IMAGE,
        )
    width, height = (
        (thumbnail.source_width, thumbnail.source_height)
        if thumbnail is not None
        else (header.width, header.height)
    )
    incoming = len(contents) + (len(thumbnail.data) if thumbnail else 0)
    try:
        await attachments_service.enforce_storage_quota(
            session, guild_id=guild_context.guild_id, incoming_bytes=incoming
        )
    except attachments_service.StorageQuotaExceededError:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=AttachmentMessages.STORAGE_QUOTA_EXCEEDED,
        )
    return contents, header.content_type, extension, width, height, thumbnail


def _store_blob(
    session: RLSSessionDep,
    guild_context: GuildContext,
    user: User,
    contents: bytes,
    extension: str,
    content_type: str,
) -> str:
    """Write one blob to the guild's storage and record it in ``uploads``, the
    row the storage quota is summed from. Returns the served URL."""
    file_url = attachments_service.save_document_file(
        contents, extension, guild_context.guild_id, content_type=content_type
    )
    session.add(
        Upload(
            filename=file_url.split("/")[-1],
            guild_id=guild_context.guild_id,
            created_by=user.id,
            size_bytes=len(contents),
            content_type=content_type,
            content_hash=attachments_service.compute_content_hash(contents),
        )
    )
    return file_url


def _store_thumbnail(
    session: RLSSessionDep,
    guild_context: GuildContext,
    user: User,
    thumbnail: galleries_service.Thumbnail | None,
) -> str | None:
    if thumbnail is None:
        return None
    return _store_blob(
        session,
        guild_context,
        user,
        thumbnail.data,
        thumbnail.extension,
        thumbnail.content_type,
    )


async def _gallery_scope(
    session: RLSSessionDep,
    current_user: User,
    guild_context: GuildContext,
    *,
    initiative_id: Optional[int],
    search: Optional[str] = None,
) -> list | None:
    """Which galleries this reader may see — the guild, the feature switch,
    sharing, and the search box. ``None`` means the initiative exists but has
    the tool turned off."""
    conditions = [Gallery.guild_id == guild_context.guild_id]

    if initiative_id is not None:
        initiative = await session.get(Initiative, initiative_id)
        if initiative and not initiative.galleries_enabled:
            return None
        conditions.append(Gallery.initiative_id == initiative_id)
    else:
        conditions.append(
            Gallery.initiative_id.in_(
                select(Initiative.id).where(Initiative.galleries_enabled == True)  # noqa: E712
            )
        )

    conditions.append(
        permissions_service.listing_scope_clause(
            Tool.gallery,
            Gallery.id,
            current_user.id,
            guild_id=guild_context.guild_id,
            initiative_id=initiative_id,
        )
    )

    name_match = search_service.tool_search_clause(Tool.gallery, Gallery.id, search)
    if name_match is not None:
        conditions.append(name_match)

    return conditions


def _image_scope(
    gallery: Gallery,
    *,
    tag_ids: Optional[List[int]],
    search: Optional[str],
) -> list:
    """Which of a gallery's pictures a request is asking about.

    Sharing was settled on the gallery — reaching this means reaching every
    picture in it — so the legs here only narrow: the gallery, the tag
    filter, and the search box. Tags are ANY-of: "everything still awaiting a
    decision" is one tag, and asking for two is asking for either.
    """
    conditions = [GalleryImage.gallery_id == gallery.id]
    if tag_ids:
        conditions.append(
            GalleryImage.id.in_(
                tags_service.tagged_entity_ids(
                    tags_service.TAG_LINKS["gallery_image"], tuple(tag_ids)
                )
            )
        )
    if search and search.strip():
        needle = f"%{search.strip()}%"
        conditions.append(
            func.coalesce(GalleryImage.title, "").ilike(needle)
            | func.coalesce(GalleryImage.caption, "").ilike(needle)
            | func.coalesce(GalleryImage.original_filename, "").ilike(needle)
        )
    return conditions


# ---------------------------------------------------------------------------
# Galleries
# ---------------------------------------------------------------------------


@router.get("/", response_model=GalleryListResponse)
async def list_galleries(
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(
        default=None,
        description=(
            "Full-text match over the gallery's name and description, through "
            "the same index the search page reads."
        ),
    ),
    sort_by: Optional[str] = Query(
        default=None,
        description="Order by one of: name, initiative, updated_at. Omit for newest first.",
    ),
    sort_dir: Optional[str] = Query(default=None, description="asc (default) or desc."),
    archived: Optional[bool] = Query(
        default=None, description=archive_service.ARCHIVED_QUERY_DESCRIPTION
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=0, le=500),
) -> GalleryListResponse:
    """List galleries visible to the current user (guild admins see all)."""
    scope = await _gallery_scope(
        session, current_user, guild_context, initiative_id=initiative_id, search=search
    )
    if scope is None:
        return GalleryListResponse(
            items=[], total_count=0, page=page, page_size=page_size, has_next=False
        )

    scope = [*scope, archive_service.archive_filter_clause(Gallery, archived)]
    count_subq = select(Gallery.id).where(*scope).subquery()
    total_count = (
        await session.exec(select(func.count()).select_from(count_subq))
    ).one()

    stmt = (
        select(Gallery).where(*scope).options(*galleries_service.list_loader_options())
    )
    stmt = tool_listing.apply_tool_order(
        stmt,
        Gallery,
        sort_by,
        sort_dir,
        default=[Gallery.updated_at.desc(), Gallery.id.desc()],
    )
    if page_size > 0:
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    galleries = (await session.exec(stmt)).unique().all()
    await _annotate(session, list(galleries))

    items = [serialize_gallery_summary(g, user_id=current_user.id) for g in galleries]
    has_next = page_size > 0 and page * page_size < total_count
    return GalleryListResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=has_next,
    )


@router.get("/counts/by-initiative", response_model=InitiativeGroupedCountsResponse)
async def get_gallery_counts_by_initiative(
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> InitiativeGroupedCountsResponse:
    """Visible-gallery counts grouped by initiative, for the sidebar badges."""
    conditions = [
        Gallery.guild_id == guild_context.guild_id,
        Gallery.initiative_id.in_(
            select(Initiative.id).where(Initiative.galleries_enabled == True)  # noqa: E712
        ),
        permissions_service.granted_scope_clause(
            Tool.gallery,
            Gallery.id,
            current_user.id,
            guild_id=guild_context.guild_id,
        ),
    ]
    statement = (
        select(Gallery.initiative_id, func.count(Gallery.id))
        .where(*conditions)
        .group_by(Gallery.initiative_id)
    )
    rows = (await session.exec(statement)).all()
    return InitiativeGroupedCountsResponse(
        counts={initiative_id: count for initiative_id, count in rows}
    )


@router.get("/{gallery_id}", response_model=GalleryRead)
async def read_gallery(
    gallery_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
    include_deleted: IncludeDeletedDep = False,
) -> GalleryRead:
    gallery = await resource_access.load_authorized(
        session, Tool.gallery, gallery_id, current_user, guild_context
    )
    await _annotate(session, [gallery])
    return serialize_gallery(gallery, user_id=current_user.id)


@router.post("/", response_model=GalleryRead, status_code=status.HTTP_201_CREATED)
async def create_gallery(
    gallery_in: GalleryCreate,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> GalleryRead:
    """Create a gallery. Requires create_galleries permission on the
    initiative (or guild admin); the creator gets the owner grant."""
    initiative = await _get_initiative_for_gallery(session, gallery_in.initiative_id)
    if not initiative.galleries_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GalleryMessages.FEATURE_DISABLED,
        )
    await resource_access.require_create(
        session, Tool.gallery, initiative, current_user, guild_context
    )

    gallery = Gallery(
        guild_id=guild_context.guild_id,
        initiative_id=initiative.id,
        created_by=current_user.id,
        name=gallery_in.name.strip(),
        description=(gallery_in.description or "").strip() or None,
    )
    session.add(gallery)
    await session.flush()

    session.add(
        ResourceGrant(
            resource_type="gallery",
            resource_id=gallery.id,
            user_id=current_user.id,
            role_id=None,
            level=ResourceAccessLevel.owner,
            guild_id=guild_context.guild_id,
            initiative_id=initiative.id,
        )
    )
    await permissions_service.replace_resource_grants(
        session,
        resource_type="gallery",
        resource_id=gallery.id,
        guild_id=guild_context.guild_id,
        initiative_id=initiative.id,
        owner_id=current_user.id,
        grants=gallery_in.grants,
    )
    if gallery_in.tag_ids:
        await tags_service.set_entity_tags(
            session,
            tags_service.TOOL_TAG_LINKS[Tool.gallery],
            guild_id=guild_context.guild_id,
            entity_id=gallery.id,
            tag_ids=gallery_in.tag_ids,
        )
    await session.commit()
    hydrated = await _refetch_gallery(session, gallery.id, user_id=current_user.id)
    return serialize_gallery(hydrated, user_id=current_user.id)


@router.patch("/{gallery_id}", response_model=GalleryRead)
async def update_gallery(
    gallery_id: int,
    gallery_in: GalleryUpdate,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> GalleryRead:
    """Rename, describe, or choose the cover. Requires write access."""
    gallery = await resource_access.load_authorized(
        session, Tool.gallery, gallery_id, current_user, guild_context, access="write"
    )
    update_data = gallery_in.model_dump(exclude_unset=True)
    updated = False

    if "name" in update_data and update_data["name"] is not None:
        gallery.name = update_data["name"].strip()
        updated = True
    if "description" in update_data:
        gallery.description = (update_data["description"] or "").strip() or None
        updated = True
    if "cover_image_id" in update_data:
        cover_id = update_data["cover_image_id"]
        if cover_id is not None:
            cover = await galleries_service.get_image(session, gallery.id, cover_id)
            if cover is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=GalleryMessages.COVER_NOT_IN_GALLERY,
                )
        gallery.cover_image_id = cover_id
        updated = True

    if updated:
        gallery.updated_at = datetime.now(timezone.utc)
        session.add(gallery)
        await session.commit()

    hydrated = await _refetch_gallery(session, gallery.id, user_id=current_user.id)
    return serialize_gallery(hydrated, user_id=current_user.id)


@router.delete("/{gallery_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gallery(
    gallery_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> None:
    """Soft-delete a gallery and its pictures. Requires owner permission or
    guild admin."""
    from app.services.platform import guilds as guilds_service
    from app.services.tenant.soft_delete import soft_delete_entity

    gallery = await resource_access.load_authorized(
        session,
        Tool.gallery,
        gallery_id,
        current_user,
        guild_context,
        require_owner=True,
    )
    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    await soft_delete_entity(
        session,
        gallery,
        deleted_by_user_id=current_user.id,
        retention_days=retention_days,
    )
    await session.commit()


@router.put("/{gallery_id}/grants", response_model=GalleryRead)
async def set_gallery_grants(
    gallery_id: int,
    grants: List[ResourceGrantSchema],
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> GalleryRead:
    """Replace the gallery's entire sharing state in one call — the body is
    the full list of grants. Every non-owner grant is rebuilt from it; the
    owner is always preserved."""
    await resource_access.set_resource_grants(
        session, Tool.gallery, gallery_id, current_user, guild_context, grants
    )
    hydrated = await _refetch_gallery(session, gallery_id, user_id=current_user.id)
    return serialize_gallery(hydrated, user_id=current_user.id)


# ---------------------------------------------------------------------------
# Recent-view tracking (powers the layout header tabs bar)
# ---------------------------------------------------------------------------


@router.post("/{gallery_id}/view", response_model=RecentViewWrite)
async def record_gallery_view(
    gallery_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> RecentViewWrite:
    gallery = await resource_access.load_authorized(
        session, Tool.gallery, gallery_id, current_user, guild_context
    )
    record = await recent_views_service.record_view(
        session,
        user_id=current_user.id,
        entity_type="gallery",
        entity_id=gallery.id,
        persist=not guild_context.is_pam,
        limit=current_user.recent_tabs_limit,
    )
    return RecentViewWrite(
        entity_type="gallery",
        entity_id=gallery.id,
        last_viewed_at=record.last_viewed_at,
    )


@router.delete("/{gallery_id}/view", status_code=status.HTTP_204_NO_CONTENT)
async def clear_gallery_view(
    gallery_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> None:
    await resource_access.load_authorized(
        session, Tool.gallery, gallery_id, current_user, guild_context
    )
    await recent_views_service.clear_view(
        session,
        user_id=current_user.id,
        entity_type="gallery",
        entity_id=gallery_id,
    )


# ---------------------------------------------------------------------------
# Pictures
# ---------------------------------------------------------------------------


@router.get("/{gallery_id}/images", response_model=GalleryImageListResponse)
async def list_gallery_images(
    gallery_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
    tag_ids: Optional[List[int]] = Query(
        default=None, description="Only pictures carrying ANY of these tags."
    ),
    search: Optional[str] = Query(
        default=None, description="Match on title, caption or filename."
    ),
    oldest_first: bool = Query(
        default=False,
        description="Read the gallery in the order it was filled rather than newest first.",
    ),
    until: Optional[datetime] = Query(
        default=None,
        description=(
            "Start the list at this instant, inclusive, measured by upload "
            "time — which is what the list is ordered by. This is how a "
            "timeline jumps to a month without paging through everything "
            "since. It follows the list's own direction: newest first it is a "
            "ceiling and the page walks back from it, oldest first a floor "
            "and the page walks forward, so pair it with the matching end of "
            "the timeline bucket."
        ),
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=IMAGE_PAGE_SIZE, ge=1, le=MAX_IMAGE_PAGE_SIZE),
) -> GalleryImageListResponse:
    """One page of a gallery's pictures, newest first.

    Reaching the gallery is the whole gate: its pictures are its content, so
    there is no per-picture sharing to consult.
    """
    gallery = await resource_access.load_authorized(
        session, Tool.gallery, gallery_id, current_user, guild_context
    )
    conditions = _image_scope(gallery, tag_ids=tag_ids, search=search)
    if until is not None:
        conditions.append(
            galleries_service.anchored_clause(until, oldest_first=oldest_first)
        )

    count_subq = select(GalleryImage.id).where(*conditions).subquery()
    total_count = (
        await session.exec(select(func.count()).select_from(count_subq))
    ).one()

    stmt = (
        select(GalleryImage)
        .where(*conditions)
        .options(*galleries_service.image_loader_options())
        .order_by(*galleries_service.image_order(oldest_first=oldest_first))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    images = list((await session.exec(stmt)).unique().all())
    await tags_service.annotate_tags(session, images)
    await galleries_service.annotate_version_counts(session, images)
    return GalleryImageListResponse(
        items=[serialize_gallery_image(i) for i in images],
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=page * page_size < total_count,
    )


@router.get("/{gallery_id}/images/timeline", response_model=TimelineResponse)
async def get_gallery_image_timeline(
    gallery_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
    tag_ids: Optional[List[int]] = Query(default=None),
    search: Optional[str] = Query(default=None),
    tz: Optional[str] = Query(
        default=None,
        description=(
            "IANA zone the month boundaries are cut in, e.g. Pacific/Auckland. "
            "Defaults to UTC."
        ),
    ),
) -> TimelineResponse:
    """The months this gallery has pictures in, newest first — what the
    timeline rail is drawn from. Takes the same filters the list does, so the
    rail is a picture of the list as it currently stands."""
    try:
        zone = timeline_service.resolve_zone(tz)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=CommonMessages.UNKNOWN_TIMEZONE,
        ) from exc
    gallery = await resource_access.load_authorized(
        session, Tool.gallery, gallery_id, current_user, guild_context
    )
    conditions = _image_scope(gallery, tag_ids=tag_ids, search=search)
    return TimelineResponse(
        buckets=await timeline_service.month_buckets(
            session, date_expr=GalleryImage.created_at, conditions=conditions, tz=zone
        )
    )


@router.post(
    "/{gallery_id}/images",
    response_model=GalleryImageRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_gallery_image(
    gallery_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
    file: UploadFile = File(...),
    title: Optional[str] = Form(default=None),
    caption: Optional[str] = Form(default=None),
) -> GalleryImageRead:
    """Add one picture to a gallery. Requires write access.

    One picture per request, so a drop of forty files is forty requests the
    client can run a few at a time and report on one by one — and one that
    fails does not take the other thirty-nine with it.
    """
    gallery = await resource_access.load_authorized(
        session, Tool.gallery, gallery_id, current_user, guild_context, access="write"
    )
    # Pick up a backend/credential change saved in another worker before writing.
    await storage_config.ensure_storage_config_fresh(session)
    contents, mime, extension, width, height, thumb = await _read_picture(
        session, guild_context, file
    )
    file_url = _store_blob(
        session, guild_context, current_user, contents, extension, mime
    )
    thumbnail_url = _store_thumbnail(session, guild_context, current_user, thumb)

    now = datetime.now(timezone.utc)
    image = GalleryImage(
        guild_id=guild_context.guild_id,
        gallery_id=gallery.id,
        title=(title or "").strip()[:255] or None,
        caption=(caption or "").strip() or None,
        file_url=file_url,
        thumbnail_url=thumbnail_url,
        file_content_type=mime,
        file_size=len(contents),
        original_filename=file.filename,
        width=width,
        height=height,
        created_by=current_user.id,
        created_at=now,
        updated_at=now,
    )
    session.add(image)
    await session.flush()
    session.add(
        GalleryImageVersion(
            gallery_image_id=image.id,
            guild_id=guild_context.guild_id,
            version_number=1,
            file_url=file_url,
            thumbnail_url=thumbnail_url,
            file_content_type=mime,
            file_size=len(contents),
            original_filename=file.filename,
            width=width,
            height=height,
            created_by=current_user.id,
        )
    )
    # A gallery that just gained a picture has changed, and the list orders by
    # that.
    gallery.updated_at = now
    session.add(gallery)
    # The blobs are in storage and the rows that account for them are not
    # committed yet, so a failure here can strand them — see
    # :func:`_discard_orphans` for which failures that is true of.
    try:
        await session.commit()
    except Exception as failed:
        await session.rollback()
        _discard_orphans([file_url, thumbnail_url], failed)
        raise

    hydrated = await _refetch_image(session, gallery.id, image.id)
    return serialize_gallery_image(hydrated)


@router.get("/{gallery_id}/images/{image_id}", response_model=GalleryImageRead)
async def read_gallery_image(
    gallery_id: int,
    image_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> GalleryImageRead:
    _, image = await _load_image(
        session, gallery_id, image_id, current_user, guild_context
    )
    await galleries_service.annotate_version_counts(session, [image])
    return serialize_gallery_image(image)


@router.patch("/{gallery_id}/images/{image_id}", response_model=GalleryImageRead)
async def update_gallery_image(
    gallery_id: int,
    image_id: int,
    image_in: GalleryImageUpdate,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> GalleryImageRead:
    """Retitle, caption or retag a picture. Requires write access on the
    gallery."""
    gallery, image = await _load_image(
        session, gallery_id, image_id, current_user, guild_context, access="write"
    )
    update_data = image_in.model_dump(exclude_unset=True)
    if "title" in update_data:
        image.title = (update_data["title"] or "").strip() or None
    if "caption" in update_data:
        image.caption = (update_data["caption"] or "").strip() or None
    if "tag_ids" in update_data and update_data["tag_ids"] is not None:
        await tags_service.set_entity_tags(
            session,
            tags_service.TAG_LINKS["gallery_image"],
            guild_id=guild_context.guild_id,
            entity_id=image.id,
            tag_ids=update_data["tag_ids"],
        )
    image.updated_at = datetime.now(timezone.utc)
    session.add(image)
    await session.commit()
    hydrated = await _refetch_image(session, gallery.id, image.id)
    return serialize_gallery_image(hydrated)


@router.delete(
    "/{gallery_id}/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_gallery_image(
    gallery_id: int,
    image_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> None:
    """Send a picture to the trash. Requires write access on the gallery —
    removing a picture is editing the gallery, and it can be restored."""
    from app.services.platform import guilds as guilds_service
    from app.services.tenant.soft_delete import soft_delete_entity

    gallery, image = await _load_image(
        session, gallery_id, image_id, current_user, guild_context, access="write"
    )
    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    await soft_delete_entity(
        session,
        image,
        deleted_by_user_id=current_user.id,
        retention_days=retention_days,
    )
    if gallery.cover_image_id == image.id:
        # The list falls back to the newest picture rather than a trashed one.
        gallery.cover_image_id = None
        session.add(gallery)
    await session.commit()


@router.post(
    "/{gallery_id}/images/bulk-delete",
    response_model=GalleryImageBulkDeleteResponse,
)
async def bulk_delete_gallery_images(
    gallery_id: int,
    payload: GalleryImageBulkDelete,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> GalleryImageBulkDeleteResponse:
    """Send a selection of pictures to the trash in one transaction. Requires
    write access on the gallery — the same gate removing one asks — and
    refuses the whole request if any id is not one of this gallery's own,
    rather than trashing the rest and reporting a partial success."""
    from app.services.platform import guilds as guilds_service
    from app.services.tenant.soft_delete import soft_delete_entity

    gallery = await resource_access.load_authorized(
        session, Tool.gallery, gallery_id, current_user, guild_context, access="write"
    )
    ids = list(dict.fromkeys(payload.image_ids))
    images = list(
        (
            await session.exec(
                select(GalleryImage).where(
                    GalleryImage.gallery_id == gallery.id, GalleryImage.id.in_(ids)
                )
            )
        ).all()
    )
    if len(images) != len(ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GalleryMessages.IMAGE_NOT_FOUND,
        )
    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    for image in images:
        await soft_delete_entity(
            session,
            image,
            deleted_by_user_id=current_user.id,
            retention_days=retention_days,
        )
    if gallery.cover_image_id in ids:
        gallery.cover_image_id = None
        session.add(gallery)
    await session.commit()
    return GalleryImageBulkDeleteResponse(deleted_count=len(images))


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


@router.post(
    "/{gallery_id}/images/{image_id}/versions",
    response_model=GalleryImageVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_gallery_image_version(
    gallery_id: int,
    image_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
    file: UploadFile = File(...),
) -> GalleryImageVersionRead:
    """Replace a picture with a new rendition, keeping the old one as history.
    Requires write access on the gallery."""
    gallery, image = await _load_image(
        session, gallery_id, image_id, current_user, guild_context, access="write"
    )
    await storage_config.ensure_storage_config_fresh(session)
    contents, mime, extension, width, height, thumb = await _read_picture(
        session, guild_context, file
    )
    file_url = _store_blob(
        session, guild_context, current_user, contents, extension, mime
    )
    thumbnail_url = _store_thumbnail(session, guild_context, current_user, thumb)

    version = GalleryImageVersion(
        gallery_image_id=image.id,
        guild_id=guild_context.guild_id,
        version_number=await galleries_service.next_version_number(session, image.id),
        file_url=file_url,
        thumbnail_url=thumbnail_url,
        file_content_type=mime,
        file_size=len(contents),
        original_filename=file.filename,
        width=width,
        height=height,
        created_by=current_user.id,
    )
    session.add(version)
    galleries_service.mirror_version(image, version)
    image.updated_at = datetime.now(timezone.utc)
    session.add(image)
    try:
        await session.commit()
    except Exception as failed:
        await session.rollback()
        _discard_orphans([file_url, thumbnail_url], failed)
        if isinstance(failed, IntegrityError):
            # A concurrent upload claimed the same version number between the
            # MAX() read and this commit. Ask the caller to retry rather than
            # surfacing a 500.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=GalleryMessages.VERSION_CONFLICT,
            ) from failed
        raise
    await session.refresh(version)
    return serialize_gallery_image_version(version, is_current=True)


@router.get(
    "/{gallery_id}/images/{image_id}/versions",
    response_model=List[GalleryImageVersionRead],
)
async def list_gallery_image_versions(
    gallery_id: int,
    image_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> List[GalleryImageVersionRead]:
    """Every stored rendition of a picture, newest first."""
    _, image = await _load_image(
        session, gallery_id, image_id, current_user, guild_context
    )
    result = await session.exec(
        select(GalleryImageVersion)
        .where(GalleryImageVersion.gallery_image_id == image.id)
        .order_by(GalleryImageVersion.version_number.desc())
    )
    return serialize_gallery_image_versions(list(result.all()))


@router.delete(
    "/{gallery_id}/images/{image_id}/versions/{version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_gallery_image_version(
    gallery_id: int,
    image_id: int,
    version_id: int,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> None:
    """Delete one rendition of a picture. Owner only. Deleting the current
    one promotes the previous; deleting the last is refused — remove the
    picture instead."""
    _, image = await _load_image(
        session, gallery_id, image_id, current_user, guild_context, require_owner=True
    )
    # Serialize concurrent deletes on the same picture: two owner DELETEs that
    # both observe two versions could otherwise each remove one and leave none.
    await session.exec(
        select(GalleryImage).where(GalleryImage.id == image.id).with_for_update()
    )
    versions = list(
        (
            await session.exec(
                select(GalleryImageVersion)
                .where(GalleryImageVersion.gallery_image_id == image.id)
                .order_by(GalleryImageVersion.version_number.desc())
            )
        ).all()
    )
    if len(versions) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GalleryMessages.CANNOT_DELETE_LAST_VERSION,
        )
    target = next((v for v in versions if v.id == version_id), None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GalleryMessages.VERSION_NOT_FOUND,
        )
    is_current = target.version_number == versions[0].version_number
    doomed_urls = galleries_service.image_blob_urls(target)

    await session.delete(target)
    await session.flush()
    await session.exec(
        sa_delete(Upload).where(
            Upload.filename.in_([u.split("/")[-1] for u in doomed_urls])
        )
    )
    if is_current:
        promoted = next((v for v in versions if v.id != version_id), None)
        if promoted is not None:
            galleries_service.mirror_version(image, promoted)
            image.updated_at = datetime.now(timezone.utc)
            session.add(image)
    await session.commit()
    # Blobs after the rows, so a failed commit does not orphan files.
    attachments_service.delete_uploads_by_urls(doomed_urls)

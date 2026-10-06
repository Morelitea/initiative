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

from datetime import datetime, timezone
from typing import Annotated, Any, List, Optional, cast

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
from sqlalchemy import func
from sqlmodel import select

from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    GuildContextDep,
    IncludeDeletedDep,
    RLSSessionDep,
    get_current_active_user,
    plugin_scope,
)
from app.core.messages import (
    AttachmentMessages,
    GalleryMessages,
)
from app.core.tools import Tool
from app.db.query import apply_pagination, build_paginated_response
from app.models.platform.user import User
from app.models.tenant.gallery import Gallery, GalleryImage, GalleryImageVersion
from app.schemas.tenant.gallery import (
    GalleryCreate,
    GalleryImageBulkDelete,
    GalleryImageBulkDeleteResponse,
    GalleryImageListResponse,
    GalleryImageRead,
    GalleryImageUpdate,
    GalleryImageVersionRead,
    GalleryRead,
    GalleryUpdate,
    serialize_gallery_image,
)
from app.schemas.tenant.tool import serialize_tool
from app.schemas.tenant.timeline import TimelineResponse
from app.services.permissions import Action
from app.services import storage_config
from app.services.tenant import attachments as attachments_service
from app.services.tenant import file_versions
from app.services.tenant import galleries as galleries_service
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service
from app.services.tenant import timeline as timeline_service

#: How many pictures one page carries. A picture is a thumbnail and a few
#: fields, so this is generous — the point is that the grid fetches the next
#: page as somebody nears the bottom, not that anyone pages by hand.
IMAGE_PAGE_SIZE = 40
MAX_IMAGE_PAGE_SIZE = 200

router = APIRouter(route_class=ActorRoute)

#: The routes an installed plug-in may call, under the galleries scopes.
GalleriesRead = Annotated[ActorContext, Depends(plugin_scope("galleries:read"))]
GalleriesWrite = Annotated[ActorContext, Depends(plugin_scope("galleries:write"))]
CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _refetch_image(session: RLSSessionDep, image_id: int) -> GalleryImage:
    image = await resource_access.reload_child(session, GalleryImage, image_id)
    await galleries_service.annotate_version_counts(session, [image])
    return image


async def _read_picture(
    session: RLSSessionDep,
    guild_context: ActorContext,
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


async def _store_blob(
    session: RLSSessionDep,
    guild_context: ActorContext,
    gallery: Gallery,
    contents: bytes,
    extension: str,
    content_type: str,
) -> str:
    """Store one blob of ``gallery``'s and return its served URL."""
    return await attachments_service.store_upload(
        session,
        guild_id=guild_context.guild_id,
        filename=attachments_service.new_upload_filename(extension),
        data=contents,
        content_type=content_type,
        created_by=guild_context.user_id,
        initiative_id=gallery.initiative_id,
    )


async def _store_picture(
    session: RLSSessionDep,
    guild_context: ActorContext,
    gallery: Gallery,
    file: UploadFile,
) -> dict[str, Any]:
    """Read, check and store an uploaded picture and its thumbnail, and return
    the version columns they were stored as."""
    # Pick up a backend/credential change saved in another worker before writing.
    await storage_config.ensure_storage_config_fresh(session)
    contents, mime, extension, width, height, thumb = await _read_picture(
        session, guild_context, file
    )
    file_url = await _store_blob(
        session, guild_context, gallery, contents, extension, mime
    )
    thumbnail_url = (
        await _store_blob(
            session,
            guild_context,
            gallery,
            thumb.data,
            thumb.extension,
            thumb.content_type,
        )
        if thumb is not None
        else None
    )
    return {
        "file_url": file_url,
        "thumbnail_url": thumbnail_url,
        "file_content_type": mime,
        "file_size": len(contents),
        "original_filename": file.filename,
        "width": width,
        "height": height,
    }


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
            | GalleryImage.current_version.has(
                GalleryImageVersion.original_filename.ilike(needle)
            )
        )
    return conditions


# ---------------------------------------------------------------------------
# Galleries
# ---------------------------------------------------------------------------


@router.get("/{gallery_id}", response_model=GalleryRead)
async def read_gallery(
    gallery_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: GalleriesRead,
    include_deleted: IncludeDeletedDep = False,
) -> GalleryRead:
    gallery = await resource_access.load_authorized(
        session, Tool.gallery, gallery_id, current_user, guild_context, hydrated=True
    )
    return serialize_tool(
        GalleryRead, gallery, user_id=guild_context.user_id, context=guild_context
    )


@router.post("/", response_model=GalleryRead, status_code=status.HTTP_201_CREATED)
async def create_gallery(
    gallery_in: GalleryCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: GalleriesWrite,
) -> GalleryRead:
    """Create a gallery. Requires create_galleries permission on the
    initiative (or guild admin); the creator gets the owner grant."""
    resource_access.refuse_plugin_sharing(guild_context, gallery_in, "grants")
    initiative = await resource_access.prepare_create(
        session, Tool.gallery, gallery_in.initiative_id, current_user, guild_context
    )

    gallery = Gallery(
        initiative_id=initiative.id,
        created_by=guild_context.user_id,
        name=gallery_in.name.strip(),
        description=(gallery_in.description or "").strip() or None,
    )
    session.add(gallery)
    await session.flush()

    await resource_access.grant_initial_sharing(
        session,
        guild_context,
        Tool.gallery,
        user=current_user,
        resource_id=gallery.id,
        initiative_id=initiative.id,
        payload=gallery_in,
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
    await attachments_service.claim_uploads(session, gallery)
    await properties_service.write_on_create(session, gallery, gallery_in.properties)
    await session.commit()
    return await read_after_write(session, gallery.id, current_user, guild_context)


@router.patch("/{gallery_id}", response_model=GalleryRead)
async def update_gallery(
    gallery_id: int,
    gallery_in: GalleryUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: GalleriesWrite,
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
            cover = await session.exec(
                select(GalleryImage.id).where(
                    GalleryImage.id == cover_id, GalleryImage.gallery_id == gallery.id
                )
            )
            if cover.one_or_none() is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=GalleryMessages.COVER_NOT_IN_GALLERY,
                )
        gallery.cover_image_id = cover_id
        updated = True

    if updated:
        gallery.updated_at = datetime.now(timezone.utc)
        session.add(gallery)
        await attachments_service.claim_uploads(session, gallery)
        await session.commit()

    return await read_after_write(session, gallery.id, current_user, guild_context)


async def read_after_write(
    session: RLSSessionDep,
    gallery_id: int,
    user: Optional[User],
    guild_context: ActorContext,
) -> GalleryRead:
    """The gallery a write answers with: re-read after the commit, serialized.

    Registered in ``tool_lists.TOOL_LISTS`` so the shared sharing route
    (``tool_grants.py``) answers in this tool's own shape.
    """
    hydrated = await galleries_service.get_gallery_hydrated(
        session, gallery_id, populate_existing=True
    )
    if hydrated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=Tool.gallery.not_found_code,
        )
    return serialize_tool(
        GalleryRead, hydrated, user_id=guild_context.user_id, context=guild_context
    )


# ---------------------------------------------------------------------------
# Pictures
# ---------------------------------------------------------------------------


@router.get("/{gallery_id}/images", response_model=GalleryImageListResponse)
async def list_gallery_images(
    gallery_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: GalleriesRead,
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

    stmt = apply_pagination(
        select(GalleryImage)
        .where(*conditions)
        .options(*galleries_service.image_loader_options())
        .order_by(*galleries_service.image_order(oldest_first=oldest_first)),
        page,
        page_size,
    )
    images = list((await session.exec(stmt)).unique().all())
    await tags_service.annotate_tags(session, images)
    await properties_service.annotate_properties(session, images)
    await galleries_service.annotate_version_counts(session, images)
    items = [serialize_gallery_image(i, context=guild_context) for i in images]
    return GalleryImageListResponse(
        **build_paginated_response(items, total_count, page, page_size)
    )


@router.get("/{gallery_id}/images/timeline", response_model=TimelineResponse)
async def get_gallery_image_timeline(
    gallery_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: GalleriesRead,
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
    gallery = await resource_access.load_authorized(
        session, Tool.gallery, gallery_id, current_user, guild_context
    )
    conditions = _image_scope(gallery, tag_ids=tag_ids, search=search)
    return TimelineResponse(
        buckets=await timeline_service.month_buckets(
            session, date_expr=GalleryImage.created_at, conditions=conditions, tz=tz
        )
    )


@router.post(
    "/{gallery_id}/images",
    response_model=GalleryImageRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_gallery_image(
    gallery_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: GalleriesWrite,
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
    stored = await _store_picture(session, guild_context, gallery, file)

    now = datetime.now(timezone.utc)
    image = GalleryImage(
        gallery_id=gallery.id,
        title=(title or "").strip()[:255] or None,
        caption=(caption or "").strip() or None,
        created_by=guild_context.user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(image)
    await session.flush()
    version = await file_versions.add_version(
        session, image, created_by=guild_context.user_id, **stored
    )
    # A gallery that just gained a picture has changed, and the list orders by
    # that.
    gallery.updated_at = now
    session.add(gallery)
    await file_versions.commit_version(session, guild_context.guild_id, version)

    hydrated = await _refetch_image(session, image.id)
    return serialize_gallery_image(hydrated, context=guild_context)


@router.get("/{gallery_id}/images/{image_id}", response_model=GalleryImageRead)
async def read_gallery_image(
    gallery_id: int,
    image_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: GalleriesRead,
) -> GalleryImageRead:
    image = await resource_access.load_child(
        session, GalleryImage, image_id, parent_id=gallery_id
    )
    await galleries_service.annotate_version_counts(session, [image])
    return serialize_gallery_image(image, context=guild_context)


@router.patch("/{gallery_id}/images/{image_id}", response_model=GalleryImageRead)
async def update_gallery_image(
    gallery_id: int,
    image_id: int,
    image_in: GalleryImageUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: GalleriesWrite,
) -> GalleryImageRead:
    """Retitle, caption, retag or set the properties of a picture. Requires
    write access on the gallery."""
    image = await resource_access.load_child(
        session, GalleryImage, image_id, access="write", parent_id=gallery_id
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
    await properties_service.write_on_update(session, image, image_in.properties)
    image.updated_at = datetime.now(timezone.utc)
    session.add(image)
    await attachments_service.claim_uploads(session, image)
    await session.commit()
    hydrated = await _refetch_image(session, image.id)
    return serialize_gallery_image(hydrated, context=guild_context)


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
    from app.services.tenant.soft_delete import trash

    image = await resource_access.load_child(
        session, GalleryImage, image_id, access="write", parent_id=gallery_id
    )
    gallery = cast(Gallery, image.gallery)
    await trash(
        session,
        image,
        deleted_by_user_id=guild_context.user_id,
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
    retention_days = await guilds_service.get_guild_retention_days(session)
    for image in images:
        await soft_delete_entity(
            session,
            image,
            deleted_by_user_id=guild_context.user_id,
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
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: GalleriesWrite,
    file: UploadFile = File(...),
) -> GalleryImageVersionRead:
    """Replace a picture with a new rendition, keeping the old one as history.
    Requires write access on the gallery."""
    image = await resource_access.load_child(
        session, GalleryImage, image_id, access="write", parent_id=gallery_id
    )
    stored = await _store_picture(session, guild_context, image.gallery, file)
    version = await file_versions.add_version(
        session, image, created_by=guild_context.user_id, **stored
    )
    await file_versions.commit_version(
        session,
        guild_context.guild_id,
        version,
        conflict=GalleryMessages.VERSION_CONFLICT,
    )
    return file_versions.read(GalleryImageVersionRead, version, image)


@router.get(
    "/{gallery_id}/images/{image_id}/versions",
    response_model=List[GalleryImageVersionRead],
)
async def list_gallery_image_versions(
    gallery_id: int,
    image_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: GalleriesRead,
) -> List[GalleryImageVersionRead]:
    """Every stored rendition of a picture, newest first."""
    image = await resource_access.load_child(
        session, GalleryImage, image_id, parent_id=gallery_id
    )
    return [
        file_versions.read(GalleryImageVersionRead, version, image)
        for version in await file_versions.versions_newest_first(session, image)
    ]


@router.delete(
    "/{gallery_id}/images/{image_id}/versions/{version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_gallery_image_version(
    gallery_id: int,
    image_id: int,
    version_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: GalleriesWrite,
) -> None:
    """Delete one rendition of a picture. Owner only. Deleting the current
    one promotes the previous; deleting the last is refused — remove the
    picture instead."""
    image = await resource_access.load_child(
        session, GalleryImage, image_id, action=Action.delete, parent_id=gallery_id
    )
    deleted = await file_versions.delete_version(
        session, image, version_id, GalleryMessages
    )
    await session.commit()
    await file_versions.release_files(guild_context.guild_id, deleted)

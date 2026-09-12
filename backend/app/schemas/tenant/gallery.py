from __future__ import annotations

from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from pydantic import ConfigDict, Field

from app.core.tools import Tool
from app.schemas.base import SanitizedBaseModel, TitleStr
from app.schemas.tenant.archive import ArchiveState
from app.schemas.tenant.comment import CommentAuthor
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.schemas.tenant.tag import TagSummary, annotated_tags

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.gallery import Gallery, GalleryImage, GalleryImageVersion


class GalleryBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)


class GalleryCreate(GalleryBase):
    name: TitleStr = Field(..., min_length=1, max_length=255)
    initiative_id: int
    tag_ids: Optional[List[int]] = None
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    # A gallery defaults to readable by the whole initiative: pictures are put
    # somewhere to be seen.
    grants: List[ResourceGrantSchema] = Field(
        default_factory=lambda: [
            ResourceGrantSchema(all_initiative_members=True, level="read")
        ]
    )


class GalleryUpdate(SanitizedBaseModel):
    name: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    #: The picture that stands for the gallery in a list. ``null`` clears the
    #: choice and the list falls back to the newest picture; a set value has
    #: to be one of this gallery's own.
    cover_image_id: Optional[int] = None


class GalleryCover(SanitizedBaseModel):
    """What a list draws for a gallery: one picture, at whichever size it has."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    image_id: int
    file_url: str
    thumbnail_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


class GallerySummary(GalleryBase, ArchiveState):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    initiative_id: int
    guild_id: int
    created_by: int
    created_at: datetime
    updated_at: datetime
    #: How many pictures it holds. Served with the row so a list of galleries
    #: can say so without a request per card.
    image_count: int = 0
    #: The chosen cover, or ``null`` where none was chosen. ``cover`` is that
    #: picture; ``preview`` is the newest few, which is what a list draws —
    #: as a small grid — for a gallery nobody chose a cover for.
    cover_image_id: Optional[int] = None
    cover: Optional[GalleryCover] = None
    preview: List[GalleryCover] = Field(default_factory=list)
    my_permission_level: Optional[str] = None
    # When false this entity's comment thread is off — the UI renders none
    # and the API refuses to read or post one.
    comments_enabled: bool = True
    comment_count: int = 0
    tags: List[TagSummary] = Field(default_factory=list)
    grants: List[ResourceGrantSchema] = Field(default_factory=list)


class GalleryRead(GallerySummary):
    """A gallery on its own page. The same shape as its summary: the pictures
    are paged separately, because a gallery is browsed rather than read."""


class GalleryListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[GallerySummary]
    total_count: int
    page: int
    page_size: int
    has_next: bool


class GalleryImageUpdate(SanitizedBaseModel):
    title: Optional[TitleStr] = Field(default=None, max_length=255)
    caption: Optional[str] = Field(default=None, max_length=2000)
    tag_ids: Optional[List[int]] = None


class GalleryImageBulkDelete(SanitizedBaseModel):
    """The pictures to send to the trash together — a selection on the wall."""

    image_ids: List[int] = Field(min_length=1, max_length=500)


class GalleryImageBulkDeleteResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    deleted_count: int


class GalleryImageRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    gallery_id: int
    guild_id: int
    #: What somebody called it, if they did. Surfaces fall back to
    #: ``original_filename``, which is at least what the uploader called it.
    title: Optional[str] = None
    caption: Optional[str] = None
    #: The current version's file, served at ``/uploads/{guild}/{name}``.
    file_url: str
    #: A smaller rendition for grids, or ``null`` where none was made — the
    #: grid then shows the picture itself.
    thumbnail_url: Optional[str] = None
    file_content_type: Optional[str] = None
    file_size: Optional[int] = None
    original_filename: Optional[str] = None
    #: Pixel size, read from the file's header at upload. What lets a layout
    #: reserve the right space for a picture before its bytes arrive.
    width: Optional[int] = None
    height: Optional[int] = None
    created_by: int
    uploader: Optional[CommentAuthor] = None
    created_at: datetime
    updated_at: datetime
    #: How many renditions have been uploaded. One for most pictures; more
    #: than one is what says "this went through rounds".
    version_count: int = 1
    tags: List[TagSummary] = Field(default_factory=list)


class GalleryImageListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[GalleryImageRead]
    total_count: int
    page: int
    page_size: int
    has_next: bool


class GalleryImageVersionRead(SanitizedBaseModel):
    """One stored rendition of a picture."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    version_number: int
    file_url: str
    thumbnail_url: Optional[str] = None
    file_content_type: Optional[str] = None
    file_size: Optional[int] = None
    original_filename: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    created_by: int
    created_at: datetime
    is_current: bool = False


def gallery_cover(image: "GalleryImage | None") -> GalleryCover | None:
    if image is None or image.id is None:
        return None
    return GalleryCover(
        image_id=image.id,
        file_url=image.file_url,
        thumbnail_url=image.thumbnail_url,
        width=image.width,
        height=image.height,
    )


def serialize_gallery_summary(
    gallery: "Gallery", *, user_id: Optional[int] = None
) -> GallerySummary:
    # Local import avoids a schema -> service import cycle.
    from app.services.permissions import client_access, serialize_grants

    return GallerySummary(
        id=gallery.id,
        name=gallery.name,
        description=gallery.description,
        initiative_id=gallery.initiative_id,
        guild_id=gallery.guild_id,
        created_by=gallery.created_by,
        created_at=gallery.created_at,
        updated_at=gallery.updated_at,
        image_count=int(getattr(gallery, "image_count", 0)),
        cover_image_id=gallery.cover_image_id,
        # Stamped by the service; a row that was never annotated shows its
        # chosen cover alone and no preview.
        cover=gallery_cover(getattr(gallery, "_cover", None) or gallery.cover_image),
        preview=[
            cover
            for cover in (
                gallery_cover(image) for image in getattr(gallery, "_preview", [])
            )
            if cover is not None
        ],
        archived_at=gallery.archived_at,
        **client_access(Tool.gallery, gallery, user_id),
        comments_enabled=gallery.comments_enabled,
        comment_count=getattr(gallery, "comment_count", 0),
        tags=annotated_tags(gallery),
        grants=serialize_grants(gallery),
    )


def serialize_gallery(
    gallery: "Gallery", *, user_id: Optional[int] = None
) -> GalleryRead:
    return GalleryRead(
        **serialize_gallery_summary(gallery, user_id=user_id).model_dump()
    )


def serialize_gallery_image(image: "GalleryImage") -> GalleryImageRead:
    return GalleryImageRead(
        id=image.id,
        gallery_id=image.gallery_id,
        guild_id=image.guild_id,
        title=image.title,
        caption=image.caption,
        file_url=image.file_url,
        thumbnail_url=image.thumbnail_url,
        file_content_type=image.file_content_type,
        file_size=image.file_size,
        original_filename=image.original_filename,
        width=image.width,
        height=image.height,
        created_by=image.created_by,
        uploader=(
            CommentAuthor.model_validate(image.uploader)
            if image.uploader is not None
            else None
        ),
        created_at=image.created_at,
        updated_at=image.updated_at,
        version_count=int(getattr(image, "version_count", 1)),
        tags=annotated_tags(image),
    )


def serialize_gallery_image_version(
    version: "GalleryImageVersion", *, is_current: bool
) -> GalleryImageVersionRead:
    return GalleryImageVersionRead(
        id=version.id,
        version_number=version.version_number,
        file_url=version.file_url,
        thumbnail_url=version.thumbnail_url,
        file_content_type=version.file_content_type,
        file_size=version.file_size,
        original_filename=version.original_filename,
        width=version.width,
        height=version.height,
        created_by=version.created_by,
        created_at=version.created_at,
        is_current=is_current,
    )


def serialize_gallery_image_versions(
    versions: List["GalleryImageVersion"],
) -> List[GalleryImageVersionRead]:
    """Serialize versions, marking the highest ``version_number`` as current."""
    if not versions:
        return []
    current_number = max(v.version_number for v in versions)
    return [
        serialize_gallery_image_version(
            v, is_current=v.version_number == current_number
        )
        for v in versions
    ]

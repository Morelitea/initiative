from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional, TYPE_CHECKING

from pydantic import ConfigDict, Field

from app.schemas.base import SanitizedBaseModel, TitleStr
from app.schemas.query import PageMeta
from app.schemas.tenant.comment import CommentAuthor
from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable
from app.schemas.tenant.tag import TagSummary, annotated_tags
from app.schemas.tenant.tool import ToolSummaryBase

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext, GuildContext
    from app.models.tenant.gallery import GalleryImage, GalleryImageVersion


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
    grants: List[ResourceGrantSchema] = Field(default_factory=initiative_readable)


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


class GallerySummary(GalleryBase, ToolSummaryBase):
    #: How many pictures it holds. Served with the row so a list of galleries
    #: can say so without a request per card.
    image_count: int = 0
    #: The chosen cover, or ``null`` where none was chosen. ``cover`` is that
    #: picture; ``preview`` is the newest few, which is what a list draws —
    #: as a small grid — for a gallery nobody chose a cover for.
    cover_image_id: Optional[int] = None
    cover: Optional[GalleryCover] = None
    preview: List[GalleryCover] = Field(default_factory=list)
    comment_count: int = 0

    @classmethod
    def derived_fields(
        cls, row: Any, *, context: ActorContext, user_id: Optional[int]
    ) -> dict[str, Any]:
        # Stamped by the service; a row that was never annotated shows its
        # chosen cover alone and no preview.
        previews = (gallery_cover(image) for image in getattr(row, "_preview", []))
        return {
            "cover": gallery_cover(getattr(row, "_cover", None) or row.cover_image),
            "preview": [cover for cover in previews if cover is not None],
        }


class GalleryRead(GallerySummary):
    """A gallery on its own page. The same shape as its summary: the pictures
    are paged separately, because a gallery is browsed rather than read."""


class GalleryListResponse(PageMeta):
    items: List[GallerySummary]


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


class GalleryImageListResponse(PageMeta):
    items: List[GalleryImageRead]


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


def serialize_gallery_image(
    image: "GalleryImage", *, context: GuildContext
) -> GalleryImageRead:
    return GalleryImageRead(
        id=image.id,
        gallery_id=image.gallery_id,
        guild_id=context.guild_id,
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

"""Gallery service — loaders, the annotations a list needs, and the picture
upload rules.

A gallery is a shareable DAC resource (``resource_type='gallery'``) holding
pictures as child rows. What is genuinely this tool's own is in two places:

* **What a picture is allowed to be.** Two gates, cheapest first.
  :func:`validate_image` reads the file's header — the format, the pixel size
  — which is a few bounds-checked slices rather than a decoder. Raster only,
  and no SVG: a picture here is drawn in an ``<img>``, and an SVG is a
  document rather than a picture. Then :func:`render_thumbnail` decodes it,
  and only a body the decoder reads is stored. A header says what a file
  claims; the decode is what confirms it.
* **The order.** Newest first, always. A gallery is a record of what arrived,
  and a design round is read in the order it happened; the timeline view
  groups the same order by day.

Thumbnails are made here, at upload, with Pillow — the one place in the
request path that decodes pixels, under a pixel ceiling. A picture small
enough not to need one is stored without it and the grid shows the picture
itself; a picture that cannot be decoded at all is not stored.
"""

import io
import logging
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import aliased, selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.image_headers import ImageHeader, read_image_header
from app.core.tools import Tool
from app.models.tenant.gallery import Gallery, GalleryImage, GalleryImageVersion
from app.models.tenant.initiative import Initiative
from app.models.tenant.resource_grant import ResourceGrant
from app.services.tenant import tags as tags_service

#: How big a picture may be. Larger than a document image (10 MB): a gallery
#: is where exported canvases and store art go, and those are big.
MAX_IMAGE_BYTES = 25 * 1024 * 1024

#: The longest side of a thumbnail. Wide enough for a masonry column on a
#: large screen at 2x, small enough that a grid of forty is a few hundred KB.
THUMBNAIL_EDGE = 640

#: The most pixels a picture may hold before the decoder refuses it. Well
#: above any canvas or photo, well below what would exhaust a worker's memory
#: decompressing it — the default Pillow ceiling, stated here so it is a
#: decision rather than an inheritance.
MAX_IMAGE_PIXELS = 89_478_485

logger = logging.getLogger(__name__)

#: What a picture in a gallery may be. Exactly what ``read_image_header``
#: recognizes: the raster formats an ``<img>`` draws.
_EXTENSIONS: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class InvalidImageError(ValueError):
    """The bytes are not a raster image this gallery can show."""


class EmptyImageError(ValueError):
    """Nothing was uploaded."""


def validate_image(contents: bytes) -> tuple[ImageHeader, str]:
    """Identify an upload from its header, or refuse it.

    Returns the header (content type, pixel size) and the extension the
    stored file takes. The client's ``Content-Type`` and filename are not
    consulted: what the bytes are is the only fact that matters, and a
    mislabelled PNG is still a PNG.
    """
    if not contents:
        raise EmptyImageError()
    header = read_image_header(contents)
    if header is None or header.content_type not in _EXTENSIONS:
        raise InvalidImageError()
    return header, _EXTENSIONS[header.content_type]


@dataclass(frozen=True)
class Thumbnail:
    """A smaller rendition of a picture, and the size of the picture it was
    made from — read after EXIF orientation was applied, which the header
    check cannot see."""

    data: bytes
    content_type: str
    extension: str
    source_width: int
    source_height: int


def render_thumbnail(contents: bytes) -> Thumbnail | None:
    """Render a thumbnail, or ``None`` where one is not needed.

    WebP, because it is the smallest thing every browser draws. A picture no
    larger than the thumbnail edge needs none: the grid would only be shown a
    copy of what it already has. Animation is dropped — a thumbnail is a
    still.

    Raises :class:`InvalidImageError` for a body the decoder will not read —
    truncated, corrupt, or more pixels than :data:`MAX_IMAGE_PIXELS`. The
    caller refuses the upload on that: a picture nothing can decode is a
    picture nothing can draw.

    Decoding is the one thing in the request path that touches pixels, so it
    is boxed — the decompression-bomb warning is raised as an error, and
    everything the decoder can object to leaves by the same door.
    """
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
            with Image.open(io.BytesIO(contents)) as opened:
                image = ImageOps.exif_transpose(opened) or opened
                source_width, source_height = image.size
                if max(source_width, source_height) <= THUMBNAIL_EDGE:
                    return None
                image.thumbnail(
                    (THUMBNAIL_EDGE, THUMBNAIL_EDGE), Image.Resampling.LANCZOS
                )
                # WebP takes RGB or RGBA; palette and greyscale-with-alpha
                # images are converted rather than refused.
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                out = io.BytesIO()
                image.save(out, format="WEBP", quality=80, method=4)
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        ValueError,
    ) as exc:
        logger.info("Refused an upload the decoder would not read: %s", exc)
        raise InvalidImageError() from exc
    return Thumbnail(
        data=out.getvalue(),
        content_type="image/webp",
        extension=".webp",
        source_width=source_width,
        source_height=source_height,
    )


def list_loader_options() -> list:
    """Eager-load what a gallery *list* row needs: its sharing, its
    initiative's memberships (the DAC engine reads them), its tags, and the
    cover it chose."""
    return [
        selectinload(Gallery.grants).selectinload(ResourceGrant.role),
        selectinload(Gallery.initiative).selectinload(Initiative.memberships),
        selectinload(Gallery.cover_image),
        tags_service.TOOL_TAG_LINKS[Tool.gallery].load_options(),
    ]


def gallery_loader_options() -> list:
    """Eager-load everything gallery serialization + authorization needs."""
    return list_loader_options()


def image_loader_options() -> list:
    """Eager-load what a picture needs to be drawn: who uploaded it, its tags."""
    return [
        selectinload(GalleryImage.uploader),
        tags_service.TAG_LINKS["gallery_image"].load_options(),
    ]


def image_order(*, oldest_first: bool = False) -> list:
    """The order pictures are shown in: newest first, id as the tiebreak so
    two uploaded in the same instant still order stably. ``oldest_first``
    is the same order read the other way — a design round, in sequence."""
    if oldest_first:
        return [GalleryImage.created_at.asc(), GalleryImage.id.asc()]
    return [GalleryImage.created_at.desc(), GalleryImage.id.desc()]


def anchored_clause(until, *, oldest_first: bool = False):
    """The WHERE leg for "start the list here", inclusive.

    Measured by the same instant the list is ordered by, so the picture the
    rail's anchor names is the first one the page returns — and pointed the
    same way the list is read. Newest first, an anchor is a ceiling and the
    page walks back from it; oldest first, it is a floor and the page walks
    forward. One clause with a direction rather than two, because there is
    one question: where does this page start.
    """
    if oldest_first:
        return GalleryImage.created_at >= until
    return GalleryImage.created_at <= until


async def get_gallery(
    session: AsyncSession,
    gallery_id: int,
    *,
    populate_existing: bool = False,
) -> Gallery | None:
    """Fetch a gallery with the relationships authorization + serialization
    need. RLS scopes the row to the request's guild."""
    stmt = (
        select(Gallery)
        .where(Gallery.id == gallery_id)
        .options(*gallery_loader_options())
    )
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    result = await session.exec(stmt)
    return result.one_or_none()


async def get_image(
    session: AsyncSession,
    gallery_id: int,
    image_id: int,
    *,
    populate_existing: bool = False,
) -> GalleryImage | None:
    """One picture, by id, in the gallery the request named — a picture is
    only ever reached through its gallery, so an id from another one is
    nothing here."""
    stmt = (
        select(GalleryImage)
        .where(GalleryImage.id == image_id, GalleryImage.gallery_id == gallery_id)
        .options(*image_loader_options())
    )
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    return (await session.exec(stmt)).one_or_none()


async def annotate_image_counts(session: AsyncSession, rows: Sequence[Gallery]) -> None:
    """Set ``image_count`` on each gallery from one grouped query.

    Trashed pictures are excluded by the soft-delete filter, so a gallery
    that was emptied into the trash reads as empty rather than as full.
    """
    ids = [g.id for g in rows if g.id is not None]
    if not ids:
        return
    result = await session.exec(
        select(GalleryImage.gallery_id, func.count(GalleryImage.id))
        .where(GalleryImage.gallery_id.in_(tuple(ids)))
        .group_by(GalleryImage.gallery_id)
    )
    counts = dict(result.all())
    for gallery in rows:
        object.__setattr__(gallery, "image_count", counts.get(gallery.id, 0))


#: How many pictures a gallery shows from outside when no cover was chosen.
PREVIEW_COUNT = 4


async def annotate_covers(session: AsyncSession, rows: Sequence[Gallery]) -> None:
    """Stamp ``_cover`` and ``_preview`` on each gallery.

    ``_cover`` is the chosen picture. ``_preview`` is the newest few — what a
    list draws as a small grid for a gallery nobody has chosen a cover for,
    which is most of them: a wall of forty says what it is better than any one
    of the forty would.

    One query for the page: a window over each gallery's pictures, newest
    first, cut at :data:`PREVIEW_COUNT`. A chosen cover that has since been
    trashed reads as no choice at all, because the relationship is loaded
    under the soft-delete filter and comes back empty.
    """
    ids = [g.id for g in rows if g.id is not None]
    by_gallery: dict[int, list[GalleryImage]] = {}
    if ids:
        ranked = (
            select(
                GalleryImage,
                func.row_number()
                .over(
                    partition_by=GalleryImage.gallery_id,
                    order_by=(GalleryImage.created_at.desc(), GalleryImage.id.desc()),
                )
                .label("rank"),
            )
            .where(GalleryImage.gallery_id.in_(tuple(ids)))
            .subquery()
        )
        image_alias = aliased(GalleryImage, ranked)
        newest = (
            select(image_alias)
            .where(ranked.c.rank <= PREVIEW_COUNT)
            .order_by(ranked.c.gallery_id, ranked.c.rank)
        )
        for image in (await session.exec(newest)).all():
            by_gallery.setdefault(image.gallery_id, []).append(image)
    for gallery in rows:
        object.__setattr__(gallery, "_cover", gallery.cover_image)
        object.__setattr__(gallery, "_preview", by_gallery.get(gallery.id, []))


async def annotate_version_counts(
    session: AsyncSession, rows: Sequence[GalleryImage]
) -> None:
    """Set ``version_count`` on each picture from one grouped query."""
    ids = [i.id for i in rows if i.id is not None]
    if not ids:
        return
    result = await session.exec(
        select(GalleryImageVersion.gallery_image_id, func.count(GalleryImageVersion.id))
        .where(GalleryImageVersion.gallery_image_id.in_(tuple(ids)))
        .group_by(GalleryImageVersion.gallery_image_id)
    )
    counts = dict(result.all())
    for image in rows:
        object.__setattr__(image, "version_count", counts.get(image.id, 1))


async def next_version_number(session: AsyncSession, image_id: int) -> int:
    current = await session.scalar(
        select(func.max(GalleryImageVersion.version_number)).where(
            GalleryImageVersion.gallery_image_id == image_id
        )
    )
    return (current or 0) + 1


def mirror_version(image: GalleryImage, version: GalleryImageVersion) -> None:
    """Copy a version's file fields onto the picture row, which is what every
    surface reads — the version table is history."""
    image.file_url = version.file_url
    image.thumbnail_url = version.thumbnail_url
    image.file_content_type = version.file_content_type
    image.file_size = version.file_size
    image.original_filename = version.original_filename
    image.width = version.width
    image.height = version.height


def image_blob_urls(image: Any) -> list[str]:
    """Every stored blob a picture row names — the file and its thumbnail."""
    return [url for url in (image.file_url, image.thumbnail_url) if url]

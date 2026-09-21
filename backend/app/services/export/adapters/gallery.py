"""Gallery source adapter: the importable backup envelope (json).

A gallery is its pictures, so the envelope carries what the rows say about
them — title, caption, dimensions, the order they arrived in — and names each
blob by its **storage key**. The bytes themselves ride in the zip under
``assets/``, registered by the backup adapter, which is why a gallery only
crosses inside a backup: an envelope on its own would be a list of captions
for pictures that are not there.

That is also the whole reason the tool sat out of the export engine until now.
The blob path already existed for file documents; this puts galleries on it.

Thumbnails are deliberately **not** carried. A thumbnail is a rendition the
app makes at upload and can make again, so shipping both doubles the bytes of
a picture-heavy backup to restore something derivable.

Access rule: READ on the gallery (exporting is a formatted read), enforced by
the ``get_gallery_for_export`` seam at both count and build time, under the
caller's RLS session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.gallery import Gallery, GalleryImage
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    envelope_key,
)
from app.services.export.contract import RenderItem

#: What one gallery contributes to a batch: its row and its pictures.
Loaded = tuple[Gallery, list[GalleryImage]]


class GalleryAdapter(ToolExportAdapter):
    tool = Tool.gallery

    async def fetch(
        self, session: AsyncSession, user: User, guild_id: int, gallery_id: int, /
    ) -> Loaded:
        from app.services.tenant.galleries import get_gallery_for_export

        return await get_gallery_for_export(
            session, user, guild_id, gallery_id=gallery_id
        )

    def rows(self, loaded: Loaded, /) -> int:
        # One row per picture: a gallery's size is what is in it, not the
        # single row naming it.
        _gallery, images = loaded
        return len(images) or 1

    def item(self, loaded: Loaded, ctx: BuildContext, /) -> RenderItem:
        gallery, images = loaded
        return build_gallery_item(gallery, images, ctx.now)


def storage_key_of(url: str | None) -> str:
    """The stored blob's key, as the manifest and the importer name it."""
    return (url or "").split("/")[-1]


def build_gallery_item(
    gallery: Gallery, images: list[GalleryImage], now: datetime
) -> RenderItem:
    # The envelope is importable machine data — stays canonical, never
    # localized (translating field keys breaks import).
    return RenderItem(
        key=envelope_key(Tool.gallery, gallery.name, now.strftime("%Y-%m-%d")),
        data=_envelope(gallery, images),
    )


def _envelope(gallery: Gallery, images: list[GalleryImage]) -> dict[str, Any]:
    cover = next(
        (img for img in images if img.id == gallery.cover_image_id),
        None,
    )
    return {
        "type": "initiative-gallery",
        "schema_version": 1,
        "name": gallery.name,
        "description": gallery.description,
        # The cover crosses as a storage key for the reason a wiki's home page
        # crosses as a slug: an id means nothing in the guild this restores
        # into, and the key is what both sides call the same picture.
        "cover": storage_key_of(cover.file_url) if cover is not None else None,
        "tags": sorted(tag.name for tag in getattr(gallery, "tags", None) or []),
        "images": [_image_envelope(image) for image in images],
    }


def _image_envelope(image: GalleryImage) -> dict[str, Any]:
    return {
        "title": image.title,
        "caption": image.caption,
        "storage_key": storage_key_of(image.file_url),
        "content_type": image.file_content_type,
        "size_bytes": image.file_size,
        "original_filename": image.original_filename,
        "width": image.width,
        "height": image.height,
        "tags": sorted(tag.name for tag in getattr(image, "tags", None) or []),
    }

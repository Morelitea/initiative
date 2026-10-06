"""Gallery source adapter: the importable envelope, with its pictures.

A gallery is its pictures, so the envelope carries what the rows say about
them — title, caption, dimensions, the order they arrived in — and names each
blob by its **storage key**. The bytes ride beside it under ``assets/``, named
by that key: in a backup the backup adapter registers them, and a gallery
exported on its own is always a zip of the envelope and its pictures, because
an envelope alone would be a list of captions for pictures that are not there.
A picture whose file is gone is left out of the zip and still listed, which is
what the importer already expects of a missing file.

Thumbnails are deliberately **not** carried. A thumbnail is a rendition the
app makes at upload and can make again, so shipping both doubles the bytes of
a picture-heavy backup to restore something derivable.

Access rule: READ on the gallery (exporting is a formatted read), enforced by
the ``ToolExportAdapter.fetch`` seam at both count and build time, under the
caller's RLS session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.models.tenant.gallery import Gallery, GalleryImage
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    envelope_key,
)
from app.services.export.contract import RenderItem
from app.services.export.property_values import exported_properties
from app.services.permissions import EXPORT_ACCESS

#: What one gallery contributes to a batch: its row and its pictures.
Loaded = tuple[Gallery, list[GalleryImage]]


#: The size proxy divisor for the pictures: one "row" per MiB, as a file
#: document counts, so a gallery of large pictures is delivered as a job.
_IMAGE_ROW_BYTES = 1_048_576


class GalleryAdapter(ToolExportAdapter):
    tool = Tool.gallery
    #: Always a zip, even with no pictures: the envelope and its files are one
    #: download.
    force_zip = True

    async def fetch(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        gallery_id: int,
        /,
        *,
        access: str = EXPORT_ACCESS,
    ) -> Loaded:
        """The gallery and its pictures, oldest first: the order they were put
        in, so a restore reads the same way round."""
        from sqlmodel import select

        from app.services.tenant import properties as properties_service
        from app.services.tenant import tags as tags_service
        from app.services.tenant.galleries import image_loader_options, image_order

        gallery = await super().fetch(
            session, user, guild_id, gallery_id, access=access
        )
        images = list(
            await session.exec(
                select(GalleryImage)
                .where(GalleryImage.gallery_id == gallery.id)
                .options(*image_loader_options())
                .order_by(*image_order(oldest_first=True))
            )
        )
        await tags_service.annotate_tags(session, images)
        await properties_service.annotate_properties(session, images)
        return gallery, images

    async def reach(
        self, session: AsyncSession, params: dict, loaded: list[Loaded], /
    ) -> set[int]:
        return {gallery.initiative_id for gallery, _images in loaded}

    def title(self, loaded: Loaded, /) -> str:
        gallery, _images = loaded
        return gallery.name

    def rows(self, loaded: Loaded, /) -> int:
        # A gallery's size is what is in it, not the single row naming it:
        # each picture counts for its megabytes, and at least one.
        _gallery, images = loaded
        return 1 + sum(
            max(1, int(image.current_version.file_size or 0) // _IMAGE_ROW_BYTES)
            for image in images
        )

    def item(self, loaded: Loaded, ctx: BuildContext, /) -> RenderItem:
        gallery, images = loaded
        return build_gallery_item(gallery, images, ctx.now)

    def items(self, loaded: Loaded, ctx: BuildContext, /) -> tuple[RenderItem, ...]:
        """The envelope, then each picture whose file is still stored."""
        from app.services.storage import get_guild_storage

        _gallery, images = loaded
        storage = get_guild_storage(ctx.guild_id)
        pictures = []
        for image in images:
            version = image.current_version
            key = storage_key_of(version.file_url)
            if not key or not storage.exists(key):
                continue
            pictures.append(
                RenderItem(
                    key=key,
                    data={
                        "storage_key": key,
                        "content_type": version.file_content_type,
                    },
                    filename=f"assets/{key}",
                    format="file",
                )
            )
        return (self.item(loaded, ctx), *pictures)


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
        "type": tool_envelope_type(Tool.gallery),
        "schema_version": 1,
        "name": gallery.name,
        "description": gallery.description,
        # The cover crosses as a storage key for the reason a wiki's home page
        # crosses as a slug: an id means nothing in the guild this restores
        # into, and the key is what both sides call the same picture.
        "cover": (
            storage_key_of(cover.current_version.file_url)
            if cover is not None
            else None
        ),
        "tags": sorted(tag.name for tag in getattr(gallery, "tags", None) or []),
        "properties": exported_properties(gallery),
        "images": [_image_envelope(image) for image in images],
    }


def _image_envelope(image: GalleryImage) -> dict[str, Any]:
    version = image.current_version
    return {
        "title": image.title,
        "caption": image.caption,
        "storage_key": storage_key_of(version.file_url),
        "content_type": version.file_content_type,
        "size_bytes": version.file_size,
        "original_filename": version.original_filename,
        "width": version.width,
        "height": version.height,
        "tags": sorted(tag.name for tag in getattr(image, "tags", None) or []),
        "properties": exported_properties(image),
        # What a reference to this picture points at across one import.
        "external_ref": f"gallery_image:{image.id}",
    }

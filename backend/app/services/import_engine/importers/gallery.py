"""``initiative-gallery`` importer: the gallery row, its pictures, and the
tags on both.

A picture is a row plus a blob, and only the row is in the envelope. The bytes
travel as an asset in the backup zip and are restored under their original
storage key before entries apply, so an image's ``storage_key`` resolves to a
blob that is already there. A key that resolves to nothing is **skipped and
counted**, not written: a gallery row pointing at bytes that never arrived
would be a broken tile that no one can fix.

That is why a gallery envelope on its own — outside a backup — imports as an
empty gallery and says so. Nothing is lost that was ever there.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import routed_guild_id
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.gallery import Gallery, GalleryImage
from app.models.tenant.initiative import Initiative, PermissionKey
from app.schemas.tenant.import_envelopes import GalleryEnvelope
from app.services.import_engine.common import ensure_tag, unique_name
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.import_engine.context import ImportContext
from app.services.import_engine.importers._base import (
    QuotesNobody,
    grant_ownership,
    parse_envelope,
)
from app.services.storage import get_guild_storage
from app.services.tenant import tags as tags_service


class GalleryImporter(QuotesNobody):
    envelope_type = "initiative-gallery"
    permission = PermissionKey.create_galleries

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        return parse_envelope(GalleryEnvelope, envelope)

    def count(self, validated: BaseModel) -> int:
        envelope: GalleryEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        return len(envelope.images) + 1

    def archive_assets(
        self, envelope: dict[str, Any]
    ) -> list[tuple[dict[str, Any], str]]:
        """The pictures an exported gallery's zip carries beside it, as the
        envelope names them: each one's ``storage_key`` is its file under
        ``assets/``."""
        images = envelope.get("images")
        if not isinstance(images, list):
            return []
        return [(image, "picture") for image in images if isinstance(image, dict)]

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
        context: ImportContext | None = None,
    ) -> EnvelopeImportResult:
        env: GalleryEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model
        guild_id = routed_guild_id(session)
        warnings: list[str] = []

        existing_names = {
            row
            for row in (
                await session.exec(
                    select(Gallery.name).where(
                        Gallery.initiative_id == target_initiative.id
                    )
                )
            ).all()
        }
        gallery = Gallery(
            name=unique_name(existing_names, env.name),
            description=env.description,
            initiative_id=target_initiative.id,
            created_by=importer.id,
        )
        session.add(gallery)
        await session.flush()

        await grant_ownership(
            session,
            tool=Tool.gallery,
            entity_id=gallery.id,
            target_initiative=target_initiative,
            importer=importer,
        )

        tags_created = 0
        tags_matched = 0

        async def attach_tags(surface: str, entity_id: int, names: list[str]) -> None:
            nonlocal tags_created, tags_matched
            for tag_name in names:
                resolved = await ensure_tag(session, name=tag_name, color="#6b7280")
                if resolved.created:
                    tags_created += 1
                else:
                    tags_matched += 1
                session.add(
                    tags_service.tag_edge(
                        tags_service.TAG_LINKS[surface], entity_id, resolved.id
                    )
                )

        await attach_tags("gallery", gallery.id, env.tags)

        storage = get_guild_storage(guild_id)
        created = 0
        missing = 0
        cover_id: int | None = None
        for image_env in env.images:
            key = (image_env.storage_key or "").strip()
            # A key with a path in it is not a key. The backup importer holds
            # assets to the same rule when it restores them.
            if not key or "/" in key or "\\" in key or key in (".", ".."):
                missing += 1
                continue
            if storage.open_readable(key) is None:
                missing += 1
                continue
            row = GalleryImage(
                gallery_id=gallery.id,
                title=image_env.title,
                caption=image_env.caption,
                file_url=f"/uploads/{guild_id}/{key}",
                file_content_type=image_env.content_type,
                file_size=image_env.size_bytes,
                original_filename=image_env.original_filename,
                width=image_env.width,
                height=image_env.height,
                created_by=importer.id,
            )
            session.add(row)
            await session.flush()
            if context is not None:
                context.links.register(
                    image_env.external_ref, SearchEntityType.gallery_image, row.id
                )
            created += 1
            if env.cover and key == env.cover:
                cover_id = row.id
            await attach_tags("gallery_image", row.id, image_env.tags)

        if cover_id is not None:
            gallery.cover_image_id = cover_id
            session.add(gallery)
        if missing:
            # The list a gallery draws is its pictures, so a missing one is
            # worth saying out loud rather than leaving somebody to count.
            warnings.append(f"missing_image_files:{missing}")

        await session.flush()
        return EnvelopeImportResult(
            entity_id=gallery.id,
            entity_title=gallery.name,
            created={"galleries": 1, "images": created, "tags": tags_created},
            matched={"tags": tags_matched},
            failed={"images": missing} if missing else {},
            warnings=warnings,
        )

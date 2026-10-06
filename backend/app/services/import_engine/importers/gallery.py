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
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import routed_guild_id
from app.core.search import SearchEntityType
from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.models.tenant.gallery import Gallery, GalleryImage
from app.models.tenant.initiative import Initiative, PermissionKey
from app.schemas.tenant.import_envelopes import GalleryEnvelope
from app.services.import_engine.common import unique_name_in_initiative
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.import_engine.context import ImportContext
from app.services.import_engine.importers._base import (
    NamesPeopleInPassing,
    PropertyRestore,
    TagRestore,
    grant_ownership,
    parse_envelope,
)
from app.services.tenant import file_versions


class GalleryImporter(NamesPeopleInPassing):
    envelope_type = tool_envelope_type(Tool.gallery)
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

        gallery = Gallery(
            name=await unique_name_in_initiative(
                session, Gallery, target_initiative.id, env.name
            ),
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

        tags = TagRestore(session)
        await tags.attach(gallery, env.tags)
        props = PropertyRestore(
            session, initiative_id=target_initiative.id, context=context
        )
        await props.attach(gallery, env.properties)

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
            # Stored here, and a picture a gallery shows, by its bytes.
            content_type = await file_versions.stored_file_type(
                GalleryImage, guild_id, key
            )
            if content_type is None:
                missing += 1
                continue
            row = GalleryImage(
                gallery_id=gallery.id,
                title=image_env.title,
                caption=image_env.caption,
                created_by=importer.id,
            )
            session.add(row)
            await session.flush()
            await file_versions.add_version(
                session,
                row,
                created_by=importer.id,
                file_url=f"/uploads/{guild_id}/{key}",
                file_content_type=content_type,
                file_size=image_env.size_bytes,
                original_filename=image_env.original_filename,
                width=image_env.width,
                height=image_env.height,
            )
            if context is not None:
                context.links.register(
                    image_env.external_ref, SearchEntityType.gallery_image, row.id
                )
            created += 1
            if env.cover and key == env.cover:
                cover_id = row.id
            await tags.attach(row, image_env.tags)
            await props.attach(row, image_env.properties)

        if cover_id is not None:
            gallery.cover_image_id = cover_id
            session.add(gallery)
        if missing:
            # The list a gallery draws is its pictures, so a missing one is
            # worth saying out loud rather than leaving somebody to count.
            warnings.append(f"missing_image_files:{missing}")

        return EnvelopeImportResult(
            entity_id=gallery.id,
            entity_title=gallery.name,
            created={
                Tool.gallery.plural: 1,
                "images": created,
                "tags": tags.created,
                "properties": props.created,
            },
            matched={"tags": tags.matched, "properties": props.matched},
            failed={"images": missing} if missing else {},
            unmatched_handles=await props.settle(gallery),
            warnings=warnings,
        )

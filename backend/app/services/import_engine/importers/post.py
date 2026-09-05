"""``initiative-post`` importer: one bulletin-board notice with its tags.

The pin is not carried by the envelope and so is not restored — a pin belongs
to the board it was made on, not to the notice. An imported post arrives in
the feed by its own date like anything else somebody just wrote.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User
from app.models.tenant.initiative import Initiative, PermissionKey
from app.models.tenant.post import Post, PostTag
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.schemas.tenant.import_envelopes import PostEnvelope
from app.services.import_engine.common import ensure_tag, unique_name
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.import_engine.importers._base import parse_envelope


class PostImporter:
    envelope_type = "initiative-post"
    permission = PermissionKey.create_posts

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        return parse_envelope(PostEnvelope, envelope)

    def count(self, validated: BaseModel) -> int:
        return 1

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
    ) -> EnvelopeImportResult:
        env: PostEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model
        guild_id = target_initiative.guild_id

        existing_names = {
            row
            for row in (
                await session.exec(
                    select(Post.name).where(Post.initiative_id == target_initiative.id)
                )
            ).all()
        }

        post = Post(
            name=unique_name(existing_names, env.name),
            body=env.body or {},
            initiative_id=target_initiative.id,
            guild_id=guild_id,
            created_by=importer.id,
        )
        session.add(post)
        await session.flush()

        session.add(
            ResourceGrant(
                resource_type="post",
                resource_id=post.id,
                user_id=importer.id,
                role_id=None,
                level=ResourceAccessLevel.owner,
                guild_id=guild_id,
                initiative_id=target_initiative.id,
            )
        )

        tags_created = 0
        tags_matched = 0
        for tag_name in env.tags:
            resolved = await ensure_tag(
                session, guild_id=guild_id, name=tag_name, color="#6b7280"
            )
            if resolved.created:
                tags_created += 1
            else:
                tags_matched += 1
            session.add(PostTag(post_id=post.id, tag_id=resolved.id))

        await session.flush()
        return EnvelopeImportResult(
            entity_id=post.id,
            entity_title=post.name,
            created={"posts": 1, "tags": tags_created},
            matched={"tags": tags_matched},
        )

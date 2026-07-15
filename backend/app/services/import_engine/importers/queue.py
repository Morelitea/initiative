"""``initiative-queue`` importer: the queue row, its items in rotation
order, item tags, and the current-item pointer. Member/document/task
references in the envelope are display text (guild-local ids can't rebind)
and are dropped with a warning count."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User
from app.models.tenant.initiative import Initiative, PermissionKey
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.models.tenant.queue import Queue, QueueItem, QueueItemTag
from app.schemas.tenant.import_envelopes import QueueEnvelope
from app.services.import_engine.common import ensure_tag, unique_name
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.import_engine.importers._base import parse_envelope


class QueueImporter:
    envelope_type = "initiative-queue"
    permission = PermissionKey.create_queues

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        return parse_envelope(QueueEnvelope, envelope)

    def count(self, validated: BaseModel) -> int:
        envelope: QueueEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        return len(envelope.items) + 1

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
    ) -> EnvelopeImportResult:
        env: QueueEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model
        guild_id = target_initiative.guild_id
        warnings: list[str] = []

        existing_names = {
            row
            for row in (
                await session.exec(
                    select(Queue.name).where(
                        Queue.initiative_id == target_initiative.id
                    )
                )
            ).all()
        }
        queue = Queue(
            name=unique_name(existing_names, env.name),
            description=env.description,
            is_active=env.is_active,
            current_round=env.current_round,
            initiative_id=target_initiative.id,
            guild_id=guild_id,
            created_by_id=importer.id,
        )
        session.add(queue)
        await session.flush()

        session.add(
            ResourceGrant(
                resource_type="queue",
                resource_id=queue.id,
                user_id=importer.id,
                role_id=None,
                level=ResourceAccessLevel.owner,
                guild_id=guild_id,
                initiative_id=target_initiative.id,
            )
        )

        tags_created = 0
        tags_matched = 0
        dropped_members = 0
        current_item_id: int | None = None
        for item in env.items:
            row = QueueItem(
                queue_id=queue.id,
                guild_id=guild_id,
                label=item.label,
                position=item.position,
                color=item.color,
                notes=item.notes,
                is_visible=item.is_visible,
                held_at_round=item.held_at_round,
            )
            session.add(row)
            await session.flush()
            if item.is_current and current_item_id is None:
                current_item_id = row.id
            if item.member:
                dropped_members += 1
            for tag_name in item.tags:
                resolved = await ensure_tag(
                    session, guild_id=guild_id, name=tag_name, color="#6b7280"
                )
                if resolved.created:
                    tags_created += 1
                else:
                    tags_matched += 1
                session.add(QueueItemTag(queue_item_id=row.id, tag_id=resolved.id))

        if current_item_id is not None:
            queue.current_item_id = current_item_id
            session.add(queue)
        if dropped_members:
            warnings.append(f"dropped_member_links:{dropped_members}")

        await session.flush()
        return EnvelopeImportResult(
            entity_id=queue.id,
            entity_title=queue.name,
            created={"queues": 1, "items": len(env.items), "tags": tags_created},
            matched={"tags": tags_matched},
            warnings=warnings,
        )

"""``initiative-queue`` importer: the queue row, its items in rotation
order, the tags on both, and the current-item pointer. Member/file/task
references in the envelope are display text (guild-local ids can't rebind)
and are dropped with a warning count."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.search import SearchEntityType
from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative, PermissionKey
from app.models.tenant.queue import Queue, QueueItem
from app.schemas.tenant.import_envelopes import QueueEnvelope
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


class QueueImporter(NamesPeopleInPassing):
    envelope_type = tool_envelope_type(Tool.queue)
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
        context: ImportContext | None = None,
    ) -> EnvelopeImportResult:
        env: QueueEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model
        warnings: list[str] = []

        queue = Queue(
            name=await unique_name_in_initiative(
                session, Queue, target_initiative.id, env.name
            ),
            description=env.description,
            is_active=env.is_active,
            current_round=env.current_round,
            initiative_id=target_initiative.id,
            created_by=importer.id,
        )
        session.add(queue)
        await session.flush()

        await grant_ownership(
            session,
            tool=Tool.queue,
            entity_id=queue.id,
            target_initiative=target_initiative,
            importer=importer,
        )

        tags = TagRestore(session)
        await tags.attach(queue, env.tags)
        props = PropertyRestore(
            session, initiative_id=target_initiative.id, context=context
        )
        await props.attach(queue, env.properties)

        dropped_members = 0
        current_item_id: int | None = None
        for item in env.items:
            row = QueueItem(
                queue_id=queue.id,
                label=item.label,
                position=item.position,
                color=item.color,
                notes=item.notes,
                is_visible=item.is_visible,
                held_at_round=item.held_at_round,
            )
            session.add(row)
            await session.flush()
            if context is not None:
                context.links.register(
                    item.external_ref, SearchEntityType.queue_item, row.id
                )
            if item.is_current and current_item_id is None:
                current_item_id = row.id
            if item.member:
                dropped_members += 1
            await tags.attach(row, item.tags)
            await props.attach(row, item.properties)

        if current_item_id is not None:
            queue.current_item_id = current_item_id
            session.add(queue)
        if dropped_members:
            warnings.append(f"dropped_member_links:{dropped_members}")

        return EnvelopeImportResult(
            entity_id=queue.id,
            entity_title=queue.name,
            created={
                Tool.queue.plural: 1,
                "items": len(env.items),
                "tags": tags.created,
                "properties": props.created,
            },
            matched={"tags": tags.matched, "properties": props.matched},
            unmatched_handles=await props.settle(queue),
            warnings=warnings,
        )

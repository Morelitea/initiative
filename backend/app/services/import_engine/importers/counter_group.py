"""``initiative-counter-group`` importer: the group with its tags, and its
counters with configuration and current values."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.search import SearchEntityType
from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.models.tenant.counter import Counter, CounterGroup, CounterViewMode
from app.models.tenant.initiative import Initiative, PermissionKey
from app.schemas.tenant.import_envelopes import CounterGroupEnvelope
from app.services.import_engine.common import ensure_tag, unique_name
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.import_engine.context import ImportContext
from app.services.import_engine.importers._base import (
    NamesPeopleInPassing,
    PropertyRestore,
    grant_ownership,
    parse_envelope,
)
from app.services.tenant import tags as tags_service


class CounterGroupImporter(NamesPeopleInPassing):
    envelope_type = tool_envelope_type(Tool.counter_group)
    permission = PermissionKey.create_counter_groups

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        return parse_envelope(CounterGroupEnvelope, envelope)

    def count(self, validated: BaseModel) -> int:
        envelope: CounterGroupEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        return len(envelope.counters) + 1

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
        context: ImportContext | None = None,
    ) -> EnvelopeImportResult:
        env: CounterGroupEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model

        existing_names = {
            row
            for row in (
                await session.exec(
                    select(CounterGroup.name).where(
                        CounterGroup.initiative_id == target_initiative.id
                    )
                )
            ).all()
        }
        group = CounterGroup(
            name=unique_name(existing_names, env.name),
            description=env.description,
            initiative_id=target_initiative.id,
            created_by=importer.id,
        )
        session.add(group)
        await session.flush()

        await grant_ownership(
            session,
            tool=Tool.counter_group,
            entity_id=group.id,
            target_initiative=target_initiative,
            importer=importer,
        )

        tags_created = 0
        tags_matched = 0
        for tag_name in env.tags:
            resolved = await ensure_tag(session, name=tag_name, color="#6b7280")
            if resolved.created:
                tags_created += 1
            else:
                tags_matched += 1
            session.add(
                tags_service.tag_edge(
                    tags_service.TOOL_TAG_LINKS[Tool.counter_group],
                    group.id,
                    resolved.id,
                )
            )
        props = PropertyRestore(
            session, initiative_id=target_initiative.id, context=context
        )
        await props.attach(group, env.properties)

        for c in env.counters:
            try:
                view_mode = CounterViewMode(c.view_mode)
            except ValueError:
                view_mode = CounterViewMode.number
            counter = Counter(
                counter_group_id=group.id,
                name=c.name,
                color=c.color,
                count=_dec(c.count),
                min=_dec(c.min),
                max=_dec(c.max),
                step=_dec(c.step),
                initial_count=_dec(c.initial_count),
                view_mode=view_mode,
                position=_dec(c.position),
            )
            session.add(counter)
            await session.flush()
            if context is not None:
                context.links.register(
                    c.external_ref, SearchEntityType.counter, counter.id
                )
            await props.attach(counter, c.properties)

        return EnvelopeImportResult(
            entity_id=group.id,
            entity_title=group.name,
            created={
                "counter_groups": 1,
                "counters": len(env.counters),
                "tags": tags_created,
                "properties": props.created,
            },
            matched={"tags": tags_matched, "properties": props.matched},
            unmatched_handles=await props.settle(group),
        )


def _dec(value: float | None) -> Decimal | None:
    if value is None:
        return None
    # Through str so 0.1 stays 0.1, not the float's binary expansion.
    return Decimal(str(value))

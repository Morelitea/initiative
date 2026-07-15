"""``initiative-counter-group`` importer: the group and its counters with
configuration and current values."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User
from app.models.tenant.counter import Counter, CounterGroup, CounterViewMode
from app.models.tenant.initiative import Initiative, PermissionKey
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.schemas.tenant.import_envelopes import CounterGroupEnvelope
from app.services.import_engine.common import unique_name
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.import_engine.importers._base import parse_envelope


class CounterGroupImporter:
    envelope_type = "initiative-counter-group"
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
    ) -> EnvelopeImportResult:
        env: CounterGroupEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model
        guild_id = target_initiative.guild_id

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
            guild_id=guild_id,
            created_by_id=importer.id,
        )
        session.add(group)
        await session.flush()

        session.add(
            ResourceGrant(
                resource_type="counter_group",
                resource_id=group.id,
                user_id=importer.id,
                role_id=None,
                level=ResourceAccessLevel.owner,
                guild_id=guild_id,
                initiative_id=target_initiative.id,
            )
        )

        for c in env.counters:
            try:
                view_mode = CounterViewMode(c.view_mode)
            except ValueError:
                view_mode = CounterViewMode.number
            session.add(
                Counter(
                    counter_group_id=group.id,
                    guild_id=guild_id,
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
            )

        await session.flush()
        return EnvelopeImportResult(
            entity_id=group.id,
            entity_title=group.name,
            created={"counter_groups": 1, "counters": len(env.counters)},
        )


def _dec(value: float | None) -> Decimal | None:
    if value is None:
        return None
    # Through str so 0.1 stays 0.1, not the float's binary expansion.
    return Decimal(str(value))

"""Shared importer plumbing: version gating, envelope parsing, and by-name
property-value attachment for envelopes that carry values without their
definitions (documents, calendar events)."""

from __future__ import annotations

from typing import Any, Type

from pydantic import BaseModel, ValidationError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ImportEngineMessages
from app.models.tenant.property import PropertyDefinition, PropertyType
from app.schemas.tenant.import_envelopes import (
    CURRENT_SCHEMA_VERSION,
    MIN_SUPPORTED_IMPORT_VERSION,
    EnvelopePropertyValue,
)
from app.services.import_engine.common import (
    decode_property_value,
    load_initiative_properties,
    unique_property_name,
)
from app.services.import_engine.contract import ImportEngineError


def parse_envelope(model: Type[BaseModel], envelope: dict[str, Any]) -> BaseModel:
    """Pydantic-parse + version-gate a raw envelope dict."""
    try:
        validated = model.model_validate(envelope)
    except ValidationError as exc:
        raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_ENVELOPE) from exc
    version = getattr(validated, "schema_version", CURRENT_SCHEMA_VERSION)
    if not (MIN_SUPPORTED_IMPORT_VERSION <= version <= CURRENT_SCHEMA_VERSION):
        raise ImportEngineError(ImportEngineMessages.IMPORT_SCHEMA_VERSION_UNSUPPORTED)
    return validated


def _options_for_value(pv: EnvelopePropertyValue) -> list[dict] | None:
    """Synthesize a minimal option set for a select/multi_select definition
    reconstructed from values alone (the flat by-name encoding carries no
    definition), so the stored value is a valid option on the target side."""
    if pv.property_type == PropertyType.select and pv.value_text:
        return [{"value": pv.value_text, "label": pv.value_text}]
    if pv.property_type == PropertyType.multi_select and isinstance(
        pv.value_json, list
    ):
        return [{"value": v, "label": v} for v in pv.value_json if isinstance(v, str)]
    return None


class AttachedProperties:
    __slots__ = ("column_kwargs_by_id", "created", "matched")

    def __init__(self) -> None:
        # property_definition_id -> typed value column kwargs
        self.column_kwargs_by_id: dict[int, dict[str, Any]] = {}
        self.created = 0
        self.matched = 0


async def resolve_property_values(
    session: AsyncSession,
    *,
    initiative_id: int,
    values: list[EnvelopePropertyValue],
    member_emails: dict[str, int],
) -> AttachedProperties:
    """Resolve flat by-name property values against the target initiative's
    definitions: match by (name, type); a missing definition is recreated
    minimally (select options synthesized from the value so it stays valid).
    Unresolvable values (user refs with no matching member) are dropped —
    the caller reports counts, mirroring the project importer's policy."""
    existing = await load_initiative_properties(session, initiative_id=initiative_id)
    attached = AttachedProperties()
    for pv in values:
        definition = existing.get(pv.property_name)
        if definition is not None and definition.type != pv.property_type:
            # Name collision with a different type: create a renamed def
            # (never mutate the target's), same rule as the project importer.
            renamed = await unique_property_name(
                session,
                initiative_id=initiative_id,
                desired_name=f"{pv.property_name}_{pv.property_type.value}",
            )
            definition = None
            name = renamed
        else:
            name = pv.property_name
        if definition is None:
            definition = PropertyDefinition(
                initiative_id=initiative_id,
                name=name,
                type=pv.property_type,
                position=len(existing),
                options=_options_for_value(pv),
            )
            session.add(definition)
            await session.flush()
            existing[name] = definition
            attached.created += 1
        else:
            attached.matched += 1
        column_kwargs = decode_property_value(pv, member_emails)
        if column_kwargs is None:
            continue
        attached.column_kwargs_by_id[definition.id] = column_kwargs  # ty: ignore[invalid-assignment] — persisted row, id is set
    return attached

"""Shared importer plumbing: version gating, envelope parsing, the owner
grant every importer writes for what it creates, and by-name property-value
attachment for envelopes that carry values without their definitions
(documents, calendar events)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Type

from pydantic import BaseModel, ValidationError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ImportEngineMessages
from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.models.tenant.property import PropertyDefinition, PropertyType
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
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

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.schemas.tenant.backup_export import ManifestPerson
    from app.services.import_engine.people import PeopleMap


class QuotesNobody:
    """An envelope that names no people, which is most of them.

    The people step exists to ask who the handles in an envelope are, and an
    envelope carrying no handles has nothing to ask. Mixed in rather than
    left to a default on the protocol, so "this one quotes nobody" is a
    statement each importer makes rather than something it forgot to say —
    the day a tool's envelope starts carrying comments, dropping this base
    class is what makes the wizard notice.
    """

    def people(self, validated: BaseModel) -> list["ManifestPerson"]:
        return []


class NamesPeopleInPassing:
    """An envelope that names people without quoting them: through user-type
    property values, and through the mentions in its body.

    A document's properties and a calendar event's can say who somebody is —
    an owner, a reviewer — and a document or a post can mention somebody.
    Both are placed through the people step's answer, like an assignee is. So
    these envelopes are a question whenever they carry one: the wizard asks,
    rather than the value or the mention landing on whoever happens to share
    the name, or on nobody.
    """

    def people(self, validated: BaseModel) -> list["ManifestPerson"]:
        from app.schemas.tenant.backup_export import ManifestPerson
        from app.services.import_engine.common import handle_key
        from app.services.import_engine.mentions import mention_handles_in
        from app.services.import_engine.people import user_reference_handles

        payload = validated.model_dump(mode="json")
        handles: dict[str, str] = {}
        for handle in (
            *user_reference_handles(payload),
            *mention_handles_in(payload),
        ):
            handles.setdefault(handle_key(handle), handle)
        return [
            ManifestPerson(handle=handle, name=None, comment_count=0)
            for handle in sorted(handles.values(), key=str.lower)
        ]


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


async def grant_ownership(
    session: AsyncSession,
    *,
    tool: Tool,
    entity_id: int,
    target_initiative: Initiative,
    importer: User,
) -> None:
    """Make the importer the owner of what it just created. Sharing does not
    cross in any envelope — who may read a thing is a fact about the community
    it was written in — so every importer writes this one row and no other.

    Created on the importer's own request, the row is already there: the
    table's owner trigger wrote it. A job's request names nobody, and the row
    is written here.

    The flush is part of it: the sharing has to be in the database before the
    content it governs, and a flush orders its statements by table rather than
    by the order things were added.
    """
    owned = (
        await session.exec(
            select(ResourceGrant.id).where(
                ResourceGrant.resource_type == tool.value,
                ResourceGrant.resource_id == entity_id,
                ResourceGrant.level == ResourceAccessLevel.owner,
            )
        )
    ).first()
    if owned is not None:
        return
    session.add(
        ResourceGrant(
            resource_type=tool.value,
            resource_id=entity_id,
            user_id=importer.id,
            role_id=None,
            level=ResourceAccessLevel.owner,
            initiative_id=target_initiative.id,
        )
    )
    await session.flush()


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
    __slots__ = ("column_kwargs_by_id", "created", "matched", "named", "unmatched")

    def __init__(self) -> None:
        # property_definition_id -> typed value column kwargs
        self.column_kwargs_by_id: dict[int, dict[str, Any]] = {}
        self.created = 0
        self.matched = 0
        #: Person values placed, by account, with the handle that named them.
        self.named: dict[int, str] = {}
        #: Person values whose handle landed on nobody.
        self.unmatched: set[str] = set()


async def resolve_property_values(
    session: AsyncSession,
    *,
    initiative_id: int,
    values: list[EnvelopePropertyValue],
    member_handles: dict[str, int],
    people: "PeopleMap | None" = None,
) -> AttachedProperties:
    """Resolve flat by-name property values against the target initiative's
    definitions: match by (name, type); a missing definition is recreated
    minimally (select options synthesized from the value so it stays valid).
    Unresolvable values (user refs nobody was mapped to) are dropped and their
    handles collected, mirroring the project importer's policy."""
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
        column_kwargs = decode_property_value(pv, member_handles, people=people)
        if column_kwargs is None:
            if pv.value_handle:
                attached.unmatched.add(pv.value_handle)
            continue
        if column_kwargs.get("value_user_id") is not None and pv.value_handle:
            attached.named.setdefault(column_kwargs["value_user_id"], pv.value_handle)
        attached.column_kwargs_by_id[definition.id] = column_kwargs  # ty: ignore[invalid-assignment] — persisted row, id is set
    return attached

"""Import-side pydantic mirrors of the export envelopes.

Each model parses the dict shape its export adapter emits (see
``services/export/adapters/{document,queue,counter_group,calendar_event}.py``)
with ``extra="ignore"``: informational export fields (queue member/document/
task display text, event ids and timestamps, linked document titles) parse
and drop — they reference guild-local state an import cannot rebind.

Versioning is per envelope type: ``MIN_SUPPORTED_IMPORT_VERSION`` ..
``CURRENT_SCHEMA_VERSION`` (both 1 today). Early 0.56.0 exports spelled the
discriminator ``kind``; the validators accept both spellings.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import ConfigDict, model_validator

from app.models.tenant.property import PropertyType
from app.schemas.base import SanitizedBaseModel

CURRENT_SCHEMA_VERSION = 1
MIN_SUPPORTED_IMPORT_VERSION = 1


class _EnvelopeBase(SanitizedBaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: int = CURRENT_SCHEMA_VERSION

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_kind(cls, data: Any) -> Any:
        # 0.56.0-era exports used `kind`; fill `type` from it when absent.
        if isinstance(data, dict) and "type" not in data and "kind" in data:
            data = {**data, "type": data["kind"]}
        return data


class EnvelopePropertyValue(SanitizedBaseModel):
    """Flat, by-name property value — the shared encoding written by
    ``export/property_values.py::property_export_dict``."""

    model_config = ConfigDict(extra="ignore")

    property_name: str
    property_type: PropertyType
    value_text: Optional[str] = None
    value_number: Optional[float] = None
    value_boolean: Optional[bool] = None
    value_json: Any = None
    value_email: Optional[str] = None


class DocumentEnvelope(_EnvelopeBase):
    type: Literal["initiative-document"]
    document_type: str  # native | spreadsheet | smart_link | whiteboard
    title: str
    content: dict[str, Any] = {}
    tags: list[str] = []
    properties: list[EnvelopePropertyValue] = []


class QueueEnvelopeItem(SanitizedBaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str
    position: float = 0.0
    color: Optional[str] = None
    notes: Optional[str] = None
    is_visible: bool = True
    held_at_round: Optional[int] = None
    is_current: bool = False
    tags: list[str] = []
    # `member`, `documents`, `tasks` are informational display text in the
    # export — ignored here (extra="ignore"), counted as a warning on apply.
    member: Optional[str] = None


class QueueEnvelope(_EnvelopeBase):
    type: Literal["initiative-queue"]
    name: str
    description: Optional[str] = None
    is_active: bool = False
    current_round: int = 1
    items: list[QueueEnvelopeItem] = []


class CounterEnvelopeItem(SanitizedBaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    color: Optional[str] = None
    count: float = 0
    min: Optional[float] = None
    max: Optional[float] = None
    step: float = 1
    initial_count: float = 0
    view_mode: str = "number"
    position: float = 0


class CounterGroupEnvelope(_EnvelopeBase):
    type: Literal["initiative-counter-group"]
    name: str
    description: Optional[str] = None
    counters: list[CounterEnvelopeItem] = []


class EventEnvelopeAttendee(SanitizedBaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = None
    email: Optional[str] = None
    rsvp: str = "pending"


class EventEnvelopeItem(SanitizedBaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    start_at: str
    end_at: str
    all_day: bool = False
    color: Optional[str] = None
    recurrence: Optional[dict[str, Any]] = None
    attendees: list[EventEnvelopeAttendee] = []
    tags: list[str] = []
    properties: list[EnvelopePropertyValue] = []


class CalendarEventsEnvelope(_EnvelopeBase):
    type: Literal["initiative-calendar-events"]
    events: list[EventEnvelopeItem] = []

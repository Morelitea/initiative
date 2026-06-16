"""Schemas for iCal import/export."""

from typing import List, Optional

from pydantic import Field

from app.schemas.base import RawTextStr, SanitizedBaseModel


class ICalEventPreview(SanitizedBaseModel):
    summary: str
    start_at: str
    end_at: Optional[str] = None
    all_day: bool
    has_recurrence: bool


class ICalParseResult(SanitizedBaseModel):
    event_count: int
    events: List[ICalEventPreview]
    has_recurring: bool


class ICalParseRequest(SanitizedBaseModel):
    ics_content: RawTextStr = Field(..., max_length=2_000_000)


class ICalImportRequest(SanitizedBaseModel):
    initiative_id: int
    ics_content: RawTextStr = Field(..., max_length=2_000_000)


class ICalImportResult(SanitizedBaseModel):
    events_created: int = 0
    events_failed: int = 0
    errors: List[str] = Field(default_factory=list)

"""Schemas for iCal import/export."""

from typing import List, Optional

from pydantic import BaseModel, Field


class ICalEventPreview(BaseModel):
    summary: str
    start_at: str
    end_at: Optional[str] = None
    all_day: bool
    has_recurrence: bool


class ICalParseResult(BaseModel):
    event_count: int
    events: List[ICalEventPreview]
    has_recurring: bool


class ICalParseRequest(BaseModel):
    ics_content: str = Field(..., max_length=2_000_000)


class ICalImportRequest(BaseModel):
    initiative_id: int
    ics_content: str = Field(..., max_length=2_000_000)


class ICalImportResult(BaseModel):
    events_created: int = 0
    events_failed: int = 0
    errors: List[str] = Field(default_factory=list)

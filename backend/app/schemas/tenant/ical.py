"""Schemas for iCal import/export."""

from enum import Enum
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
    # The zone a floating time in the file is read in.
    tz: Optional[str] = Field(default=None, max_length=64)


class ICalImportRequest(SanitizedBaseModel):
    calendar_id: int
    ics_content: RawTextStr = Field(..., max_length=2_000_000)
    # The zone a floating time in the file is read in.
    tz: Optional[str] = Field(default=None, max_length=64)


class ICalImportProblem(str, Enum):
    """Why one event in the file was not imported."""

    no_start = "no_start"
    unreadable = "unreadable"
    not_saved = "not_saved"


class ICalImportError(SanitizedBaseModel):
    problem: ICalImportProblem
    #: The event's title as the file gives it, when it gives one.
    title: Optional[str] = None


class ICalImportResult(SanitizedBaseModel):
    events_created: int = 0
    events_failed: int = 0
    errors: List[ICalImportError] = Field(default_factory=list)

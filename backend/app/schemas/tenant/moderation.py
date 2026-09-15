"""Payloads for reporting something, and for settling a report."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import Field as PydanticField

from app.core.moderation import ReportOutcome, ReportReason, ReportVenue
from app.schemas.base import SanitizedBaseModel


class ReportCreate(SanitizedBaseModel):
    """What a person sends. The same shape from every surface."""

    #: A ``SearchEntityType`` or a ``PlatformReportTarget`` value.
    target_type: str
    target_id: int
    reason: ReportReason
    #: The reporter's own words. Optional: a reason is often the whole report.
    detail: Optional[str] = PydanticField(default=None, max_length=4000)
    #: Which community the reporter was standing in, when they were in one.
    #: Validated as theirs before it is used, and it decides no venue.
    guild_id: Optional[int] = None


class ReportAccepted(SanitizedBaseModel):
    """What the reporter is told: that we have it, and nothing else.

    Not who will see it, not whether one already existed, and never an outcome
    — a report is not a conversation with the person who sent it.
    """

    accepted: bool = True
    venue: ReportVenue


class ModerationReportRead(SanitizedBaseModel):
    """One report, as its community's moderators see it."""

    id: int
    initiative_id: int
    target_type: str
    target_id: int
    reason: ReportReason
    reported_at: datetime
    #: How many distinct people reported it. The identities are held on the
    #: reporters table and deliberately not served here: reporting stays
    #: confidential inside the community, and the count is what a decision
    #: rests on.
    reporter_count: int
    #: What each of them said, unattributed.
    details: List[str]
    outcome: Optional[ReportOutcome] = None
    note: Optional[str] = None
    decided_by: Optional[int] = None
    decided_at: Optional[datetime] = None


class ModerationReportList(SanitizedBaseModel):
    items: List[ModerationReportRead]
    total: int


class ReportSettle(SanitizedBaseModel):
    """Settling a report. Every outcome closes it."""

    outcome: ReportOutcome
    note: Optional[str] = PydanticField(default=None, max_length=4000)

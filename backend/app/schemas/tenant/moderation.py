"""Payloads for reporting something, and for settling a report."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import Field as PydanticField

from app.core.moderation import ReportOutcome, ReportReason, ReportVenue
from app.core.search import SearchEntityType
from app.core.tools import Tool
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


class ReportTargetLink(SanitizedBaseModel):
    """Where a reported thing is read.

    A comment has no page of its own — it is read on whatever it was said on —
    so this names that thing rather than the comment. Everything else names
    itself. The trio is the one a search hit carries, and means the same here:
    what to open, and the tool it is addressed inside, since a task needs its
    project's id to be addressed at all.
    """

    entity_type: SearchEntityType
    entity_id: int
    tool: Tool
    tool_id: int


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
    #: What the reported thing says — a comment's opening, anything else's
    #: name — read from the index that already holds exactly that line. None
    #: when the row is no longer there, which is the honest answer for content
    #: that has since been deleted or taken down.
    target_excerpt: Optional[str] = None
    #: Where to go and read it. None for the same reasons the excerpt is.
    target_link: Optional["ReportTargetLink"] = None


class ModerationReportList(SanitizedBaseModel):
    items: List[ModerationReportRead]
    #: How many are in this page. Settled reports accumulate without bound, so
    #: the list is paged and this is not a count of everything there is.
    total: int


class ReportSettle(SanitizedBaseModel):
    """Settling a report. Every outcome closes it."""

    outcome: ReportOutcome
    note: Optional[str] = PydanticField(default=None, max_length=4000)


class SharedResourceRead(SanitizedBaseModel):
    """One resource in the initiative, and how widely it is reached."""

    resource_type: str
    resource_id: int
    name: Optional[str] = None
    all_initiative_members: bool
    user_grant_count: int
    role_grant_count: int
    via_dashboard: bool


class InitiativeSharingRead(SanitizedBaseModel):
    """Who can reach what, across one initiative.

    Counts rather than names: the question this answers is *how widely*, and a
    moderator who needs the detail opens the resource's own sharing control,
    which is the one editor for it.
    """

    items: List[SharedResourceRead]

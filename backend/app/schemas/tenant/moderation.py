"""Payloads for reporting something, and for settling a report."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import Field as PydanticField, model_validator

from app.core.moderation import (
    HoldReason,
    LegalBasis,
    ModerationAct,
    RemovalReason,
    ReportOutcome,
    ReportReason,
)
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.schemas.base import SanitizedBaseModel
from app.schemas.tenant.evidence import EvidenceRead
from app.schemas.query import PageMeta


class ReportCreate(SanitizedBaseModel):
    """What a person sends. The same shape from every surface."""

    #: A ``SearchEntityType`` or a ``PlatformReportTarget`` value.
    target_type: str
    target_id: int
    reason: ReportReason
    #: The reporter's own words. A reason is often the whole report; an
    #: ``illegal`` or ``other`` one says what is wrong.
    detail: Optional[str] = PydanticField(default=None, max_length=4000)
    #: The law an ``illegal`` report says it breaks. Required then, and only
    #: then.
    legal_basis: Optional[LegalBasis] = None
    #: Which community the reporter was standing in, when they were in one.
    #: Validated as theirs before it is used, and it decides no venue.
    community_id: Optional[int] = None


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
    #: What the reporters attached, oldest first. Who attached which is not
    #: said, as who reported is not.
    evidence: List[EvidenceRead] = PydanticField(default_factory=list)
    #: The law an ``illegal`` report named.
    legal_basis: Optional[LegalBasis] = None
    #: When the platform was told as well — an ``illegal`` report goes to both
    #: at once. Null when only this community was.
    platform_notified_at: Optional[datetime] = None
    #: What settling it did to the target, in the moderation log.
    action_id: Optional[int] = None


class ModerationReportList(PageMeta):
    items: List[ModerationReportRead]


class ReportHold(SanitizedBaseModel):
    """Why a report's target is being held for the platform."""

    reason: HoldReason
    #: Required for ``illegal_content``.
    legal_basis: Optional[LegalBasis] = None
    #: Who asked, a reference number. Read only by the platform.
    note: Optional[str] = PydanticField(default=None, max_length=2000)


class ReportSettle(SanitizedBaseModel):
    """Settling a report. Every outcome closes it."""

    outcome: ReportOutcome
    #: The moderators' own note, for the record. Never shown to anyone else.
    note: Optional[str] = PydanticField(default=None, max_length=4000)
    #: For ``held``: why the reported thing is held. Required then, and
    #: refused with any other outcome.
    hold: Optional[ReportHold] = None
    #: For ``content_removed``: why it is taken down, when not for the
    #: reason it was reported for.
    removal_reason: Optional[RemovalReason] = None
    #: For ``member_warned``: what whoever wrote it is told. Required then,
    #: and refused with any other outcome.
    message: Optional[str] = PydanticField(default=None, max_length=2000)

    @model_validator(mode="after")
    def _each_goes_with_its_outcome(self) -> "ReportSettle":
        if (self.outcome == ReportOutcome.held) != (self.hold is not None):
            raise ValueError("a hold goes with the held outcome, and only with it")
        if self.removal_reason is not None and (
            self.outcome != ReportOutcome.content_removed
        ):
            raise ValueError("a removal reason goes with content_removed")
        warned = self.outcome == ReportOutcome.member_warned
        if warned != bool((self.message or "").strip()):
            raise ValueError("a message goes with member_warned, and only with it")
        return self


class ModerationActCreate(SanitizedBaseModel):
    """A moderator acting on something directly, rather than settling a
    report about it."""

    act: ModerationAct
    #: A ``SearchEntityType`` value, and which one.
    target_type: str
    target_id: int
    #: For ``remove``: why. Required then.
    reason: Optional[RemovalReason] = None
    #: Why, for the log. For ``warn``, what the member is told: required then.
    note: Optional[str] = PydanticField(default=None, max_length=2000)

    @model_validator(mode="after")
    def _says_why(self) -> "ModerationActCreate":
        if self.act == ModerationAct.restore:
            raise ValueError("a restore names the removal it undoes")
        if self.act == ModerationAct.remove and self.reason is None:
            raise ValueError("a removal says why")
        if self.act == ModerationAct.warn and not (self.note or "").strip():
            raise ValueError("a warning says what the member is told")
        return self


class ModerationRestore(SanitizedBaseModel):
    """Putting back what a removal took down."""

    note: Optional[str] = PydanticField(default=None, max_length=2000)


class ModerationPerson(SanitizedBaseModel):
    """Somebody the moderation log names: who acted, or whose work it was."""

    id: int
    name: str


class ModerationActionRead(SanitizedBaseModel):
    """One row of a community's moderation log, as its moderators read it."""

    id: int
    initiative_id: int
    action: ModerationAct
    target_type: str
    target_id: int
    reason: Optional[RemovalReason] = None
    #: The moderator's note. For a warning, what the member was told.
    note: Optional[str] = None
    #: The words a comment's removal took down.
    snapshot: Optional[str] = None
    #: The moderator, or nobody for the platform acting on a hold it ended.
    actor: Optional[ModerationPerson] = None
    #: Whose work it was.
    subject: Optional[ModerationPerson] = None
    report_id: Optional[int] = None
    #: Set when the platform did it, ending a hold.
    hold_id: Optional[int] = None
    created_at: datetime
    #: A removal still standing on its target, so it can be put back.
    restorable: bool = False


class ModerationLogList(PageMeta):
    items: List[ModerationActionRead]


class SharedResourceRead(SanitizedBaseModel):
    """One resource in the initiative, and how widely it is reached."""

    resource_type: str
    resource_id: int
    name: Optional[str] = None
    all_initiative_members: bool
    user_grant_count: int
    role_grant_count: int


class InitiativeSharingRead(SanitizedBaseModel):
    """Who can reach what, across one initiative.

    Counts rather than names: the question this answers is *how widely*, and a
    moderator who needs the detail opens the resource's own sharing control,
    which is the one editor for it.
    """

    items: List[SharedResourceRead]

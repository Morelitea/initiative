"""Reports a community's moderators settle.

A moderation report is **not a task**. A task carries a checklist, a priority,
dates, recurrence, a drag position, several assignees with per-assignee
completion, custom properties, tags and a sharing model — a moderator needs
none of it. They look at what was reported and decide. So this is its own small
thing: one row per reported target, holding what it is, why, and what was done.

Platform-handled reports are different work and keep their own shape — they are
intake cases (tasks) in the operations guild, triaged and assigned by staff.
See ``history/moderation-surface-design.md``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

from app.core.moderation import ReportOutcome, ReportReason

#: Longest a target-type value can be. A ``SearchEntityType`` or a
#: ``PlatformReportTarget``, stored as its string.
TARGET_TYPE_LENGTH = 32


class ModerationReport(SQLModel, table=True):
    """One reported target in one initiative, open until it is settled."""

    __tablename__ = "moderation_reports"

    id: Optional[int] = Field(default=None, primary_key=True)

    guild_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False
        )
    )
    # No index of its own: the migration's (initiative_id, outcome,
    # reported_at DESC) index leads on this column and answers both the
    # moderator's list and the open-report lookup.
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
        )
    )

    # What was reported. A weak reference, never content: reaching the thing is
    # the moderator following the link, under the access they already hold.
    target_type: str = Field(
        sa_column=Column(String(length=TARGET_TYPE_LENGTH), nullable=False)
    )
    target_id: int = Field(sa_column=Column(Integer, nullable=False))

    #: Why the first reporter said they were reporting it.
    reason: ReportReason = Field(sa_column=Column(String(length=32), nullable=False))
    #: When the first report arrived. Later ones move nothing here.
    reported_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )

    # NULL while open. Every outcome closes the report: it is either work or a
    # record, never both.
    outcome: Optional[ReportOutcome] = Field(
        default=None, sa_column=Column(String(length=32), nullable=True)
    )
    note: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    #: Who settled it, and when. Set by the act, not typed in.
    decided_by: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    decided_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class ModerationReportReporter(SQLModel, table=True):
    """One person's report of a target, joined to the open row for it.

    A row per reporter rather than a count on the report: the count has to mean
    *distinct people*, and only the identities make it mean that. They are held
    for that and for an escalation to carry. The community's own moderators are
    served the count; the names stay here.
    """

    __tablename__ = "moderation_report_reporters"
    __table_args__ = (
        UniqueConstraint(
            "report_id", "reporter_id", name="uq_moderation_report_reporter"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    # No index of its own: the unique constraint above leads on this column,
    # which is what reading a report's reporters looks up.
    report_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("moderation_reports.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    #: Weak ref, no FK — an erased account leaves a dangling id rather than a
    #: preserved person, like every other reference on this plane.
    reporter_id: int = Field(sa_column=Column(Integer, nullable=False))
    reported_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    #: This reporter's own words.
    detail: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

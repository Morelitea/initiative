"""Where operations work lands, and which cases are already open.

Two guild-schema tables:

``intake_bindings``
    *This stream lands in that project.* One row per stream per guild, naming
    an initiative, a project, and optionally the status a new case starts in.
    Guild-schema because every id on it — initiative, project, status — is a
    per-schema id and belongs beside the rows it points at.

``intake_cases``
    The key -> task map the writer reads to answer "is this already a case?",
    and the window mark a repeating source is measured against. One row per
    case; ``last_seen_at`` is stamped by the writer, so an unrelated edit to
    the task does not move the window.

Both are initiative-scoped for RLS (see ``app.db.initiative_rls``): a binding
through its project, a case through the task it points at. Reading a case is
therefore exactly as hard as reading the task it describes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

from app.core.intake import IntakeStream
from app.models.tenant._mixins import CreatedByMixin

#: Longest a stream value can be. The column is a CHECKed text rather than a
#: Postgres enum so that adding a stream is a release, not a type migration in
#: every guild schema.
STREAM_LENGTH = 32

#: Longest dedupe key the writer will store. A key is built from a rule's name
#: plus the ids it keys on, never from anything a submitter typed.
DEDUPE_KEY_LENGTH = 200


class IntakeBinding(CreatedByMixin, table=True):
    """One stream, routed to one project in this guild."""

    __tablename__ = "intake_bindings"
    __table_args__ = (UniqueConstraint("stream", name="uq_intake_bindings_stream"),)

    id: Optional[int] = Field(default=None, primary_key=True)

    stream: IntakeStream = Field(
        sa_column=Column(String(length=STREAM_LENGTH), nullable=False)
    )

    # The project is the whole address. Which initiative it belongs to is the
    # project's own column, read from there by everything that needs it, so
    # this table keeps no second copy of an answer that already has one place.
    project_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )

    # The status a new case starts in. NULL means the project's default, which
    # is what the task endpoints already fall back to — so a project whose
    # statuses are rearranged keeps working without anybody revisiting this row.
    default_status_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("task_statuses.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Whether the writer routes to this project right now. A disabled binding
    # keeps the project and the history; it just stops receiving.
    enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )

    created_by: Optional[int] = Field(default=None, nullable=True)


class IntakeCase(SQLModel, table=True):
    """One case the writer opened, and how often its source has recurred.

    Keyed on the **project** rather than on the binding row. What the mark
    answers is "is this incident already being worked?", and that is a question
    about the project the work is in: repointing a stream at another project
    starts fresh there, and unbinding and rebinding to the same one finds the
    case that is still open.

    Every case gets a row, keyed or not, so "when did this stream last open a
    case" is answerable exactly rather than inferred from whatever tasks happen
    to be in the project.
    """

    __tablename__ = "intake_cases"

    id: Optional[int] = Field(default=None, primary_key=True)

    project_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    stream: IntakeStream = Field(
        sa_column=Column(String(length=STREAM_LENGTH), nullable=False)
    )
    task_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )

    #: NULL for a case nothing keys on — a report, a help request. A keyed case
    #: is one a repeating source can find again.
    dedupe_key: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=DEDUPE_KEY_LENGTH), nullable=True),
    )

    opened_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    #: When the source was last seen at all. Every occurrence moves it.
    last_seen_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    #: When a recurrence was last recorded on the case. The window is measured
    #: from here, so a run in progress does not note itself once per event.
    noted_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    #: How many times the source has been seen, the opening included.
    occurrences: int = Field(
        default=1, sa_column=Column(Integer, nullable=False, server_default="1")
    )

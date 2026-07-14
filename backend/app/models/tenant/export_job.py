"""Export job — one asynchronous export request (guild-content, own-row).

The row stores job metadata and the filter *selector* only — never resolved
rows, exported content, secrets, or tokens; it must not become a second copy
of sensitive data. The rendered artifact lives behind the guild's storage
backend at ``artifact_ref`` and is served only through the job-gated download
endpoint. Inline (small) exports persist no row at all.

RLS: guild-level placement with the ``own_row_*`` policy overlay
(``app.db.tenancy.OWN_ROW_TABLES``) — a job may span initiatives ("export all
my tasks"), so it can't be initiative-scoped, but the selector text and the
artifact download must not be guild-wide-readable either. Owner or routed
guild admin only.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class ExportJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    expired = "expired"


class ExportJob(SQLModel, table=True):
    __tablename__ = "export_jobs"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)
    created_by_id: int = Field(foreign_key="users.id", nullable=False)

    source: str = Field(nullable=False)  # "tasks" | "project-report" | …
    template_id: str = Field(nullable=False)
    format: str = Field(default="pdf", nullable=False)
    # The filter SELECTOR the user chose (their own query input) — the worker
    # replays it through the source adapter at render time. NOT results.
    params: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )

    # Stored as a plain string (no shared PG enum type to provision per
    # schema); ExportJobStatus is a str-enum, so members compare and bind
    # directly against the column.
    status: ExportJobStatus = Field(
        default=ExportJobStatus.queued,
        sa_column=Column(String, nullable=False, index=True, server_default="queued"),
    )
    # Storage key relative to the guild prefix, e.g. "exports/{id}.pdf".
    artifact_ref: Optional[str] = Field(default=None)
    error: Optional[str] = Field(default=None)
    # Artifact GC deadline — set when the artifact is written.
    expires_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

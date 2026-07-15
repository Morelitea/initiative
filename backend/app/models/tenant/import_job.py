"""Import job — one asynchronous import request (guild-content, own-row).

The row stores job metadata and the caller's *options* only — never envelope
content, resolved rows, secrets, or tokens. A payload too large to apply
inline is staged behind the guild's storage backend at ``payload_ref`` and
read back by the worker; small envelope imports apply in-request and persist
no row at all (mirroring inline exports).

Unlike an export job, a stale ``running`` import row is never re-claimed and
re-applied: the interrupted apply has already committed chunks under the
always-create policy, so a re-run would duplicate them. The worker fails such
rows closed instead.

RLS: guild-level placement with the ``own_row_*`` policy overlay
(``app.db.tenancy.OWN_ROW_TABLES``) — a backup import spans initiatives, so
it can't be initiative-scoped, but the options/plan/report text must not be
guild-wide-readable either. Owner or routed guild admin only.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class ImportJobStatus(str, Enum):
    # Backup only: payload uploaded, plan persisted, awaiting user confirm.
    staged = "staged"
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    # User-cancelled while staged/queued (payload deleted).
    cancelled = "cancelled"
    # Staged payload GC'd unconfirmed past its TTL.
    expired = "expired"


class ImportJob(SQLModel, table=True):
    __tablename__ = "import_jobs"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)
    created_by_id: int = Field(foreign_key="users.id", nullable=False)

    # Envelope type ("initiative-document", …) or "backup".
    source: str = Field(nullable=False)
    # The caller's OPTIONS (target initiative, include map) — never content.
    params: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    # Staged payload storage key, e.g. "imports/{uuid4hex}.json|.zip".
    payload_ref: Optional[str] = Field(default=None)
    # Backup pre-flight summary (counts/names shown at confirm) — not content.
    plan: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    # Terminal report (per-entry outcomes, unmatched emails, renames).
    result: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )

    # Plain string column (no shared PG enum type to provision per schema);
    # ImportJobStatus is a str-enum, so members compare and bind directly.
    status: ImportJobStatus = Field(
        default=ImportJobStatus.queued,
        sa_column=Column(String, nullable=False, index=True, server_default="queued"),
    )
    error: Optional[str] = Field(default=None)
    # Staged-payload GC deadline (unconfirmed backups expire).
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

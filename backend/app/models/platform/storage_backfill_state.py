from datetime import datetime
from typing import Optional

from pydantic import ConfigDict
from sqlalchemy import JSON, Column, DateTime, Integer, String
from sqlmodel import Field, SQLModel


class StorageBackfillState(SQLModel, table=True):
    """Cluster-wide status of the local->S3 upload backfill (singleton, id=1).

    Shared state so every worker reports the *same* status — the in-memory
    per-process version could show running/failed/idle inconsistently across a
    multi-worker deployment. Written only by the app_admin (BYPASSRLS) engine via
    the owner-gated backfill endpoints; no scoped request role is granted access.
    """

    __tablename__ = "storage_backfill_state"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int = Field(default=1, primary_key=True)

    # idle | running | complete | failed
    status: str = Field(
        default="idle",
        sa_column=Column(String(20), nullable=False, server_default="idle"),
    )
    copied: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    skipped: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    failed: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    hash_mismatches: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    failed_keys: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )
    error: Optional[str] = Field(
        default=None, sa_column=Column(String(2000), nullable=True)
    )
    started_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    finished_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # Updated as the run progresses; a 'running' row whose heartbeat has gone
    # stale is treated as a dead worker and may be reclaimed by a new run.
    heartbeat: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

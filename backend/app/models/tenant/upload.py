from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, String
from sqlmodel import Field, SQLModel


class Upload(SQLModel, table=True):
    __tablename__ = "uploads"

    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str = Field(unique=True, index=True)
    guild_id: int = Field(foreign_key="guilds.id", index=True)
    uploader_user_id: int = Field(foreign_key="users.id")
    size_bytes: int = Field(default=0)
    # MIME type recorded at upload time, so serving can set Content-Type without
    # sniffing the bytes (and a future object-store backend can set it on the
    # object). Nullable: legacy rows stay NULL until backfilled.
    content_type: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    # SHA-256 hex of the stored bytes — integrity verification for the eventual
    # object-store migration, and the basis for future content dedup.
    content_hash: Optional[str] = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

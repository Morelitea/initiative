"""A guild member's AI preference: which connection they use, and whether
AI is enabled for them.

One row per member per guild (guild schema). References the chosen
connection by ``(connection_scope, connection_id)``. App-layer own-user
scoping.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlmodel import Field, SQLModel
from pydantic import ConfigDict


class GuildAIMemberPref(SQLModel, table=True):
    __tablename__ = "guild_ai_member_prefs"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: Optional[int] = Field(
        default=None, foreign_key="guilds.id", nullable=True, index=True
    )
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        )
    )
    connection_scope: Optional[str] = Field(
        default=None, sa_column=Column(String(20), nullable=True)
    )
    connection_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    enabled: Optional[bool] = Field(
        default=None, sa_column=Column(Boolean, nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

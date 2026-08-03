"""A guild member's own API key for a specific AI connection.

Lives in the member's guild schema regardless of config mode, so platform
and guild modes share one code path. References a connection by
``(connection_scope, connection_id)`` — ``platform`` -> the shared
``platform_ai_connections`` row, ``guild`` -> ``guild_ai_connections`` — so
the connection definition is not copied per guild.

Guild-level table with app-layer own-user scoping: the ciphertext is never
returned by the API (reads expose only ``has_key``), and every query filters
by the acting user.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlmodel import Field, SQLModel
from pydantic import ConfigDict


class GuildAIMemberKey(SQLModel, table=True):
    __tablename__ = "guild_ai_member_keys"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "connection_scope",
            "connection_id",
            name="uq_ai_member_key_user_connection",
        ),
    )
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
            index=True,
        )
    )
    # "platform" -> platform_ai_connections.id, "guild" -> guild_ai_connections.id
    connection_scope: str = Field(sa_column=Column(String(20), nullable=False))
    connection_id: int = Field(sa_column=Column(Integer, nullable=False))
    api_key_encrypted: str = Field(sa_column=Column(String(2000), nullable=False))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

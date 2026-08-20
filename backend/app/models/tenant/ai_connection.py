"""Guild-owned AI connections (guild config mode).

Used when ``ai_config_mode == "guild"``: a guild admin configures the
guild's AI providers here (guild schema). Members attach their own keys
referencing these by ``(scope="guild", id)``. Guild-level table (guild-wide
config, schema-boundary protected). ``base_url`` is validated public-only —
a guild admin can never persist a private/internal target.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, String
from sqlmodel import Field
from pydantic import ConfigDict

from app.models.tenant._mixins import AuthorshipMixin


class GuildAIConnection(AuthorshipMixin, table=True):
    __tablename__ = "guild_ai_connections"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: Optional[int] = Field(
        default=None, foreign_key="guilds.id", nullable=True, index=True
    )
    label: str = Field(sa_column=Column(String(100), nullable=False))
    provider: str = Field(sa_column=Column(String(50), nullable=False))
    base_url: Optional[str] = Field(
        default=None, sa_column=Column(String(1000), nullable=True)
    )
    model: Optional[str] = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    api_key_encrypted: Optional[str] = Field(
        default=None, sa_column=Column(String(2000), nullable=True)
    )
    enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    is_default: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # Whether members may attach their own key to this connection. When false,
    # this connection uses its own shared key only (members can't override).
    allow_member_keys: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

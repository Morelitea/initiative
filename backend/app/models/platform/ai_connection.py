"""Operator-owned AI connections (platform config mode).

The single source of truth for ``ai_config_mode == "platform"``: the
operator configures one or more AI providers here (public table), and every
guild uses them. Guild members attach their own keys per-guild
(``guild_ai_member_keys``) referencing these by ``(scope="platform", id)``.
Read on the request path via an in-process cache, not per-request DB reads.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, String
from sqlmodel import Field, SQLModel
from pydantic import ConfigDict


class AIConnectionColumns(SQLModel):
    """The columns of an AI connection, shared by the operator's table here
    and a guild's own (``GuildAIConnection``).

    Declared without ``sa_column`` so each table builds its own Column.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    label: str = Field(sa_type=String(100), nullable=False)
    provider: str = Field(sa_type=String(50), nullable=False)
    base_url: Optional[str] = Field(default=None, sa_type=String(1000), nullable=True)
    model: Optional[str] = Field(default=None, sa_type=String(500), nullable=True)
    enabled: bool = Field(
        default=True, nullable=False, sa_column_kwargs={"server_default": "true"}
    )
    is_default: bool = Field(
        default=False, nullable=False, sa_column_kwargs={"server_default": "false"}
    )
    # Whether members may attach their own key to this connection. When false,
    # this connection uses its own shared key only (members can't override).
    allow_member_keys: bool = Field(
        default=True, nullable=False, sa_column_kwargs={"server_default": "true"}
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
        nullable=False,
    )


class PlatformAIConnection(AIConnectionColumns, table=True):
    __tablename__ = "platform_ai_connections"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    api_key_encrypted: Optional[str] = Field(
        default=None, sa_type=String(2000), nullable=True
    )

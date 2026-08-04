"""Operator-owned AI connections (platform config mode).

The single source of truth for ``ai_config_mode == "platform"``: the
operator configures one or more AI providers here (public table), and every
guild uses them. Guild members attach their own keys per-guild
(``guild_ai_member_keys``) referencing these by ``(scope="platform", id)``.
Read on the request path via an in-process cache, not per-request DB reads.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, String
from sqlmodel import Field, SQLModel
from pydantic import ConfigDict


class PlatformAIConnection(SQLModel, table=True):
    __tablename__ = "platform_ai_connections"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
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

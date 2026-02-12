from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Column, DateTime, Integer, String
from sqlmodel import Field, SQLModel
from pydantic import ConfigDict


class OIDCMappingTargetType(str, Enum):
    guild = "guild"
    initiative = "initiative"


class OIDCClaimMapping(SQLModel, table=True):
    __tablename__ = "oidc_claim_mappings"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    claim_value: str = Field(
        max_length=500,
        sa_column=Column(String(500), nullable=False),
    )
    target_type: OIDCMappingTargetType = Field(
        sa_column=Column(String(20), nullable=False),
    )
    guild_id: int = Field(
        sa_column=Column(
            Integer,
            sa.ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    guild_role: str = Field(
        max_length=20,
        sa_column=Column(String(20), nullable=False, server_default="member"),
    )
    initiative_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            sa.ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    initiative_role_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            sa.ForeignKey("initiative_roles.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

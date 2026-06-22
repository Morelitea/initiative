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
    # --- ARCHITECTURE DEBT: deliberate, documented, not an oversight ---
    # These are plain integer columns, NOT foreign keys.
    #
    # Why it's wrong: this is a PLATFORM table (lives in `public`, shared across
    # all guilds), but `initiatives` / `initiative_roles` are GUILD-SCOPED — under
    # schema-per-guild they move into per-guild schemas. So these columns reach
    # from shared data down into per-guild data, crossing the tenancy boundary.
    # A real FK can't span that (the target lives in a different schema per row),
    # so there is no DB-level referential integrity here: nothing stops a stale
    # or wrong id, and nothing cleans these up when an initiative/role is deleted.
    #
    # The clean fix (if this is ever worth it): move initiative-level OIDC
    # mappings into a separate GUILD-SCOPED table that lives alongside initiatives,
    # where the FKs are intra-schema and valid; keep this platform table
    # guild-target only. We chose not to, because OIDC->initiative provisioning is
    # a niche self-hoster feature and didn't justify the split.
    #
    # Guardrails that compensate for the missing FK:
    #   - the create endpoint (settings.py) validates the initiative/role exists
    #     and belongs to the mapping's guild before inserting;
    #   - oidc_sync skips any initiative/role reference that no longer resolves,
    #     so a dangling row can't crash a login sync.
    initiative_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )
    initiative_role_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

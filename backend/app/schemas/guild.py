from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.guild import GuildRole


class GuildBase(BaseModel):
    name: str
    description: Optional[str] = None
    icon_base64: Optional[str] = None


class GuildCreate(GuildBase):
    pass


class GuildRead(GuildBase):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    role: GuildRole
    position: int
    created_at: datetime
    updated_at: datetime


class GuildInviteCreate(BaseModel):
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = Field(default=1, ge=1)
    invitee_email: Optional[EmailStr] = None


class GuildInviteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    code: str
    guild_id: int
    created_by_user_id: Optional[int]
    expires_at: Optional[datetime]
    max_uses: Optional[int]
    uses: int
    invitee_email: Optional[str]
    created_at: datetime


class GuildInviteAcceptRequest(BaseModel):
    code: str


class GuildInviteStatus(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    code: str
    guild_id: Optional[int] = None
    guild_name: Optional[str] = None
    is_valid: bool
    reason: Optional[str] = None
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = None
    uses: Optional[int] = None


class GuildUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    icon_base64: Optional[str] = None


class GuildOrderUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    guild_ids: list[int] = Field(min_length=1, alias="guildIds")


class GuildSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    name: str
    icon_base64: Optional[str] = None


class GuildMembershipUpdate(BaseModel):
    """Schema for updating a user's guild membership role."""
    role: GuildRole


class LeaveGuildEligibilityResponse(BaseModel):
    """Response for checking if a user can leave a guild."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    can_leave: bool
    is_last_admin: bool
    sole_pm_initiatives: list[str] = []

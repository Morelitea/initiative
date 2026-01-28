"""Admin-related schemas for platform administration."""

from pydantic import BaseModel

from app.models.user import UserRole


class PlatformRoleUpdate(BaseModel):
    """Schema for updating a user's platform role."""
    role: UserRole


class PlatformAdminCountResponse(BaseModel):
    """Response schema for platform admin count."""
    count: int

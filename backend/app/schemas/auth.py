from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class VerificationSendResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    status: str


class VerificationConfirmRequest(BaseModel):
    token: str = Field(min_length=10)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetSubmit(BaseModel):
    token: str = Field(min_length=10)
    password: str = Field(min_length=8, max_length=256)


# Device token schemas for mobile app authentication


class DeviceTokenRequest(BaseModel):
    """Request body for creating a device token."""

    email: EmailStr
    password: str = Field(min_length=1)
    device_name: str = Field(min_length=1, max_length=255)


class DeviceTokenResponse(BaseModel):
    """Response containing the device token."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    device_token: str
    token_type: str = "device_token"


class DeviceTokenInfo(BaseModel):
    """Information about a device token (for listing/management)."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    device_name: Optional[str]
    created_at: datetime

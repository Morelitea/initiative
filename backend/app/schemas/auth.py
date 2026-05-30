from datetime import datetime
from typing import Optional

from pydantic import ConfigDict, EmailStr, Field

from app.schemas.base import SanitizedBaseModel


class VerificationSendResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    status: str


class VerificationConfirmRequest(SanitizedBaseModel):
    token: str = Field(min_length=10)


class PasswordResetRequest(SanitizedBaseModel):
    email: EmailStr


class PasswordResetSubmit(SanitizedBaseModel):
    token: str = Field(min_length=10)
    # ``max_length`` is a cheap DoS gate so we don't argon2-hash a
    # multi-megabyte payload. The min length and breach checks live in
    # ``app.core.password_policy`` and are invoked from the endpoint,
    # so all policy failures surface with a flat error code from
    # ``PasswordMessages`` that ``errors.json`` can map.
    password: str = Field(max_length=256)


# Device token schemas for mobile app authentication


class DeviceTokenRequest(SanitizedBaseModel):
    """Request body for creating a device token."""

    email: EmailStr
    password: str = Field(min_length=1)
    device_name: str = Field(min_length=1, max_length=255)


class DeviceTokenResponse(SanitizedBaseModel):
    """Response containing the device token."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    device_token: str
    token_type: str = "device_token"


class DeviceTokenInfo(SanitizedBaseModel):
    """Information about a device token (for listing/management)."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    device_name: Optional[str]
    created_at: datetime

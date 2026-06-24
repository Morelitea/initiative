from datetime import datetime
from typing import Optional

from pydantic import ConfigDict, EmailStr, Field

from app.schemas.base import RawTextStr, SanitizedBaseModel


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
    password: RawTextStr = Field(max_length=256)


# Device token schemas for mobile app authentication


class DeviceTokenRequest(SanitizedBaseModel):
    """Request body for creating a device token."""

    email: EmailStr
    password: RawTextStr = Field(min_length=1)
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


class UploadTokenResponse(SanitizedBaseModel):
    """Short-lived, uploads-scoped credential for native media loads.

    Native (Capacitor) <img>/<iframe> tags can't send the Authorization header
    or the HttpOnly session cookie, so they carry auth as a ``?token=`` query
    param. This token is accepted only by the /uploads + document-download
    routes and expires quickly, so a leak via logs/history/Referer is harmless
    compared with putting the 7-day session JWT in the URL. ``expires_in`` is
    the lifetime in seconds so the SPA can refresh before it lapses.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    upload_token: str
    token_type: str = "upload_token"
    expires_in: int

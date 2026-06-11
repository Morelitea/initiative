from typing import Optional

from pydantic import ConfigDict, Field

from app.schemas.base import RawTextStr, SanitizedBaseModel


class PushTokenRegisterRequest(SanitizedBaseModel):
    """Request body for registering a push notification token."""

    push_token: str = Field(min_length=1, max_length=512)
    platform: str = Field(pattern="^(android|ios)$")
    device_token_id: Optional[int] = None


class PushTokenUnregisterRequest(SanitizedBaseModel):
    """Request body for unregistering a push notification token."""

    push_token: str = Field(min_length=1, max_length=512)


class PushTokenResponse(SanitizedBaseModel):
    """Generic response for push token operations."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    status: str


class FCMConfigResponse(SanitizedBaseModel):
    """Public FCM configuration for mobile app initialization.

    Only exposes public fields (API key, project ID, sender ID).
    Does NOT expose service account credentials.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    enabled: bool
    project_id: Optional[str] = None
    application_id: Optional[str] = None
    api_key: Optional[RawTextStr] = None
    sender_id: Optional[str] = None

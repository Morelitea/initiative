from typing import Optional

from pydantic import BaseModel, Field


class PushTokenRegisterRequest(BaseModel):
    """Request body for registering a push notification token."""

    push_token: str = Field(min_length=1, max_length=512)
    platform: str = Field(pattern="^(android|ios)$")
    device_token_id: Optional[int] = None


class PushTokenUnregisterRequest(BaseModel):
    """Request body for unregistering a push notification token."""

    push_token: str = Field(min_length=1, max_length=512)


class PushTokenResponse(BaseModel):
    """Generic response for push token operations."""

    status: str


class FCMConfigResponse(BaseModel):
    """Public FCM configuration for mobile app initialization.

    Only exposes public fields (API key, project ID, sender ID).
    Does NOT expose service account credentials.
    """

    enabled: bool
    project_id: Optional[str] = None
    application_id: Optional[str] = None
    api_key: Optional[str] = None
    sender_id: Optional[str] = None

"""Wire shapes of the app platform's token endpoint, install listing and
consent requests.

The token endpoint speaks OAuth 2.0 (RFC 6749): its success and error bodies
are the ones that specification defines, and an error's ``error`` is a
protocol value rather than text for a person to read.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.platform.identity_ref import REF_MAX_LENGTH
from app.schemas.base import TitleStr
from app.models.tenant.app_member_consent import (
    LABEL_MAX_LENGTH,
    PURPOSE_MAX_LENGTH,
    ConsentAccess,
    ConsentStatus,
    is_valid_purpose,
)


class AppAccessTokenResponse(BaseModel):
    """A successful token response (RFC 6749 §5.1)."""

    access_token: str
    token_type: str = "Bearer"
    #: Seconds until the token stops being accepted.
    expires_in: int
    #: The scopes the token carries, space-separated. Empty for an app token.
    scope: str


class AppOAuthErrorResponse(BaseModel):
    """An error response (RFC 6749 §5.2)."""

    error: str
    error_description: str


class AppInstallationRead(BaseModel):
    """One install of the calling app."""

    #: What the app calls the community it is installed in. Passed back as
    #: ``installation`` to ask for a token there.
    installation: str
    #: The scopes the community has granted it.
    scopes: List[str]
    #: The initiatives it is placed in.
    initiatives: List[int]
    #: Switched on, in a community in use: a token can be issued for it. An
    #: install that is off or whose community is paused is listed as inactive,
    #: and one that is gone is not listed.
    active: bool


class AppConsentRequestCreate(BaseModel):
    """An app asking one member to let it act as them, for one purpose."""

    model_config = ConfigDict(extra="forbid")

    #: The member, by the reference this install holds for them.
    member: str = Field(min_length=1, max_length=REF_MAX_LENGTH)
    #: The app's own id for what it wants to do as the member; absent for
    #: app-wide consent.
    purpose: Optional[str] = None
    #: What the purpose is, in the app's own words. The member reads it as the
    #: app's.
    label: TitleStr = Field(min_length=1, max_length=LABEL_MAX_LENGTH)
    #: The one initiative the purpose is bound to, when it is.
    initiative_id: Optional[int] = Field(default=None, gt=0, le=2**31 - 1)
    access: ConsentAccess

    @field_validator("purpose")
    @classmethod
    def _purpose(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not is_valid_purpose(value):
            raise ValueError(
                f"purpose is 1 to {PURPOSE_MAX_LENGTH} letters, digits or -_.:/@"
            )
        return value

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        value = value.strip()
        if not value or not value.isprintable():
            raise ValueError("label is printable text")
        return value


class AppConsentRequestRead(BaseModel):
    """A request to act as a member, as it stands."""

    member: str
    purpose: Optional[str] = None
    label: str
    initiative_id: Optional[int] = None
    requested_access: ConsentAccess
    #: ``pending`` until the member answers; then ``granted``, ``declined``, or
    #: ``revoked`` when they withdrew what they allowed.
    status: ConsentStatus
    #: What the member allowed, while it stands.
    granted_access: Optional[ConsentAccess] = None
    requested_at: datetime

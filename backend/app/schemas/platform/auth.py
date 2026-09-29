import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import ConfigDict, EmailStr, Field, field_validator

from app.core.user_agents import ClientKind
from app.schemas.base import RawTextStr, SanitizedBaseModel


class LoginProviderEntry(SanitizedBaseModel):
    """One sign-in provider offered on the login page (non-secret metadata)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    # Registry row id — what the guild auth-policy endpoints identify a
    # provider by. None only for a platform entry not yet reconciled to a row.
    id: Optional[int] = None
    slug: str
    display_name: str
    kind: str
    login_url: str
    icon: Optional[str] = None
    button_style: Optional[str] = None


class LoginProvidersResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    providers: List[LoginProviderEntry]
    # Guild-addressed listings only: the guild's display name for its login
    # page. Set exactly when the listing is non-empty, so a guild without
    # login-ready providers stays indistinguishable from an unknown id.
    guild_name: Optional[str] = None


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


class DeviceTokenExchangeRequest(SanitizedBaseModel):
    """A device token offered in return for a session."""

    device_token: str


#: RFC 7636 §4.1: a verifier is 43–128 unreserved characters.
_VERIFIER_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


class NativeSignInRedeem(SanitizedBaseModel):
    """The code a sign-in in the phone's browser came back with, and the PKCE
    verifier the app began it with."""

    code: str = Field(max_length=4096)
    code_verifier: str = Field(min_length=43, max_length=128)

    @field_validator("code_verifier")
    @classmethod
    def _unreserved(cls, value: str) -> str:
        if not set(value) <= _VERIFIER_CHARS:
            raise ValueError("code_verifier holds a character RFC 7636 does not allow")
        return value


class RefreshRequest(SanitizedBaseModel):
    """How a caller with no cookie presents its refresh token.

    The browser sends nothing here — its refresh token is a cookie it cannot
    read. A native client keeps its own in secure storage, so it has to hand it
    over explicitly.
    """

    refresh_token: Optional[str] = None


class DeviceTokenResponse(SanitizedBaseModel):
    """What a native sign-in is handed.

    The device token is what older builds read, and it keeps working. Beside it
    is a session of the ordinary kind — an access token and the refresh token
    that renews it — so a build that prefers them has them from the first
    sign-in. A client that does not know the fields ignores them.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    device_token: str
    token_type: str = "device_token"
    #: The session opened alongside. ``expires_in`` is the access token's life
    #: in seconds; the refresh token belongs in the platform's secure storage.
    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None


class DeviceTokenInfo(SanitizedBaseModel):
    """Information about a device token (for listing/management)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    device_name: Optional[str]
    created_at: datetime


class SignedInSessionInfo(SanitizedBaseModel):
    """One browser session, as the account's own "where you're signed in" list
    shows it.

    Beside it in that list sit the account's native devices, which are
    :class:`DeviceTokenInfo` and a different credential — this is the rotating
    kind a browser holds. ``started_at`` is the sign-in, not the last renewal,
    so a browser left open for a month reads as a month old.

    ``label`` is derived from the user agent (``core.user_agents``), because
    only a native sign-in is handed a name to go by. ``is_current`` marks the
    session doing the asking, which the list shows rather than offers to end.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: uuid.UUID
    label: Optional[str]
    kind: ClientKind
    ip: Optional[str]
    started_at: datetime
    last_used_at: Optional[datetime]
    is_current: bool


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


class UsernameAvailabilityResponse(SanitizedBaseModel):
    """Whether a name part can still be handed out.

    Almost always ``true``: the number behind a name is what resolves
    contention, so this answers about the two cases that survive — a reserved
    or malformed name, and one whose ten thousand numbers are all taken.
    ``reason`` carries the flat code for those.
    """

    available: bool
    reason: Optional[str] = None

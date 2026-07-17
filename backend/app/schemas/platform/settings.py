from typing import List, Literal, Optional

from pydantic import ConfigDict, EmailStr, Field, field_validator

from app.models.platform.app_setting import AuthScope
from app.schemas.base import RawTextStr, SanitizedBaseModel


class AuthScopeUpdate(SanitizedBaseModel):
    """Switch where login is configured (platform-wide vs per-guild)."""

    scope: AuthScope


class AuthProviderAdminRead(SanitizedBaseModel):
    """One registry provider for the operator admin — never the secret."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    slug: str
    display_name: str
    kind: str
    enabled: bool
    issuer: Optional[str] = None
    client_id: Optional[str] = None
    scopes: Optional[str] = None
    role_claim_path: Optional[str] = None
    allow_jit: bool
    icon: Optional[str] = None
    button_style: Optional[str] = None
    # Whether a client secret is stored (write-only; its value is never read
    # back on any request path).
    secret_set: bool = False
    # The platform provider row is configured through the SSO settings form,
    # not this CRUD.
    reserved: bool = False


_SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"


class AuthProviderCreate(SanitizedBaseModel):
    """A new operator-global login provider. Complete rows only — the login
    flow refuses config-incomplete providers, so the CRUD does too."""

    slug: str = Field(pattern=_SLUG_PATTERN)
    display_name: str = Field(min_length=1, max_length=128)
    kind: Literal["oidc"] = "oidc"
    enabled: bool = True
    # https-only, matching discovery's rule — surfaced at write time instead
    # of as a stray error mid-login.
    issuer: str = Field(pattern=r"^https://.+")
    client_id: str = Field(min_length=1)
    client_secret: Optional[RawTextStr] = None  # None = public / PKCE-only
    scopes: Optional[str] = Field(default="openid email profile", max_length=512)
    role_claim_path: Optional[str] = Field(default=None, max_length=256)
    allow_jit: bool = True
    icon: Optional[str] = Field(default=None, max_length=64)
    button_style: Optional[str] = Field(default=None, max_length=64)


class AuthProviderUpdate(SanitizedBaseModel):
    """Partial update. ``client_secret``: absent = keep, empty = clear,
    value = replace. The slug is immutable — it is the identity the login
    URLs, flow states, and linked identities hang off."""

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    enabled: Optional[bool] = None
    issuer: Optional[str] = Field(default=None, pattern=r"^https://.+")
    client_id: Optional[str] = Field(default=None, min_length=1)
    client_secret: Optional[RawTextStr] = None
    scopes: Optional[str] = Field(default=None, max_length=512)
    role_claim_path: Optional[str] = Field(default=None, max_length=256)
    allow_jit: Optional[bool] = None
    icon: Optional[str] = Field(default=None, max_length=64)
    button_style: Optional[str] = Field(default=None, max_length=64)

    @field_validator("display_name", "issuer", "client_id", "enabled", "allow_jit")
    @classmethod
    def _no_explicit_null(cls, value, info):
        """Absent means keep; an explicit null would strip config a login-ready
        row requires (the login flow refuses config-incomplete providers)."""
        if value is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return value


class OIDCSettingsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    auth_scope: AuthScope
    enabled: bool
    issuer: Optional[str] = None
    client_id: Optional[str] = None
    redirect_uri: Optional[str] = None
    post_login_redirect: Optional[str] = None
    mobile_redirect_uri: Optional[str] = None
    provider_name: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)


class OIDCSettingsUpdate(SanitizedBaseModel):
    enabled: bool
    issuer: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[RawTextStr] = None
    redirect_uri: Optional[str] = None
    post_login_redirect: Optional[str] = None
    provider_name: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)


class InterfaceSettingsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    light_accent_color: str
    dark_accent_color: str
    # Non-secret posture info: the login page and guild settings need to know
    # where sign-in is configured without a config.manage read. Required — a
    # construction site that forgets it must fail, not silently claim platform.
    auth_scope: AuthScope


class InterfaceSettingsUpdate(SanitizedBaseModel):
    light_accent_color: str
    dark_accent_color: str


class EmailSettingsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    host: Optional[str] = None
    port: Optional[int] = None
    secure: bool = False
    reject_unauthorized: bool = True
    username: Optional[str] = None
    has_password: bool = False
    from_address: Optional[str] = None
    test_recipient: Optional[EmailStr] = None


class EmailSettingsUpdate(SanitizedBaseModel):
    host: Optional[str] = None
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    secure: bool = False
    reject_unauthorized: bool = True
    username: Optional[str] = None
    password: Optional[RawTextStr] = None
    from_address: Optional[str] = None
    test_recipient: Optional[EmailStr] = None


class EmailTestRequest(SanitizedBaseModel):
    recipient: Optional[EmailStr] = None


# --- Object storage schemas ---


class StorageSettingsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    backend: Literal["local", "s3"] = "local"
    s3_bucket: Optional[str] = None
    s3_region: str = "us-east-1"
    s3_endpoint_url: Optional[str] = None
    s3_access_key_id: Optional[str] = None
    has_secret_access_key: bool = False
    s3_use_path_style: bool = False
    s3_kms_key_id: Optional[str] = None
    s3_local_fallback: bool = False


class StorageSettingsUpdate(SanitizedBaseModel):
    backend: Literal["local", "s3"] = "local"
    s3_bucket: Optional[str] = None
    s3_region: str = "us-east-1"
    s3_endpoint_url: Optional[str] = None
    s3_access_key_id: Optional[str] = None
    s3_secret_access_key: Optional[RawTextStr] = None
    s3_use_path_style: bool = False
    s3_kms_key_id: Optional[str] = None
    s3_local_fallback: bool = False


class StorageTestResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    success: bool
    message: str


class StorageBackfillStatusResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    status: Literal["idle", "running", "complete", "failed"] = "idle"
    copied: int = 0
    skipped: int = 0
    failed: int = 0
    hash_mismatches: int = 0
    failed_keys: List[str] = Field(default_factory=list)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None


# --- OIDC Claim Mapping schemas ---


class OIDCClaimMappingCreate(SanitizedBaseModel):
    claim_value: str = Field(min_length=1, max_length=500)
    target_type: str  # "guild" or "initiative"
    guild_id: int
    guild_role: str = "member"
    initiative_id: Optional[int] = None
    initiative_role_id: Optional[int] = None


class OIDCClaimMappingUpdate(SanitizedBaseModel):
    claim_value: Optional[str] = Field(default=None, min_length=1, max_length=500)
    target_type: Optional[str] = None
    guild_id: Optional[int] = None
    guild_role: Optional[str] = None
    initiative_id: Optional[int] = None
    initiative_role_id: Optional[int] = None


class OIDCClaimMappingRead(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    claim_value: str
    target_type: str
    guild_id: int
    guild_role: str
    initiative_id: Optional[int] = None
    initiative_role_id: Optional[int] = None
    guild_name: Optional[str] = None
    initiative_name: Optional[str] = None
    initiative_role_name: Optional[str] = None


class OIDCClaimPathUpdate(SanitizedBaseModel):
    claim_path: Optional[str] = Field(default=None, max_length=500)


class OIDCMappingsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    claim_path: Optional[str] = None
    mappings: List[OIDCClaimMappingRead] = Field(default_factory=list)

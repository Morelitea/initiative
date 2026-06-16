from typing import List, Optional

from pydantic import ConfigDict, EmailStr, Field

from app.schemas.base import RawTextStr, SanitizedBaseModel


class OIDCSettingsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

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


class InterfaceSettingsUpdate(SanitizedBaseModel):
    light_accent_color: str
    dark_accent_color: str


class RoleLabelsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    admin: str
    project_manager: str
    member: str


class RoleLabelsUpdate(SanitizedBaseModel):
    admin: Optional[str] = Field(default=None, min_length=1, max_length=64)
    project_manager: Optional[str] = Field(default=None, min_length=1, max_length=64)
    member: Optional[str] = Field(default=None, min_length=1, max_length=64)


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

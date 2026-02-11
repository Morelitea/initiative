from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

class OIDCSettingsResponse(BaseModel):
    enabled: bool
    discovery_url: Optional[str] = None
    client_id: Optional[str] = None
    redirect_uri: Optional[str] = None
    post_login_redirect: Optional[str] = None
    mobile_redirect_uri: Optional[str] = None
    provider_name: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)


class OIDCSettingsUpdate(BaseModel):
    enabled: bool
    discovery_url: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    redirect_uri: Optional[str] = None
    post_login_redirect: Optional[str] = None
    provider_name: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)


class InterfaceSettingsResponse(BaseModel):
    light_accent_color: str
    dark_accent_color: str


class InterfaceSettingsUpdate(BaseModel):
    light_accent_color: str
    dark_accent_color: str


class RoleLabelsResponse(BaseModel):
    admin: str
    project_manager: str
    member: str


class RoleLabelsUpdate(BaseModel):
    admin: Optional[str] = Field(default=None, min_length=1, max_length=64)
    project_manager: Optional[str] = Field(default=None, min_length=1, max_length=64)
    member: Optional[str] = Field(default=None, min_length=1, max_length=64)


class EmailSettingsResponse(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    secure: bool = False
    reject_unauthorized: bool = True
    username: Optional[str] = None
    has_password: bool = False
    from_address: Optional[str] = None
    test_recipient: Optional[EmailStr] = None


class EmailSettingsUpdate(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    secure: bool = False
    reject_unauthorized: bool = True
    username: Optional[str] = None
    password: Optional[str] = None
    from_address: Optional[str] = None
    test_recipient: Optional[EmailStr] = None


class EmailTestRequest(BaseModel):
    recipient: Optional[EmailStr] = None


# --- OIDC Claim Mapping schemas ---

class OIDCClaimMappingCreate(BaseModel):
    claim_value: str = Field(min_length=1, max_length=500)
    target_type: str  # "guild" or "initiative"
    guild_id: int
    guild_role: str = "member"
    initiative_id: Optional[int] = None
    initiative_role_id: Optional[int] = None


class OIDCClaimMappingUpdate(BaseModel):
    claim_value: Optional[str] = Field(default=None, min_length=1, max_length=500)
    target_type: Optional[str] = None
    guild_id: Optional[int] = None
    guild_role: Optional[str] = None
    initiative_id: Optional[int] = None
    initiative_role_id: Optional[int] = None


class OIDCClaimMappingRead(BaseModel):
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


class OIDCClaimPathUpdate(BaseModel):
    claim_path: Optional[str] = Field(default=None, max_length=500)


class OIDCMappingsResponse(BaseModel):
    claim_path: Optional[str] = None
    mappings: List[OIDCClaimMappingRead] = Field(default_factory=list)

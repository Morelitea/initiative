from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import UserRead


class RegistrationSettingsUpdate(BaseModel):
    auto_approved_domains: List[str] = Field(default_factory=list)


class RegistrationSettingsResponse(BaseModel):
    auto_approved_domains: List[str] = Field(default_factory=list)
    pending_users: List[UserRead] = Field(default_factory=list)


class OIDCSettingsResponse(BaseModel):
    enabled: bool
    discovery_url: Optional[str] = None
    client_id: Optional[str] = None
    redirect_uri: Optional[str] = None
    post_login_redirect: Optional[str] = None
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

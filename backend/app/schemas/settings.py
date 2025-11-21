from typing import List, Optional

from pydantic import BaseModel, Field

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

from typing import Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class AppSetting(SQLModel, table=True):
    __tablename__ = "app_settings"

    id: Optional[int] = Field(default=1, primary_key=True)
    auto_approved_domains: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )
    oidc_enabled: bool = Field(default=False, nullable=False)
    oidc_discovery_url: Optional[str] = None
    oidc_client_id: Optional[str] = None
    oidc_client_secret: Optional[str] = None
    oidc_provider_name: Optional[str] = None
    oidc_scopes: list[str] = Field(
        default_factory=lambda: ["openid", "profile", "email"],
        sa_column=Column(JSON, nullable=False, server_default='["openid","profile","email"]'),
    )

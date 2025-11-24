import json
from typing import Optional

from sqlalchemy import Column, JSON, String
from sqlmodel import Field, SQLModel

DEFAULT_ROLE_LABELS = {
    "admin": "Admin",
    "project_manager": "Project manager",
    "member": "Member",
}


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
    light_accent_color: str = Field(
        default="#2563eb",
        sa_column=Column(String(20), nullable=False, server_default="#2563eb"),
    )
    dark_accent_color: str = Field(
        default="#60a5fa",
        sa_column=Column(String(20), nullable=False, server_default="#60a5fa"),
    )
    role_labels: dict[str, str] = Field(
        default_factory=lambda: DEFAULT_ROLE_LABELS.copy(),
        sa_column=Column(JSON, nullable=False, server_default=json.dumps(DEFAULT_ROLE_LABELS)),
    )

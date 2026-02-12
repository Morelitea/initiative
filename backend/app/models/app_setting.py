import json
from typing import Optional

from sqlalchemy import Boolean, Column, Integer, JSON, String
from sqlmodel import Field, SQLModel
from pydantic import ConfigDict

DEFAULT_ROLE_LABELS = {
    "admin": "Admin",
    "project_manager": "Project manager",
    "member": "Member",
}


class AppSetting(SQLModel, table=True):
    __tablename__ = "app_settings"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int = Field(default=1, primary_key=True)

    oidc_enabled: bool = Field(default=False, nullable=False)
    oidc_issuer: Optional[str] = None
    oidc_client_id: Optional[str] = None
    oidc_client_secret: Optional[str] = None
    oidc_provider_name: Optional[str] = None
    oidc_scopes: list[str] = Field(
        default_factory=lambda: ["openid", "profile", "email", "offline_access"],
        sa_column=Column(JSON, nullable=False, server_default='["openid","profile","email","offline_access"]'),
    )
    oidc_role_claim_path: Optional[str] = Field(
        default=None,
        sa_column=Column(String(500), nullable=True),
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

    smtp_host: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    smtp_port: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    smtp_secure: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    smtp_reject_unauthorized: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    smtp_username: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    smtp_password: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    smtp_from_address: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    smtp_test_recipient: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))

    # AI Settings
    ai_enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    ai_provider: Optional[str] = Field(default=None, sa_column=Column(String(50), nullable=True))
    ai_api_key: Optional[str] = Field(default=None, sa_column=Column(String(2000), nullable=True))
    ai_base_url: Optional[str] = Field(default=None, sa_column=Column(String(1000), nullable=True))
    ai_model: Optional[str] = Field(default=None, sa_column=Column(String(500), nullable=True))
    ai_allow_guild_override: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    ai_allow_user_override: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )

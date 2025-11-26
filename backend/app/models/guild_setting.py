import json
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, Column, Integer, JSON, String
from sqlmodel import Field, SQLModel, Relationship
from pydantic import ConfigDict

if TYPE_CHECKING:  # pragma: no cover
    from app.models.guild import Guild

DEFAULT_ROLE_LABELS = {
    "admin": "Admin",
    "project_manager": "Project manager",
    "member": "Member",
}


class GuildSetting(SQLModel, table=True):
    __tablename__ = "guild_settings"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", unique=True, nullable=False)
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

    guild: Optional["Guild"] = Relationship(back_populates="settings", sa_relationship_kwargs={"uselist": False})

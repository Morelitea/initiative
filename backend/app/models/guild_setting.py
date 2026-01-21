from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, String
from sqlmodel import Field, SQLModel, Relationship
from pydantic import ConfigDict

if TYPE_CHECKING:  # pragma: no cover
    from app.models.guild import Guild


class GuildSetting(SQLModel, table=True):
    __tablename__ = "guild_settings"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", unique=True, nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    # AI Settings (nullable = inherit from platform)
    ai_enabled: Optional[bool] = Field(default=None, sa_column=Column(Boolean, nullable=True))
    ai_provider: Optional[str] = Field(default=None, sa_column=Column(String(50), nullable=True))
    ai_api_key: Optional[str] = Field(default=None, sa_column=Column(String(2000), nullable=True))
    ai_base_url: Optional[str] = Field(default=None, sa_column=Column(String(1000), nullable=True))
    ai_model: Optional[str] = Field(default=None, sa_column=Column(String(500), nullable=True))
    ai_allow_user_override: Optional[bool] = Field(default=None, sa_column=Column(Boolean, nullable=True))

    guild: Optional["Guild"] = Relationship(back_populates="settings", sa_relationship_kwargs={"uselist": False})

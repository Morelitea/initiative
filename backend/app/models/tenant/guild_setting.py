from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Column, DateTime, Integer
from sqlmodel import Field
from pydantic import ConfigDict

from app.models.tenant._mixins import CreatedByMixin

if TYPE_CHECKING:  # pragma: no cover
    pass


class GuildSetting(CreatedByMixin, table=True):
    __tablename__ = "guild_settings"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    # Trash retention. NULL means "never auto-purge". Default 90 days.
    retention_days: Optional[int] = Field(
        default=90,
        sa_column=Column(Integer, nullable=True, server_default="90"),
    )

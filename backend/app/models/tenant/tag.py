from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Column, DateTime, String
from sqlmodel import Field, Relationship
from pydantic import ConfigDict

from app.models.tenant._mixins import CreatedByMixin, SoftDeleteMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.platform.guild import Guild


class Tag(CreatedByMixin, SoftDeleteMixin, table=True):
    """Guild-scoped tag for categorizing tasks, projects, and documents.

    Supports nested tag naming via "/" convention (e.g., "books/fiction").
    The "/" is purely visual/organizational - no parent-child DB relationships.
    """

    __tablename__ = "tags"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)
    name: str = Field(
        sa_column=Column(String(length=100), nullable=False),
    )
    color: str = Field(
        default="#6366F1",
        sa_column=Column(String(length=9), nullable=False, server_default="#6366F1"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    guild: Optional["Guild"] = Relationship()

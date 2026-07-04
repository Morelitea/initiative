from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, Text
from sqlmodel import Field, SQLModel


# Allowed values mirror the CHECK constraint on the table. Keep in sync with
# migration ``20260523_0088_create_recent_views.py``.
RECENT_ENTITY_TYPES: tuple[str, ...] = (
    "project",
    "document",
    "queue",
    "counter_group",
)


class RecentView(SQLModel, table=True):
    """Polymorphic record of a recently opened guild-scoped entity.

    Composite primary key is ``(user_id, entity_type, entity_id)``. ``guild_id``
    is populated by a DB trigger from the underlying entity table so RLS can
    enforce isolation without us re-deriving it in Python.
    """

    __tablename__ = "recent_views"

    user_id: int = Field(foreign_key="users.id", primary_key=True)
    # DDL: unbounded TEXT constrained by ck_recent_views_entity_type, not length
    entity_type: str = Field(sa_column=Column(Text, primary_key=True, nullable=False))
    entity_id: int = Field(primary_key=True)
    guild_id: Optional[int] = Field(
        default=None, foreign_key="guilds.id", nullable=True
    )
    last_viewed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

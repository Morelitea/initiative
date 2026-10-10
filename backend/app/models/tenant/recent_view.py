from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, Text
from sqlmodel import Field, SQLModel

from app.core.tools import Tool
from app.db.registry_checks import FROM_REGISTRY


# Allowed values, derived from the canonical Tool enum. The CHECK below is
# rendered from them at boot (``app.db.registry_checks``).
RECENT_ENTITY_TYPES: tuple[str, ...] = tuple(t.value for t in Tool)
_ENTITY_TYPE_VALUES = ", ".join(f"'{kind}'" for kind in RECENT_ENTITY_TYPES)


class RecentView(SQLModel, table=True):
    """Polymorphic record of a recently opened guild-scoped entity.

    Composite primary key is ``(user_id, entity_type, entity_id)``. The row is
    in its community's schema, which is what says which community it is; RLS
    resolves the initiative through the entity the row names.
    """

    __tablename__ = "recent_views"
    __table_args__ = (
        CheckConstraint(
            f"entity_type IN ({_ENTITY_TYPE_VALUES})",
            name="ck_recent_views_entity_type",
            info={FROM_REGISTRY: True},
        ),
    )

    user_id: int = Field(foreign_key="users.id", primary_key=True)
    entity_type: str = Field(sa_column=Column(Text, primary_key=True, nullable=False))
    entity_id: int = Field(primary_key=True)
    last_viewed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

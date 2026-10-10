from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import CheckConstraint, Column, DateTime, Text
from sqlmodel import Field, SQLModel

from app.core.tools import CONTENT_KINDS, Tool
from app.db.registry_checks import FROM_REGISTRY


# Opening any tool, or anything inside one (``CONTENT_KINDS``), is recorded. The
# CHECKs below are rendered from their values at boot (``app.db.registry_checks``).
#: The kinds that become tabs.
RECENT_TAB_TYPES: tuple[str, ...] = tuple(t.value for t in Tool)


class ViewSource(str, Enum):
    """Where an open came from."""

    #: A link, an address, a tab, or moving around inside the app.
    direct = "direct"
    #: A search result or the command palette.
    search = "search"


_ENTITY_TYPE_VALUES = ", ".join(f"'{kind}'" for kind in CONTENT_KINDS)
_SOURCE_VALUES = ", ".join(f"'{source.value}'" for source in ViewSource)


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
        CheckConstraint(
            f"source IN ({_SOURCE_VALUES})",
            name="ck_recent_views_source",
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
    #: Where the latest open came from: a :class:`ViewSource` value.
    source: str = Field(
        default=ViewSource.direct.value,
        sa_column=Column(Text, nullable=False, server_default=ViewSource.direct.value),
    )

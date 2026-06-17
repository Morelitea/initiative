from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlmodel import Enum as SQLEnum, Field, Relationship

from app.models._mixins import SoftDeleteMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.initiative import Initiative
    from app.models.resource_grant import ResourceGrant


class CounterViewMode(str, Enum):
    number = "number"
    progress_bar = "progress_bar"
    segmented_clock = "segmented_clock"


class CounterPermissionLevel(str, Enum):
    owner = "owner"
    write = "write"
    read = "read"


class CounterGroup(SoftDeleteMixin, table=True):
    """Initiative-scoped container for a set of related counters."""

    __tablename__ = "counter_groups"
    _owner_field = "created_by_id"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)
    initiative_id: int = Field(foreign_key="initiatives.id", nullable=False, index=True)
    name: str = Field(nullable=False, max_length=255)
    description: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    created_by_id: int = Field(foreign_key="users.id", nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    initiative: Optional["Initiative"] = Relationship(back_populates="counter_groups")
    counters: List["Counter"] = Relationship(
        back_populates="group",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "Counter.position",
        },
    )
    grants: List["ResourceGrant"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(foreign(ResourceGrant.resource_id) == CounterGroup.id, "
                "ResourceGrant.resource_type == 'counter_group')"
            ),
            "viewonly": True,
        }
    )


class Counter(SoftDeleteMixin, table=True):
    """A single named numeric counter inside a counter group."""

    __tablename__ = "counters"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)
    counter_group_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("counter_groups.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    name: str = Field(nullable=False, max_length=255)
    color: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=32), nullable=True),
    )
    count: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(20, 10), nullable=False, server_default="0"),
    )
    min: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric(20, 10), nullable=True),
    )
    max: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric(20, 10), nullable=True),
    )
    step: Decimal = Field(
        default=Decimal("1"),
        sa_column=Column(Numeric(20, 10), nullable=False, server_default="1"),
    )
    initial_count: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(20, 10), nullable=False, server_default="0"),
    )
    view_mode: CounterViewMode = Field(
        default=CounterViewMode.number,
        sa_column=Column(
            SQLEnum(
                CounterViewMode,
                name="counter_view_mode",
                create_type=False,
            ),
            nullable=False,
            server_default="number",
        ),
    )
    position: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(20, 10), nullable=False, server_default="0"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    group: Optional[CounterGroup] = Relationship(back_populates="counters")

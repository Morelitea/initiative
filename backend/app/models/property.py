from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, List, Optional, TYPE_CHECKING

from pydantic import ConfigDict
from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Enum as SQLEnum, Field, Relationship, SQLModel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.document import Document
    from app.models.guild import Guild
    from app.models.task import Task
    from app.models.user import User


class PropertyType(str, Enum):
    """Supported value types for a property definition."""

    text = "text"
    number = "number"
    checkbox = "checkbox"
    date = "date"
    datetime = "datetime"
    url = "url"
    select = "select"
    multi_select = "multi_select"
    user_reference = "user_reference"


class PropertyAppliesTo(str, Enum):
    """Which entity kinds a property definition may attach to."""

    document = "document"
    task = "task"
    both = "both"


class PropertyDefinition(SQLModel, table=True):
    """Guild-scoped custom property definition.

    Mirrors the Tag pattern: definitions live on the guild, values live on
    entity-specific junction tables (``document_property_values`` /
    ``task_property_values``) so they stay SARGable under RLS.
    """

    __tablename__ = "property_definitions"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)
    name: str = Field(
        sa_column=Column(String(length=100), nullable=False),
    )
    type: PropertyType = Field(
        sa_column=Column(
            SQLEnum(
                PropertyType,
                name="property_type",
                create_type=False,
                values_callable=lambda e: [item.value for item in e],
            ),
            nullable=False,
        ),
    )
    applies_to: PropertyAppliesTo = Field(
        default=PropertyAppliesTo.both,
        sa_column=Column(
            SQLEnum(
                PropertyAppliesTo,
                name="property_applies_to",
                create_type=False,
                values_callable=lambda e: [item.value for item in e],
            ),
            nullable=False,
            server_default="both",
        ),
    )
    position: float = Field(
        default=0.0,
        sa_column=Column(Float, nullable=False, server_default="0"),
    )
    color: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=7), nullable=True),
    )
    options: Optional[List[dict]] = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
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
    document_values: List["DocumentPropertyValue"] = Relationship(
        back_populates="property_definition",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    task_values: List["TaskPropertyValue"] = Relationship(
        back_populates="property_definition",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class DocumentPropertyValue(SQLModel, table=True):
    """Typed property value attached to a document."""

    __tablename__ = "document_property_values"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    document_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    property_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("property_definitions.id", ondelete="CASCADE"),
            primary_key=True,
            index=True,
        ),
    )
    value_text: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    value_number: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric, nullable=True),
    )
    value_boolean: Optional[bool] = Field(
        default=None,
        sa_column=Column(Boolean, nullable=True),
    )
    value_date: Optional[date] = Field(
        default=None,
        sa_column=Column(Date, nullable=True),
    )
    value_datetime: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    value_user_id: Optional[int] = Field(
        default=None,
        foreign_key="users.id",
        nullable=True,
    )
    value_json: Optional[Any] = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    document: Optional["Document"] = Relationship(back_populates="property_values")
    property_definition: Optional[PropertyDefinition] = Relationship(
        back_populates="document_values"
    )
    value_user: Optional["User"] = Relationship()


class TaskPropertyValue(SQLModel, table=True):
    """Typed property value attached to a task."""

    __tablename__ = "task_property_values"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    task_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    property_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("property_definitions.id", ondelete="CASCADE"),
            primary_key=True,
            index=True,
        ),
    )
    value_text: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    value_number: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric, nullable=True),
    )
    value_boolean: Optional[bool] = Field(
        default=None,
        sa_column=Column(Boolean, nullable=True),
    )
    value_date: Optional[date] = Field(
        default=None,
        sa_column=Column(Date, nullable=True),
    )
    value_datetime: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    value_user_id: Optional[int] = Field(
        default=None,
        foreign_key="users.id",
        nullable=True,
    )
    value_json: Optional[Any] = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    task: Optional["Task"] = Relationship(back_populates="property_values")
    property_definition: Optional[PropertyDefinition] = Relationship(
        back_populates="task_values"
    )
    value_user: Optional["User"] = Relationship()

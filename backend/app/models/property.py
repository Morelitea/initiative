from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, List, Optional, TYPE_CHECKING

from pydantic import ConfigDict
from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Enum as SQLEnum, Field, Relationship, SQLModel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.calendar_event import CalendarEvent
    from app.models.document import Document
    from app.models.initiative import Initiative
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


class PropertyDefinition(SQLModel, table=True):
    """Initiative-scoped custom property definition.

    Definitions live on a single initiative; values live on entity-specific
    junction tables (``document_property_values`` / ``task_property_values``
    / ``calendar_event_property_values``) so they stay SARGable under RLS.
    """

    __tablename__ = "property_definitions"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    initiative_id: int = Field(foreign_key="initiatives.id", nullable=False, index=True)
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
    # NUMERIC(20, 10) on the DB side; ``asdecimal=False`` keeps the Python
    # value a plain ``float`` so downstream serializers (Pydantic/Orval) don't
    # have to juggle Decimal. Exact representation in Postgres avoids float
    # precision rounding when drag-reorder sets midpoint positions.
    position: float = Field(
        default=0.0,
        sa_column=Column(
            Numeric(20, 10, asdecimal=False), nullable=False, server_default="0"
        ),
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

    initiative: Optional["Initiative"] = Relationship()
    document_values: List["DocumentPropertyValue"] = Relationship(
        back_populates="property_definition",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    task_values: List["TaskPropertyValue"] = Relationship(
        back_populates="property_definition",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    event_values: List["CalendarEventPropertyValue"] = Relationship(
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


class CalendarEventPropertyValue(SQLModel, table=True):
    """Typed property value attached to a calendar event."""

    __tablename__ = "calendar_event_property_values"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    event_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("calendar_events.id", ondelete="CASCADE"),
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

    calendar_event: Optional["CalendarEvent"] = Relationship(back_populates="property_values")
    property_definition: Optional[PropertyDefinition] = Relationship(
        back_populates="event_values"
    )
    value_user: Optional["User"] = Relationship()

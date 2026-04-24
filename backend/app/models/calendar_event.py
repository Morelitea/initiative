from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from pydantic import ConfigDict
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlmodel import Enum as SQLEnum, Field, Relationship, SQLModel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.initiative import Initiative
    from app.models.property import CalendarEventPropertyValue
    from app.models.user import User
    from app.models.tag import Tag
    from app.models.document import Document


class CalendarEvent(SQLModel, table=True):
    """Initiative-scoped calendar event (Google Calendar-like).

    Access is controlled at the initiative level — any initiative member
    with events_enabled can view events, managers can create/edit/delete.
    No per-event DAC.
    """
    __tablename__ = "calendar_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)
    initiative_id: int = Field(foreign_key="initiatives.id", nullable=False, index=True)
    title: str = Field(nullable=False, max_length=255)
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    location: Optional[str] = Field(default=None, max_length=500)
    start_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    end_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    all_day: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    color: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=32), nullable=True),
    )
    recurrence: Optional[str] = Field(
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

    initiative: Optional["Initiative"] = Relationship(back_populates="calendar_events")
    creator: Optional["User"] = Relationship()
    attendees: List["CalendarEventAttendee"] = Relationship(
        back_populates="calendar_event",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    tag_links: List["CalendarEventTag"] = Relationship(
        back_populates="calendar_event",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    document_links: List["CalendarEventDocument"] = Relationship(
        back_populates="calendar_event",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    property_values: List["CalendarEventPropertyValue"] = Relationship(
        back_populates="calendar_event",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class RSVPStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    declined = "declined"
    tentative = "tentative"


class CalendarEventAttendee(SQLModel, table=True):
    """Attendee (invitee) on a calendar event with RSVP status."""
    __tablename__ = "calendar_event_attendees"

    calendar_event_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("calendar_events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    user_id: int = Field(foreign_key="users.id", primary_key=True, index=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False)
    rsvp_status: RSVPStatus = Field(
        default=RSVPStatus.pending,
        sa_column=Column(
            SQLEnum(RSVPStatus, name="rsvp_status", create_type=True),
            nullable=False,
            server_default="pending",
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    calendar_event: Optional[CalendarEvent] = Relationship(back_populates="attendees")
    user: Optional["User"] = Relationship()


class CalendarEventTag(SQLModel, table=True):
    """Junction table linking calendar events to tags."""
    __tablename__ = "calendar_event_tags"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    calendar_event_id: int = Field(foreign_key="calendar_events.id", primary_key=True)
    tag_id: int = Field(foreign_key="tags.id", primary_key=True, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    calendar_event: Optional[CalendarEvent] = Relationship(back_populates="tag_links")
    tag: Optional["Tag"] = Relationship(back_populates="calendar_event_links")


class CalendarEventDocument(SQLModel, table=True):
    """Junction table linking calendar events to documents."""
    __tablename__ = "calendar_event_documents"

    calendar_event_id: int = Field(foreign_key="calendar_events.id", primary_key=True)
    document_id: int = Field(foreign_key="documents.id", primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False)
    attached_by_id: Optional[int] = Field(default=None, foreign_key="users.id", nullable=True)
    attached_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    calendar_event: Optional[CalendarEvent] = Relationship(back_populates="document_links")
    document: Optional["Document"] = Relationship(back_populates="calendar_event_links")

from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING

from pydantic import ConfigDict
from sqlalchemy import Column, DateTime, String, Text
from sqlmodel import Field, Relationship, SQLModel

from app.models.tenant._mixins import AuthorshipMixin, SoftDeleteMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.calendar_event import CalendarEvent
    from app.models.tenant.initiative import Initiative
    from app.models.tenant.resource_grant import ResourceGrant
    from app.models.platform.user import User
    from app.models.tenant.tag import Tag


DEFAULT_CALENDAR_COLOR = "#6366f1"


class Calendar(AuthorshipMixin, SoftDeleteMixin, table=True):
    """Initiative-scoped calendar — the shareable container for events.

    A calendar is to events what a project is to tasks: DAC grants attach to
    the calendar (``resource_type='calendar'``) and events inherit access from
    it. ``color`` is the display color for the calendar and its events, and
    every calendar has one — NOT NULL, defaulted at the schema layer.
    """

    __tablename__ = "calendars"
    _owner_field = "created_by_id"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)
    # NULL means a guild-level calendar: it belongs to the guild rather than to
    # any initiative, and who may read or write it is decided by its grants.
    # Everything else about a calendar — its events, its UI, its permission
    # computation — is unchanged, which is the point of reusing the table rather
    # than adding a parallel one.
    initiative_id: Optional[int] = Field(
        default=None, foreign_key="initiatives.id", nullable=True, index=True
    )
    name: str = Field(index=True, nullable=False, max_length=255)
    description: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    color: str = Field(
        default=DEFAULT_CALENDAR_COLOR,
        sa_column=Column(
            String(length=32), nullable=False, server_default=DEFAULT_CALENDAR_COLOR
        ),
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

    initiative: Optional["Initiative"] = Relationship(back_populates="calendars")
    creator: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Calendar.created_by_id]"},
    )
    events: List["CalendarEvent"] = Relationship(
        back_populates="calendar",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    tag_links: List["CalendarTag"] = Relationship(
        back_populates="calendar",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    grants: List["ResourceGrant"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(foreign(ResourceGrant.resource_id) == Calendar.id, "
                "ResourceGrant.resource_type == 'calendar')"
            ),
            "viewonly": True,
        }
    )


class CalendarTag(SQLModel, table=True):
    """Junction table linking calendars to tags."""

    __tablename__ = "calendar_tags"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    calendar_id: int = Field(foreign_key="calendars.id", primary_key=True)
    tag_id: int = Field(foreign_key="tags.id", primary_key=True, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    calendar: Optional[Calendar] = Relationship(back_populates="tag_links")
    tag: Optional["Tag"] = Relationship(back_populates="calendar_links")

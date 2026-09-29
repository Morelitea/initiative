from datetime import datetime, timezone
from typing import Any, List, Optional, TYPE_CHECKING

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship

from app.core.tools import Tool
from app.models.tenant._mixins import (
    ArchiveMixin,
    attach_actions,
    CommentsToggleMixin,
    CreatedByMixin,
    ListingProvenanceMixin,
    SoftDeleteMixin,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.initiative import Initiative
    from app.models.tenant.resource_grant import ResourceGrant
    from app.models.platform.user_profile_view import MemberProfile


class Dashboard(
    CommentsToggleMixin,
    CreatedByMixin,
    ArchiveMixin,
    ListingProvenanceMixin,
    SoftDeleteMixin,
    table=True,
):
    """An initiative's dashboard: a canvas of widgets over existing data.

    ``definition`` is the validated, declarative body — layout plus widgets and
    their data bindings. It is a presentation spec only: it names *where* data
    comes from (a task filter, a counter, a document range) and never carries
    content, credentials, or actions. Every binding resolves per viewer through
    the normal gated endpoints, so a dashboard grants no access of its own and
    can never mutate what it displays.

    ``config`` fills the binding slots a definition leaves open, so one shared
    definition can be pointed at this initiative's actual counters/documents.

    Dashboards are initiative-scoped: there is no guild-wide (NULL initiative)
    form — a guild-level surface is an app, which is a separate concept.
    """

    __tablename__ = "dashboards"
    # A tool row is written before anything has been shared, so it is read
    # back by no RETURNING clause: the id comes from the sequence first and
    # the INSERT stands alone. See app/db/initiative_rls.py.
    #
    # Provenance (``listing_uid``/``listing_version``) is every tool's, from
    # ``ListingProvenanceMixin``. A dashboard is the one tool that reads it back
    # — the upgrade button re-pins an installed dashboard to its listing — so it
    # is the one that keeps an index on it.
    __table_args__ = (
        Index("ix_dashboards_listing_uid", "listing_uid"),
        {"implicit_returning": False},
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    name: str = Field(nullable=False, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    definition: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
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
    creator: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(Dashboard.created_by) == MemberProfile.id",
            "viewonly": True,
        }
    )
    grants: List["ResourceGrant"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(foreign(ResourceGrant.resource_id) == Dashboard.id, "
                "ResourceGrant.resource_type == 'dashboard')"
            ),
            "viewonly": True,
        }
    )


attach_actions(Dashboard, Tool.dashboard)

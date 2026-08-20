from datetime import datetime, timezone
from typing import Any, List, Optional, TYPE_CHECKING

from pydantic import ConfigDict
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel

from app.models.tenant._mixins import RowAuditMixin, SoftDeleteMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.initiative import Initiative
    from app.models.tenant.resource_grant import ResourceGrant
    from app.models.tenant.tag import Tag
    from app.models.platform.user import User


class Dashboard(RowAuditMixin, SoftDeleteMixin, table=True):
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
    _owner_field = "created_by_id"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)
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
    # Provenance when installed from the marketplace; both NULL for a dashboard
    # authored from scratch. The uid points at the public catalog listing; the
    # version records which published definition this instance pinned.
    listing_uid: Optional[str] = Field(
        default=None,
        sa_column=Column(String(14), nullable=True, index=True),
    )
    listing_version: Optional[str] = Field(
        default=None,
        sa_column=Column(String(32), nullable=True),
    )
    definition: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
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

    initiative: Optional["Initiative"] = Relationship()
    creator: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "Dashboard.created_by_id"}
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
    tag_links: List["DashboardTag"] = Relationship(
        back_populates="dashboard",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class DashboardTag(SQLModel, table=True):
    """Junction table linking dashboards to tags."""

    __tablename__ = "dashboard_tags"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    dashboard_id: int = Field(foreign_key="dashboards.id", primary_key=True)
    tag_id: int = Field(foreign_key="tags.id", primary_key=True, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    dashboard: Optional[Dashboard] = Relationship(back_populates="tag_links")
    tag: Optional["Tag"] = Relationship(back_populates="dashboard_links")

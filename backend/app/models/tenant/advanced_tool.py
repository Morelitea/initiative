from datetime import datetime, timezone
from typing import Any, List, Optional, TYPE_CHECKING

from pydantic import ConfigDict
from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel

from app.models.tenant._mixins import SoftDeleteMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.initiative import Initiative
    from app.models.tenant.resource_grant import ResourceGrant
    from app.models.tenant.tag import Tag


class AdvancedTool(SoftDeleteMixin, table=True):
    """A guild's advanced tool.

    A name plus a machine-defined ``data`` blob that an external
    service interprets and runs (steps, API hookups, arbitrarily complex
    systems) — opaque to us. We keep the row here so **deletion stays
    guild-controlled** (soft-delete + trash) and so sharing uses the standard
    ``resource_grants`` DAC like every other tool.

    Scope: ``initiative_id`` set → an initiative-scoped tool (initiative-member
    RLS + per-resource DAC, like queues/counters). ``initiative_id`` NULL →
    **guild-wide**, and RLS restricts those rows to guild admins only.
    """

    __tablename__ = "advanced_tools"
    _owner_field = "created_by_id"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)
    # Nullable: NULL = guild-wide (admin-only, enforced by RLS); set =
    # initiative-scoped (initiative-member RLS + DAC).
    initiative_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    name: str = Field(nullable=False, max_length=255)
    data: dict[str, Any] = Field(
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

    # No back_populates: guild-wide rows have no initiative, and the DAC engine
    # only reads ``row.initiative`` (with its memberships) for scoped rows.
    initiative: Optional["Initiative"] = Relationship()
    grants: List["ResourceGrant"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(foreign(ResourceGrant.resource_id) == AdvancedTool.id, "
                "ResourceGrant.resource_type == 'advanced_tool')"
            ),
            "viewonly": True,
        }
    )
    tag_links: List["AdvancedToolTag"] = Relationship(
        back_populates="advanced_tool",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class AdvancedToolTag(SQLModel, table=True):
    """Junction table linking advanced tools to tags."""

    __tablename__ = "advanced_tool_tags"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    advanced_tool_id: int = Field(foreign_key="advanced_tools.id", primary_key=True)
    tag_id: int = Field(foreign_key="tags.id", primary_key=True, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    advanced_tool: Optional[AdvancedTool] = Relationship(back_populates="tag_links")
    tag: Optional["Tag"] = Relationship(back_populates="advanced_tool_links")

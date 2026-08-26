"""Saved filter presets for a project's task list.

A preset is a **named, project-wide** set of filter values — "Incomplete",
"Unassigned", "Mine" — that anyone in the project sees and that a link can
address by slug. It is the shared counterpart to the per-user filter state the
frontend keeps in ``user_view_preferences``: that blob remembers what *you*
last looked at, a preset names something the *team* looks at.

``filters`` holds a normalized spec (validated by
``app.schemas.tenant.filter_preset.TaskFilterSpec``), not the raw ``conditions``
DSL the list endpoint takes. The filter panel has to render a preset back into
controls and project duplication has to remap per-project status ids, and
neither is possible against an arbitrary condition tree. The client expands the
spec into ``conditions`` at query time, so the endpoint keeps its single
contract and a saved preset can never exceed the DSL's limits.
"""

from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship

from app.models.tenant._mixins import CreatedByMixin

if TYPE_CHECKING:  # pragma: no cover - imported lazily for type checking only
    from app.models.tenant.project import Project


class ProjectFilterPreset(CreatedByMixin, table=True):
    __tablename__ = "project_filter_presets"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: Optional[int] = Field(
        default=None, foreign_key="guilds.id", nullable=True
    )
    project_id: int = Field(foreign_key="projects.id", nullable=False, index=True)
    # Immutable after creation: the slug is what a shared link carries, so a
    # rename must not break every link already pasted into a chat.
    slug: str = Field(sa_column=Column(String(length=64), nullable=False))
    name: str = Field(sa_column=Column(String(length=100), nullable=False))
    position: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    is_default: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    filters: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_project_filter_presets_slug"),
        # At most one default per project, enforced by the database rather than
        # by the write paths alone.
        Index(
            "ix_project_filter_presets_one_default",
            "project_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    project: Optional["Project"] = Relationship(back_populates="filter_presets")

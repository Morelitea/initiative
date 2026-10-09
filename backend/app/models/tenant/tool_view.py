"""An initiative's views of a tool, and its item layouts.

A row is one view (``kind = 'view'``: named, ordered, one of them the default)
or one item layout (``kind = 'item_layout'``: how one kind of item's page is
laid out). Either belongs to a target: one instance of a tool (``tool``,
``tool_id``: a project), or, for a tool whose page is shared by the whole
initiative, the initiative itself (``tool_id`` NULL: the calendar).

A target with no rows uses the views Initiative ships. Once anything is stored
the stored rows are the whole set, written together
(``app.services.tenant.tool_views``).

``definition`` holds the validated tree (``app.schemas.tenant.tool_view``).
There is no foreign key to the instance: the purge removes an instance's views
explicitly, as it does its property values. The initiative is a foreign key, so
a shared page's views go with their initiative.

Read by the initiative's members; written by whoever may write the instance,
or, for a shared page, by the initiative's managers and the community's admin
(``app.db.initiative_rls``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.core.tools import VIEW_TOOLS, VIEWS_SHARED
from app.models.tenant._mixins import CreatedByMixin

_TOOL_VALUES = ", ".join(f"'{tool.value}'" for tool in VIEW_TOOLS)
_SHARED_VALUES = ", ".join(f"'{tool.value}'" for tool in VIEWS_SHARED)

VIEW_KIND = "view"
ITEM_LAYOUT_KIND = "item_layout"

#: The columns a row's target is named by.
_TARGET = ("initiative_id", "tool", "tool_id")


class ToolView(CreatedByMixin, table=True):
    __tablename__ = "tool_views"
    __table_args__ = (
        CheckConstraint(f"tool IN ({_TOOL_VALUES})", name="ck_tool_views_tool"),
        # A shared page names no instance, and every other tool's view names one.
        CheckConstraint(
            f"(tool IN ({_SHARED_VALUES})) = (tool_id IS NULL)",
            name="ck_tool_views_target",
        ),
        CheckConstraint(
            f"(kind = '{VIEW_KIND}' AND name IS NOT NULL AND slug IS NOT NULL"
            " AND item_kind IS NULL)"
            f" OR (kind = '{ITEM_LAYOUT_KIND}' AND item_kind IS NOT NULL)",
            name="ck_tool_views_kind",
        ),
        Index(
            "uq_tool_views_slug",
            *_TARGET,
            "slug",
            unique=True,
            postgresql_where=text(f"kind = '{VIEW_KIND}'"),
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "uq_tool_views_item_layout",
            *_TARGET,
            "item_kind",
            unique=True,
            postgresql_where=text(f"kind = '{ITEM_LAYOUT_KIND}'"),
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "uq_tool_views_one_default",
            *_TARGET,
            unique=True,
            postgresql_where=text(f"kind = '{VIEW_KIND}' AND is_default"),
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    tool: str = Field(sa_column=Column(String(32), nullable=False))
    tool_id: Optional[int] = Field(default=None, sa_column=Column(Integer))
    kind: str = Field(sa_column=Column(String(16), nullable=False))
    item_kind: Optional[str] = Field(default=None, sa_column=Column(String(32)))
    name: Optional[str] = Field(default=None, sa_column=Column(String(100)))
    slug: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    position: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    is_default: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    definition: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

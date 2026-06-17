"""Polymorphic per-resource access grants — the single DAC table.

One row = a user OR an initiative role may access a resource at a level. Replaces
the per-resource ``*_permissions`` / ``*_role_permissions`` tables (see
history/resource-grants-consolidation-design.md).
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.initiative import InitiativeRoleModel
    from app.models.user import User


class ResourceAccessLevel(str, Enum):
    owner = "owner"
    write = "write"
    read = "read"


RESOURCE_TYPES = frozenset(
    {"project", "document", "queue", "counter_group", "calendar_event"}
)


class ResourceGrant(SQLModel, table=True):
    __tablename__ = "resource_grants"

    __table_args__ = (
        CheckConstraint(
            "(user_id IS NULL) <> (role_id IS NULL)",
            name="resource_grants_one_grantee",
        ),
        # NULLS NOT DISTINCT so the unused grantee column (NULL) compares equal —
        # otherwise two identical user grants (role_id NULL) wouldn't collide.
        UniqueConstraint(
            "resource_type",
            "resource_id",
            "user_id",
            "role_id",
            name="resource_grants_unique_grantee",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)
    # Carried directly so RLS is a plain initiative_access(initiative_id) — no hop.
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    # resource_id is polymorphic (keyed by resource_type) — no FK; cleaned up in the
    # resource's delete path, inert if orphaned.
    resource_type: str = Field(
        sa_column=Column(String(length=32), nullable=False, index=True)
    )
    resource_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    role_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("initiative_roles.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    level: ResourceAccessLevel = Field(
        sa_column=Column(String(length=16), nullable=False)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    # For serialization (role grants surface the role's name/display_name).
    role: Optional["InitiativeRoleModel"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "ResourceGrant.role_id",
            "viewonly": True,
        }
    )
    user: Optional["User"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "ResourceGrant.user_id",
            "viewonly": True,
        }
    )

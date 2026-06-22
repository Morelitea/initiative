"""Polymorphic per-resource access grants — the single DAC table.

One row grants access to a resource at a level for exactly one of three grantee
kinds:

- a **user** (``user_id`` set),
- an **initiative role** (``role_id`` set), or
- the **whole initiative** — a "general access" row with neither ``user_id`` nor
  ``role_id`` set and ``all_initiative_members`` true; ``level`` (read/write)
  gives the Viewer/Editor level. The backend aggregates every member of the
  row's ``initiative_id`` for it (see ``app.services.permissions``).
  ``all_initiative_members`` may only be set when there is no user/role grantee
  (enforced by the ``resource_grants_one_grantee`` check).

Replaces the per-resource ``*_permissions`` / ``*_role_permissions`` tables (see
history/resource-grants-consolidation-design.md). General access:
history/general-access-sharing-design.md.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.initiative import InitiativeRoleModel
    from app.models.platform.user import User


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
        # Exactly one grantee kind per row: a user, an initiative role, or the
        # whole initiative (all_initiative_members). This keeps the old XOR (never
        # user AND role) and forbids the share boolean whenever a user/role
        # grantee is set.
        CheckConstraint(
            "(user_id IS NOT NULL)::int + (role_id IS NOT NULL)::int "
            "+ (all_initiative_members)::int = 1",
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
    # All-initiative-members grant — when true (and there is no user/role
    # grantee), the row grants every member of ``initiative_id`` access at
    # ``level`` (read = Viewer, write = Editor). The constraint forbids it being
    # set alongside a user/role.
    all_initiative_members: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
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

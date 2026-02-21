from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, Enum as SAEnum, ForeignKey, Integer, String, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.project import Project
    from app.models.user import User
    from app.models.guild import Guild
    from app.models.document import Document


# Legacy enum kept for backwards compatibility during migration
class InitiativeRole(str, Enum):
    project_manager = "project_manager"
    member = "member"


# Permission keys for role-based access control
class PermissionKey(str, Enum):
    docs_enabled = "docs_enabled"
    projects_enabled = "projects_enabled"
    create_docs = "create_docs"
    create_projects = "create_projects"


# Fallback values when a permission is not explicitly set on a role.
# Feature visibility defaults to True (permissive), creation defaults to False (restrictive).
# When adding new permission keys, add an entry here to define the fallback behavior.
DEFAULT_PERMISSION_VALUES: dict["PermissionKey", bool] = {
    PermissionKey.docs_enabled: True,
    PermissionKey.projects_enabled: True,
    PermissionKey.create_docs: False,
    PermissionKey.create_projects: False,
}


# Default permission sets for built-in roles
BUILTIN_ROLE_PERMISSIONS = {
    "project_manager": {
        PermissionKey.docs_enabled: True,
        PermissionKey.projects_enabled: True,
        PermissionKey.create_docs: True,
        PermissionKey.create_projects: True,
    },
    "member": {
        PermissionKey.docs_enabled: True,
        PermissionKey.projects_enabled: True,
        PermissionKey.create_docs: False,
        PermissionKey.create_projects: False,
    },
}


class InitiativeRoleModel(SQLModel, table=True):
    """Defines roles available per initiative."""
    __tablename__ = "initiative_roles"
    __table_args__ = (
        UniqueConstraint("initiative_id", "name", name="uq_initiative_role_name"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    name: str = Field(max_length=100)  # e.g., "project_manager", "viewer"
    display_name: str = Field(max_length=100)  # e.g., "Project Manager"
    is_builtin: bool = Field(default=False)  # true for PM/Member
    is_manager: bool = Field(default=False)  # counts toward manager constraint
    position: int = Field(default=0)  # for ordering in UI

    initiative: Optional["Initiative"] = Relationship(back_populates="roles")
    permissions: List["InitiativeRolePermission"] = Relationship(
        back_populates="role",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    members: List["InitiativeMember"] = Relationship(back_populates="role_ref")


class InitiativeRolePermission(SQLModel, table=True):
    """Permission toggles per role."""
    __tablename__ = "initiative_role_permissions"

    initiative_role_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiative_roles.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    permission_key: PermissionKey = Field(
        sa_column=Column(
            SAEnum(PermissionKey, name="permissionkey", create_constraint=False, native_enum=False, length=50),
            primary_key=True,
        )
    )
    enabled: bool = Field(default=True)

    role: Optional["InitiativeRoleModel"] = Relationship(back_populates="permissions")


class InitiativeMember(SQLModel, table=True):
    __tablename__ = "initiative_members"

    initiative_id: int = Field(foreign_key="initiatives.id", primary_key=True)
    user_id: int = Field(foreign_key="users.id", primary_key=True, index=True)
    guild_id: Optional[int] = Field(default=None, foreign_key="guilds.id", nullable=True)
    role_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("initiative_roles.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    joined_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    oidc_managed: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )

    initiative: Optional["Initiative"] = Relationship(back_populates="memberships")
    user: Optional["User"] = Relationship(back_populates="initiative_memberships")
    role_ref: Optional["InitiativeRoleModel"] = Relationship(back_populates="members")


class Initiative(SQLModel, table=True):
    __tablename__ = "initiatives"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)
    name: str = Field(index=True, nullable=False)
    description: Optional[str] = Field(default=None)
    color: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=32), nullable=True),
    )
    is_default: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    memberships: List["InitiativeMember"] = Relationship(
        back_populates="initiative",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    roles: List["InitiativeRoleModel"] = Relationship(
        back_populates="initiative",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    projects: List["Project"] = Relationship(back_populates="initiative")
    guild: Optional["Guild"] = Relationship(back_populates="initiatives")
    documents: List["Document"] = Relationship(
        back_populates="initiative",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlmodel import Field, Relationship, SQLModel

from app.core.tools import CORE_TOOLS, TOGGLEABLE_TOOLS, Tool
from app.models.tenant._mixins import CreatedByMixin, SoftDeleteMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.project import Project
    from app.models.platform.user import User
    from app.models.platform.guild import Guild
    from app.models.tenant.document import Document
    from app.models.tenant.queue import Queue
    from app.models.tenant.calendar import Calendar
    from app.models.tenant.counter import CounterGroup


class InitiativeJoinPolicy(str, Enum):
    """How a guild member may come to hold a membership row in an initiative.

    The policy governs *how a membership row comes to exist* — it is never
    consulted by RLS. ``public.initiative_access`` still answers every access
    question from ``initiative_members`` exactly as it did before.

    - ``private``: invisible outside its membership; a manager adds people by
      hand. The default, so nothing opens on upgrade.
    - ``request``: listed in the guild's initiative directory; members ask and a
      manager resolves the request.
    - ``open``: listed in the directory; any guild member self-joins and
      receives the built-in ``member`` role.

    Stored as a plain string with a table CHECK (the ``guilds.status`` pattern)
    rather than a Postgres enum, so adding a policy is an ordinary migration.
    """

    private = "private"
    request = "request"
    open = "open"


class JoinRequestStatus(str, Enum):
    """Lifecycle of a row in ``initiative_join_requests``."""

    pending = "pending"
    approved = "approved"
    denied = "denied"


# Permission keys for role-based access control — fully derived from the Tool
# enum: one `{plural}_enabled` + `create_{plural}` pair per tool
# (documents_enabled, create_documents, …, counter_groups_enabled,
# create_counter_groups). A new Tool member gets its keys automatically; only
# the DB CHECK constraint on initiative_role_permissions still needs a guild
# migration to accept the new values.
PermissionKey = Enum(
    "PermissionKey",
    [(name, name) for t in Tool for name in (t.view_permission, t.create_permission)],
    type=str,
)


# Fallback values when a permission is not explicitly set on a role, derived
# from the tool classification: viewing a core (always-on) tool defaults to
# True, viewing an opt-in tool defaults to False (its initiative master switch
# gates availability, and within that only managers see it unless a custom
# role grants it), and creation is always False (restrictive).
DEFAULT_PERMISSION_VALUES: dict["PermissionKey", bool] = {
    **{PermissionKey(t.view_permission): t in CORE_TOOLS for t in Tool},
    **{PermissionKey(t.create_permission): False for t in Tool},
}


# Default permission sets for built-in roles: managers get everything, members
# get view-only on the core (always-on) tools.
BUILTIN_ROLE_PERMISSIONS = {
    "project_manager": {key: True for key in PermissionKey},
    "member": dict(DEFAULT_PERMISSION_VALUES),
}


class InitiativeRoleModel(CreatedByMixin, table=True):
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
    # "Full access": members with this role view/edit ALL content in the
    # initiative regardless of how each item is shared, and may manage sharing
    # (the gate-4 / DAC override, scoped to this one initiative). Off by default;
    # only a guild admin may turn it on, and only on the built-in project_manager
    # role. See history/initiative-admin-override-design.md.
    override_share_restrictions: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
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
            SAEnum(
                PermissionKey,
                name="permissionkey",
                create_constraint=False,
                native_enum=False,
                length=50,
            ),
            primary_key=True,
        )
    )
    enabled: bool = Field(default=True)

    role: Optional["InitiativeRoleModel"] = Relationship(back_populates="permissions")


class InitiativeMember(SQLModel, table=True):
    __tablename__ = "initiative_members"

    initiative_id: int = Field(foreign_key="initiatives.id", primary_key=True)
    user_id: int = Field(foreign_key="users.id", primary_key=True, index=True)
    guild_id: Optional[int] = Field(
        default=None, foreign_key="guilds.id", nullable=True
    )
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


class InitiativeJoinRequest(SQLModel, table=True):
    """A guild member knocking on a ``request``-policy initiative.

    Deliberately guild-level rather than initiative-scoped (see
    ``app.db.tenancy.GUILD_LEVEL_TABLES``): a requester is by definition not yet
    a member, so an initiative-membership row gate would hide their own request
    from them. Who may read which rows is decided in the service layer instead —
    requesters see their own, managers see their initiative's.
    """

    __tablename__ = "initiative_join_requests"

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'denied')",
            name="ck_initiative_join_requests_status",
        ),
        # One live request per user per initiative; resolved rows stay as history.
        Index(
            "uq_initiative_join_requests_pending",
            "initiative_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
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
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id"),
            nullable=False,
            index=True,
        )
    )
    status: str = Field(
        default=JoinRequestStatus.pending.value,
        sa_column=Column(
            String(length=20),
            nullable=False,
            server_default=JoinRequestStatus.pending.value,
        ),
    )
    # Optional note from the requester to the initiative's managers.
    message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    resolved_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # The manager who approved or denied; NULL while pending.
    resolved_by: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


# One `{tool.plural}_enabled` master-switch column per toggleable Tool —
# derived from the Tool enum, so a new opt-in tool grows its column here
# automatically. The actual DDL still ships as a guild migration (and the
# provisioning drift tests catch a model/schema mismatch).
_InitiativeToolSwitchColumns = type(
    "_InitiativeToolSwitchColumns",
    (SQLModel,),
    {
        "__module__": __name__,
        "__annotations__": {t.view_permission: bool for t in TOGGLEABLE_TOOLS},
        **{
            t.view_permission: Field(
                default=False,
                nullable=False,
                sa_column_kwargs={"server_default": "false"},
            )
            for t in TOGGLEABLE_TOOLS
        },
    },
)


class Initiative(
    _InitiativeToolSwitchColumns, CreatedByMixin, SoftDeleteMixin, table=True
):
    __tablename__ = "initiatives"

    __table_args__ = (
        # Literal SQL, mirroring the migration that creates them: the vocabulary
        # is InitiativeJoinPolicy, and widening it is a migration either way.
        CheckConstraint(
            "join_policy IN ('private', 'request', 'open')",
            name="ck_initiatives_join_policy",
        ),
        # Auto-join enrols arrivals automatically, so the initiative must also be
        # one they could have found and joined themselves.
        CheckConstraint(
            "(NOT auto_join) OR join_policy = 'open'",
            name="ck_initiatives_auto_join_open",
        ),
    )

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
    is_archived: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # See InitiativeJoinPolicy. Guarded by ck_initiatives_join_policy.
    join_policy: str = Field(
        default=InitiativeJoinPolicy.private.value,
        sa_column=Column(
            String(length=20),
            nullable=False,
            server_default=InitiativeJoinPolicy.private.value,
        ),
    )
    # New guild members are enrolled in this initiative automatically. Guild-admin
    # settable, and only on an `open` initiative (ck_initiatives_auto_join_open).
    auto_join: bool = Field(
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
    queues: List["Queue"] = Relationship(
        back_populates="initiative",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    calendars: List["Calendar"] = Relationship(
        back_populates="initiative",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    counter_groups: List["CounterGroup"] = Relationship(
        back_populates="initiative",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

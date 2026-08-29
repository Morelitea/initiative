from datetime import datetime
from typing import Dict, List, Optional, TYPE_CHECKING

from pydantic import ConfigDict, Field, create_model

from app.core.tools import CORE_TOOLS, TOGGLEABLE_TOOLS, Tool
from app.schemas.base import RichTextStr, SanitizedBaseModel

from app.models.tenant.initiative import (
    InitiativeJoinPolicy,
    JoinRequestStatus,
    PermissionKey,
)
from app.schemas.platform.user import UserPublic, UserSummary

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.initiative import (
        Initiative,
        InitiativeMember,
        InitiativeRoleModel,
    )


HEX_COLOR_PATTERN = r"^#(?:[0-9a-fA-F]{3}){1,2}$"

#: A join request's note is a sentence or two for the managers reading the
#: queue, not a document — so it is capped well below the 8 KB plain-text
#: ceiling every ``SanitizedBaseModel`` string already carries.
JOIN_REQUEST_MESSAGE_MAX_LENGTH = 1000


# Derived bases: one `{tool.plural}_enabled` master-switch field per
# toggleable Tool. A new Tool member grows these schemas automatically (the
# SQLModel column itself is still declared on the Initiative model — real DDL
# stays explicit, pinned by its migration and the drift test).
_InitiativeToolSwitches = create_model(
    "_InitiativeToolSwitches",
    __base__=SanitizedBaseModel,
    **{t.view_permission: (bool, False) for t in TOGGLEABLE_TOOLS},
)
_InitiativeToolSwitchesPatch = create_model(
    "_InitiativeToolSwitchesPatch",
    __base__=SanitizedBaseModel,
    **{t.view_permission: (Optional[bool], None) for t in TOGGLEABLE_TOOLS},
)


class InitiativeBase(_InitiativeToolSwitches):
    name: str
    description: Optional[RichTextStr] = None
    color: Optional[str] = Field(default=None, pattern=HEX_COLOR_PATTERN)


class InitiativeCreate(InitiativeBase):
    # Creation is guild-admin only, so the policy is theirs to set from the
    # start; defaulting private keeps "open" an explicit choice.
    join_policy: InitiativeJoinPolicy = InitiativeJoinPolicy.private


class InitiativeUpdate(_InitiativeToolSwitchesPatch):
    name: Optional[str] = None
    description: Optional[RichTextStr] = None
    color: Optional[str] = Field(default=None, pattern=HEX_COLOR_PATTERN)
    is_archived: Optional[bool] = None
    # Settable by whoever may already update the initiative (managers, guild
    # admins).
    join_policy: Optional[InitiativeJoinPolicy] = None
    # Guild admins only — enforced in the endpoint, and only valid alongside a
    # resulting join_policy of 'open'.
    auto_join: Optional[bool] = None


# Role schemas
class InitiativeRoleRead(SanitizedBaseModel):
    """Role definition with permissions."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    name: str
    display_name: str
    is_builtin: bool
    is_manager: bool
    # "Full access": this role views/edits all initiative content regardless of
    # sharing and may manage sharing. Guild-admin-settable, project_manager only.
    override_share_restrictions: bool = False
    position: int
    permissions: Dict[PermissionKey, bool] = Field(default_factory=dict)
    member_count: int = 0


class InitiativeRoleCreate(SanitizedBaseModel):
    """Create a new custom role."""

    name: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=100)
    is_manager: bool = False
    permissions: Optional[Dict[PermissionKey, bool]] = None


class InitiativeRoleUpdate(SanitizedBaseModel):
    """Update a role's display name and/or permissions."""

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    is_manager: Optional[bool] = None
    # "Full access" toggle. Only a guild admin may change it, and only on the
    # built-in project_manager role (enforced in the endpoint).
    override_share_restrictions: Optional[bool] = None
    permissions: Optional[Dict[PermissionKey, bool]] = None


class MyInitiativePermissions(SanitizedBaseModel):
    """Current user's permissions for an initiative."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    role_id: Optional[int] = None
    role_name: Optional[str] = None
    role_display_name: Optional[str] = None
    is_manager: bool = False
    # True when the current user can view/edit every item in this initiative
    # regardless of sharing, and manage sharing — a guild admin, or a member
    # whose role has "Full access" (override_share_restrictions). Drives the
    # client's manage-sharing affordances.
    override_share_restrictions: bool = False
    permissions: Dict[PermissionKey, bool] = Field(default_factory=dict)


class InitiativeGroupedCountsResponse(SanitizedBaseModel):
    """Per-initiative resource counts (initiative_id -> visible count).

    Shared response shape for the documents/projects grouped-count
    endpoints that back sidebar and landing-card badges.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    counts: Dict[int, int] = Field(default_factory=dict)


# Member schemas - updated to work with role_id
class InitiativeMemberAdd(SanitizedBaseModel):
    """Add a member to an initiative."""

    user_id: int
    role_id: Optional[int] = None


class InitiativeMemberUpdate(SanitizedBaseModel):
    """Update a member's role."""

    role_id: int


# Derived: one `can_view_{tool.plural}` / `can_create_{tool.plural}` pair per
# Tool, for UI filtering. View defaults True only for core tools.
_MemberToolFlags = create_model(
    "_MemberToolFlags",
    __base__=SanitizedBaseModel,
    **{t.member_view_field: (bool, t in CORE_TOOLS) for t in Tool},
    **{t.member_create_field: (bool, False) for t in Tool},
)


class InitiativeMemberRead(_MemberToolFlags):
    """Member info including their role."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    user: UserPublic
    role_id: Optional[int] = None
    role_name: Optional[str] = None
    role_display_name: Optional[str] = None
    is_manager: bool = False
    joined_at: datetime
    oidc_managed: bool = False


class InitiativeRead(InitiativeBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    guild_id: int
    is_default: bool = False
    # Hidden from the main sidebar when true (see Initiative.is_archived).
    is_archived: bool = False
    # How guild members may join (see InitiativeJoinPolicy). Never consulted by
    # RLS — it governs how a membership row comes to exist, nothing more.
    join_policy: InitiativeJoinPolicy = InitiativeJoinPolicy.private
    auto_join: bool = False
    created_at: datetime
    updated_at: datetime
    members: List[InitiativeMemberRead] = Field(default_factory=list)


class InitiativeDirectoryEntry(SanitizedBaseModel):
    """One card in a guild's initiative directory.

    Only initiatives that chose to be listed (``request`` / ``open``) ever reach
    this shape; a ``private`` one is excluded in the service. The three caller-
    relative fields answer which call to action the card renders: already in it,
    knocked and waiting, or free to join.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    join_policy: InitiativeJoinPolicy
    # Whether new guild members are enrolled here on arrival. Discloses nothing
    # a card does not already: ``ck_initiatives_auto_join_open`` means only an
    # ``open`` initiative can carry it, and an open one is listed to every guild
    # member anyway. It is what lets a guild's admin see, from the list they
    # would pick from, whether arrivals currently land anywhere at all.
    auto_join: bool = False
    member_count: int = 0
    is_member: bool = False
    has_pending_request: bool = False
    # How many people are waiting at this door — the badge on a manager's card.
    # Zero for everyone who could not act on the queue anyway (see
    # ``list_directory_entries``), so the directory never tells a bystander how
    # many of their peers asked to get in.
    pending_join_request_count: int = 0


class InitiativeJoinRequestCreate(SanitizedBaseModel):
    """A guild member knocking on a ``request``-policy initiative."""

    message: Optional[str] = Field(
        default=None, max_length=JOIN_REQUEST_MESSAGE_MAX_LENGTH
    )


class InitiativeJoinRequestRead(SanitizedBaseModel):
    """One row of an initiative's join-request queue.

    Carries everything the manager needs to decide without a second call: who
    is asking (the same slim user projection the member pickers use), what they
    said, when they asked, and how many times this initiative has turned them
    down before — a denied requester may ask again, so the history is what keeps
    the repeat visible.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    initiative_id: int
    user: UserSummary
    status: JoinRequestStatus
    message: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[int] = None
    prior_denials: int = 0


def serialize_role(
    role: "InitiativeRoleModel", member_count: int = 0
) -> InitiativeRoleRead:
    """Serialize a role model to a read schema."""
    permissions = {
        perm.permission_key: perm.enabled for perm in (role.permissions or [])
    }
    return InitiativeRoleRead(
        id=role.id,
        name=role.name,
        display_name=role.display_name,
        is_builtin=role.is_builtin,
        is_manager=role.is_manager,
        override_share_restrictions=getattr(role, "override_share_restrictions", False),
        position=role.position,
        permissions=permissions,
        member_count=member_count,
    )


def member_tool_flags(
    initiative: "Initiative", membership: "InitiativeMember"
) -> dict[str, bool]:
    """Effective per-tool view/create flags for one membership.

    Derived per Tool from one rule instead of a hand-rolled branch per tool:
    defaults (view core tools only) → manager gets everything → otherwise the
    role's `{plural}_enabled` / `create_{plural}` permissions → the
    initiative's master switch force-disables toggleable tools it turned off.
    """
    role_ref = getattr(membership, "role_ref", None)
    is_manager = role_ref.is_manager if role_ref else False
    flags = {
        **{t.member_view_field: t in CORE_TOOLS for t in Tool},
        **{t.member_create_field: False for t in Tool},
    }
    if is_manager:
        flags = {name: True for name in flags}
    elif role_ref:
        # getattr to avoid lazy loading
        role_permissions = getattr(role_ref, "permissions", None) or []
        enabled_by_key = {p.permission_key: p.enabled for p in role_permissions}
        for t in Tool:
            view = enabled_by_key.get(PermissionKey(t.view_permission))
            if view is not None:
                flags[t.member_view_field] = view
            if enabled_by_key.get(PermissionKey(t.create_permission)):
                flags[t.member_create_field] = True
    for t in TOGGLEABLE_TOOLS:
        if not getattr(initiative, t.view_permission, False):
            flags[t.member_view_field] = False
            flags[t.member_create_field] = False
    return flags


def serialize_initiative(initiative: "Initiative") -> InitiativeRead:
    members: List[InitiativeMemberRead] = []
    for membership in getattr(initiative, "memberships", []) or []:
        if membership.user is None:
            continue
        # Get role info from role_ref if available
        role_ref = getattr(membership, "role_ref", None)
        role_name = role_ref.name if role_ref else None

        members.append(
            InitiativeMemberRead(
                user=UserPublic.model_validate(membership.user),
                role_id=membership.role_id,
                role_name=role_name,
                role_display_name=role_ref.display_name if role_ref else None,
                is_manager=role_ref.is_manager if role_ref else False,
                joined_at=membership.joined_at,
                oidc_managed=membership.oidc_managed,
                **member_tool_flags(initiative, membership),
            )
        )
    return InitiativeRead(
        id=initiative.id,
        guild_id=initiative.guild_id,
        name=initiative.name,
        description=initiative.description,
        color=initiative.color,
        is_default=initiative.is_default,
        is_archived=getattr(initiative, "is_archived", False),
        join_policy=getattr(
            initiative, "join_policy", InitiativeJoinPolicy.private.value
        ),
        auto_join=getattr(initiative, "auto_join", False),
        created_at=initiative.created_at,
        updated_at=initiative.updated_at,
        members=members,
        **{
            t.view_permission: getattr(initiative, t.view_permission, False)
            for t in TOGGLEABLE_TOOLS
        },
    )

from datetime import datetime
from typing import Dict, List, Optional, TYPE_CHECKING

from pydantic import ConfigDict, Field, create_model

from app.core.tools import CORE_TOOLS, TOGGLEABLE_TOOLS, Tool
from app.schemas.base import RichTextStr, SanitizedBaseModel

from app.models.tenant.initiative import InitiativeRole, PermissionKey
from app.schemas.platform.user import UserPublic

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.initiative import (
        Initiative,
        InitiativeMember,
        InitiativeRoleModel,
    )


HEX_COLOR_PATTERN = r"^#(?:[0-9a-fA-F]{3}){1,2}$"


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
    pass


class InitiativeUpdate(_InitiativeToolSwitchesPatch):
    name: Optional[str] = None
    description: Optional[RichTextStr] = None
    color: Optional[str] = Field(default=None, pattern=HEX_COLOR_PATTERN)
    is_archived: Optional[bool] = None


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


class AdvancedToolHandoffResponse(SanitizedBaseModel):
    """Short-lived bootstrap token for the embedded advanced-tool iframe.

    The SPA passes this to the iframe via postMessage. The iframe's backend
    validates the JWT (same SECRET_KEY, audience claim) and exchanges it
    for its own session — never used directly as long-lived auth.

    ``scope`` distinguishes "initiative" vs "guild" embeds. The receiving
    iframe MUST treat the URL query param as a hint only and trust the
    JWT's own ``scope`` claim — the param isn't enough to authorize.
    For initiative scope, ``initiative_id`` is set; for guild scope it's
    None and only ``guild_id`` (in the JWT) identifies the tenant.
    """

    handoff_token: str
    expires_in_seconds: int
    iframe_url: str
    scope: str
    initiative_id: Optional[int] = None


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
    # Flat initiative-level master switch for the optional embedded
    # advanced tool. Mirrored here so the proprietary embed backend can
    # gate access in a single permissions call.
    advanced_tools_enabled: bool = False


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
    # Legacy field for backward compatibility
    role: InitiativeRole = InitiativeRole.member
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
    created_at: datetime
    updated_at: datetime
    members: List[InitiativeMemberRead] = Field(default_factory=list)


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

        # Determine legacy role for backward compatibility
        legacy_role = (
            InitiativeRole.project_manager
            if role_name == "project_manager"
            else InitiativeRole.member
        )

        members.append(
            InitiativeMemberRead(
                user=UserPublic.model_validate(membership.user),
                role_id=membership.role_id,
                role_name=role_name,
                role_display_name=role_ref.display_name if role_ref else None,
                is_manager=role_ref.is_manager if role_ref else False,
                joined_at=membership.joined_at,
                role=legacy_role,
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
        created_at=initiative.created_at,
        updated_at=initiative.updated_at,
        members=members,
        **{
            t.view_permission: getattr(initiative, t.view_permission, False)
            for t in TOGGLEABLE_TOOLS
        },
    )

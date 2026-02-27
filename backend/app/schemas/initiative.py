from datetime import datetime
from typing import Dict, List, Optional, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from app.models.initiative import InitiativeRole, PermissionKey
from app.schemas.user import UserPublic

if TYPE_CHECKING:  # pragma: no cover
    from app.models.initiative import Initiative, InitiativeRoleModel


HEX_COLOR_PATTERN = r"^#(?:[0-9a-fA-F]{3}){1,2}$"


class InitiativeBase(BaseModel):
    name: str
    description: Optional[str] = None
    color: Optional[str] = Field(default=None, pattern=HEX_COLOR_PATTERN)


class InitiativeCreate(InitiativeBase):
    pass


class InitiativeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = Field(default=None, pattern=HEX_COLOR_PATTERN)


# Role schemas
class InitiativeRolePermissionRead(BaseModel):
    """Permission entry for a role."""
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    permission_key: PermissionKey
    enabled: bool


class InitiativeRoleRead(BaseModel):
    """Role definition with permissions."""
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    name: str
    display_name: str
    is_builtin: bool
    is_manager: bool
    position: int
    permissions: Dict[PermissionKey, bool] = Field(default_factory=dict)
    member_count: int = 0


class InitiativeRoleCreate(BaseModel):
    """Create a new custom role."""
    name: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=100)
    is_manager: bool = False
    permissions: Optional[Dict[PermissionKey, bool]] = None


class InitiativeRoleUpdate(BaseModel):
    """Update a role's display name and/or permissions."""
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    is_manager: Optional[bool] = None
    permissions: Optional[Dict[PermissionKey, bool]] = None


class MyInitiativePermissions(BaseModel):
    """Current user's permissions for an initiative."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    role_id: Optional[int] = None
    role_name: Optional[str] = None
    role_display_name: Optional[str] = None
    is_manager: bool = False
    permissions: Dict[PermissionKey, bool] = Field(default_factory=dict)


# Member schemas - updated to work with role_id
class InitiativeMemberBase(BaseModel):
    user_id: int
    role_id: Optional[int] = None
    # Keep legacy role field for backward compatibility
    role: InitiativeRole = InitiativeRole.member


class InitiativeMemberAdd(BaseModel):
    """Add a member to an initiative."""
    user_id: int
    role_id: Optional[int] = None


class InitiativeMemberUpdate(BaseModel):
    """Update a member's role."""
    role_id: int


class InitiativeMemberRead(BaseModel):
    """Member info including their role."""
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    user: UserPublic
    role_id: Optional[int] = None
    role_name: Optional[str] = None
    role_display_name: Optional[str] = None
    is_manager: bool = False
    joined_at: datetime
    # Legacy field for backward compatibility
    role: InitiativeRole = InitiativeRole.member
    oidc_managed: bool = False
    # Permission flags for UI filtering
    can_view_docs: bool = True
    can_view_projects: bool = True
    can_view_queues: bool = False
    can_create_docs: bool = False
    can_create_projects: bool = False
    can_create_queues: bool = False


class InitiativeRead(InitiativeBase):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    guild_id: int
    is_default: bool = False
    created_at: datetime
    updated_at: datetime
    members: List[InitiativeMemberRead] = Field(default_factory=list)


def serialize_role(role: "InitiativeRoleModel", member_count: int = 0) -> InitiativeRoleRead:
    """Serialize a role model to a read schema."""
    permissions = {
        perm.permission_key: perm.enabled
        for perm in (role.permissions or [])
    }
    return InitiativeRoleRead(
        id=role.id,
        name=role.name,
        display_name=role.display_name,
        is_builtin=role.is_builtin,
        is_manager=role.is_manager,
        position=role.position,
        permissions=permissions,
        member_count=member_count,
    )


def serialize_initiative(initiative: "Initiative") -> InitiativeRead:
    members: List[InitiativeMemberRead] = []
    for membership in getattr(initiative, "memberships", []) or []:
        if membership.user is None:
            continue
        # Get role info from role_ref if available
        role_ref = getattr(membership, "role_ref", None)
        role_name = role_ref.name if role_ref else None
        role_display_name = role_ref.display_name if role_ref else None
        is_manager = role_ref.is_manager if role_ref else False

        # Compute permissions from role
        can_view_docs = True
        can_view_projects = True
        can_view_queues = False
        can_create_docs = False
        can_create_projects = False
        can_create_queues = False
        if is_manager:
            # Managers have all permissions
            can_create_docs = True
            can_create_projects = True
            can_view_queues = True
            can_create_queues = True
        elif role_ref:
            # Check role permissions (use getattr to avoid lazy loading)
            role_permissions = getattr(role_ref, "permissions", None) or []
            for perm in role_permissions:
                if perm.permission_key == PermissionKey.docs_enabled:
                    can_view_docs = perm.enabled
                elif perm.permission_key == PermissionKey.projects_enabled:
                    can_view_projects = perm.enabled
                elif perm.permission_key == PermissionKey.queues_enabled:
                    can_view_queues = perm.enabled
                elif perm.permission_key == PermissionKey.create_docs and perm.enabled:
                    can_create_docs = True
                elif perm.permission_key == PermissionKey.create_projects and perm.enabled:
                    can_create_projects = True
                elif perm.permission_key == PermissionKey.create_queues and perm.enabled:
                    can_create_queues = True

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
                role_display_name=role_display_name,
                is_manager=is_manager,
                joined_at=membership.joined_at,
                role=legacy_role,
                oidc_managed=membership.oidc_managed,
                can_view_docs=can_view_docs,
                can_view_projects=can_view_projects,
                can_view_queues=can_view_queues,
                can_create_docs=can_create_docs,
                can_create_projects=can_create_projects,
                can_create_queues=can_create_queues,
            )
        )
    return InitiativeRead(
        id=initiative.id,
        guild_id=initiative.guild_id,
        name=initiative.name,
        description=initiative.description,
        color=initiative.color,
        is_default=initiative.is_default,
        created_at=initiative.created_at,
        updated_at=initiative.updated_at,
        members=members,
    )

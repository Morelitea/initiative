"""Platform-level capability model.

Authorization for app-wide (platform) operations is expressed in terms of
*capabilities*, not role names. Each :class:`~app.models.user.UserRole` is a
preset that maps to a frozen set of capabilities (see ``ROLE_CAPABILITIES``).
Endpoints and services should check a capability via
:func:`user_has_capability` (or the ``require_capability`` dependency in
``app.api.deps``) so the privilege ladder can change without touching every
call site.

This is deliberately separate from *guild* roles (``GuildRole``) and
*initiative* roles, which are scoped tenancy concepts. Capabilities here are
about platform-wide privilege.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, FrozenSet

from app.models.user import UserRole

if TYPE_CHECKING:  # pragma: no cover
    from app.models.user import User


class Capability(str, Enum):
    """A discrete platform-level permission.

    Values are stable dotted strings shared with the frontend (exposed on
    ``UserRead.capabilities``); treat them as part of the API contract.
    """

    # Read-only cross-guild visibility (served via admin endpoints that
    # bypass RLS, gated purely by capability).
    USERS_READ = "users.read"
    GUILDS_READ = "guilds.read"
    AUDIT_READ = "audit.read"

    # Trust & safety / user lifecycle.
    CONTENT_MODERATE = "content.moderate"
    USERS_MANAGE = "users.manage"
    USERS_DELETE = "users.delete"

    # Platform operations.
    GUILDS_MANAGE = "guilds.manage"
    ROLES_ASSIGN = "roles.assign"

    # The standing, all-guild RLS bypass (``app.is_superadmin``). admin+owner
    # only — PAM grants are the least-privilege alternative for everyone else.
    DATA_BYPASS = "data.bypass"

    # Privileged Access Management (time-bound, per-guild grants).
    ACCESS_REQUEST = "access.request"
    ACCESS_APPROVE = "access.approve"
    ACCESS_READ = "access.read"

    # App-wide configuration (OIDC, SMTP, branding, role labels). owner only.
    CONFIG_MANAGE = "config.manage"


# Capability presets per platform role, least → most privileged. Each higher
# tier is a strict superset of the tier below it, but the model itself does
# not assume that — membership is explicit so the matrix can diverge later.
_MEMBER: FrozenSet[Capability] = frozenset()

_SUPPORT: FrozenSet[Capability] = _MEMBER | {
    Capability.USERS_READ,
    Capability.GUILDS_READ,
    Capability.AUDIT_READ,
    Capability.ACCESS_REQUEST,
}

_MODERATOR: FrozenSet[Capability] = _SUPPORT | {
    Capability.CONTENT_MODERATE,
    Capability.USERS_MANAGE,
}

_ADMIN: FrozenSet[Capability] = _MODERATOR | {
    Capability.GUILDS_MANAGE,
    Capability.USERS_DELETE,
    Capability.DATA_BYPASS,
    Capability.ROLES_ASSIGN,
    Capability.ACCESS_APPROVE,
    Capability.ACCESS_READ,
}

_OWNER: FrozenSet[Capability] = (
    _ADMIN
    | {
        Capability.CONFIG_MANAGE,
    }
) - {
    # Owners approve access requests; they don't request elevated access for
    # themselves (they already hold the standing all-guild bypass).
    Capability.ACCESS_REQUEST,
}


ROLE_CAPABILITIES: dict[UserRole, FrozenSet[Capability]] = {
    UserRole.member: _MEMBER,
    UserRole.support: _SUPPORT,
    UserRole.moderator: _MODERATOR,
    UserRole.admin: _ADMIN,
    UserRole.owner: _OWNER,
}


def capabilities_for(role: UserRole) -> FrozenSet[Capability]:
    """Return the capability set granted by a standing platform role."""
    return ROLE_CAPABILITIES.get(role, _MEMBER)


def roles_with_capability(capability: Capability) -> FrozenSet[UserRole]:
    """Return every standing role whose preset grants ``capability``.

    Used to translate a capability into a role filter for queries (e.g.
    "how many users can still manage platform config").
    """
    return frozenset(
        role for role, caps in ROLE_CAPABILITIES.items() if capability in caps
    )


def user_has_capability(user: "User", capability: Capability) -> bool:
    """True iff the user's standing platform role grants ``capability``.

    This reflects *standing* privilege only. Time-bound PAM grants (cross-guild
    data access) are resolved separately when the guild session is built.
    """
    return capability in capabilities_for(user.role)


# Privilege ladder, least → most. Assignment is bounded by rank rather than
# capability-subset: the presets aren't strictly nested (owner intentionally
# drops ``access.request``, which the lower tiers carry), so a subset check
# would wrongly forbid an owner from assigning ``admin``. Mirrors the
# frontend's PLATFORM_ROLE_ORDER.
_ROLE_RANK: dict[UserRole, int] = {
    UserRole.member: 0,
    UserRole.support: 1,
    UserRole.moderator: 2,
    UserRole.admin: 3,
    UserRole.owner: 4,
}


def role_rank(role: UserRole) -> int:
    return _ROLE_RANK.get(role, 0)


def can_assign_role(actor: "User", target_role: UserRole) -> bool:
    """Whether ``actor`` may assign ``target_role`` to someone.

    Bounded delegation: you can only grant a role at or below your own rung of
    the ladder (an admin can't mint an owner). Requires the actor to hold
    ``ROLES_ASSIGN`` in the first place.
    """
    if not user_has_capability(actor, Capability.ROLES_ASSIGN):
        return False
    return role_rank(target_role) <= role_rank(actor.role)

"""Initiative-level access helpers and the sharing pickers' roster queries.

What the database enforces is the guild schema's own policies and functions
(``app/db/authorization.py``); what a request holds is its standing
(``GuildContext``, built by the seam in ``app/api/deps``). This module keeps the
questions those two do not answer as a value: who manages an initiative, which
of its members a role permits, and the roster and override queries the sharing
surfaces list from.

The guild-level questions that used to live here — is this an admin, does
this account hold the seat, is there a membership row — are the standing's:
``GuildContext.is_admin``, ``.seat``, ``.reaches``.
"""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import func
from sqlmodel import select

from app.core.messages import InitiativeMessages
from app.models.tenant.initiative import (
    InitiativeMember,
    InitiativeRoleModel,
    PermissionKey,
    DEFAULT_PERMISSION_VALUES,
)
from app.models.platform.user import User

# Re-export the RLS context helper so callers can import from a single place.
from app.db.session import require_guild_context, set_rls_context  # noqa: F401


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Initiative manager checks
# ---------------------------------------------------------------------------


async def is_initiative_manager(session: AsyncSession, *, initiative_id: int) -> bool:
    """Whether this request manages ``initiative_id``, by the standing.

    The seam computed ``app.manager_initiatives`` from the roster and the
    roles' rows when it routed the session; this reads that answer back rather
    than asking the rows again. Granted access manages nothing.
    """
    context = require_guild_context(session)
    return initiative_id in context.manager_initiatives


async def assert_initiative_manager(
    session: AsyncSession, *, initiative_id: int
) -> None:
    """Raise ``PermissionError`` unless this request manages the initiative."""
    if await is_initiative_manager(session, initiative_id=initiative_id):
        return
    raise PermissionError(InitiativeMessages.MANAGER_REQUIRED)


async def check_initiative_permission(
    session: AsyncSession,
    *,
    initiative_id: int,
    user: User,
    permission_key: PermissionKey,
) -> bool:
    """Whether ``user``'s role in the initiative permits ``permission_key``.

    Asked of the schema's own ``initiative_role_permits`` — the function the
    content policies call — so the rule has one body: a manager holds every
    key, a stored row decides, and the key's documented default decides when
    there is none. It reads the standing the session was routed with, so it
    answers for the request's own account.
    """
    default = DEFAULT_PERMISSION_VALUES.get(permission_key, False)
    return bool(
        (
            await session.exec(
                select(
                    func.initiative_role_permits(
                        initiative_id, user.id, permission_key.value, default
                    )
                )
            )
        ).one()
    )


def _role_grants(
    role_ref: InitiativeRoleModel | None, permission_key: PermissionKey
) -> bool:
    """Resolve a single role's grant for ``permission_key`` — the same rule as
    :func:`check_initiative_permission` (manager ⇒ all; explicit row; else the
    documented default), factored out so the bulk resolver can't drift from it."""
    if role_ref is None:
        return False
    if role_ref.is_manager:
        return True
    for perm in role_ref.permissions:
        if perm.permission_key == permission_key:
            return perm.enabled
    return DEFAULT_PERMISSION_VALUES.get(permission_key, False)


async def members_permitted(
    session: AsyncSession,
    *,
    initiative_id: int,
    user_ids: set[int],
    permission_key: PermissionKey,
) -> set[int]:
    """Which of ``user_ids`` hold ``permission_key`` in ``initiative_id``.

    :func:`check_initiative_permission` asked about many people at once, through
    the same :func:`_role_grants` rule, so sharing can narrow a list of
    grantees without restating what a role grants.
    """
    from sqlalchemy.orm import selectinload
    from sqlmodel import select

    if not user_ids:
        return set()
    memberships = (
        await session.exec(
            select(InitiativeMember)
            .options(
                selectinload(InitiativeMember.role_ref).selectinload(
                    InitiativeRoleModel.permissions
                )
            )
            .where(
                InitiativeMember.initiative_id == initiative_id,
                InitiativeMember.user_id.in_(list(user_ids)),
            )
        )
    ).all()
    return {
        m.user_id
        for m in memberships
        if _role_grants(m.role_ref, permission_key) and m.user_id is not None
    }


async def roles_permitting(
    session: AsyncSession,
    *,
    initiative_id: int,
    role_ids: set[int],
    permission_key: PermissionKey,
) -> set[int]:
    """Which of ``role_ids`` grant ``permission_key`` — the role-shaped form of
    :func:`members_permitted`, for sharing addressed to a role."""
    from sqlalchemy.orm import selectinload
    from sqlmodel import select

    if not role_ids:
        return set()
    roles = (
        await session.exec(
            select(InitiativeRoleModel)
            .options(selectinload(InitiativeRoleModel.permissions))
            .where(
                InitiativeRoleModel.initiative_id == initiative_id,
                InitiativeRoleModel.id.in_(list(role_ids)),
            )
        )
    ).all()
    return {r.id for r in roles if _role_grants(r, permission_key) and r.id is not None}


def override_sharing_initiatives_select(user_id: int):
    """Select the initiative ids (in the routed guild schema) where the user
    holds a role with ``override_share_restrictions`` ("Full access") — the set
    the request's DAC override consults
    (:meth:`app.db.guild_standing.GuildContext.overrides_sharing`).

    One indexed read over the user's memberships, joined to their role. Handed
    out as a statement rather than a result because the standing statement folds
    it into the ``set_config`` that records the answer
    (:data:`app.db.guild_standing.STANDING_SQL`), so this stays the one place
    that says which initiatives those are.
    """
    from sqlmodel import select

    return (
        select(InitiativeMember.initiative_id)
        .join(
            InitiativeRoleModel,
            InitiativeRoleModel.id == InitiativeMember.role_id,
        )
        .where(
            InitiativeMember.user_id == user_id,
            InitiativeRoleModel.override_share_restrictions.is_(True),
        )
    )


async def override_sharing_initiative_ids(
    session: AsyncSession,
    *,
    user_id: int,
) -> set[int]:
    """Run :func:`override_sharing_initiatives_select` and return its ids.

    For callers that want the set on its own — a cross-guild hop, a published
    view resolving its author — rather than as the request's recorded override.
    Usually empty (most users are full-access PMs nowhere).
    """
    return set((await session.exec(override_sharing_initiatives_select(user_id))).all())

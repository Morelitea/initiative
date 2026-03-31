"""Automations endpoints — stub for infra/paid pipeline integration.

Initiative-scoped automations. Access is gated at the infrastructure level
(ENABLE_AUTOMATIONS env var) and at the initiative level via
automations_enabled + create_automations permission keys.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import select

from app.api.deps import RLSSessionDep, get_current_active_user, GuildContext, get_guild_membership
from app.core.config import settings
from app.core.messages import AutomationsMessages, InitiativeMessages
from app.models.initiative import Initiative, PermissionKey
from app.models.user import User
from app.services import rls as rls_service

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_active_user)]
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


def _require_infra_flag() -> None:
    """Raise 403 if automations are not enabled at the infrastructure level."""
    if not settings.ENABLE_AUTOMATIONS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AutomationsMessages.INFRA_FEATURE_DISABLED,
        )


async def _get_initiative_or_404(
    session: RLSSessionDep,
    initiative_id: int,
) -> Initiative:
    """Guild-scoped initiative lookup (RLS enforces guild tenancy)."""
    stmt = select(Initiative).where(Initiative.id == initiative_id)
    result = await session.exec(stmt)
    initiative = result.one_or_none()
    if not initiative:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.NOT_FOUND,
        )
    return initiative


async def _check_initiative_permission(
    session: RLSSessionDep,
    initiative: Initiative,
    user: User,
    guild_context: GuildContext,
    permission_key: PermissionKey,
) -> None:
    """Check that user has the required permission on the initiative."""
    if rls_service.is_guild_admin(guild_context.role):
        return
    has_perm = await rls_service.check_initiative_permission(
        session,
        initiative_id=initiative.id,
        user=user,
        permission_key=permission_key,
    )
    if not has_perm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AutomationsMessages.FEATURE_DISABLED,
        )


@router.get("/automations")
async def list_automations(
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    initiative_id: int = Query(..., description="Initiative to list automations for"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> dict:
    """List automations for an initiative. Stub endpoint for future pipeline integration."""
    _require_infra_flag()

    initiative = await _get_initiative_or_404(session, initiative_id)
    if not initiative.automations_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AutomationsMessages.FEATURE_DISABLED,
        )
    await _check_initiative_permission(
        session, initiative, current_user, guild_context, PermissionKey.automations_enabled,
    )

    return {
        "items": [],
        "total_count": 0,
        "page": page,
        "page_size": page_size,
        "has_next": False,
    }

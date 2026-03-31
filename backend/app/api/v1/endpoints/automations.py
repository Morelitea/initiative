"""Automations endpoints — stub for infra/paid pipeline integration.

Initiative-scoped automations. Access is gated at the infrastructure level
(ENABLE_AUTOMATIONS env var) and at the initiative level via
automations_enabled + create_automations permission keys.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import RLSSessionDep, get_current_active_user, GuildContext
from app.core.config import settings
from app.core.messages import AutomationsMessages
from app.models.initiative import Initiative
from app.models.user import User

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_active_user)]
GuildContextDep = Annotated[GuildContext, Depends()]


def _require_infra_flag() -> None:
    """Raise 403 if automations are not enabled at the infrastructure level."""
    if not settings.ENABLE_AUTOMATIONS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AutomationsMessages.INFRA_FEATURE_DISABLED,
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

    initiative = await session.get(Initiative, initiative_id)
    if not initiative:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="INITIATIVE_NOT_FOUND",
        )
    if not initiative.automations_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AutomationsMessages.FEATURE_DISABLED,
        )

    return {
        "items": [],
        "total_count": 0,
        "page": page,
        "page_size": page_size,
        "has_next": False,
    }

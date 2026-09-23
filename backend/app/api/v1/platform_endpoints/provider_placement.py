"""The platform's sign-in placement rules, per provider.

Operators and owners (``guilds.manage``) write the rules; whether they apply
to every community is an owner's call (``config.manage``). Everything runs on
the system engine, and the logic lives in
``app.services.platform.provider_placement``.
"""

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.platform_endpoints.admin import ConfigManageDep, GuildsManageDep
from app.db.session import get_admin_session
from app.schemas.platform.settings import (
    GuildNarrowingPending,
    PlacementCommunityRead,
    PlacementEverywhereUpdate,
    PlacementInitiativeRead,
    ProviderPlacementResponse,
    ProviderPlacementRuleCreate,
    ProviderPlacementRuleRead,
    ProviderPlacementRuleUpdate,
)
from app.services.auth import narrowing_review
from app.services.platform import provider_placement

router = APIRouter()

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]


@router.get("/", response_model=ProviderPlacementResponse)
async def list_provider_placement(
    session: AdminSessionDep,
    _operator: GuildsManageDep,
) -> ProviderPlacementResponse:
    """Every provider, its rules, and whether rules apply everywhere."""
    return await provider_placement.list_rules(session)


@router.get("/requests", response_model=List[GuildNarrowingPending])
async def list_placement_requests(
    session: AdminSessionDep,
    _operator: GuildsManageDep,
) -> List[GuildNarrowingPending]:
    """Communities waiting for somebody to agree that the domain or tenant
    they named is theirs. Answered on the community's own narrowing route."""
    return await narrowing_review.unanswered(session)


@router.put("/everywhere", response_model=PlacementEverywhereUpdate)
async def set_provider_placement_everywhere(
    payload: PlacementEverywhereUpdate,
    session: AdminSessionDep,
    owner: ConfigManageDep,
) -> PlacementEverywhereUpdate:
    """Apply provider rules to every community they name, or only to the ones
    that accepted them. Recorded on every change."""
    enabled = await provider_placement.set_placement_everywhere(
        session, enabled=payload.enabled, actor_user_id=owner.id
    )
    return PlacementEverywhereUpdate(enabled=enabled)


@router.get("/communities", response_model=List[PlacementCommunityRead])
async def list_placement_communities(
    session: AdminSessionDep,
    _operator: GuildsManageDep,
    provider_id: int,
    q: Optional[str] = Query(default=None, max_length=100),
) -> List[PlacementCommunityRead]:
    """Communities a rule for this provider may name, by name."""
    return await provider_placement.list_communities(
        session, provider_id=provider_id, query=q
    )


@router.get(
    "/providers/{provider_id}/communities/{guild_id}/initiatives",
    response_model=List[PlacementInitiativeRead],
)
async def list_placement_targets(
    provider_id: int,
    guild_id: int,
    session: AdminSessionDep,
    _operator: GuildsManageDep,
) -> List[PlacementInitiativeRead]:
    """The initiatives and roles a rule for this community may place people
    in, for a community this provider's rules apply to."""
    return await provider_placement.list_targets(
        session, provider_id=provider_id, guild_id=guild_id
    )


@router.post(
    "/rules",
    response_model=ProviderPlacementRuleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_provider_placement_rule(
    payload: ProviderPlacementRuleCreate,
    session: AdminSessionDep,
    operator: GuildsManageDep,
) -> ProviderPlacementRuleRead:
    return await provider_placement.create_rule(
        session, payload=payload, actor_user_id=operator.id
    )


@router.patch("/rules/{rule_id}", response_model=ProviderPlacementRuleRead)
async def update_provider_placement_rule(
    rule_id: int,
    payload: ProviderPlacementRuleUpdate,
    session: AdminSessionDep,
    operator: GuildsManageDep,
) -> ProviderPlacementRuleRead:
    return await provider_placement.update_rule(
        session, rule_id=rule_id, payload=payload, actor_user_id=operator.id
    )


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_placement_rule(
    rule_id: int,
    session: AdminSessionDep,
    operator: GuildsManageDep,
) -> None:
    await provider_placement.delete_rule(
        session, rule_id=rule_id, actor_user_id=operator.id
    )

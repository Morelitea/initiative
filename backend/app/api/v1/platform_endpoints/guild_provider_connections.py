"""Which of the platform's providers a community signs its members in through.

Managed here: a community's ``guild_provider_connections`` rows, and the rules
riding them. A community does not register a provider — the operator holds
every one of those — so nothing on this surface takes an issuer, a client id or
a secret. What it takes is which provider, the claim that narrows it to this
community's own tenant, and where the groups that provider asserts land.

Those are one sentence said in one breath, which is why they share a router and
a gate: *our people come in through this, and these of them belong here.*

Exists only where the operator has granted the community that option (404
otherwise, like the rest of the guild auth surface).

Reading is a guild admin's; changing is the superadmin's, the seat that
holds a community's sign-in configuration.

Reading runs on the request-path session; changing runs on the seat's, which
is routed into ``guild_<id>_superadmin``. The connections themselves are read
and written on the system engine (``guild_provider_connections`` and
``auth_providers`` carry no request-path grants).
"""

from typing import Annotated, List

from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    SeatWriteSessionDep,
    SettingsAdminContextDep,
    get_current_active_user,
)
from app.api.v1.platform_endpoints.guilds import _require_guild_auth_option
from app.core.guild_auth_options import GuildAuthOption
from app.db.session import get_admin_session
from app.models.platform.user import User
from app.schemas.platform.settings import (
    ConnectableProviderRead,
    GuildClaimRuleCreate,
    GuildClaimRuleRead,
    GuildClaimRulesResponse,
    GuildClaimRuleUpdate,
    GuildProviderConnectionCreate,
    GuildProviderConnectionRead,
    GuildProviderConnectionUpdate,
)
from app.services.auth import guild_claim_rules as claim_rules
from app.services.auth import guild_provider_connections as connections
from app.services.platform import guilds as guilds_service

router = APIRouter()
AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]
CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


async def _require_connection_option(
    admin_session: AsyncSession, guild_id: int
) -> None:
    """Changing it: the operator's grant of the option. The seat itself is
    :data:`~app.api.deps.SeatWriteSessionDep`, which routed the request here — who
    may enter a community is that seat's to decide."""
    await _require_guild_auth_option(admin_session, guild_id, GuildAuthOption.providers)


@router.get(
    "/{guild_id}/auth/connections", response_model=List[GuildProviderConnectionRead]
)
async def list_guild_provider_connections(
    guild_id: int,
    _guild_context: SettingsAdminContextDep,
    admin_session: AdminSessionDep,
) -> List[GuildProviderConnectionRead]:
    await _require_guild_auth_option(admin_session, guild_id, GuildAuthOption.providers)
    return await connections.list_connections(admin_session, guild_id=guild_id)


@router.get(
    "/{guild_id}/auth/connections/available",
    response_model=List[ConnectableProviderRead],
)
async def list_connectable_providers(
    guild_id: int,
    _guild_context: SettingsAdminContextDep,
    admin_session: AdminSessionDep,
) -> List[ConnectableProviderRead]:
    """The providers this community may choose from: the ones on offer, plus
    the ones it already connects to. Names only — a community picks a provider
    by name, and one registered for a single customer is nobody else's to
    see."""
    await _require_guild_auth_option(admin_session, guild_id, GuildAuthOption.providers)
    return await connections.list_connectable(admin_session, guild_id=guild_id)


@router.post(
    "/{guild_id}/auth/connections",
    response_model=GuildProviderConnectionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_guild_provider_connection(
    guild_id: int,
    payload: GuildProviderConnectionCreate,
    _session: SeatWriteSessionDep,
    admin_session: AdminSessionDep,
    current_user: CurrentUserDep,
) -> GuildProviderConnectionRead:
    await _require_connection_option(admin_session, guild_id)
    return await connections.create_connection(
        admin_session, payload, guild_id=guild_id, actor_user_id=current_user.id
    )


@router.patch(
    "/{guild_id}/auth/connections/{connection_id}",
    response_model=GuildProviderConnectionRead,
)
async def update_guild_provider_connection(
    guild_id: int,
    connection_id: int,
    payload: GuildProviderConnectionUpdate,
    session: SeatWriteSessionDep,
    admin_session: AdminSessionDep,
    current_user: CurrentUserDep,
) -> GuildProviderConnectionRead:
    await _require_connection_option(admin_session, guild_id)
    if payload.enabled is False:
        await guilds_service.lock_guild_seats(session, guild_id)
    return await connections.update_connection(
        admin_session,
        connection_id,
        payload,
        guild_id=guild_id,
        actor_user_id=current_user.id,
    )


@router.delete(
    "/{guild_id}/auth/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_guild_provider_connection(
    guild_id: int,
    connection_id: int,
    session: SeatWriteSessionDep,
    admin_session: AdminSessionDep,
    current_user: CurrentUserDep,
) -> None:
    """Disconnect. Nobody is signed out and no account changes — what goes is
    the button on this community's sign-in page, and its claim on who arrives
    through that provider. Lift any sign-in requirement that depends on this
    connection first: the gate reads the connections, so a requirement without
    one has nothing left to satisfy it."""
    await _require_connection_option(admin_session, guild_id)
    # Setting a requirement takes the same lock. Whichever wins commits before
    # the other checks, so a provider cannot become required while its
    # connection is being removed through the separate system session.
    await guilds_service.lock_guild_seats(session, guild_id)
    await connections.delete_connection(
        admin_session, connection_id, guild_id=guild_id, actor_user_id=current_user.id
    )


@router.get("/{guild_id}/auth/rules", response_model=GuildClaimRulesResponse)
async def list_guild_claim_rules(
    guild_id: int,
    _guild_context: SettingsAdminContextDep,
    admin_session: AdminSessionDep,
) -> GuildClaimRulesResponse:
    """Where this community places the people its providers vouch for."""
    await _require_guild_auth_option(admin_session, guild_id, GuildAuthOption.providers)
    return await claim_rules.list_rules(admin_session, guild_id=guild_id)


@router.post(
    "/{guild_id}/auth/rules",
    response_model=GuildClaimRuleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_guild_claim_rule(
    guild_id: int,
    payload: GuildClaimRuleCreate,
    _session: SeatWriteSessionDep,
    admin_session: AdminSessionDep,
    current_user: CurrentUserDep,
) -> GuildClaimRuleRead:
    """Place the people carrying one group. The rule reads a provider this
    community already counts as its own — saying what a group means is the
    same sentence as saying whose people arrive through it."""
    await _require_connection_option(admin_session, guild_id)
    return await claim_rules.create_rule(
        admin_session,
        guild_id=guild_id,
        payload=payload,
        actor_user_id=current_user.id,
    )


@router.patch("/{guild_id}/auth/rules/{rule_id}", response_model=GuildClaimRuleRead)
async def update_guild_claim_rule(
    guild_id: int,
    rule_id: int,
    payload: GuildClaimRuleUpdate,
    _session: SeatWriteSessionDep,
    admin_session: AdminSessionDep,
    current_user: CurrentUserDep,
) -> GuildClaimRuleRead:
    await _require_connection_option(admin_session, guild_id)
    return await claim_rules.update_rule(
        admin_session,
        guild_id=guild_id,
        rule_id=rule_id,
        payload=payload,
        actor_user_id=current_user.id,
    )


@router.delete(
    "/{guild_id}/auth/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_guild_claim_rule(
    guild_id: int,
    rule_id: int,
    _session: SeatWriteSessionDep,
    admin_session: AdminSessionDep,
    current_user: CurrentUserDep,
) -> None:
    """Stop placing the people carrying one group. Nobody loses a standing
    they already hold until their next sign-in through that provider, which
    reconciles against the rules as they stand then."""
    await _require_connection_option(admin_session, guild_id)
    await claim_rules.delete_rule(
        admin_session,
        guild_id=guild_id,
        rule_id=rule_id,
        actor_user_id=current_user.id,
    )

"""Which of the platform's providers a community signs its members in through.

Managed here: a community's ``guild_provider_connections`` rows. A community
does not register a provider — the operator holds every one of those — so
nothing on this surface takes an issuer, a client id or a secret. What it takes
is which provider, and the claim that narrows it to this community's own
tenant.

Exists only where the operator has granted the community that option (404
otherwise, like the rest of the guild auth surface).

Reading is a guild admin's; changing is the superadmin's, the seat that
holds a community's sign-in configuration.

The posture and role checks run on the request-path session; the connections
themselves are read and written on the system engine
(``guild_provider_connections`` and ``auth_providers`` carry no request-path
grants).
"""

from typing import Annotated, List

from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import SessionDep, get_current_active_user
from app.api.v1.platform_endpoints.guilds import (
    _ensure_guild_admin,
    _ensure_guild_superadmin,
    _require_guild_auth_option,
)
from app.core.guild_auth_options import GuildAuthOption
from app.db.session import get_admin_session
from app.models.platform.user import User
from app.schemas.platform.settings import (
    ConnectableProviderRead,
    GuildProviderConnectionCreate,
    GuildProviderConnectionRead,
    GuildProviderConnectionUpdate,
)
from app.services.auth import guild_provider_connections as connections

router = APIRouter()
AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]
CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


async def _require_connection_reader(
    session: AsyncSession,
    admin_session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
) -> None:
    """Seeing what a community signs in through: the operator's grant of the
    option, then guild admin. Reading is admin-or-above, one rung below
    writing — an admin who cannot see what is set cannot ask for it to be
    changed."""
    await _require_guild_auth_option(admin_session, guild_id, GuildAuthOption.providers)
    await _ensure_guild_admin(session, guild_id=guild_id, user_id=user_id)


async def _require_connection_admin(
    session: AsyncSession,
    admin_session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
) -> None:
    """Changing it: the same grant, then the superadmin seat — who may
    enter a community is that seat's to decide."""
    await _require_guild_auth_option(admin_session, guild_id, GuildAuthOption.providers)
    await _ensure_guild_superadmin(session, guild_id=guild_id, user_id=user_id)


@router.get(
    "/{guild_id}/auth/connections", response_model=List[GuildProviderConnectionRead]
)
async def list_guild_provider_connections(
    guild_id: int,
    session: SessionDep,
    admin_session: AdminSessionDep,
    current_user: CurrentUserDep,
) -> List[GuildProviderConnectionRead]:
    await _require_connection_reader(
        session, admin_session, guild_id=guild_id, user_id=current_user.id
    )
    return await connections.list_connections(admin_session, guild_id=guild_id)


@router.get(
    "/{guild_id}/auth/connections/available",
    response_model=List[ConnectableProviderRead],
)
async def list_connectable_providers(
    guild_id: int,
    session: SessionDep,
    admin_session: AdminSessionDep,
    current_user: CurrentUserDep,
) -> List[ConnectableProviderRead]:
    """The providers this community may choose from: the ones on offer, plus
    the ones it already connects to. Names only — a community picks a provider
    by name, and one registered for a single customer is nobody else's to
    see."""
    await _require_connection_reader(
        session, admin_session, guild_id=guild_id, user_id=current_user.id
    )
    return await connections.list_connectable(admin_session, guild_id=guild_id)


@router.post(
    "/{guild_id}/auth/connections",
    response_model=GuildProviderConnectionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_guild_provider_connection(
    guild_id: int,
    payload: GuildProviderConnectionCreate,
    session: SessionDep,
    admin_session: AdminSessionDep,
    current_user: CurrentUserDep,
) -> GuildProviderConnectionRead:
    await _require_connection_admin(
        session, admin_session, guild_id=guild_id, user_id=current_user.id
    )
    return await connections.create_connection(
        admin_session, payload, guild_id=guild_id
    )


@router.patch(
    "/{guild_id}/auth/connections/{connection_id}",
    response_model=GuildProviderConnectionRead,
)
async def update_guild_provider_connection(
    guild_id: int,
    connection_id: int,
    payload: GuildProviderConnectionUpdate,
    session: SessionDep,
    admin_session: AdminSessionDep,
    current_user: CurrentUserDep,
) -> GuildProviderConnectionRead:
    await _require_connection_admin(
        session, admin_session, guild_id=guild_id, user_id=current_user.id
    )
    return await connections.update_connection(
        admin_session, connection_id, payload, guild_id=guild_id
    )


@router.delete(
    "/{guild_id}/auth/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_guild_provider_connection(
    guild_id: int,
    connection_id: int,
    session: SessionDep,
    admin_session: AdminSessionDep,
    current_user: CurrentUserDep,
) -> None:
    """Disconnect. Nobody is signed out and no account changes — what goes is
    the button on this community's sign-in page, and its claim on who arrives
    through that provider. A sign-in requirement naming the provider is left
    standing, so lift that first if the community means to reopen."""
    await _require_connection_admin(
        session, admin_session, guild_id=guild_id, user_id=current_user.id
    )
    await connections.delete_connection(admin_session, connection_id, guild_id=guild_id)

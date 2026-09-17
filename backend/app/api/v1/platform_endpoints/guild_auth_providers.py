"""CRUD for the guild's own login provider registry.

Managed here: guild-scoped ``auth_providers`` rows — the identity providers a
guild configures for itself. Exists only where the operator has granted the
guild that option (404 otherwise, like the rest of the guild auth surface).

Reading is a guild admin's; changing is the security admin's, the seat that
holds a guild's sign-in configuration. Looking a provider up — ``discover``
for an address still being typed, ``{id}/test`` for a saved row's own issuer —
goes with changing rather than reading: the answer exists to fill in a form
only that seat may save, and the lookup spends the deployment's egress. Both
are rate limited.

The CRUD logic — namespace scoping, slug rules, write-only secrets, delete
semantics — lives in ``app.services.auth.provider_registry``, shared with the
operator CRUD; this router only gates and delegates. The posture and
guild-admin checks run on the request-path session; registry reads and writes
run on the system engine (``auth_providers`` and its secret companion carry no
request-path grants).
"""

from typing import Annotated, List

from fastapi import APIRouter, Depends, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import SessionDep, get_current_active_user
from app.core.guild_auth_options import GuildAuthOption
from app.api.v1.platform_endpoints.guilds import (
    _ensure_guild_admin,
    _ensure_guild_security_admin,
    _require_guild_auth_option,
)
from app.core.rate_limit import limiter
from app.db.session import get_admin_session
from app.models.platform.user import User
from app.schemas.platform.settings import (
    AuthProviderAdminRead,
    AuthProviderCreate,
    AuthProviderDiscoverRequest,
    AuthProviderProbeResult,
    AuthProviderUpdate,
)
from app.services.auth import provider_probe, provider_registry

router = APIRouter()
AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]
CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


async def _require_guild_provider_reader(
    session: AsyncSession,
    admin_session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
) -> None:
    """Seeing the registry: the operator's grant of the providers option, then
    guild admin. Without the grant the surface 404s but the guild's provider
    rows are left intact — existing members keep signing in through them.

    Reading is admin-or-above, one rung below writing (below): an admin who
    cannot see what is configured cannot ask for it to be changed.
    """
    await _require_guild_auth_option(admin_session, guild_id, GuildAuthOption.providers)
    await _ensure_guild_admin(session, guild_id=guild_id, user_id=user_id)


async def _require_guild_provider_admin(
    session: AsyncSession,
    admin_session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
) -> None:
    """Changing the registry: the same operator grant, then the security admin
    seat — the guild's identity providers are its sign-in configuration."""
    await _require_guild_auth_option(admin_session, guild_id, GuildAuthOption.providers)
    await _ensure_guild_security_admin(session, guild_id=guild_id, user_id=user_id)


@router.get("/{guild_id}/auth/providers", response_model=List[AuthProviderAdminRead])
async def list_guild_auth_providers(
    guild_id: int,
    session: SessionDep,
    admin_session: AdminSessionDep,
    current_user: CurrentUserDep,
) -> List[AuthProviderAdminRead]:
    await _require_guild_provider_reader(
        session, admin_session, guild_id=guild_id, user_id=current_user.id
    )
    return await provider_registry.list_providers(admin_session, guild_id=guild_id)


@router.post(
    "/{guild_id}/auth/providers",
    response_model=AuthProviderAdminRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_guild_auth_provider(
    guild_id: int,
    provider_in: AuthProviderCreate,
    session: SessionDep,
    admin_session: AdminSessionDep,
    current_user: CurrentUserDep,
) -> AuthProviderAdminRead:
    await _require_guild_provider_admin(
        session, admin_session, guild_id=guild_id, user_id=current_user.id
    )
    return await provider_registry.create_provider(
        admin_session, provider_in, guild_id=guild_id
    )


@router.patch(
    "/{guild_id}/auth/providers/{provider_id}", response_model=AuthProviderAdminRead
)
async def update_guild_auth_provider(
    guild_id: int,
    provider_id: int,
    provider_in: AuthProviderUpdate,
    session: SessionDep,
    admin_session: AdminSessionDep,
    current_user: CurrentUserDep,
) -> AuthProviderAdminRead:
    await _require_guild_provider_admin(
        session, admin_session, guild_id=guild_id, user_id=current_user.id
    )
    return await provider_registry.update_provider(
        admin_session, provider_id, provider_in, guild_id=guild_id
    )


@router.delete(
    "/{guild_id}/auth/providers/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_guild_auth_provider(
    guild_id: int,
    provider_id: int,
    session: SessionDep,
    admin_session: AdminSessionDep,
    current_user: CurrentUserDep,
) -> None:
    """Delete one of the guild's providers. Linked identities cascade with it;
    a provider the guild's auth policy requires is refused (409) — change the
    policy first."""
    await _require_guild_provider_admin(
        session, admin_session, guild_id=guild_id, user_id=current_user.id
    )
    await provider_registry.delete_provider(
        admin_session, provider_id, guild_id=guild_id
    )


@router.post(
    "/{guild_id}/auth/providers/discover", response_model=AuthProviderProbeResult
)
@limiter.limit("10/minute")
async def discover_guild_auth_provider(
    request: Request,
    guild_id: int,
    payload: AuthProviderDiscoverRequest,
    session: SessionDep,
    admin_session: AdminSessionDep,
    current_user: CurrentUserDep,
) -> AuthProviderProbeResult:
    """Look up an address and report what it offers, before anything is saved."""
    await _require_guild_provider_admin(
        session, admin_session, guild_id=guild_id, user_id=current_user.id
    )
    result = await provider_probe.probe_issuer(payload.issuer, guild_id=guild_id)
    return AuthProviderProbeResult.model_validate(result, from_attributes=True)


@router.post(
    "/{guild_id}/auth/providers/{provider_id}/test",
    response_model=AuthProviderProbeResult,
)
@limiter.limit("10/minute")
async def test_guild_auth_provider(
    request: Request,
    guild_id: int,
    provider_id: int,
    session: SessionDep,
    admin_session: AdminSessionDep,
    current_user: CurrentUserDep,
) -> AuthProviderProbeResult:
    """Look up a saved provider's own issuer. The address comes off the row."""
    await _require_guild_provider_admin(
        session, admin_session, guild_id=guild_id, user_id=current_user.id
    )
    result = await provider_probe.probe_provider(
        admin_session, provider_id, guild_id=guild_id
    )
    return AuthProviderProbeResult.model_validate(result, from_attributes=True)

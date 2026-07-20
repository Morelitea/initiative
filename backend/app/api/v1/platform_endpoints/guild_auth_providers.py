"""Guild-admin CRUD for the guild's own login provider registry.

Managed here: guild-scoped ``auth_providers`` rows — the identity providers a
guild configures for itself when the platform runs per-guild auth. Exists only
in that posture (404 otherwise, like the rest of the guild auth surface) and
only for the guild's own admins.

The CRUD logic — namespace scoping, slug rules, write-only secrets, delete
semantics — lives in ``app.services.auth.provider_registry``, shared with the
operator CRUD; this router only gates and delegates. The posture and
guild-admin checks run on the request-path session; registry reads and writes
run on the system engine (``auth_providers`` and its secret companion carry no
request-path grants).
"""

from typing import Annotated, List

from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import SessionDep, get_current_active_user
from app.api.v1.platform_endpoints.guilds import (
    _ensure_guild_admin,
    _require_guild_auth_scope,
)
from app.db.session import get_admin_session
from app.models.platform.user import User
from app.schemas.platform.settings import (
    AuthProviderAdminRead,
    AuthProviderCreate,
    AuthProviderUpdate,
)
from app.services.auth import provider_registry

router = APIRouter()
AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]
CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


async def _require_guild_provider_admin(
    session: AsyncSession, *, guild_id: int, user_id: int
) -> None:
    """The shared gate for every route here: per-guild auth posture, then
    guild admin."""
    _require_guild_auth_scope()
    await _ensure_guild_admin(session, guild_id=guild_id, user_id=user_id)


@router.get("/{guild_id}/auth/providers", response_model=List[AuthProviderAdminRead])
async def list_guild_auth_providers(
    guild_id: int,
    session: SessionDep,
    admin_session: AdminSessionDep,
    current_user: CurrentUserDep,
) -> List[AuthProviderAdminRead]:
    await _require_guild_provider_admin(
        session, guild_id=guild_id, user_id=current_user.id
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
        session, guild_id=guild_id, user_id=current_user.id
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
        session, guild_id=guild_id, user_id=current_user.id
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
        session, guild_id=guild_id, user_id=current_user.id
    )
    await provider_registry.delete_provider(
        admin_session, provider_id, guild_id=guild_id
    )

"""Operator CRUD for the login provider registry (``auth_providers``).

Managed here: operator-global registry rows — the providers the login page
offers besides the platform SSO form. The platform provider row (slug
``oidc``) is reconciled from ``app_settings`` and is read-only in this CRUD
(listed with ``reserved=True``); guild-scoped rows have their own CRUD
(``guild_auth_providers``) and never appear here.

Gating: ``config.manage`` (the same wall as the rest of the admin settings).
The CRUD logic — namespace scoping, slug rules, write-only secrets, delete
semantics — lives in ``app.services.auth.provider_registry``, shared with the
guild CRUD; this router only gates and delegates. All reads and writes run on
the system engine — ``auth_providers`` and its secret companion carry no
request-path grants.
"""

from typing import Annotated, List

from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.platform_endpoints.admin import ConfigManageDep
from app.db.session import get_admin_session
from app.schemas.platform.settings import (
    AuthProviderAdminRead,
    AuthProviderCreate,
    AuthProviderUpdate,
)
from app.services.auth import provider_registry

router = APIRouter()
AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]


@router.get("/", response_model=List[AuthProviderAdminRead])
async def list_auth_providers(
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> List[AuthProviderAdminRead]:
    return await provider_registry.list_providers(session, guild_id=None)


@router.post(
    "/", response_model=AuthProviderAdminRead, status_code=status.HTTP_201_CREATED
)
async def create_auth_provider(
    provider_in: AuthProviderCreate,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> AuthProviderAdminRead:
    return await provider_registry.create_provider(session, provider_in, guild_id=None)


@router.patch("/{provider_id}", response_model=AuthProviderAdminRead)
async def update_auth_provider(
    provider_id: int,
    provider_in: AuthProviderUpdate,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> AuthProviderAdminRead:
    return await provider_registry.update_provider(
        session, provider_id, provider_in, guild_id=None
    )


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_auth_provider(
    provider_id: int,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> None:
    """Delete a provider. Its linked identities (and their stored refresh
    tokens) go with it via cascade — users who signed in through it keep their
    accounts and any other sign-in methods. A provider some guild's auth
    policy requires is refused (409): drop or repoint the policy first."""
    await provider_registry.delete_provider(session, provider_id, guild_id=None)

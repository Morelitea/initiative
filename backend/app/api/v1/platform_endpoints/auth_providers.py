"""Operator CRUD for the login provider registry (``auth_providers``).

Managed here: operator-global registry rows — the providers the login page
offers besides the platform SSO form. The platform provider row (slug
``oidc``) is reconciled from ``app_settings`` and is read-only in this CRUD
(listed with ``reserved=True``). Every row here is the operator's; a community
reaches one through ``guild_provider_connections``.

Gating: ``config.manage`` (the same wall as the rest of the admin settings).
The CRUD logic — slug rules, write-only secrets, delete semantics — lives in
``app.services.auth.provider_registry``; this router only gates and delegates. All reads and writes run on
the system engine — ``auth_providers`` and its secret companion carry no
request-path grants.

Two routes here read rather than write: ``discover`` looks up an address
somebody is still typing, and ``{id}/test`` looks up a saved row's own issuer.
Both go through ``app.services.auth.provider_probe`` and are rate limited,
because both spend the deployment's egress.
"""

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.platform_endpoints.admin import ConfigManageDep
from app.core.rate_limit import limiter
from app.db.session import get_admin_session
from app.schemas.platform.settings import (
    AuthProviderAdminRead,
    AuthProviderCreate,
    AuthProviderDiscoverRequest,
    AuthProviderProbeResult,
    AuthProviderUpdate,
    PlatformProviderDefaultRead,
    PlatformProviderDefaultUpdate,
)
from app.services.auth import provider_defaults, provider_probe, provider_registry

router = APIRouter()
AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]


@router.get("/", response_model=List[AuthProviderAdminRead])
async def list_auth_providers(
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> List[AuthProviderAdminRead]:
    return await provider_registry.list_providers(session)


@router.post(
    "/", response_model=AuthProviderAdminRead, status_code=status.HTTP_201_CREATED
)
async def create_auth_provider(
    provider_in: AuthProviderCreate,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> AuthProviderAdminRead:
    return await provider_registry.create_provider(session, provider_in)


@router.patch("/{provider_id}", response_model=AuthProviderAdminRead)
async def update_auth_provider(
    provider_id: int,
    provider_in: AuthProviderUpdate,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> AuthProviderAdminRead:
    return await provider_registry.update_provider(session, provider_id, provider_in)


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
    await provider_registry.delete_provider(session, provider_id)


@router.post("/discover", response_model=AuthProviderProbeResult)
@limiter.limit("10/minute")
async def discover_auth_provider(
    request: Request,
    payload: AuthProviderDiscoverRequest,
    _admin: ConfigManageDep,
) -> AuthProviderProbeResult:
    """Look up an address and report what it offers, before anything is saved.

    Reaches only as far as signing in does — https, under the shared size cap
    and timeout — so this never refuses an issuer a login would accept. What
    comes back is parsed and named; a failure is one of the discovery codes.
    """
    result = await provider_probe.probe_issuer(payload.issuer)
    return AuthProviderProbeResult.model_validate(result, from_attributes=True)


@router.post("/{provider_id}/test", response_model=AuthProviderProbeResult)
@limiter.limit("10/minute")
async def test_auth_provider(
    request: Request,
    provider_id: int,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> AuthProviderProbeResult:
    """Look up a saved provider's own issuer. The address comes off the row."""
    result = await provider_probe.probe_provider(session, provider_id)
    return AuthProviderProbeResult.model_validate(result, from_attributes=True)


@router.get(
    "/{provider_id}/default", response_model=Optional[PlatformProviderDefaultRead]
)
async def get_provider_default(
    provider_id: int,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> Optional[PlatformProviderDefaultRead]:
    """The deployment's own answer for this provider, or null where it has
    made none and every community speaks for itself."""
    return await provider_defaults.get_default(session, provider_id)


@router.put("/{provider_id}/default", response_model=PlatformProviderDefaultRead)
async def set_provider_default(
    provider_id: int,
    payload: PlatformProviderDefaultUpdate,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> PlatformProviderDefaultRead:
    """Answer once for the communities that have not.

    A community's own connection to this provider is untouched and goes on
    overriding this outright. Nobody is signed out: the gate reads the
    arrangement in force when it is asked, so this reaches the next request.
    """
    return await provider_defaults.set_default(session, provider_id, payload)


@router.delete("/{provider_id}/default", status_code=status.HTTP_204_NO_CONTENT)
async def clear_provider_default(
    provider_id: int,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> None:
    """Withdraw the answer. Communities that wrote their own keep them; the
    rest stop counting this provider as theirs."""
    await provider_defaults.clear_default(session, provider_id)

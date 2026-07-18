"""Operator CRUD for the login provider registry (``auth_providers``).

Managed here: operator-global registry rows — the providers the login page
offers besides the platform SSO form. The platform provider row (slug
``oidc``) is reconciled from ``app_settings`` and is read-only in this CRUD
(listed with ``reserved=True``); guild-scoped providers arrive with a later
phase.

Gating: ``config.manage`` (the same wall as the rest of the admin settings).
All reads and writes run on the system engine — ``auth_providers`` and its
secret companion carry no request-path grants. The client secret is
write-only: it is encrypted into ``auth_provider_secrets`` and never returned
by any endpoint; responses carry ``secret_set`` instead.
"""

import logging
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.platform_endpoints.admin import ConfigManageDep
from app.core.encryption import SALT_OIDC_CLIENT_SECRET, encrypt_field
from app.core.messages import AuthProviderMessages
from app.db.session import get_admin_session
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.auth_provider_secret import AuthProviderSecret
from app.schemas.platform.settings import (
    AuthProviderAdminRead,
    AuthProviderCreate,
    AuthProviderUpdate,
)
from app.services.auth.platform_provider import PLATFORM_OIDC_SLUG

logger = logging.getLogger(__name__)

router = APIRouter()
AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]


def _admin_read(row: AuthProvider, *, secret_set: bool) -> AuthProviderAdminRead:
    return AuthProviderAdminRead(
        id=row.id,
        slug=row.slug,
        display_name=row.display_name,
        kind=row.kind,
        enabled=row.enabled,
        issuer=row.issuer,
        client_id=row.client_id,
        scopes=row.scopes,
        role_claim_path=row.role_claim_path,
        allow_jit=row.allow_jit,
        icon=row.icon,
        button_style=row.button_style,
        secret_set=secret_set,
        reserved=row.slug == PLATFORM_OIDC_SLUG,
    )


async def _secret_set(session: AsyncSession, provider_id: int) -> bool:
    secret = await session.get(AuthProviderSecret, provider_id)
    return bool(secret and secret.client_secret_encrypted)


async def _set_provider_secret(
    session: AsyncSession, provider_id: int, client_secret: str | None
) -> None:
    """Store (or clear, with ``None``/empty) the encrypted client secret in
    the companion row; clearing deletes the row rather than leaving an empty
    one. Stages only — the caller commits."""
    secret = await session.get(AuthProviderSecret, provider_id)
    if not client_secret:
        if secret is not None:
            await session.delete(secret)
        return
    encrypted = encrypt_field(client_secret, SALT_OIDC_CLIENT_SECRET)
    if secret is None:
        secret = AuthProviderSecret(
            provider_id=provider_id, client_secret_encrypted=encrypted
        )
    else:
        secret.client_secret_encrypted = encrypted
    session.add(secret)


async def _editable_provider(session: AsyncSession, provider_id: int) -> AuthProvider:
    """The operator-global row for one id, or the 404/400 the CRUD contract
    promises (reserved rows are configured through the SSO settings form)."""
    row = (
        await session.exec(
            select(AuthProvider).where(
                AuthProvider.id == provider_id,
                AuthProvider.guild_id.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthProviderMessages.NOT_FOUND,
        )
    if row.slug == PLATFORM_OIDC_SLUG:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthProviderMessages.SLUG_RESERVED,
        )
    return row


@router.get("/", response_model=List[AuthProviderAdminRead])
async def list_auth_providers(
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> List[AuthProviderAdminRead]:
    rows = (
        await session.exec(
            select(AuthProvider)
            .where(AuthProvider.guild_id.is_(None))
            .order_by(AuthProvider.display_name)
        )
    ).all()
    with_secret = set(
        (
            await session.exec(
                select(AuthProviderSecret.provider_id).where(
                    AuthProviderSecret.client_secret_encrypted.is_not(None)
                )
            )
        ).all()
    )
    return [_admin_read(row, secret_set=row.id in with_secret) for row in rows]


@router.post(
    "/", response_model=AuthProviderAdminRead, status_code=status.HTTP_201_CREATED
)
async def create_auth_provider(
    provider_in: AuthProviderCreate,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> AuthProviderAdminRead:
    if provider_in.slug == PLATFORM_OIDC_SLUG:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthProviderMessages.SLUG_RESERVED,
        )
    existing = (
        await session.exec(
            select(AuthProvider.id).where(
                AuthProvider.slug == provider_in.slug,
                AuthProvider.guild_id.is_(None),
            )
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthProviderMessages.SLUG_TAKEN,
        )

    row = AuthProvider(
        **provider_in.model_dump(exclude={"client_secret"}),
        guild_id=None,
    )
    session.add(row)
    await session.flush()
    await _set_provider_secret(session, row.id, provider_in.client_secret)
    await session.commit()
    await session.refresh(row)
    logger.info("auth provider %s (%s) created", row.slug, row.id)
    return _admin_read(row, secret_set=bool(provider_in.client_secret))


@router.patch("/{provider_id}", response_model=AuthProviderAdminRead)
async def update_auth_provider(
    provider_id: int,
    provider_in: AuthProviderUpdate,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> AuthProviderAdminRead:
    row = await _editable_provider(session, provider_id)
    update_data = provider_in.model_dump(exclude_unset=True)

    # Write-only secret: absent = keep, empty = clear, value = replace.
    if "client_secret" in update_data:
        await _set_provider_secret(session, row.id, update_data.pop("client_secret"))

    for field_name, value in update_data.items():
        setattr(row, field_name, value)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _admin_read(row, secret_set=await _secret_set(session, row.id))


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
    row = await _editable_provider(session, provider_id)
    secret = await session.get(AuthProviderSecret, row.id)
    if secret is not None:
        await session.delete(secret)
    await session.delete(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthProviderMessages.IN_USE,
        ) from exc
    logger.info("auth provider %s (%s) deleted", row.slug, provider_id)

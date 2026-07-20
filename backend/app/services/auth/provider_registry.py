"""The login-provider registry's CRUD core, shared by its two namespaces.

``auth_providers`` holds two disjoint namespaces in one table: operator-global
rows (``guild_id IS NULL``, the platform login page's registry) and
guild-scoped rows (a set ``guild_id``, that guild's own IdPs under per-guild
auth). Every function here takes the namespace as ``guild_id`` and implements
the scoping, slug rules, write-only secret handling, and delete semantics
once — the routers own only their gates (operator ``config.manage`` vs.
per-guild posture + guild admin) and delegate here.

The client secret is write-only across both namespaces: encrypted into the
``auth_provider_secrets`` companion and never returned; reads carry
``secret_set`` instead. All callers run on the system engine — neither table
carries request-path grants.
"""

import logging

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import SALT_OIDC_CLIENT_SECRET, encrypt_field
from app.core.messages import AuthProviderMessages
from app.db.errors import FOREIGN_KEY_VIOLATION_SQLSTATE, dbapi_sqlstate
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.auth_provider_secret import AuthProviderSecret
from app.schemas.platform.settings import (
    AuthProviderAdminRead,
    AuthProviderCreate,
    AuthProviderUpdate,
)
from app.services.auth.platform_provider import PLATFORM_OIDC_SLUG

logger = logging.getLogger(__name__)


def _namespace_clause(guild_id: int | None):
    return (
        AuthProvider.guild_id.is_(None)
        if guild_id is None
        else AuthProvider.guild_id == guild_id
    )


def admin_read(row: AuthProvider, *, secret_set: bool) -> AuthProviderAdminRead:
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


async def secret_is_set(session: AsyncSession, provider_id: int) -> bool:
    secret = await session.get(AuthProviderSecret, provider_id)
    return bool(secret and secret.client_secret_encrypted)


async def set_provider_secret(
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


async def editable_provider(
    session: AsyncSession, provider_id: int, *, guild_id: int | None
) -> AuthProvider:
    """The namespace's row for one id, or the 404/400 the CRUD contract
    promises. An id from any other namespace is indistinguishable from a
    missing one; the reserved platform row (operator namespace only — no
    guild row can carry its slug) is configured through the SSO settings
    form, not a registry CRUD."""
    row = (
        await session.exec(
            select(AuthProvider).where(
                AuthProvider.id == provider_id,
                _namespace_clause(guild_id),
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


async def list_providers(
    session: AsyncSession, *, guild_id: int | None
) -> list[AuthProviderAdminRead]:
    rows = (
        await session.exec(
            select(AuthProvider)
            .where(_namespace_clause(guild_id))
            .order_by(AuthProvider.display_name)
        )
    ).all()
    row_ids = [row.id for row in rows]
    with_secret: set[int] = set()
    if row_ids:
        with_secret = set(
            (
                await session.exec(
                    select(AuthProviderSecret.provider_id).where(
                        AuthProviderSecret.provider_id.in_(row_ids),
                        AuthProviderSecret.client_secret_encrypted.is_not(None),
                    )
                )
            ).all()
        )
    return [admin_read(row, secret_set=row.id in with_secret) for row in rows]


async def create_provider(
    session: AsyncSession,
    provider_in: AuthProviderCreate,
    *,
    guild_id: int | None,
) -> AuthProviderAdminRead:
    """Create a row in the namespace. The platform slug is reserved in every
    namespace; slugs are unique within a namespace (409)."""
    if provider_in.slug == PLATFORM_OIDC_SLUG:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthProviderMessages.SLUG_RESERVED,
        )
    existing = (
        await session.exec(
            select(AuthProvider.id).where(
                AuthProvider.slug == provider_in.slug,
                _namespace_clause(guild_id),
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
        guild_id=guild_id,
    )
    session.add(row)
    await session.flush()
    await set_provider_secret(session, row.id, provider_in.client_secret)
    await session.commit()
    await session.refresh(row)
    logger.info(
        "auth provider %s (%s) created in namespace %s",
        row.slug,
        row.id,
        "global" if guild_id is None else f"guild {guild_id}",
    )
    return admin_read(row, secret_set=bool(provider_in.client_secret))


async def update_provider(
    session: AsyncSession,
    provider_id: int,
    provider_in: AuthProviderUpdate,
    *,
    guild_id: int | None,
) -> AuthProviderAdminRead:
    row = await editable_provider(session, provider_id, guild_id=guild_id)
    update_data = provider_in.model_dump(exclude_unset=True)

    # Write-only secret: absent = keep, empty = clear, value = replace.
    if "client_secret" in update_data:
        await set_provider_secret(session, row.id, update_data.pop("client_secret"))

    for field_name, value in update_data.items():
        setattr(row, field_name, value)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return admin_read(row, secret_set=await secret_is_set(session, row.id))


async def delete_provider(
    session: AsyncSession, provider_id: int, *, guild_id: int | None
) -> None:
    """Delete a row from the namespace. Its linked identities (and their
    stored refresh tokens) go with it via cascade — users who signed in
    through it keep their accounts and any other sign-in methods. A provider
    some guild's auth policy requires is refused (409): drop or repoint the
    policy first."""
    row = await editable_provider(session, provider_id, guild_id=guild_id)
    secret = await session.get(AuthProviderSecret, row.id)
    if secret is not None:
        await session.delete(secret)
    await session.delete(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if dbapi_sqlstate(exc) != FOREIGN_KEY_VIOLATION_SQLSTATE:
            raise
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthProviderMessages.IN_USE,
        ) from exc
    logger.info("auth provider %s (%s) deleted", row.slug, provider_id)

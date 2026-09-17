"""Which of the platform's providers a community signs its members in through.

The division of labour this implements: **the operator holds providers, a
community connects to one.** An operator says this deployment can sign people
in with Google; a community says its members come in through that, and only its
own workspace. A community supplies no issuer, no client id and no secret — so
it names no address the deployment will fetch, and there is no provider
configuration for it to get wrong on behalf of its members.

Two readers and one writer live here. Login asks which provider serves a
community and whether the person who just arrived belongs to it; the CRUD
answers to the security-admin seat. Everything runs on the system engine —
``guild_provider_connections`` carries no request-path grants.
"""

import logging

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import AuthProviderMessages
from app.db.errors import UNIQUE_VIOLATION_SQLSTATE, dbapi_sqlstate
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.guild_provider_connection import GuildProviderConnection
from app.schemas.platform.settings import (
    ConnectableProviderRead,
    GuildProviderConnectionCreate,
    GuildProviderConnectionRead,
    GuildProviderConnectionUpdate,
)

logger = logging.getLogger(__name__)


def connection_read(
    connection: GuildProviderConnection, provider: AuthProvider
) -> GuildProviderConnectionRead:
    return GuildProviderConnectionRead(
        id=connection.id,
        provider_id=provider.id,
        provider_slug=provider.slug,
        provider_display_name=provider.display_name,
        provider_icon=provider.icon,
        claim=connection.claim,
        claim_values=list(connection.claim_values or ()),
        enabled=connection.enabled,
        login_ready=is_login_ready_provider(provider),
    )


def is_login_ready_provider(provider: AuthProvider) -> bool:
    """Whether the provider behind a connection could serve a sign-in.

    A community can connect to a provider the operator has since switched off
    or left half-configured. Saying so on the connection is kinder than a
    button that fails.
    """
    from app.services.auth.platform_provider import is_login_ready

    return is_login_ready(provider)


async def list_connections(
    session: AsyncSession, *, guild_id: int
) -> list[GuildProviderConnectionRead]:
    rows = (
        await session.exec(
            select(GuildProviderConnection, AuthProvider)
            .join(AuthProvider, AuthProvider.id == GuildProviderConnection.provider_id)
            .where(GuildProviderConnection.guild_id == guild_id)
            .order_by(AuthProvider.display_name)
        )
    ).all()
    return [connection_read(connection, provider) for connection, provider in rows]


async def list_connectable(
    session: AsyncSession, *, guild_id: int
) -> list[ConnectableProviderRead]:
    """The providers this community may choose from.

    On offer, or already connected. That second half is what keeps a provider
    the operator registered for one customer visible to that customer and to
    nobody else — offering it to everybody would put every customer's identity
    provider in every other customer's list.

    Non-secret metadata only, and deliberately less than the operator sees: a
    community picks a provider by name, not by issuer.
    """
    connected = select(GuildProviderConnection.provider_id).where(
        GuildProviderConnection.guild_id == guild_id
    )
    rows = (
        await session.exec(
            select(AuthProvider)
            .where(
                or_(
                    AuthProvider.connectable_by_guilds.is_(True),
                    AuthProvider.id.in_(connected),
                )
            )
            .order_by(AuthProvider.display_name)
        )
    ).all()
    return [
        ConnectableProviderRead(
            id=row.id,
            display_name=row.display_name,
            icon=row.icon,
            login_ready=is_login_ready_provider(row),
        )
        for row in rows
    ]


async def editable_connection(
    session: AsyncSession, connection_id: int, *, guild_id: int
) -> GuildProviderConnection:
    """This community's connection for one id, or a 404. One belonging to
    another community is indistinguishable from one that is not there."""
    row = (
        await session.exec(
            select(GuildProviderConnection).where(
                GuildProviderConnection.id == connection_id,
                GuildProviderConnection.guild_id == guild_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthProviderMessages.CONNECTION_NOT_FOUND,
        )
    return row


async def _connectable_provider(
    session: AsyncSession, provider_id: int, *, guild_id: int
) -> AuthProvider:
    """The provider a community is allowed to connect to, or a 404.

    Allowed means on offer, or already connected — the same rule the picker
    lists by, applied again at the write so a guessed id gets no further than
    a name the community was never shown.
    """
    already = (
        await session.exec(
            select(GuildProviderConnection.id).where(
                GuildProviderConnection.guild_id == guild_id,
                GuildProviderConnection.provider_id == provider_id,
            )
        )
    ).first()
    row = (
        await session.exec(
            select(AuthProvider).where(
                AuthProvider.id == provider_id,
                or_(
                    AuthProvider.connectable_by_guilds.is_(True),
                    AuthProvider.id == (provider_id if already else None),
                ),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthProviderMessages.NOT_FOUND,
        )
    return row


def _clean_claim(
    claim: str | None, claim_values: list[str] | None
) -> tuple[str | None, list[str] | None]:
    """A narrowing is both halves or neither.

    A claim with no values would admit nobody and a value with no claim names
    nothing to read it from; either alone is a half-written rule that would
    look configured.
    """
    named = (claim or "").strip()
    values = [v.strip() for v in (claim_values or []) if v.strip()]
    if not named or not values:
        if named or values:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=AuthProviderMessages.CONNECTION_HALF_NARROWED,
            )
        return None, None
    return named, values


async def create_connection(
    session: AsyncSession,
    payload: GuildProviderConnectionCreate,
    *,
    guild_id: int,
) -> GuildProviderConnectionRead:
    provider = await _connectable_provider(
        session, payload.provider_id, guild_id=guild_id
    )
    claim, claim_values = _clean_claim(payload.claim, payload.claim_values)
    row = GuildProviderConnection(
        guild_id=guild_id,
        provider_id=provider.id,
        claim=claim,
        claim_values=claim_values,
        enabled=payload.enabled,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if dbapi_sqlstate(exc) != UNIQUE_VIOLATION_SQLSTATE:
            raise
        # A community connects to a provider once; two narrowings of one
        # provider would be two answers to one question.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthProviderMessages.CONNECTION_EXISTS,
        ) from exc
    await session.refresh(row)
    logger.info(
        "guild %s connected provider %s (connection %s)",
        guild_id,
        provider.slug,
        row.id,
    )
    return connection_read(row, provider)


async def update_connection(
    session: AsyncSession,
    connection_id: int,
    payload: GuildProviderConnectionUpdate,
    *,
    guild_id: int,
) -> GuildProviderConnectionRead:
    row = await editable_connection(session, connection_id, guild_id=guild_id)
    data = payload.model_dump(exclude_unset=True)
    # The provider a connection is to is what it is; pointing an existing one
    # somewhere else would silently change who gets in. Disconnect and connect.
    if "claim" in data or "claim_values" in data:
        row.claim, row.claim_values = _clean_claim(
            data.get("claim", row.claim), data.get("claim_values", row.claim_values)
        )
    if "enabled" in data:
        row.enabled = data["enabled"]
    session.add(row)
    await session.commit()
    await session.refresh(row)
    provider = await session.get(AuthProvider, row.provider_id)
    return connection_read(row, provider)


async def delete_connection(
    session: AsyncSession, connection_id: int, *, guild_id: int
) -> None:
    """Disconnect. Nobody is signed out and no account changes — what goes is
    the button, and the community's claim on who arrives through it."""
    row = await editable_connection(session, connection_id, guild_id=guild_id)
    await session.delete(row)
    await session.commit()
    logger.info("guild %s disconnected connection %s", guild_id, connection_id)


# ── What login asks ───────────────────────────────────────────────────────


async def connected_providers(
    session: AsyncSession, *, guild_id: int
) -> list[AuthProvider]:
    """The providers this community's sign-in page offers, in display order.

    Replaces the old ``AuthProvider.guild_id == guild_id``: a provider serves a
    community because the community connects to it, not because it belongs to
    one.
    """
    rows = (
        await session.exec(
            select(AuthProvider)
            .join(
                GuildProviderConnection,
                GuildProviderConnection.provider_id == AuthProvider.id,
            )
            .where(
                GuildProviderConnection.guild_id == guild_id,
                GuildProviderConnection.enabled.is_(True),
            )
            .order_by(AuthProvider.display_name)
        )
    ).all()
    return list(rows)


async def connection_for(
    session: AsyncSession, *, guild_id: int, provider_id: int
) -> GuildProviderConnection | None:
    """The live connection a sign-in is coming in on, if there is one."""
    return (
        await session.exec(
            select(GuildProviderConnection).where(
                GuildProviderConnection.guild_id == guild_id,
                GuildProviderConnection.provider_id == provider_id,
                GuildProviderConnection.enabled.is_(True),
            )
        )
    ).one_or_none()

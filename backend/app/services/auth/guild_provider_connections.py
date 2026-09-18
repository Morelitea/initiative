"""Which of the platform's providers a community signs its members in through.

The division of labour this implements: **the operator holds providers, a
community connects to one.** An operator says this deployment can sign people
in with Google; a community says its members come in through that, and only its
own workspace. A community supplies no issuer, no client id and no secret — so
it names no address the deployment will fetch, and there is no provider
configuration for it to get wrong on behalf of its members.

Two readers and one writer live here. Login asks which providers a
community connects to and applies what it said about them; the CRUD answers to
the superadmin seat, on the system engine. The gate asks a third question —
does this credential satisfy one of them — and that one defers to
``public.guild_connection_admits`` so the rule has one statement rather than
two.
"""

import logging

from fastapi import HTTPException, status
from sqlalchemy import Integer, cast, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import auth_context

from app.core.login_methods import LoginMethod
from app.core.messages import AuthProviderMessages
from app.db.errors import UNIQUE_VIOLATION_SQLSTATE, dbapi_sqlstate
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.guild_auth_policy import GuildAuthPolicy
from app.models.platform.guild_provider_connection import GuildProviderConnection
from app.models.platform.platform_provider_default import PlatformProviderDefault
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
        auto_join=connection.auto_join,
        login_ready=is_login_ready_provider(provider),
    )


def default_read(
    default: PlatformProviderDefault, provider: AuthProvider
) -> GuildProviderConnectionRead:
    """The deployment's answer for a provider, in the shape a community's own
    connection has — so one surface renders both."""
    return GuildProviderConnectionRead(
        id=None,
        inherited=True,
        provider_id=default.provider_id,
        provider_slug=provider.slug,
        provider_display_name=provider.display_name,
        provider_icon=provider.icon,
        claim=default.claim,
        claim_values=list(default.claim_values or []),
        enabled=default.enabled,
        # Never inherited: joining a community is the community's own say.
        auto_join=False,
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
    """What this community signs in through — what it said, and what the
    deployment answered for it where it has said nothing.

    Both are shown, because a community cannot override an arrangement it
    cannot see. An inherited row carries no id: connecting to that provider is
    what turns it into one of this community's own.
    """
    rows = (
        await session.exec(
            select(GuildProviderConnection, AuthProvider)
            .join(AuthProvider, AuthProvider.id == GuildProviderConnection.provider_id)
            .where(GuildProviderConnection.guild_id == guild_id)
            .order_by(AuthProvider.display_name)
        )
    ).all()
    entries = [connection_read(connection, provider) for connection, provider in rows]
    spoken_for = {connection.provider_id for connection, _ in rows}

    inherited = (
        await session.exec(
            select(PlatformProviderDefault, AuthProvider)
            .join(
                AuthProvider,
                AuthProvider.id == PlatformProviderDefault.provider_id,
            )
            .order_by(AuthProvider.display_name)
        )
    ).all()
    entries.extend(
        default_read(default, provider)
        for default, provider in inherited
        if default.provider_id not in spoken_for
    )
    entries.sort(key=lambda entry: entry.provider_display_name)
    return entries


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
    rows = (
        await session.exec(select(AuthProvider).order_by(AuthProvider.display_name))
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


async def _ensure_not_required(
    session: AsyncSession,
    connection: GuildProviderConnection,
    *,
    guild_id: int,
) -> None:
    """Refuse a change that would leave a requirement with nothing to satisfy.

    The gate asks the connections, so a community that requires a sign-in
    through a provider needs the connection that says the provider is theirs.
    Lifting the requirement first is the way round it.
    """
    policy = await session.get(GuildAuthPolicy, guild_id)
    required = policy is not None and policy.policy == "required"
    names_this_provider = required and policy.provider_id == connection.provider_id
    is_last_live_connection = False
    if (
        required
        and connection.enabled
        and LoginMethod.sso.value in (policy.require_methods or ())
    ):
        another = (
            await session.exec(
                select(GuildProviderConnection.id).where(
                    GuildProviderConnection.guild_id == guild_id,
                    GuildProviderConnection.enabled.is_(True),
                    GuildProviderConnection.id != connection.id,
                )
            )
        ).first()
        is_last_live_connection = another is None
    if names_this_provider or is_last_live_connection:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthProviderMessages.IN_USE,
        )


async def _connectable_provider(
    session: AsyncSession, provider_id: int, *, guild_id: int
) -> AuthProvider:
    """The provider a community is connecting to, or a 404.

    Every provider the deployment offers is a way in that anybody may use, so
    there is nothing to be allowed onto: what a community decides is whether
    arrivals through it are its own.
    """
    row = await session.get(AuthProvider, provider_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthProviderMessages.NOT_FOUND,
        )
    return row


def clean_claim(
    claim: str | None, claim_values: list[str] | None
) -> tuple[str | None, list[str] | None]:
    """A narrowing is both halves or neither.

    Shared with the deployment-level defaults, so an operator answering for a
    community and a community answering for itself are held to one rule.

    A claim says which value to read and the values say which ones count, so
    one without the other is a half-written rule. Either alone is cleared.
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
    claim, claim_values = clean_claim(payload.claim, payload.claim_values)
    row = GuildProviderConnection(
        guild_id=guild_id,
        provider_id=provider.id,
        claim=claim,
        claim_values=claim_values,
        enabled=payload.enabled,
        auto_join=payload.auto_join,
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
        row.claim, row.claim_values = clean_claim(
            data.get("claim", row.claim), data.get("claim_values", row.claim_values)
        )
    if "enabled" in data and data["enabled"] is not None:
        if not data["enabled"]:
            await _ensure_not_required(session, row, guild_id=guild_id)
        row.enabled = data["enabled"]
    if "auto_join" in data and data["auto_join"] is not None:
        row.auto_join = data["auto_join"]
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
    await _ensure_not_required(session, row, guild_id=guild_id)
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
    own = (
        await session.exec(
            select(AuthProvider, GuildProviderConnection.enabled)
            .join(
                GuildProviderConnection,
                GuildProviderConnection.provider_id == AuthProvider.id,
            )
            .where(GuildProviderConnection.guild_id == guild_id)
        )
    ).all()
    spoken_for = {provider.id for provider, _ in own}
    offered = {provider.id: provider for provider, enabled in own if enabled}

    # And the deployment's own answer, for a provider this community has said
    # nothing about. A community that connected to it — even with the button
    # off — has spoken, and what it said stands instead.
    inherited = (
        await session.exec(
            select(AuthProvider)
            .join(
                PlatformProviderDefault,
                PlatformProviderDefault.provider_id == AuthProvider.id,
            )
            .where(PlatformProviderDefault.enabled.is_(True))
        )
    ).all()
    for provider in inherited:
        if provider.id not in spoken_for:
            offered[provider.id] = provider

    return sorted(offered.values(), key=lambda row: row.display_name)


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


async def admits_this_session(
    session: AsyncSession,
    *,
    guild_id: int,
    provider_id: int | None = None,
) -> bool:
    """Does the credential on this request satisfy one of the community's
    connections? Pass a provider id to ask about one of them.

    Defers to ``public.guild_connection_admits`` rather than restating it, the
    way ``initiative_scope_clause`` defers to ``initiative_access``. The facts
    are passed in because this runs before the session context exists, which
    is where the policy legs read them from.
    """
    providers = sorted(auth_context.satisfied_provider_ids())
    if not providers:
        return False
    claims = auth_context.satisfied_claims()
    return bool(
        await session.scalar(
            select(
                func.guild_connection_admits(
                    guild_id,
                    cast(providers, ARRAY(Integer)),
                    # The dict, not a dumped string: the JSONB type serialises
                    # what it is handed, and a string would arrive as a JSON
                    # scalar rather than the object the gate indexes into.
                    cast(claims, JSONB),
                    provider_id,
                )
            )
        )
    )


async def narrowed_by(session: AsyncSession, *, provider_id: int) -> set[str]:
    """The claim names some community narrows this provider by.

    What a sign-in through it has to record, so the gate can compare it later.
    A provider nobody narrows records nothing.
    """
    rows = (
        await session.exec(
            select(GuildProviderConnection.claim).where(
                GuildProviderConnection.provider_id == provider_id,
                GuildProviderConnection.enabled.is_(True),
                GuildProviderConnection.claim.is_not(None),
            )
        )
    ).all()
    return {claim for claim in rows if claim}


async def admitting_connections(
    session: AsyncSession,
    *,
    provider_id: int,
    claims: dict,
) -> list[GuildProviderConnection]:
    """Every enabled connection to this provider that counts this arrival as
    one of its community's own."""
    rows = (
        await session.exec(
            select(GuildProviderConnection).where(
                GuildProviderConnection.provider_id == provider_id,
                GuildProviderConnection.enabled.is_(True),
            )
        )
    ).all()
    return [row for row in rows if row.admits(claims)]


async def join_on_arrival(
    session: AsyncSession,
    *,
    provider_id: int,
    user_id: int,
    claims: dict,
) -> list[int]:
    """Place somebody in the communities whose connection says to, and return
    which.

    A community at capacity is skipped rather than failing the sign-in: the
    person signed in to the deployment, and one community being full is that
    community's business rather than a reason to refuse them their account.
    """
    from app.services.platform import guilds as guilds_service

    # Plain values up front: the commit below expires the rows, and reading
    # an expired attribute mid-loop would need an await of its own.
    wanted = [
        connection.guild_id
        for connection in await admitting_connections(
            session, provider_id=provider_id, claims=claims
        )
        if connection.auto_join
    ]

    joined: list[int] = []
    for guild_id in wanted:
        # A savepoint each, so a community at capacity undoes its own attempt
        # and leaves the sign-in that carried it here alone.
        try:
            async with session.begin_nested():
                await guilds_service.ensure_membership(
                    session, guild_id=guild_id, user_id=user_id
                )
        except guilds_service.GuildCapacityError:
            logger.info(
                "guild %s is at capacity; nobody joined it on arrival", guild_id
            )
            continue
        joined.append(guild_id)
    if joined:
        await session.commit()
    return joined

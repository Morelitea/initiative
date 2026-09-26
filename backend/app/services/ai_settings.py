"""AI settings & connections service (mode-based, schema-per-guild).

AI config ownership is a single global **mode** (``platform`` or ``guild``,
never both). The mode's owner defines *connections* — the destination
(provider, base_url, model) plus an optional shared key. Guild members attach
their own key and pick a connection; they never set a destination, so a member
can never point an inherited key at a host they chose.

Resolution (member M generating in guild G):
1. mode (cached, loaded on the system engine — the request path never queries
   ``platform_ai_connections`` under a guild role).
2. connection: member pref (guild-local) -> owner default -> first enabled.
3. key: member key for that connection (guild-local) -> the connection's own key.
4. destination always comes from the connection (owner-set). ``allow_private``
   is server-computed as (provider == ollama and the connection is a platform
   connection) — never from request input.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import routed_guild_id
from app.core.audit_events import AuditEventType
from app.core.encryption import SALT_AI_API_KEY, decrypt_field, encrypt_field
from app.core.messages import AIMessages
from app.db import session as db_session
from app.models.platform.ai_connection import PlatformAIConnection
from app.models.platform.user import User
from app.models.tenant.ai_connection import GuildAIConnection
from app.models.tenant.ai_member_key import GuildAIMemberKey
from app.models.tenant.ai_member_pref import GuildAIMemberPref
from app.services.platform.app_settings import get_app_settings
from app.schemas.ai_settings import (
    AIConfigMode,
    AIConnectionCreate,
    AIConnectionResponse,
    AIConnectionTestResponse,
    AIConnectionUpdate,
    AIModelsResponse,
    AIProvider,
    ConnectionScope,
    MemberAIConnectionView,
    MemberAIKeyUpdate,
    MemberAIPrefUpdate,
    MemberAIView,
    PlatformAIModeResponse,
    PlatformAIModeUpdate,
    ResolvedAISettings,
    ResolvedAISettingsResponse,
)
from app.services import audit as audit_service
from app.services.guild_sweeps import Scope, each_guild
from app.services.safe_http import request_public_target
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
    assert_target_url_is_public_async,
)

logger = logging.getLogger(__name__)

#: What a connection consists of, for the record. The key is not among them —
#: it is reported as a boolean beside the diff.
AUDITED_CONNECTION_FIELDS: tuple[str, ...] = (
    "label",
    "provider",
    "base_url",
    "model",
    "enabled",
    "is_default",
    "allow_member_keys",
)


def _normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


# ---------------------------------------------------------------------------
# Platform config cache (mode + operator connections)
# ---------------------------------------------------------------------------
# The global mode and the operator's connections change rarely and are shared by
# every guild, so they are loaded once on the system engine and cached in-process
# (short TTL + explicit invalidation on operator write). The request path reads
# the cache, never ``platform_ai_connections`` under a guild role — so the
# operator key ciphertext is never exposed to a guild/member session.


@dataclass(frozen=True)
class _ConnRow:
    scope: str  # "platform" | "guild"
    id: int
    label: str
    provider: str
    base_url: str | None
    model: str | None
    api_key_encrypted: str | None
    enabled: bool
    is_default: bool
    allow_member_keys: bool


@dataclass(frozen=True)
class _PlatformConfig:
    mode: str
    version: int
    connections: tuple[_ConnRow, ...]


# Only the owner-only platform CONNECTIONS are cached (the expensive read). The
# mode + a monotonic version live on app_settings, which every role can read, so
# each request reads them fresh on its own (guild) session and reloads the cached
# connections only when the version moves. An operator change therefore reaches
# every worker/replica at once — there is no per-process staleness window.
_cache: _PlatformConfig | None = None


async def _load_platform_connections() -> tuple[_ConnRow, ...]:
    """Read the operator connections on the system engine (app_admin-only table)."""
    async with db_session.system_engine.connect() as conn:
        # Pooled connection: shed any guild role a prior checkout assumed.
        await conn.execute(text("SELECT set_config('role', 'none', false)"))
        conn_rows = (
            await conn.execute(
                text(
                    "SELECT id, label, provider, base_url, model, "
                    "api_key_encrypted, enabled, is_default, allow_member_keys "
                    "FROM public.platform_ai_connections ORDER BY id"
                )
            )
        ).all()
    return tuple(
        _ConnRow(
            scope="platform",
            id=r[0],
            label=r[1],
            provider=r[2],
            base_url=r[3],
            model=r[4],
            api_key_encrypted=r[5],
            enabled=bool(r[6]),
            is_default=bool(r[7]),
            allow_member_keys=bool(r[8]),
        )
        for r in conn_rows
    )


async def get_platform_ai_config(session: AsyncSession) -> _PlatformConfig:
    """Resolve the global mode + (in platform mode) operator connections.

    ``mode`` + ``version`` come from ``app_settings`` on the caller's own session
    (cheap, always fresh, seen by every worker). Only platform mode needs the
    operator connections, cached and reloaded whenever ``version`` changes.
    """
    global _cache
    settings = await get_app_settings(session)
    mode, version = settings.ai_config_mode, settings.ai_config_version
    if mode != AIConfigMode.platform.value:
        return _PlatformConfig(mode=mode, version=version, connections=())
    if _cache is not None and _cache.version == version:
        return _cache
    _cache = _PlatformConfig(
        mode=mode,
        version=version,
        connections=await _load_platform_connections(),
    )
    return _cache


def invalidate_platform_ai_cache() -> None:
    """Drop the cached operator connections. Belt-and-suspenders after an
    operator write in the serving worker; cross-worker freshness is guaranteed by
    the version bump, so other replicas reload on their next read."""
    global _cache
    _cache = None


async def _bump_ai_config_version(session: AsyncSession) -> None:
    """Advance the version so every worker's cache reloads on its next read.
    Called on every operator write that changes the mode or a platform
    connection. The caller owns the commit."""
    settings = await get_app_settings(session)
    settings.ai_config_version += 1
    session.add(settings)


async def _purge_platform_connection_member_data(connection_id: int) -> None:
    """Delete every member key and pref that referenced a now-deleted platform
    connection, in every community whose schema exists. A community that fails
    is rolled back and logged; the rows are inert once the connection is gone."""

    async def purge(session: AsyncSession, _guild_id: int) -> None:
        await session.exec(
            delete(GuildAIMemberKey).where(
                GuildAIMemberKey.connection_scope == "platform",
                GuildAIMemberKey.connection_id == connection_id,
            )
        )
        await session.exec(
            delete(GuildAIMemberPref).where(
                GuildAIMemberPref.connection_scope == "platform",
                GuildAIMemberPref.connection_id == connection_id,
            )
        )

    await each_guild(
        [(Scope.PROVISIONED, purge)],
        name="purge-platform-ai-connection",
    )


def _conn_from_guild(row: GuildAIConnection) -> _ConnRow:
    return _ConnRow(
        scope="guild",
        id=row.id,  # type: ignore[arg-type]
        label=row.label,
        provider=row.provider,
        base_url=row.base_url,
        model=row.model,
        api_key_encrypted=row.api_key_encrypted,
        enabled=row.enabled,
        is_default=row.is_default,
        allow_member_keys=row.allow_member_keys,
    )


def _provider_or_none(value: str) -> AIProvider | None:
    try:
        return AIProvider(value)
    except ValueError:
        return None


def _allow_private_for(provider: AIProvider, scope: str) -> bool:
    """Private/loopback egress is permitted ONLY for an operator (platform)
    Ollama connection. Server-computed; never from request input."""
    return provider == AIProvider.ollama and scope == "platform"


def _enforce_key_ownership(row) -> None:  # noqa: ANN001 (Platform/Guild connection)
    """A connection's key is EITHER shared (admin-set) OR member-supplied, never
    both. The ``allow_member_keys`` toggle is the switch: when it's on, members
    bring their own key, so any shared key is cleared."""
    if row.allow_member_keys:
        row.api_key_encrypted = None


# ---------------------------------------------------------------------------
# Base URL validation for a stored connection
# ---------------------------------------------------------------------------
async def _validate_connection_base_url(
    provider: AIProvider, base_url: str | None, scope: str
) -> None:
    """A connection's ``base_url`` is validated public-only for every provider,
    EXCEPT a platform Ollama connection (the operator may target a private host
    they own). A guild connection is always public-only, so a guild admin can
    never persist a private/internal target."""
    if not base_url:
        return
    if _allow_private_for(provider, scope):
        return
    try:
        await assert_target_url_is_public_async(base_url)
    except (WebhookTargetUrlError, WebhookTargetUrlPrivateError):
        raise HTTPException(status_code=400, detail=AIMessages.INVALID_BASE_URL)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
async def resolve_ai_settings(
    session: AsyncSession,
    user: User,
    guild_id: int | None = None,
) -> ResolvedAISettings:
    """Compute the AI settings for ``user`` generating in guild ``guild_id``."""
    if guild_id is None:
        return ResolvedAISettings(enabled=False, source="disabled")

    cfg = await get_platform_ai_config(session)
    if cfg.mode not in ("platform", "guild"):
        return ResolvedAISettings(enabled=False, source="disabled")

    # Connections available in the active mode.
    if cfg.mode == "platform":
        conns = [c for c in cfg.connections if c.enabled]
    else:
        rows = (
            await session.exec(
                select(GuildAIConnection).where(GuildAIConnection.enabled.is_(True))
            )
        ).all()
        conns = [_conn_from_guild(r) for r in rows]
    conns = [c for c in conns if _provider_or_none(c.provider) is not None]
    if not conns:
        return ResolvedAISettings(enabled=False, source=cfg.mode)

    by_key = {(c.scope, c.id): c for c in conns}

    # Member preference (guild-local, own-row RLS).
    pref = (
        await session.exec(
            select(GuildAIMemberPref).where(GuildAIMemberPref.user_id == user.id)
        )
    ).one_or_none()

    chosen: _ConnRow | None = None
    if pref and pref.connection_scope and pref.connection_id is not None:
        chosen = by_key.get((pref.connection_scope, pref.connection_id))
    if chosen is None:
        chosen = next((c for c in conns if c.is_default), None) or conns[0]

    provider = _provider_or_none(chosen.provider)
    assert provider is not None  # filtered above
    allow_private = _allow_private_for(provider, chosen.scope)

    if pref is not None and pref.enabled is False:
        # Member explicitly turned AI off.
        return ResolvedAISettings(
            enabled=False,
            provider=provider,
            base_url=chosen.base_url,
            model=chosen.model,
            allow_private=allow_private,
            scope=ConnectionScope(chosen.scope),
            connection_id=chosen.id,
            source=cfg.mode,
        )

    # Member key for the chosen connection (guild-local, own-row RLS), else the
    # connection's own shared key. Per-connection: a connection that disallows
    # member keys always uses its own shared key.
    member_key: str | None = None
    if chosen.allow_member_keys:
        mk = (
            await session.exec(
                select(GuildAIMemberKey).where(
                    GuildAIMemberKey.user_id == user.id,
                    GuildAIMemberKey.connection_scope == chosen.scope,
                    GuildAIMemberKey.connection_id == chosen.id,
                )
            )
        ).one_or_none()
        if mk:
            member_key = decrypt_field(mk.api_key_encrypted, SALT_AI_API_KEY)
    conn_key = (
        decrypt_field(chosen.api_key_encrypted, SALT_AI_API_KEY)
        if chosen.api_key_encrypted
        else None
    )
    api_key = member_key or conn_key

    usable = provider == AIProvider.ollama or bool(api_key)
    return ResolvedAISettings(
        enabled=usable,
        provider=provider,
        api_key=api_key,
        base_url=chosen.base_url,
        model=chosen.model,
        allow_private=allow_private,
        scope=ConnectionScope(chosen.scope),
        connection_id=chosen.id,
        source=cfg.mode,
    )


async def get_resolved_ai_settings_response(
    session: AsyncSession,
    user: User,
    guild_id: int | None = None,
) -> ResolvedAISettingsResponse:
    """Resolved settings for the frontend (no API key)."""
    resolved = await resolve_ai_settings(session, user, guild_id)
    return ResolvedAISettingsResponse(
        enabled=resolved.enabled,
        provider=resolved.provider,
        has_api_key=bool(resolved.api_key),
        base_url=resolved.base_url,
        model=resolved.model,
        source=resolved.source,
    )


# ---------------------------------------------------------------------------
# Platform mode + connection CRUD (config.manage — owner only)
# ---------------------------------------------------------------------------
async def get_platform_ai_mode(session: AsyncSession) -> PlatformAIModeResponse:
    settings = await get_app_settings(session)
    return PlatformAIModeResponse(mode=AIConfigMode(settings.ai_config_mode))


async def update_platform_ai_mode(
    session: AsyncSession,
    payload: PlatformAIModeUpdate,
    *,
    actor_user_id: int | None = None,
) -> PlatformAIModeResponse:
    settings = await get_app_settings(session)
    before = {"ai_config_mode": settings.ai_config_mode}
    settings.ai_config_mode = payload.mode.value
    settings.ai_config_version += 1
    session.add(settings)
    changed = audit_service.changed_fields(
        before, {"ai_config_mode": settings.ai_config_mode}
    )
    if actor_user_id is not None and changed["changed"]:
        await audit_service.record(
            session,
            event_type=AuditEventType.PLATFORM_SETTINGS_CHANGED,
            actor_user_id=actor_user_id,
            detail={"area": "ai_mode", **changed},
        )
    await session.commit()
    invalidate_platform_ai_cache()
    return PlatformAIModeResponse(mode=payload.mode)


def _platform_conn_response(row: PlatformAIConnection) -> AIConnectionResponse:
    return AIConnectionResponse(
        id=row.id,  # type: ignore[arg-type]
        scope=ConnectionScope.platform,
        label=row.label,
        provider=AIProvider(row.provider),
        base_url=row.base_url,
        model=row.model,
        has_api_key=bool(row.api_key_encrypted),
        enabled=row.enabled,
        is_default=row.is_default,
        allow_member_keys=row.allow_member_keys,
    )


async def list_platform_connections(
    session: AsyncSession,
) -> list[AIConnectionResponse]:
    rows = (
        await session.exec(
            select(PlatformAIConnection).order_by(PlatformAIConnection.id)
        )
    ).all()
    return [_platform_conn_response(r) for r in rows]


async def create_platform_connection(
    session: AsyncSession,
    payload: AIConnectionCreate,
    *,
    actor_user_id: int | None = None,
) -> AIConnectionResponse:
    base_url = _normalize_optional_string(payload.base_url)
    await _validate_connection_base_url(payload.provider, base_url, "platform")
    row = PlatformAIConnection(
        label=payload.label.strip(),
        provider=payload.provider.value,
        base_url=base_url,
        model=_normalize_optional_string(payload.model),
        api_key_encrypted=(
            encrypt_field(payload.api_key.strip(), SALT_AI_API_KEY)
            if payload.api_key and payload.api_key.strip()
            else None
        ),
        enabled=payload.enabled,
        is_default=payload.is_default,
        allow_member_keys=payload.allow_member_keys,
    )
    _enforce_key_ownership(row)
    if payload.is_default:
        await _clear_platform_default(session)
    session.add(row)
    await _bump_ai_config_version(session)
    await session.flush()
    await audit_service.record(
        session,
        event_type=AuditEventType.AI_CONNECTION_CREATED,
        actor_user_id=actor_user_id,
        target_type="ai_connection",
        target_id=row.id,
        detail={
            "scope": ConnectionScope.platform.value,
            **audit_service.changed_fields(
                {}, audit_service.snapshot(row, AUDITED_CONNECTION_FIELDS)
            ),
            "secret_changed": bool(row.api_key_encrypted),
        },
    )
    await session.commit()
    await session.refresh(row)
    invalidate_platform_ai_cache()
    return _platform_conn_response(row)


async def _clear_platform_default(session: AsyncSession) -> None:
    rows = (
        await session.exec(
            select(PlatformAIConnection).where(
                PlatformAIConnection.is_default.is_(True)
            )
        )
    ).all()
    for r in rows:
        r.is_default = False
        session.add(r)


async def update_platform_connection(
    session: AsyncSession,
    connection_id: int,
    payload: AIConnectionUpdate,
    *,
    actor_user_id: int | None = None,
) -> AIConnectionResponse:
    row = await session.get(PlatformAIConnection, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail=AIMessages.CONNECTION_NOT_FOUND)
    data = payload.model_dump(exclude_unset=True)
    before = audit_service.snapshot(row, AUDITED_CONNECTION_FIELDS)
    key_before = row.api_key_encrypted
    provider = payload.provider or AIProvider(row.provider)
    if "base_url" in data:
        base_url = _normalize_optional_string(payload.base_url)
        await _validate_connection_base_url(provider, base_url, "platform")
        row.base_url = base_url
    elif "provider" in data:
        await _validate_connection_base_url(provider, row.base_url, "platform")
    if "label" in data and payload.label is not None:
        row.label = payload.label.strip()
    if "provider" in data and payload.provider is not None:
        row.provider = payload.provider.value
    if "model" in data:
        row.model = _normalize_optional_string(payload.model)
    if "api_key" in data:
        normalized = _normalize_optional_string(payload.api_key)
        row.api_key_encrypted = (
            encrypt_field(normalized, SALT_AI_API_KEY) if normalized else None
        )
    if "enabled" in data and payload.enabled is not None:
        row.enabled = payload.enabled
    if "allow_member_keys" in data and payload.allow_member_keys is not None:
        row.allow_member_keys = payload.allow_member_keys
    if "is_default" in data and payload.is_default is not None:
        if payload.is_default:
            await _clear_platform_default(session)
        row.is_default = payload.is_default
    _enforce_key_ownership(row)
    session.add(row)
    await _bump_ai_config_version(session)
    secret_changed = row.api_key_encrypted != key_before
    changed = audit_service.changed_fields(
        before, audit_service.snapshot(row, AUDITED_CONNECTION_FIELDS)
    )
    if changed["changed"] or secret_changed:
        await audit_service.record(
            session,
            event_type=AuditEventType.AI_CONNECTION_UPDATED,
            actor_user_id=actor_user_id,
            target_type="ai_connection",
            target_id=row.id,
            detail={
                "scope": ConnectionScope.platform.value,
                **changed,
                "secret_changed": secret_changed,
            },
        )
    await session.commit()
    await session.refresh(row)
    invalidate_platform_ai_cache()
    return _platform_conn_response(row)


async def delete_platform_connection(
    session: AsyncSession, connection_id: int, *, actor_user_id: int | None = None
) -> None:
    row = await session.get(PlatformAIConnection, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail=AIMessages.CONNECTION_NOT_FOUND)
    await session.delete(row)
    await _bump_ai_config_version(session)
    await audit_service.record(
        session,
        event_type=AuditEventType.AI_CONNECTION_DELETED,
        actor_user_id=actor_user_id,
        target_type="ai_connection",
        target_id=connection_id,
        detail={"scope": ConnectionScope.platform.value},
    )
    await session.commit()
    # Members attach their own key to a platform connection per guild, so the
    # member rows live in every guild schema — purge them so a deleted connection
    # leaves no orphaned member secrets behind.
    await _purge_platform_connection_member_data(connection_id)
    invalidate_platform_ai_cache()


# ---------------------------------------------------------------------------
# Guild connection CRUD (guild admin — guild config mode)
# ---------------------------------------------------------------------------
def _guild_conn_response(row: GuildAIConnection) -> AIConnectionResponse:
    return AIConnectionResponse(
        id=row.id,  # type: ignore[arg-type]
        scope=ConnectionScope.guild,
        label=row.label,
        provider=AIProvider(row.provider),
        base_url=row.base_url,
        model=row.model,
        has_api_key=bool(row.api_key_encrypted),
        enabled=row.enabled,
        is_default=row.is_default,
        allow_member_keys=row.allow_member_keys,
    )


async def list_guild_connections(
    session: AsyncSession,
) -> list[AIConnectionResponse]:
    rows = (
        await session.exec(select(GuildAIConnection).order_by(GuildAIConnection.id))
    ).all()
    return [_guild_conn_response(r) for r in rows]


async def _clear_guild_default(session: AsyncSession) -> None:
    rows = (
        await session.exec(
            select(GuildAIConnection).where(GuildAIConnection.is_default.is_(True))
        )
    ).all()
    for r in rows:
        r.is_default = False
        session.add(r)


async def create_guild_connection(
    session: AsyncSession,
    guild_id: int,
    user_id: int,
    payload: AIConnectionCreate,
    *,
    actor_user_id: int | None = None,
) -> AIConnectionResponse:
    base_url = _normalize_optional_string(payload.base_url)
    # Guild connections are always public-only (scope="guild" => no private).
    await _validate_connection_base_url(payload.provider, base_url, "guild")
    row = GuildAIConnection(
        created_by=user_id,
        label=payload.label.strip(),
        provider=payload.provider.value,
        base_url=base_url,
        model=_normalize_optional_string(payload.model),
        api_key_encrypted=(
            encrypt_field(payload.api_key.strip(), SALT_AI_API_KEY)
            if payload.api_key and payload.api_key.strip()
            else None
        ),
        enabled=payload.enabled,
        is_default=payload.is_default,
        allow_member_keys=payload.allow_member_keys,
    )
    _enforce_key_ownership(row)
    if payload.is_default:
        await _clear_guild_default(session)
    session.add(row)
    await session.flush()
    await audit_service.record(
        session,
        event_type=AuditEventType.AI_CONNECTION_CREATED,
        actor_user_id=actor_user_id,
        guild_id=guild_id,
        target_type="ai_connection",
        target_id=row.id,
        detail={
            "scope": ConnectionScope.guild.value,
            **audit_service.changed_fields(
                {}, audit_service.snapshot(row, AUDITED_CONNECTION_FIELDS)
            ),
            "secret_changed": bool(row.api_key_encrypted),
        },
    )
    await session.commit()
    await session.refresh(row)
    return _guild_conn_response(row)


async def update_guild_connection(
    session: AsyncSession,
    connection_id: int,
    payload: AIConnectionUpdate,
    *,
    actor_user_id: int | None = None,
) -> AIConnectionResponse:
    row = await session.get(GuildAIConnection, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail=AIMessages.CONNECTION_NOT_FOUND)
    data = payload.model_dump(exclude_unset=True)
    before = audit_service.snapshot(row, AUDITED_CONNECTION_FIELDS)
    key_before = row.api_key_encrypted
    provider = payload.provider or AIProvider(row.provider)
    if "base_url" in data:
        base_url = _normalize_optional_string(payload.base_url)
        await _validate_connection_base_url(provider, base_url, "guild")
        row.base_url = base_url
    elif "provider" in data:
        await _validate_connection_base_url(provider, row.base_url, "guild")
    if "label" in data and payload.label is not None:
        row.label = payload.label.strip()
    if "provider" in data and payload.provider is not None:
        row.provider = payload.provider.value
    if "model" in data:
        row.model = _normalize_optional_string(payload.model)
    if "api_key" in data:
        normalized = _normalize_optional_string(payload.api_key)
        row.api_key_encrypted = (
            encrypt_field(normalized, SALT_AI_API_KEY) if normalized else None
        )
    if "enabled" in data and payload.enabled is not None:
        row.enabled = payload.enabled
    if "allow_member_keys" in data and payload.allow_member_keys is not None:
        row.allow_member_keys = payload.allow_member_keys
    if "is_default" in data and payload.is_default is not None:
        if payload.is_default:
            await _clear_guild_default(session)
        row.is_default = payload.is_default
    _enforce_key_ownership(row)
    session.add(row)
    secret_changed = row.api_key_encrypted != key_before
    changed = audit_service.changed_fields(
        before, audit_service.snapshot(row, AUDITED_CONNECTION_FIELDS)
    )
    if changed["changed"] or secret_changed:
        await audit_service.record(
            session,
            event_type=AuditEventType.AI_CONNECTION_UPDATED,
            actor_user_id=actor_user_id,
            guild_id=routed_guild_id(session),
            target_type="ai_connection",
            target_id=row.id,
            detail={
                "scope": ConnectionScope.guild.value,
                **changed,
                "secret_changed": secret_changed,
            },
        )
    await session.commit()
    await session.refresh(row)
    return _guild_conn_response(row)


async def delete_guild_connection(
    session: AsyncSession, connection_id: int, *, actor_user_id: int | None = None
) -> None:
    row = await session.get(GuildAIConnection, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail=AIMessages.CONNECTION_NOT_FOUND)
    guild_id = routed_guild_id(session)
    await session.delete(row)
    await audit_service.record(
        session,
        event_type=AuditEventType.AI_CONNECTION_DELETED,
        actor_user_id=actor_user_id,
        guild_id=guild_id,
        target_type="ai_connection",
        target_id=connection_id,
        detail={"scope": ConnectionScope.guild.value},
    )
    # Connection administration includes removing every member reference. The
    # own-row policy on those tables admits the community's administrator,
    # which the seat holder running this already is in the request's standing.
    await session.exec(
        delete(GuildAIMemberKey).where(
            GuildAIMemberKey.connection_scope == ConnectionScope.guild.value,
            GuildAIMemberKey.connection_id == connection_id,
        )
    )
    await session.exec(
        delete(GuildAIMemberPref).where(
            GuildAIMemberPref.connection_scope == ConnectionScope.guild.value,
            GuildAIMemberPref.connection_id == connection_id,
        )
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Member surface (attach a key + pick a connection)
# ---------------------------------------------------------------------------
async def _active_connections(
    session: AsyncSession, cfg: _PlatformConfig
) -> list[_ConnRow]:
    if cfg.mode == "platform":
        return [c for c in cfg.connections if c.enabled]
    if cfg.mode == "guild":
        rows = (
            await session.exec(
                select(GuildAIConnection).where(GuildAIConnection.enabled.is_(True))
            )
        ).all()
        return [_conn_from_guild(r) for r in rows]
    return []


async def get_member_ai_view(
    session: AsyncSession, user: User, guild_id: int
) -> MemberAIView:
    cfg = await get_platform_ai_config(session)
    mode = (
        AIConfigMode(cfg.mode)
        if cfg.mode in ("platform", "guild")
        else AIConfigMode.disabled
    )
    if mode == AIConfigMode.disabled:
        return MemberAIView(mode=mode, enabled=False)

    conns = [
        c
        for c in await _active_connections(session, cfg)
        if _provider_or_none(c.provider) is not None
    ]

    # Member's keys + pref (guild-local, own-row RLS).
    member_keys = {
        (k.connection_scope, k.connection_id)
        for k in (
            await session.exec(
                select(GuildAIMemberKey).where(GuildAIMemberKey.user_id == user.id)
            )
        ).all()
    }
    pref = (
        await session.exec(
            select(GuildAIMemberPref).where(GuildAIMemberPref.user_id == user.id)
        )
    ).one_or_none()
    selected = (
        (pref.connection_scope, pref.connection_id)
        if pref and pref.connection_scope and pref.connection_id is not None
        else None
    )

    views = [
        MemberAIConnectionView(
            scope=ConnectionScope(c.scope),
            id=c.id,
            label=c.label,
            provider=AIProvider(c.provider),
            model=c.model,
            has_member_key=(c.scope, c.id) in member_keys,
            # A member must supply a key only when the connection has no shared
            # key of its own AND allows member keys.
            requires_member_key=not c.api_key_encrypted and c.allow_member_keys,
            allow_member_keys=c.allow_member_keys,
            is_selected=selected == (c.scope, c.id),
        )
        for c in conns
    ]

    resolved = await resolve_ai_settings(session, user, guild_id)
    return MemberAIView(mode=mode, enabled=resolved.enabled, connections=views)


async def _require_active_connection(
    session: AsyncSession, scope: ConnectionScope, connection_id: int
) -> _ConnRow:
    """The (scope, id) a member references MUST be an enabled connection in the
    active mode — a member can't attach a key to an arbitrary id."""
    cfg = await get_platform_ai_config(session)
    if cfg.mode != scope.value:
        raise HTTPException(status_code=400, detail=AIMessages.CONNECTION_NOT_FOUND)
    for c in await _active_connections(session, cfg):
        if c.id == connection_id and c.scope == scope.value:
            return c
    raise HTTPException(status_code=404, detail=AIMessages.CONNECTION_NOT_FOUND)


async def set_member_key(
    session: AsyncSession, user: User, guild_id: int, payload: MemberAIKeyUpdate
) -> MemberAIView:
    conn = await _require_active_connection(
        session, payload.scope, payload.connection_id
    )
    if not conn.allow_member_keys:
        raise HTTPException(status_code=403, detail=AIMessages.MEMBER_KEYS_DISABLED)
    normalized = payload.api_key.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail=AIMessages.INVALID_API_KEY)
    existing = (
        await session.exec(
            select(GuildAIMemberKey).where(
                GuildAIMemberKey.user_id == user.id,
                GuildAIMemberKey.connection_scope == payload.scope.value,
                GuildAIMemberKey.connection_id == payload.connection_id,
            )
        )
    ).one_or_none()
    if existing:
        existing.api_key_encrypted = encrypt_field(normalized, SALT_AI_API_KEY)
        session.add(existing)
    else:
        session.add(
            GuildAIMemberKey(
                user_id=user.id,  # type: ignore[arg-type]
                connection_scope=payload.scope.value,
                connection_id=payload.connection_id,
                api_key_encrypted=encrypt_field(normalized, SALT_AI_API_KEY),
            )
        )
    await session.commit()
    return await get_member_ai_view(session, user, guild_id)


async def delete_member_key(
    session: AsyncSession,
    user: User,
    guild_id: int,
    scope: ConnectionScope,
    connection_id: int,
) -> MemberAIView:
    existing = (
        await session.exec(
            select(GuildAIMemberKey).where(
                GuildAIMemberKey.user_id == user.id,
                GuildAIMemberKey.connection_scope == scope.value,
                GuildAIMemberKey.connection_id == connection_id,
            )
        )
    ).one_or_none()
    if existing:
        await session.delete(existing)
        await session.commit()
    return await get_member_ai_view(session, user, guild_id)


async def set_member_pref(
    session: AsyncSession, user: User, guild_id: int, payload: MemberAIPrefUpdate
) -> MemberAIView:
    await _require_active_connection(session, payload.scope, payload.connection_id)
    pref = (
        await session.exec(
            select(GuildAIMemberPref).where(GuildAIMemberPref.user_id == user.id)
        )
    ).one_or_none()
    if pref:
        pref.connection_scope = payload.scope.value
        pref.connection_id = payload.connection_id
        pref.enabled = payload.enabled
        session.add(pref)
    else:
        session.add(
            GuildAIMemberPref(
                user_id=user.id,  # type: ignore[arg-type]
                connection_scope=payload.scope.value,
                connection_id=payload.connection_id,
                enabled=payload.enabled,
            )
        )
    await session.commit()
    return await get_member_ai_view(session, user, guild_id)


# ---------------------------------------------------------------------------
# Connection probe (test / list models on a STORED connection)
# ---------------------------------------------------------------------------
# The destination + key both come from a stored connection (never a request
# body), so a probe sends a key only to the destination it was saved with.
# Ollama/custom probes go through the pinned egress; ``allow_private`` is
# server-computed per §4.


def _is_openai_chat_model(model_id: str) -> bool:
    model_lower = model_id.lower()
    chat_prefixes = ("gpt-", "o1", "o3", "chatgpt-")
    excluded = (
        "whisper",
        "tts",
        "dall-e",
        "embedding",
        "davinci",
        "babbage",
        "curie",
        "ada",
        "image",
        "audio",
    )
    if any(model_lower.startswith(p) for p in chat_prefixes):
        return not any(e in model_lower for e in excluded)
    return False


def _sort_openai_models(models: list[str]) -> list[str]:
    priority = {
        "gpt-4o": 100,
        "gpt-4-turbo": 90,
        "gpt-4": 80,
        "o1": 70,
        "o3": 70,
        "chatgpt-4o": 60,
        "gpt-3.5-turbo": 50,
    }

    def get_priority(model: str) -> int:
        ml = model.lower()
        for prefix, prio in priority.items():
            if ml.startswith(prefix):
                return prio
        return 0

    return sorted(models, key=lambda m: (-get_priority(m), m))


# Upper bound on a listed catalog, only so a provider response stays a sane
# payload. An OpenAI-compatible gateway can offer hundreds of models, so this
# has to sit well above any real catalog; when it does trim, the list is
# incomplete and callers must not read absence from it as "no such model".
_MODEL_LIST_CAP = 1000


def _error_detail(response: httpx.Response) -> str:
    """The provider's own error message when it sent one, else the status."""
    try:
        error = response.json().get("error")
    except Exception:
        error = None
    if isinstance(error, dict):
        error = error.get("message")
    return error if isinstance(error, str) and error else str(response.status_code)


def refusal_code(
    provider: AIProvider, response: httpx.Response, *, sent_key: bool
) -> str:
    """The message code for a provider's non-200 answer. What the provider
    said is logged, not returned."""
    logger.warning(
        "AI provider %s answered %s: %s",
        provider.value,
        response.status_code,
        _error_detail(response),
    )
    if response.status_code == 401 and sent_key:
        return AIMessages.INVALID_API_KEY
    return AIMessages.PROVIDER_ERROR


def failure_code(provider: AIProvider, exc: Exception) -> str:
    """The message code for a provider request that raised."""
    if isinstance(exc, (WebhookTargetUrlError, WebhookTargetUrlPrivateError)):
        return AIMessages.INVALID_BASE_URL
    logger.warning("AI provider %s request failed: %r", provider.value, exc)
    if isinstance(exc, httpx.HTTPError):
        return AIMessages.PROVIDER_UNAVAILABLE
    return AIMessages.PROVIDER_ERROR


async def _list_openai_models(api_key: str | None) -> tuple[list[str], str | None]:
    if not api_key:
        return [], AIMessages.NOT_CONFIGURED
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if resp.status_code != 200:
            return [], refusal_code(AIProvider.openai, resp, sent_key=True)
        all_models = [m["id"] for m in resp.json().get("data", [])]
        return _sort_openai_models(
            [m for m in all_models if _is_openai_chat_model(m)]
        ), None
    except Exception as exc:  # noqa: BLE001
        return [], failure_code(AIProvider.openai, exc)


async def _list_anthropic_models(api_key: str | None) -> tuple[list[str], str | None]:
    if not api_key:
        return [], AIMessages.NOT_CONFIGURED
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                params={"limit": _MODEL_LIST_CAP},
            )
        if resp.status_code != 200:
            return [], refusal_code(AIProvider.anthropic, resp, sent_key=True)
        return [m["id"] for m in resp.json().get("data", [])], None
    except Exception as exc:  # noqa: BLE001
        return [], failure_code(AIProvider.anthropic, exc)


async def _list_ollama_models(
    base_url: str | None, *, allow_private: bool
) -> tuple[list[str], str | None]:
    url = (base_url or "http://localhost:11434").rstrip("/")
    try:
        resp = await request_public_target(
            "GET", f"{url}/api/tags", timeout=10.0, allow_private=allow_private
        )
        if resp.status_code != 200:
            return [], refusal_code(AIProvider.ollama, resp, sent_key=False)
        return [m["name"] for m in resp.json().get("models", [])], None
    except Exception as exc:  # noqa: BLE001
        return [], failure_code(AIProvider.ollama, exc)


async def _list_custom_models(
    api_key: str | None, base_url: str | None, *, allow_private: bool
) -> tuple[list[str], str | None]:
    if not base_url:
        return [], AIMessages.INVALID_BASE_URL
    url = base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    try:
        resp = await request_public_target(
            "GET",
            f"{url}/models",
            headers=headers,
            timeout=10.0,
            allow_private=allow_private,
        )
        if resp.status_code != 200:
            return [], refusal_code(AIProvider.custom, resp, sent_key=bool(api_key))
        return [m["id"] for m in resp.json().get("data", [])][:_MODEL_LIST_CAP], None
    except Exception as exc:  # noqa: BLE001
        return [], failure_code(AIProvider.custom, exc)


async def _list_models(
    provider: AIProvider,
    api_key: str | None,
    base_url: str | None,
    *,
    allow_private: bool,
) -> tuple[list[str], str | None]:
    if provider == AIProvider.openai:
        return await _list_openai_models(api_key)
    if provider == AIProvider.anthropic:
        return await _list_anthropic_models(api_key)
    if provider == AIProvider.ollama:
        return await _list_ollama_models(base_url, allow_private=allow_private)
    if provider == AIProvider.custom:
        return await _list_custom_models(api_key, base_url, allow_private=allow_private)
    return [], AIMessages.NOT_CONFIGURED


async def _probe(conn: _ConnRow, api_key: str | None) -> AIConnectionTestResponse:
    provider = AIProvider(conn.provider)
    allow_private = _allow_private_for(provider, conn.scope)
    models, error = await _list_models(
        provider, api_key, conn.base_url, allow_private=allow_private
    )
    if error is not None:
        return AIConnectionTestResponse(success=False, message=error)
    listing_is_complete = len(models) < _MODEL_LIST_CAP
    if conn.model and models and listing_is_complete and conn.model not in models:
        base = {m.split(":")[0] for m in models}
        if conn.model.split(":")[0] not in base:
            return AIConnectionTestResponse(
                success=False,
                message=AIMessages.MODEL_NOT_FOUND,
                available_models=models,
            )
    return AIConnectionTestResponse(success=True, available_models=models or None)


async def test_platform_connection(
    session: AsyncSession, connection_id: int
) -> AIConnectionTestResponse:
    row = await session.get(PlatformAIConnection, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail=AIMessages.CONNECTION_NOT_FOUND)
    conn = _ConnRow(
        scope="platform",
        id=row.id,
        label=row.label,
        provider=row.provider,  # type: ignore[arg-type]
        base_url=row.base_url,
        model=row.model,
        api_key_encrypted=row.api_key_encrypted,
        enabled=row.enabled,
        is_default=row.is_default,
        allow_member_keys=row.allow_member_keys,
    )
    key = (
        decrypt_field(conn.api_key_encrypted, SALT_AI_API_KEY)
        if conn.api_key_encrypted
        else None
    )
    return await _probe(conn, key)


async def fetch_platform_connection_models(
    session: AsyncSession, connection_id: int
) -> AIModelsResponse:
    row = await session.get(PlatformAIConnection, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail=AIMessages.CONNECTION_NOT_FOUND)
    key = (
        decrypt_field(row.api_key_encrypted, SALT_AI_API_KEY)
        if row.api_key_encrypted
        else None
    )
    provider = AIProvider(row.provider)
    models, error = await _list_models(
        provider,
        key,
        row.base_url,
        allow_private=_allow_private_for(provider, "platform"),
    )
    return AIModelsResponse(models=models, error=error)


async def test_guild_connection(
    session: AsyncSession, connection_id: int
) -> AIConnectionTestResponse:
    row = await session.get(GuildAIConnection, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail=AIMessages.CONNECTION_NOT_FOUND)
    conn = _conn_from_guild(row)
    key = (
        decrypt_field(conn.api_key_encrypted, SALT_AI_API_KEY)
        if conn.api_key_encrypted
        else None
    )
    return await _probe(conn, key)


async def fetch_guild_connection_models(
    session: AsyncSession, connection_id: int
) -> AIModelsResponse:
    row = await session.get(GuildAIConnection, connection_id)
    if row is None:
        raise HTTPException(status_code=404, detail=AIMessages.CONNECTION_NOT_FOUND)
    provider = AIProvider(row.provider)
    key = (
        decrypt_field(row.api_key_encrypted, SALT_AI_API_KEY)
        if row.api_key_encrypted
        else None
    )
    models, error = await _list_models(provider, key, row.base_url, allow_private=False)
    return AIModelsResponse(models=models, error=error)


async def test_member_connection(
    session: AsyncSession, user: User, guild_id: int
) -> AIConnectionTestResponse:
    """Test the member's currently-resolved connection using their effective
    key (member key if attached, else the connection's shared key)."""
    resolved = await resolve_ai_settings(session, user, guild_id)
    if resolved.provider is None or resolved.scope is None:
        raise HTTPException(status_code=404, detail=AIMessages.CONNECTION_NOT_FOUND)
    conn = _ConnRow(
        scope=resolved.scope.value,
        id=resolved.connection_id or 0,
        label="",
        provider=resolved.provider.value,
        base_url=resolved.base_url,
        model=resolved.model,
        api_key_encrypted=None,
        enabled=True,
        is_default=False,
        allow_member_keys=True,
    )
    return await _probe(conn, resolved.api_key)

from __future__ import annotations

from collections.abc import Iterable, Mapping

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
from app.core.encryption import encrypt_token
from app.db.session import reapply_rls_context
from app.models.app_setting import AppSetting, DEFAULT_ROLE_LABELS
from app.models.guild_setting import GuildSetting
from app.services import guilds as guilds_service

GLOBAL_SETTINGS_ID = 1
ROLE_KEYS = ["admin", "project_manager", "member"]


def _normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalize_scopes(scopes: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for scope in scopes:
        cleaned = scope.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            normalized.append(cleaned)
    return normalized or ["openid", "profile", "email", "offline_access"]


def _normalize_role_labels(
    labels: Mapping[str, str | None] | None,
    *,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    normalized = dict(base or DEFAULT_ROLE_LABELS)
    for role in ROLE_KEYS:
        normalized.setdefault(role, DEFAULT_ROLE_LABELS[role])
    if not labels:
        return normalized
    for role, value in labels.items():
        if role not in ROLE_KEYS:
            continue
        cleaned = (value or "").strip()
        if cleaned:
            normalized[role] = cleaned
    return normalized


async def _ensure_guild_setting(session: AsyncSession, guild_id: int) -> GuildSetting:
    stmt = select(GuildSetting).where(GuildSetting.guild_id == guild_id)
    result = await session.exec(stmt)
    settings_row = result.one_or_none()
    if settings_row:
        return settings_row
    settings_row = GuildSetting(guild_id=guild_id)
    session.add(settings_row)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(settings_row)
    return settings_row


async def get_or_create_guild_settings(session: AsyncSession, guild_id: int | None = None) -> GuildSetting:
    resolved_guild_id = guild_id or await guilds_service.get_primary_guild_id(session)
    return await _ensure_guild_setting(session, resolved_guild_id)


async def _ensure_app_settings(session: AsyncSession) -> AppSetting:
    stmt = select(AppSetting).where(AppSetting.id == GLOBAL_SETTINGS_ID)
    result = await session.exec(stmt)
    settings_row = result.one_or_none()
    if settings_row:
        updated = False
        # NOTE: oidc_enabled is intentionally NOT overridden here.
        # It is seeded from the env var on first creation only, so that
        # admins can disable OIDC via the UI without the env var forcing
        # it back on every read.
        if not settings_row.oidc_issuer and app_config.OIDC_ISSUER:
            settings_row.oidc_issuer = _normalize_optional_string(app_config.OIDC_ISSUER)
            updated = True
        if not settings_row.oidc_client_id and app_config.OIDC_CLIENT_ID:
            settings_row.oidc_client_id = _normalize_optional_string(app_config.OIDC_CLIENT_ID)
            updated = True
        if not settings_row.oidc_client_secret_encrypted and app_config.OIDC_CLIENT_SECRET:
            v = _normalize_optional_string(app_config.OIDC_CLIENT_SECRET)
            settings_row.oidc_client_secret_encrypted = encrypt_token(v) if v else None
            updated = True
        if not settings_row.oidc_provider_name and app_config.OIDC_PROVIDER_NAME:
            settings_row.oidc_provider_name = _normalize_optional_string(app_config.OIDC_PROVIDER_NAME)
            updated = True
        env_scopes = _normalize_scopes(app_config.OIDC_SCOPES or [])
        if env_scopes and not settings_row.oidc_scopes:
            settings_row.oidc_scopes = env_scopes
            updated = True
        if updated:
            session.add(settings_row)
            await session.commit()
            await reapply_rls_context(session)
            await session.refresh(settings_row)
        return settings_row
    _oidc_secret = _normalize_optional_string(app_config.OIDC_CLIENT_SECRET)
    _smtp_pw = _normalize_optional_string(app_config.SMTP_PASSWORD)
    app_settings = AppSetting(
        id=GLOBAL_SETTINGS_ID,
        oidc_enabled=bool(app_config.OIDC_ENABLED),
        oidc_issuer=_normalize_optional_string(app_config.OIDC_ISSUER),
        oidc_client_id=_normalize_optional_string(app_config.OIDC_CLIENT_ID),
        oidc_client_secret_encrypted=encrypt_token(_oidc_secret) if _oidc_secret else None,
        oidc_provider_name=_normalize_optional_string(app_config.OIDC_PROVIDER_NAME),
        oidc_scopes=_normalize_scopes(app_config.OIDC_SCOPES or ["openid", "profile", "email", "offline_access"]),
        light_accent_color="#2563eb",
        dark_accent_color="#60a5fa",
        role_labels=DEFAULT_ROLE_LABELS.copy(),
        smtp_host=_normalize_optional_string(app_config.SMTP_HOST),
        smtp_port=app_config.SMTP_PORT if app_config.SMTP_HOST else None,
        smtp_secure=bool(app_config.SMTP_SECURE),
        smtp_reject_unauthorized=bool(app_config.SMTP_REJECT_UNAUTHORIZED),
        smtp_username=_normalize_optional_string(app_config.SMTP_USERNAME),
        smtp_password_encrypted=encrypt_token(_smtp_pw) if _smtp_pw else None,
        smtp_from_address=_normalize_optional_string(app_config.SMTP_FROM_ADDRESS),
        smtp_test_recipient=_normalize_optional_string(app_config.SMTP_TEST_RECIPIENT),
    )
    session.add(app_settings)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(app_settings)
    return app_settings


async def get_app_settings(session: AsyncSession, *, force_refresh: bool = False) -> AppSetting:
    if force_refresh:
        stmt = select(AppSetting).where(AppSetting.id == GLOBAL_SETTINGS_ID)
        result = await session.exec(stmt)
        row = result.one_or_none()
        if row:
            return row
    return await _ensure_app_settings(session)


async def update_oidc_settings(
    session: AsyncSession,
    *,
    enabled: bool,
    issuer: str | None,
    client_id: str | None,
    client_secret: str | None,
    provider_name: str | None,
    scopes: Iterable[str],
) -> AppSetting:
    settings_row = await _ensure_app_settings(session)
    settings_row.oidc_enabled = enabled
    settings_row.oidc_issuer = _normalize_optional_string(issuer)
    settings_row.oidc_client_id = _normalize_optional_string(client_id)
    if client_secret is not None:
        normalized = _normalize_optional_string(client_secret)
        settings_row.oidc_client_secret_encrypted = encrypt_token(normalized) if normalized else None
    settings_row.oidc_provider_name = _normalize_optional_string(provider_name)
    settings_row.oidc_scopes = _normalize_scopes(scopes)
    session.add(settings_row)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(settings_row)
    return settings_row


async def update_interface_colors(
    session: AsyncSession,
    *,
    light_accent_color: str,
    dark_accent_color: str,
) -> AppSetting:
    settings_row = await _ensure_app_settings(session)
    settings_row.light_accent_color = light_accent_color.strip() or "#2563eb"
    settings_row.dark_accent_color = dark_accent_color.strip() or "#60a5fa"
    session.add(settings_row)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(settings_row)
    return settings_row


async def update_role_labels(
    session: AsyncSession,
    labels: Mapping[str, str | None],
) -> AppSetting:
    settings_row = await _ensure_app_settings(session)
    settings_row.role_labels = _normalize_role_labels(labels, base=settings_row.role_labels)
    session.add(settings_row)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(settings_row)
    return settings_row


async def update_email_settings(
    session: AsyncSession,
    *,
    host: str | None,
    port: int | None,
    secure: bool,
    reject_unauthorized: bool,
    username: str | None,
    password: str | None,
    password_provided: bool,
    from_address: str | None,
    test_recipient: str | None,
) -> AppSetting:
    settings_row = await _ensure_app_settings(session)
    settings_row.smtp_host = _normalize_optional_string(host)
    settings_row.smtp_port = port if port else None
    settings_row.smtp_secure = bool(secure)
    settings_row.smtp_reject_unauthorized = bool(reject_unauthorized)
    settings_row.smtp_username = _normalize_optional_string(username)
    if password_provided:
        normalized = _normalize_optional_string(password)
        settings_row.smtp_password_encrypted = encrypt_token(normalized) if normalized else None
    settings_row.smtp_from_address = _normalize_optional_string(from_address)
    settings_row.smtp_test_recipient = _normalize_optional_string(test_recipient)
    session.add(settings_row)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(settings_row)
    return settings_row


async def ensure_defaults(session: AsyncSession) -> None:
    await _ensure_app_settings(session)
    primary_guild_id = await guilds_service.get_primary_guild_id(session)
    await _ensure_guild_setting(session, primary_guild_id)

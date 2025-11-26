from __future__ import annotations

from collections.abc import Iterable, Mapping

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
from app.models.guild_setting import GuildSetting, DEFAULT_ROLE_LABELS
from app.services import guilds as guilds_service

ROLE_KEYS = ["admin", "project_manager", "member"]


async def _default_guild_id(session: AsyncSession) -> int:
    guild = await guilds_service.get_primary_guild(session)
    return guild.id


def _normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalize_domains(domains: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for domain in domains:
        cleaned = domain.strip().lower()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            normalized.append(cleaned)
    return normalized


def _normalize_scopes(scopes: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for scope in scopes:
        cleaned = scope.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            normalized.append(cleaned)
    return normalized or ["openid", "profile", "email"]


def _normalize_role_labels(
    labels: Mapping[str, str] | None,
    *,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    normalized = dict(base or DEFAULT_ROLE_LABELS)
    for role in ROLE_KEYS:
        normalized.setdefault(role, DEFAULT_ROLE_LABELS[role])
    if not labels:
        return normalized
    for role, value in labels.items():
        if role not in ROLE_KEYS or value is None:
            continue
        cleaned = value.strip()
        normalized[role] = cleaned or DEFAULT_ROLE_LABELS[role]
    return normalized


async def get_or_create_guild_settings(
    session: AsyncSession,
    *,
    guild_id: int | None = None,
    default_domains: Iterable[str] | None = None,
) -> GuildSetting:
    resolved_guild_id = guild_id or await _default_guild_id(session)
    stmt = select(GuildSetting).where(GuildSetting.guild_id == resolved_guild_id)
    result = await session.exec(stmt)
    settings_row = result.one_or_none()
    if settings_row:
        return settings_row

    domains = default_domains or app_config.AUTO_APPROVED_EMAIL_DOMAINS
    settings_row = GuildSetting(
        guild_id=resolved_guild_id,
        auto_approved_domains=_normalize_domains(domains),
        oidc_enabled=app_config.OIDC_ENABLED,
        oidc_discovery_url=app_config.OIDC_DISCOVERY_URL,
        oidc_client_id=app_config.OIDC_CLIENT_ID,
        oidc_client_secret=app_config.OIDC_CLIENT_SECRET,
        oidc_provider_name=app_config.OIDC_PROVIDER_NAME,
        oidc_scopes=_normalize_scopes(app_config.OIDC_SCOPES),
        light_accent_color="#2563eb",
        dark_accent_color="#60a5fa",
        role_labels=_normalize_role_labels(None),
        smtp_host=_normalize_optional_string(app_config.SMTP_HOST),
        smtp_port=app_config.SMTP_PORT if app_config.SMTP_HOST else None,
        smtp_secure=bool(app_config.SMTP_SECURE),
        smtp_reject_unauthorized=bool(app_config.SMTP_REJECT_UNAUTHORIZED),
        smtp_username=_normalize_optional_string(app_config.SMTP_USERNAME),
        smtp_password=_normalize_optional_string(app_config.SMTP_PASSWORD),
        smtp_from_address=_normalize_optional_string(app_config.SMTP_FROM_ADDRESS),
        smtp_test_recipient=_normalize_optional_string(app_config.SMTP_TEST_RECIPIENT),
    )
    session.add(settings_row)
    await session.commit()
    await session.refresh(settings_row)
    return settings_row


async def update_auto_approved_domains(
    session: AsyncSession,
    domains: Iterable[str],
    *,
    guild_id: int | None = None,
) -> GuildSetting:
    settings_row = await get_or_create_guild_settings(session, guild_id=guild_id)
    settings_row.auto_approved_domains = _normalize_domains(domains)
    session.add(settings_row)
    await session.commit()
    await session.refresh(settings_row)
    return settings_row


def is_email_auto_approved(email: str, settings_row: GuildSetting) -> bool:
    if not settings_row.auto_approved_domains:
        return False
    try:
        domain = email.split("@", maxsplit=1)[1].lower()
    except IndexError:
        return False
    return domain in settings_row.auto_approved_domains


async def update_oidc_settings(
    session: AsyncSession,
    *,
    enabled: bool,
    discovery_url: str | None,
    client_id: str | None,
    client_secret: str | None,
    provider_name: str | None,
    scopes: Iterable[str],
    guild_id: int | None = None,
) -> GuildSetting:
    settings_row = await get_or_create_guild_settings(session, guild_id=guild_id)
    settings_row.oidc_enabled = enabled
    settings_row.oidc_discovery_url = discovery_url
    settings_row.oidc_client_id = client_id
    if client_secret is not None:
        settings_row.oidc_client_secret = client_secret
    settings_row.oidc_provider_name = provider_name
    settings_row.oidc_scopes = _normalize_scopes(scopes)
    session.add(settings_row)
    await session.commit()
    await session.refresh(settings_row)
    return settings_row


async def update_interface_colors(
    session: AsyncSession,
    *,
    light_accent_color: str,
    dark_accent_color: str,
    guild_id: int | None = None,
) -> GuildSetting:
    settings_row = await get_or_create_guild_settings(session, guild_id=guild_id)
    settings_row.light_accent_color = light_accent_color
    settings_row.dark_accent_color = dark_accent_color
    session.add(settings_row)
    await session.commit()
    await session.refresh(settings_row)
    return settings_row


async def update_role_labels(
    session: AsyncSession,
    labels: Mapping[str, str | None],
    *,
    guild_id: int | None = None,
) -> GuildSetting:
    settings_row = await get_or_create_guild_settings(session, guild_id=guild_id)
    settings_row.role_labels = _normalize_role_labels(labels, base=settings_row.role_labels)
    session.add(settings_row)
    await session.commit()
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
    guild_id: int | None = None,
) -> GuildSetting:
    settings_row = await get_or_create_guild_settings(session, guild_id=guild_id)
    settings_row.smtp_host = _normalize_optional_string(host)
    settings_row.smtp_port = port if port else None
    settings_row.smtp_secure = bool(secure)
    settings_row.smtp_reject_unauthorized = bool(reject_unauthorized)
    settings_row.smtp_username = _normalize_optional_string(username)
    if password_provided:
        settings_row.smtp_password = _normalize_optional_string(password)
    settings_row.smtp_from_address = _normalize_optional_string(from_address)
    settings_row.smtp_test_recipient = _normalize_optional_string(test_recipient)
    session.add(settings_row)
    await session.commit()
    await session.refresh(settings_row)
    return settings_row

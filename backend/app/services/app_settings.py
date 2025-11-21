from collections.abc import Iterable

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
from app.models.app_setting import AppSetting

DEFAULT_SETTING_ID = 1


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


async def get_or_create_app_settings(
    session: AsyncSession,
    *,
    default_domains: Iterable[str] | None = None,
) -> AppSetting:
    result = await session.exec(select(AppSetting).where(AppSetting.id == DEFAULT_SETTING_ID))
    app_settings = result.one_or_none()
    if app_settings:
        return app_settings

    domains = default_domains or app_config.AUTO_APPROVED_EMAIL_DOMAINS
    app_settings = AppSetting(
        id=DEFAULT_SETTING_ID,
        auto_approved_domains=_normalize_domains(domains),
        oidc_enabled=app_config.OIDC_ENABLED,
        oidc_discovery_url=app_config.OIDC_DISCOVERY_URL,
        oidc_client_id=app_config.OIDC_CLIENT_ID,
        oidc_client_secret=app_config.OIDC_CLIENT_SECRET,
        oidc_provider_name=app_config.OIDC_PROVIDER_NAME,
        oidc_scopes=_normalize_scopes(app_config.OIDC_SCOPES),
        light_accent_color="#2563eb",
        dark_accent_color="#60a5fa",
    )
    session.add(app_settings)
    await session.commit()
    await session.refresh(app_settings)
    return app_settings


async def update_auto_approved_domains(session: AsyncSession, domains: Iterable[str]) -> AppSetting:
    app_settings = await get_or_create_app_settings(session)
    app_settings.auto_approved_domains = _normalize_domains(domains)
    session.add(app_settings)
    await session.commit()
    await session.refresh(app_settings)
    return app_settings


def is_email_auto_approved(email: str, app_settings: AppSetting) -> bool:
    if not app_settings.auto_approved_domains:
        return False
    try:
        domain = email.split("@", maxsplit=1)[1].lower()
    except IndexError:
        return False
    return domain in app_settings.auto_approved_domains


async def update_oidc_settings(
    session: AsyncSession,
    *,
    enabled: bool,
    discovery_url: str | None,
    client_id: str | None,
    client_secret: str | None,
    provider_name: str | None,
    scopes: Iterable[str],
) -> AppSetting:
    app_settings = await get_or_create_app_settings(session)
    app_settings.oidc_enabled = enabled
    app_settings.oidc_discovery_url = discovery_url
    app_settings.oidc_client_id = client_id
    if client_secret is not None:
        app_settings.oidc_client_secret = client_secret
    app_settings.oidc_provider_name = provider_name
    app_settings.oidc_scopes = _normalize_scopes(scopes)
    session.add(app_settings)
    await session.commit()
    await session.refresh(app_settings)
    return app_settings


async def update_interface_colors(
    session: AsyncSession,
    *,
    light_accent_color: str,
    dark_accent_color: str,
) -> AppSetting:
    app_settings = await get_or_create_app_settings(session)
    app_settings.light_accent_color = light_accent_color
    app_settings.dark_accent_color = dark_accent_color
    session.add(app_settings)
    await session.commit()
    await session.refresh(app_settings)
    return app_settings

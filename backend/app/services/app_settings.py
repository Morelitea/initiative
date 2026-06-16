from __future__ import annotations

from collections.abc import Iterable, Mapping

from sqlalchemy.exc import DBAPIError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
from app.core.encryption import (
    encrypt_field,
    SALT_OIDC_CLIENT_SECRET,
    SALT_SMTP_PASSWORD,
)
from app.core.pam_context import has_active_grant
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
    # A PAM grantee can't write guild_settings (a config table deliberately
    # off-limits to grants), so the lazy INSERT would fault under RLS. Their
    # read is satisfied by a transient default — guild overrides simply don't
    # apply, which is correct for a non-member.
    if has_active_grant(guild_id):
        return GuildSetting(guild_id=guild_id)
    settings_row = GuildSetting(guild_id=guild_id)
    session.add(settings_row)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(settings_row)
    return settings_row


async def get_or_create_guild_settings(
    session: AsyncSession, guild_id: int | None = None
) -> GuildSetting:
    resolved_guild_id = guild_id or await guilds_service.get_primary_guild_id(session)
    return await _ensure_guild_setting(session, resolved_guild_id)


def _build_default_app_settings() -> AppSetting:
    """A fresh, env-seeded ``AppSetting`` singleton (id=1), NOT persisted.

    Shared by the create path (persisted by a writer) and the privilege-tolerant
    read fallback (returned transient to a non-owner caller).
    """
    _oidc_secret = _normalize_optional_string(app_config.OIDC_CLIENT_SECRET)
    _smtp_pw = _normalize_optional_string(app_config.SMTP_PASSWORD)
    return AppSetting(
        id=GLOBAL_SETTINGS_ID,
        oidc_enabled=bool(app_config.OIDC_ENABLED),
        oidc_issuer=_normalize_optional_string(app_config.OIDC_ISSUER),
        oidc_client_id=_normalize_optional_string(app_config.OIDC_CLIENT_ID),
        oidc_client_secret_encrypted=encrypt_field(
            _oidc_secret, SALT_OIDC_CLIENT_SECRET
        )
        if _oidc_secret
        else None,
        oidc_provider_name=_normalize_optional_string(app_config.OIDC_PROVIDER_NAME),
        oidc_scopes=_normalize_scopes(
            app_config.OIDC_SCOPES or ["openid", "profile", "email", "offline_access"]
        ),
        light_accent_color="#2563eb",
        dark_accent_color="#60a5fa",
        role_labels=DEFAULT_ROLE_LABELS.copy(),
        smtp_host=_normalize_optional_string(app_config.SMTP_HOST),
        smtp_port=app_config.SMTP_PORT if app_config.SMTP_HOST else None,
        smtp_secure=bool(app_config.SMTP_SECURE),
        smtp_reject_unauthorized=bool(app_config.SMTP_REJECT_UNAUTHORIZED),
        smtp_username=_normalize_optional_string(app_config.SMTP_USERNAME),
        smtp_password_encrypted=encrypt_field(_smtp_pw, SALT_SMTP_PASSWORD)
        if _smtp_pw
        else None,
        smtp_from_address=_normalize_optional_string(app_config.SMTP_FROM_ADDRESS),
        smtp_test_recipient=_normalize_optional_string(app_config.SMTP_TEST_RECIPIENT),
    )


def _is_insufficient_privilege(exc: BaseException) -> bool:
    """True for a Postgres insufficient-privilege error (SQLSTATE 42501).

    Covers both a denied GRANT and an RLS WITH CHECK violation — the two ways a
    non-owner session is blocked from writing ``app_settings`` after Phase 2.
    """
    orig = getattr(exc, "orig", None)
    code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return code == "42501"


async def _persist_app_settings(
    session: AsyncSession, settings_row: AppSetting
) -> bool:
    """Persist ``settings_row``; return True iff it was written.

    Owner / app_admin / startup sessions persist normally. After Phase 2,
    ``app_settings`` is owner-only (GRANT + RLS), so a non-owner session (``app_user``
    or a platform tier below owner) that triggers the lazy singleton create / env
    re-seed on a READ hits insufficient-privilege. We catch that inside a SAVEPOINT
    (so the read doesn't 500) and return False — the caller serves a transient,
    env-correct fallback instead.

    Contract for the caller on a False return: the SAVEPOINT rollback EXPIRES a
    *tracked/persistent* instance (its Python-side edits are lost, and async
    attribute access then faults), so a re-seed caller must capture the env-merged
    values BEFORE calling this and rebuild a transient — it cannot reuse the
    instance. A freshly-built *transient* passed in (the create path) is merely
    expunged on rollback and keeps its in-memory values, so it can be returned
    as-is.
    """
    try:
        async with session.begin_nested():
            session.add(settings_row)
            await session.flush()
    except DBAPIError as exc:
        if not _is_insufficient_privilege(exc):
            raise
        return False
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(settings_row)
    return True


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
            settings_row.oidc_issuer = _normalize_optional_string(
                app_config.OIDC_ISSUER
            )
            updated = True
        if not settings_row.oidc_client_id and app_config.OIDC_CLIENT_ID:
            settings_row.oidc_client_id = _normalize_optional_string(
                app_config.OIDC_CLIENT_ID
            )
            updated = True
        if (
            not settings_row.oidc_client_secret_encrypted
            and app_config.OIDC_CLIENT_SECRET
        ):
            v = _normalize_optional_string(app_config.OIDC_CLIENT_SECRET)
            settings_row.oidc_client_secret_encrypted = (
                encrypt_field(v, SALT_OIDC_CLIENT_SECRET) if v else None
            )
            updated = True
        if not settings_row.oidc_provider_name and app_config.OIDC_PROVIDER_NAME:
            settings_row.oidc_provider_name = _normalize_optional_string(
                app_config.OIDC_PROVIDER_NAME
            )
            updated = True
        env_scopes = _normalize_scopes(app_config.OIDC_SCOPES or [])
        if env_scopes and not settings_row.oidc_scopes:
            settings_row.oidc_scopes = env_scopes
            updated = True
        if updated:
            # Snapshot the env-merged state NOW, while the instance is attached
            # and valid. A degraded (non-owner) persist rolls back its SAVEPOINT,
            # which EXPIRES this tracked instance — dropping the in-memory env
            # values and (under async) faulting on the next attribute access. On
            # that path we return a transient, env-correct copy built from the
            # snapshot instead of the expired instance.
            snapshot = {
                col.name: getattr(settings_row, col.name)
                for col in AppSetting.__table__.columns
            }
            if not await _persist_app_settings(session, settings_row):
                return AppSetting(**snapshot)
        return settings_row
    app_settings = _build_default_app_settings()
    await _persist_app_settings(session, app_settings)
    return app_settings


async def get_app_settings(
    session: AsyncSession, *, force_refresh: bool = False
) -> AppSetting:
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
        settings_row.oidc_client_secret_encrypted = (
            encrypt_field(normalized, SALT_OIDC_CLIENT_SECRET) if normalized else None
        )
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
    settings_row.role_labels = _normalize_role_labels(
        labels, base=settings_row.role_labels
    )
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
        settings_row.smtp_password_encrypted = (
            encrypt_field(normalized, SALT_SMTP_PASSWORD) if normalized else None
        )
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

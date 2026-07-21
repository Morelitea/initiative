from __future__ import annotations


from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
from app.core.encryption import (
    encrypt_field,
    SALT_S3_SECRET_KEY,
    SALT_SMTP_PASSWORD,
)
from app.core.pam_context import has_active_grant
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.tenant.guild_setting import GuildSetting
from app.services.platform import guilds as guilds_service

GLOBAL_SETTINGS_ID = 1


def _normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


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
    _smtp_pw = _normalize_optional_string(app_config.SMTP_PASSWORD)
    _s3_secret = _normalize_optional_string(app_config.S3_SECRET_ACCESS_KEY)
    return AppSetting(
        id=GLOBAL_SETTINGS_ID,
        light_accent_color="#2563eb",
        dark_accent_color="#60a5fa",
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
        storage_backend=(app_config.STORAGE_BACKEND or "local").lower(),
        s3_bucket=_normalize_optional_string(app_config.S3_BUCKET),
        s3_region=app_config.S3_REGION or "us-east-1",
        s3_endpoint_url=_normalize_optional_string(app_config.S3_ENDPOINT_URL),
        s3_access_key_id=_normalize_optional_string(app_config.S3_ACCESS_KEY_ID),
        s3_secret_access_key_encrypted=encrypt_field(_s3_secret, SALT_S3_SECRET_KEY)
        if _s3_secret
        else None,
        s3_use_path_style=bool(app_config.S3_USE_PATH_STYLE),
        s3_kms_key_id=_normalize_optional_string(app_config.S3_KMS_KEY_ID),
        s3_local_fallback=bool(app_config.S3_LOCAL_FALLBACK),
    )


async def _session_can_write_app_settings(session: AsyncSession) -> bool:
    """Whether the current DB role may WRITE ``app_settings``.

    After Phase 2 ``app_settings`` is owner-only at the GRANT layer (write granted
    only to ``platform_owner`` + the ``app_admin`` engine; revoked from ``app_user``,
    ``platform_base``, and ``app_guild_base``), and that GRANT is the single writer
    gate. A non-owner session that reads config and would lazily create / env-reseed
    the singleton must NOT attempt the write: an ORM flush failure dooms the whole
    session transaction (a SAVEPOINT doesn't isolate a failed flush the way it does a
    plain statement). So we probe the grant up front and skip the write, serving an
    in-memory env-correct value instead. ``has_table_privilege`` respects role
    inheritance, so it is authoritative now that the grant alone gates writes.
    """
    return bool(
        await session.scalar(
            text("SELECT has_table_privilege('app_settings', 'UPDATE')")
        )
    )


async def _write_app_settings(session: AsyncSession, settings_row: AppSetting) -> None:
    session.add(settings_row)
    await session.commit()
    await session.refresh(settings_row)


async def _ensure_app_settings(session: AsyncSession) -> AppSetting:
    stmt = select(AppSetting).where(AppSetting.id == GLOBAL_SETTINGS_ID)
    result = await session.exec(stmt)
    settings_row = result.one_or_none()
    if settings_row:
        # NOTE: an existing row is served as-is — env values seed a *new* row
        # once (_build_default_app_settings); after that the DB is
        # authoritative. (The OIDC env values now seed the platform provider
        # registry row instead — see platform_provider.seed_platform_provider_from_env.)
        return settings_row
    app_settings = _build_default_app_settings()
    if await _session_can_write_app_settings(session):
        await _write_app_settings(session, app_settings)
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
    await session.refresh(settings_row)
    return settings_row


async def update_storage_settings(
    session: AsyncSession,
    *,
    backend: str,
    s3_bucket: str | None,
    s3_region: str | None,
    s3_endpoint_url: str | None,
    s3_access_key_id: str | None,
    s3_secret_access_key: str | None,
    secret_provided: bool,
    s3_use_path_style: bool,
    s3_kms_key_id: str | None,
    s3_local_fallback: bool,
) -> AppSetting:
    settings_row = await _ensure_app_settings(session)
    settings_row.storage_backend = (backend or "local").lower()
    settings_row.s3_bucket = _normalize_optional_string(s3_bucket)
    settings_row.s3_region = (s3_region or "us-east-1").strip() or "us-east-1"
    settings_row.s3_endpoint_url = _normalize_optional_string(s3_endpoint_url)
    settings_row.s3_access_key_id = _normalize_optional_string(s3_access_key_id)
    if secret_provided:
        normalized = _normalize_optional_string(s3_secret_access_key)
        settings_row.s3_secret_access_key_encrypted = (
            encrypt_field(normalized, SALT_S3_SECRET_KEY) if normalized else None
        )
    settings_row.s3_use_path_style = bool(s3_use_path_style)
    settings_row.s3_kms_key_id = _normalize_optional_string(s3_kms_key_id)
    settings_row.s3_local_fallback = bool(s3_local_fallback)
    session.add(settings_row)
    await session.commit()
    await session.refresh(settings_row)
    # Refresh the process-wide resolved storage config so the live request path
    # picks up new creds/backend immediately (lazy import avoids a cycle: the
    # storage_config module reads get_app_settings from here).
    from app.services import storage_config

    await storage_config.refresh_storage_config(session)
    return settings_row


async def ensure_defaults(session: AsyncSession) -> None:
    await _ensure_app_settings(session)
    primary_guild_id = await guilds_service.get_primary_guild_id(session)
    # guild_settings is guild-scoped (lives only in the guild schema), so route
    # into the primary guild before seeding it — mirroring init_db.init(). On
    # the unrouted (public) admin session the table isn't visible. Reset to the
    # public baseline in a finally so a failure can't leave the session
    # guild-routed for a caller that reuses it.
    await set_rls_context(session, guild_id=primary_guild_id)
    try:
        await _ensure_guild_setting(session, primary_guild_id)
    finally:
        await set_rls_context(session)

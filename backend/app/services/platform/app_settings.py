from __future__ import annotations


from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from typing import Any

from app.core.audit_events import AuditEventType
from app.services import audit as audit_service
from app.core.config import settings as app_config
from app.core.encryption import (
    encrypt_field,
    SALT_S3_SECRET_KEY,
    SALT_SMTP_PASSWORD,
)
from app.core.pam_context import has_active_grant
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.platform.user_dm_settings import DmPolicy
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
    # Flushed, not committed: a guild's settings row is normally seeded when the
    # guild is made (``guilds.create_guild_settings``), so getting here means
    # filling a gap in the middle of whatever the caller came to do. The INSERT
    # joins their transaction and lands or unwinds with the rest of it. The two
    # callers that own their transaction commit it themselves.
    await session.flush()
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
    gate. Boot asks this before seeding the singleton, so a deployment whose
    system engine cannot write the table serves the env-seeded defaults in
    memory instead of faulting: a failed flush dooms the whole session
    transaction (a SAVEPOINT doesn't isolate one the way it does a plain
    statement). ``has_table_privilege`` respects role inheritance, so it is
    authoritative now that the grant alone gates writes.
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


async def _stored_app_settings(session: AsyncSession) -> AppSetting | None:
    stmt = select(AppSetting).where(AppSetting.id == GLOBAL_SETTINGS_ID)
    result = await session.exec(stmt)
    return result.one_or_none()


async def ensure_settings_row(session: AsyncSession) -> AppSetting:
    """The stored singleton, put in place here if boot has not already.

    For callers that are about to write the row or lock it, and so need a
    stored row rather than the transient value a read is served. The INSERT
    joins the caller's transaction and does not end it; a row another
    connection inserted first is kept rather than overwritten.

    The caller must hold write access to the table — every caller does, since
    it is on its way to a write. A read wants :func:`get_app_settings`.
    """
    settings_row = await _stored_app_settings(session)
    if settings_row is not None:
        return settings_row
    defaults = _build_default_app_settings()
    columns = AppSetting.__table__.columns
    await session.exec(
        pg_insert(AppSetting.__table__)
        .values({name: getattr(defaults, name) for name in columns.keys()})
        .on_conflict_do_nothing(index_elements=["id"])
    )
    settings_row = await _stored_app_settings(session)
    if settings_row is None:  # pragma: no cover - the INSERT landed or conflicted
        raise RuntimeError("app_settings singleton could not be created")
    return settings_row


async def seed_app_settings(session: AsyncSession) -> AppSetting:
    """Create the settings singleton, once, at boot.

    This is the only place the row is created outside a write somebody asked
    for, and it runs on the system engine before any request is served. A
    deployment whose session cannot write the table gets the env-seeded
    defaults in memory and no row, which is what it had before.
    """
    settings_row = await _stored_app_settings(session)
    if settings_row is not None:
        return settings_row
    if not await _session_can_write_app_settings(session):
        return _build_default_app_settings()
    settings_row = await ensure_settings_row(session)
    await session.commit()
    await session.refresh(settings_row)
    return settings_row


async def record_running_version(session: AsyncSession, *, version: str) -> str | None:
    """Roll the deployment's version pair forward, and say what it was before.

    Called once at boot. When the running version differs from what was last
    recorded, the old value becomes ``previous_version`` — which is what tells
    a notice meant for people upgrading past some release whether this
    deployment is one of them. A fresh install has neither, and that is the
    honest answer: it never upgraded from anything.

    Idempotent across restarts on the same version: the pair only moves when
    the running version actually changed.
    """
    if not await _session_can_write_app_settings(session):
        return (await get_app_settings(session)).previous_version
    settings_row = await ensure_settings_row(session)
    if settings_row.last_seen_version == version:
        return settings_row.previous_version
    settings_row.previous_version = settings_row.last_seen_version
    settings_row.last_seen_version = version
    await _write_app_settings(session, settings_row)
    return settings_row.previous_version


async def previous_running_version(session: AsyncSession) -> str | None:
    """What this deployment was running before its current version, if anything."""
    return (await get_app_settings(session)).previous_version


async def get_app_settings(session: AsyncSession) -> AppSetting:
    """What this deployment's configuration says — a read, and only a read.

    Boot puts the singleton in place (:func:`seed_app_settings`). Until it has,
    or where it could not, the caller is served the env-seeded defaults as a
    value that is not attached to the session: reading configuration writes
    nothing, and so never ends the transaction of whoever asked.

    An existing row is served as-is — env values seed a *new* row once
    (``_build_default_app_settings``); after that the database is
    authoritative. (The OIDC env values seed the platform provider registry row
    instead — see ``platform_provider.seed_platform_provider_from_env``.)
    """
    settings_row = await _stored_app_settings(session)
    if settings_row is not None:
        return settings_row
    return _build_default_app_settings()


# Which columns of the settings singleton each area of the owner's settings
# page can move. A record names the ones that actually moved; a value rides
# along only where its type rules out a secret.
INTERFACE_FIELDS: tuple[str, ...] = (
    "light_accent_color",
    "dark_accent_color",
    "cookie_notice_enabled",
)
COMMUNITY_FIELDS: tuple[str, ...] = (
    "community_directory_enabled",
    "community_age_gate_enabled",
    "default_dm_policy",
    "direct_messages_enabled",
    "deleted_community_retention_days",
    "deleted_account_retention_days",
)
EMAIL_FIELDS: tuple[str, ...] = (
    "smtp_host",
    "smtp_port",
    "smtp_secure",
    "smtp_reject_unauthorized",
    "smtp_username",
    "smtp_password_encrypted",
    "smtp_from_address",
    "smtp_test_recipient",
)
STORAGE_FIELDS: tuple[str, ...] = (
    "storage_backend",
    "s3_bucket",
    "s3_region",
    "s3_endpoint_url",
    "s3_access_key_id",
    "s3_secret_access_key_encrypted",
    "s3_use_path_style",
    "s3_kms_key_id",
    "s3_local_fallback",
)


async def _record_settings_area(
    session: AsyncSession,
    *,
    actor_user_id: int | None,
    area: str,
    before: dict[str, Any],
    row: AppSetting,
    fields: tuple[str, ...],
    extras: dict[str, Any] | None = None,
) -> None:
    """Stage the record for one area of the settings row, if it moved.

    Staged in the same transaction as the write, so the two land together.
    A caller that names no actor — boot-time seeding — records nothing.
    """
    if actor_user_id is None:
        return
    changed = audit_service.changed_fields(before, audit_service.snapshot(row, fields))
    if not changed["changed"] and not any((extras or {}).values()):
        return
    await audit_service.record(
        session,
        event_type=AuditEventType.PLATFORM_SETTINGS_CHANGED,
        actor_user_id=actor_user_id,
        detail={"area": area, **changed, **(extras or {})},
    )


async def update_interface_settings(
    session: AsyncSession,
    *,
    light_accent_color: str,
    dark_accent_color: str,
    cookie_notice_enabled: bool | None = None,
    actor_user_id: int | None = None,
) -> AppSetting:
    """The two accent colours, and whether arriving visitors get a cookie notice.

    ``cookie_notice_enabled`` is an independent decision and is left alone when
    omitted, so saving a colour does not silently answer it.
    """
    settings_row = await ensure_settings_row(session)
    before = audit_service.snapshot(settings_row, INTERFACE_FIELDS)
    settings_row.light_accent_color = light_accent_color.strip() or "#2563eb"
    settings_row.dark_accent_color = dark_accent_color.strip() or "#60a5fa"
    if cookie_notice_enabled is not None:
        settings_row.cookie_notice_enabled = bool(cookie_notice_enabled)
    session.add(settings_row)
    await _record_settings_area(
        session,
        actor_user_id=actor_user_id,
        area="interface",
        before=before,
        row=settings_row,
        fields=INTERFACE_FIELDS,
    )
    await session.commit()
    await session.refresh(settings_row)
    return settings_row


async def community_directory_enabled(session: AsyncSession) -> bool:
    """Whether the platform owner has the community directory switched on.

    The one read of the switch. Everything the directory consists of — browsing
    it, joining from it, and a guild listing itself in it — asks this first, so
    turning it off closes all three at once.
    """
    settings_row = await get_app_settings(session)
    return bool(settings_row.community_directory_enabled)


async def community_age_gate_enabled(session: AsyncSession) -> bool:
    """Whether an account must confirm its age to belong to a listed guild.

    The one read of the switch, for the same reason
    :func:`community_directory_enabled` is: the two places that ask — the join
    that refuses, and the standing check that routes an unconfirmed account to
    the screen — must agree at every moment.
    """
    settings_row = await get_app_settings(session)
    return bool(settings_row.community_age_gate_enabled)


async def direct_messages_enabled(session: AsyncSession) -> bool:
    """Whether this deployment offers direct messages at all.

    The one read of the switch. Every direct-message endpoint is gated on it,
    and so is the roster of people My Contacts says you could reach, so turning
    it off closes the feature and everything that advertises it at once.
    """
    settings_row = await get_app_settings(session)
    return bool(settings_row.direct_messages_enabled)


async def update_community_settings(
    session: AsyncSession,
    *,
    community_directory_enabled: bool,
    community_age_gate_enabled: bool | None = None,
    default_dm_policy: "DmPolicy | None" = None,
    direct_messages_enabled: bool | None = None,
    deleted_community_retention_days: int | None = None,
    retention_provided: bool = False,
    deleted_account_retention_days: int | None = None,
    account_retention_provided: bool = False,
    actor_user_id: int | None = None,
) -> AppSetting:
    """Turn the community directory on or off for the whole deployment.

    Switching it off leaves every guild's own opt-in exactly as it was: the
    listings simply have nowhere to appear until it is switched back on, so an
    operator flipping this twice does not silently unpublish anybody.

    ``default_dm_policy`` is a third, and the same rule applies: it is the
    policy a newly created account starts on, read once when the account is
    made. Changing it moves no existing account — raising it would open
    accounts that never chose to be open, and lowering it would revoke channels
    people are using.

    ``community_age_gate_enabled`` is a second, independent decision and is
    left alone when omitted: an owner who has asserted that every account here
    belongs to an adult has not un-asserted it by toggling the directory.

    ``direct_messages_enabled`` is a fourth, and independent of all three: a
    deployment can run a directory without messaging and vice versa. Omitted,
    it is left alone. Switching it off keeps every channel, policy and queued
    message as it is, so switching it back on restores them.

    ``deleted_community_retention_days`` and
    ``deleted_account_retention_days`` are the fifth and sixth, and the only
    ones where ``None`` is an answer rather than an omission — it means deleted
    communities are never destroyed — so the caller says which it meant with
    ``retention_provided``. Changing it changes when everything already deleted
    is destroyed, because the date is counted from each deletion rather than
    stamped at the time.
    """
    settings_row = await ensure_settings_row(session)
    before = audit_service.snapshot(settings_row, COMMUNITY_FIELDS)
    settings_row.community_directory_enabled = bool(community_directory_enabled)
    if community_age_gate_enabled is not None:
        settings_row.community_age_gate_enabled = bool(community_age_gate_enabled)
    if default_dm_policy is not None:
        settings_row.default_dm_policy = default_dm_policy
    if direct_messages_enabled is not None:
        settings_row.direct_messages_enabled = bool(direct_messages_enabled)
    if retention_provided:
        settings_row.deleted_community_retention_days = deleted_community_retention_days
    if account_retention_provided:
        settings_row.deleted_account_retention_days = deleted_account_retention_days
    session.add(settings_row)
    await _record_settings_area(
        session,
        actor_user_id=actor_user_id,
        area="community",
        before=before,
        row=settings_row,
        fields=COMMUNITY_FIELDS,
    )
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
    actor_user_id: int | None = None,
) -> AppSetting:
    settings_row = await ensure_settings_row(session)
    before = audit_service.snapshot(settings_row, EMAIL_FIELDS)
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
    await _record_settings_area(
        session,
        actor_user_id=actor_user_id,
        area="email",
        before=before,
        row=settings_row,
        fields=EMAIL_FIELDS,
        extras={
            "password_changed": before["smtp_password_encrypted"]
            != settings_row.smtp_password_encrypted
        },
    )
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
    actor_user_id: int | None = None,
) -> AppSetting:
    settings_row = await ensure_settings_row(session)
    before = audit_service.snapshot(settings_row, STORAGE_FIELDS)
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
    await _record_settings_area(
        session,
        actor_user_id=actor_user_id,
        area="storage",
        before=before,
        row=settings_row,
        fields=STORAGE_FIELDS,
        extras={
            "secret_changed": before["s3_secret_access_key_encrypted"]
            != settings_row.s3_secret_access_key_encrypted
        },
    )
    await session.commit()
    await session.refresh(settings_row)
    # Refresh the process-wide resolved storage config so the live request path
    # picks up new creds/backend immediately (lazy import avoids a cycle: the
    # storage_config module reads get_app_settings from here).
    from app.services import storage_config

    await storage_config.refresh_storage_config(session)
    return settings_row


async def ensure_defaults(session: AsyncSession) -> None:
    await seed_app_settings(session)
    primary_guild_id = await guilds_service.get_primary_guild_id(session)
    # guild_settings is guild-scoped (lives only in the guild schema), so route
    # into the primary guild before seeding it — mirroring init_db.init(). On
    # the unrouted (public) admin session the table isn't visible. Reset to the
    # public baseline in a finally so a failure can't leave the session
    # guild-routed for a caller that reuses it.
    await set_rls_context(session, guild_id=primary_guild_id)
    try:
        await _ensure_guild_setting(session, primary_guild_id)
        await session.commit()
    finally:
        await set_rls_context(session)

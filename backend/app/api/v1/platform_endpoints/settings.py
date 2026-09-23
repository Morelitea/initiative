import logging
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    SessionDep,
    UserSessionDep,
    GuildContext,
    require_guild_roles,
)
from app.api.v1.platform_endpoints.access_grants import check_second_factor
from app.api.v1.platform_endpoints.operator import ConfigManageDep, GuildsManageDep
from app.api.v1.platform_endpoints.session_opening import MOBILE_CALLBACK_URI
from app.core.audit_events import AuditEventType
from app.core.config import API_V1_STR
from app.core.config import settings as app_config
from app.core.rate_limit import limiter
from app.db.session import get_system_session
from app.models.platform.app_setting import AppSetting
from app.models.platform.app_setting_secret import AppSettingSecret
from app.models.platform.guild import (
    Guild,
    GuildMembership,
    GuildRole,
)
from app.models.platform.guild_administration import GuildAdministration
from app.schemas.platform.settings import (
    NotificationSettingsResponse,
    NotificationSettingsUpdate,
    GuildNarrowingAgreement,
    GuildNarrowingPending,
    CommunitySettingsResponse,
    CommunitySettingsUpdate,
    EmailSettingsResponse,
    EmailSettingsUpdate,
    EmailTestRequest,
    EmailTestResponse,
    InterfaceSettingsResponse,
    InterfaceSettingsUpdate,
    LoginMethodStatus,
    AccountsWithoutFactor,
    LoginMethodsUpdate,
    SecondFactorRequirementUpdate,
    SessionLifetimeUpdate,
    OIDCSettingsResponse,
    PlatformAuthSettingsResponse,
    StorageBackfillStatusResponse,
    CaptchaSettingsResponse,
    CaptchaSettingsUpdate,
    PushSettingsResponse,
    PushSettingsUpdate,
    StorageSettingsResponse,
    StorageSettingsUpdate,
    StorageTestResponse,
)
from app.models.platform.guild import GuildStatus, operator_status_choices
from app.schemas.platform.guild import (
    PlatformGuildRestore,
    PlatformGuildStorageRead,
    PlatformGuildStorageUpdate,
)
from app.models.platform.access_grant import AccessGrantPurpose, AccessLevel
from app.schemas.platform.access_grant import BreakGlassCreate, SecondFactorAnswer
from app.schemas.platform.billing import BillingPortalHandoffResponse
from app.schemas.platform.push import FCMConfigResponse
from app.core.messages import (
    BillingMessages,
    GuildMessages,
    SettingsMessages,
)
from app.core.security import (
    BillingSupportHandoffNotConfiguredError,
    create_billing_support_handoff_token,
)
from app.services.platform.identity_refs import billing_refs, billing_user_ref
from app.services.platform import access_grants as access_grants_service
from app.services.auth import narrowing_review
from app.services.auth import platform_provider as platform_provider_service
from app.core.login_methods import (
    FACTOR_METHODS,
    PRIMARY_LOGIN_METHODS,
    LoginMethod,
    SecondFactorRequirement,
)
from app.services.auth import session_lifetime
from app.services.platform import auth_posture
from app.services.platform import app_settings as app_settings_service
from app.services.platform import push_config
from app.services import captcha as captcha_service
from app.services.captcha_config import ResolvedCaptchaConfig
from app.services.platform import billing as billing_service
from app.services.platform import billing_ping
from app.services.platform import guild_purge
from app.services.platform import guilds as guilds_service
from app.services.platform import push_tokens
from app.services import audit as audit_service
from app.services import email as email_service
from app.services import storage_backfill, storage_config

logger = logging.getLogger(__name__)

# Reason stamped on a grant self-issued by the Guilds tab's billing button.
BILLING_PORTAL_GRANT_REASON = "Opened the billing portal from the Guilds tab"

# Which columns of the settings singleton this page moves itself; the other
# areas are recorded by the service that writes them. A value rides along in
# the record only where its type rules out a secret.
_SESSION_LIFETIME_FIELDS: tuple[str, ...] = (
    "session_max_hours",
    "session_idle_minutes",
)

#: What this deployment permits a notification to leave the app carrying, for
#: the record.
_NOTIFICATION_FIELDS: tuple[str, ...] = (
    "push_notifications_enabled",
    "email_notifications_enabled",
    "redact_notification_content",
)

#: What the operator's caps and entitlements for one community consist of.
_GUILD_ADMINISTRATION_FIELDS: tuple[str, ...] = (
    "max_storage_bytes",
    "max_users",
    "auth_options",
    "banner_image_enabled",
    "support_enabled",
)

SystemSessionDep = Annotated[AsyncSession, Depends(get_system_session)]

router = APIRouter()

GuildAdminContext = Annotated[
    GuildContext, Depends(require_guild_roles(GuildRole.admin))
]


def _backend_redirect_uri() -> str:
    return f"{app_config.APP_URL.rstrip('/')}{API_V1_STR}/auth/oidc/callback"


def _frontend_redirect_uri() -> str:
    return f"{app_config.APP_URL.rstrip('/')}/oidc/callback"


def _email_settings_payload(
    settings_obj: AppSetting, secrets: AppSettingSecret
) -> EmailSettingsResponse:
    return EmailSettingsResponse(
        host=settings_obj.smtp_host,
        port=settings_obj.smtp_port,
        secure=settings_obj.smtp_secure,
        reject_unauthorized=settings_obj.smtp_reject_unauthorized,
        username=settings_obj.smtp_username,
        has_password=bool(secrets.smtp_password_encrypted),
        from_address=settings_obj.smtp_from_address,
        test_recipient=settings_obj.smtp_test_recipient,
    )


def _platform_oidc_response(provider) -> OIDCSettingsResponse:
    """The redirect addresses that belong to the install rather than to any one
    provider.

    The provider fields are the platform row's, kept for readers that have not
    moved to the registry; a provider is configured through
    ``/settings/auth/providers``, which is the only place that writes one."""
    return OIDCSettingsResponse(
        enabled=provider.enabled if provider else False,
        issuer=provider.issuer if provider else None,
        client_id=provider.client_id if provider else None,
        redirect_uri=_backend_redirect_uri(),
        post_login_redirect=_frontend_redirect_uri(),
        mobile_redirect_uri=MOBILE_CALLBACK_URI,
        provider_name=provider.display_name if provider else None,
        scopes=platform_provider_service.scopes_list(provider)
        if provider
        else list(platform_provider_service.DEFAULT_OIDC_SCOPES),
    )


@router.get("/auth", response_model=OIDCSettingsResponse)
async def get_oidc_settings(
    session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> OIDCSettingsResponse:
    """The install's redirect addresses. System engine: ``auth_providers``
    carries no request-path grant; the capability gate stays
    ``config.manage``."""
    provider = await platform_provider_service.get_platform_provider(session)
    return _platform_oidc_response(provider)


async def _platform_auth_payload(session) -> PlatformAuthSettingsResponse:
    """The permitted ways in, and what withdrawing one would cost.

    The counts are computed on every read so the page can state the
    consequence before the write instead of after a refusal — and so the figure
    an operator acknowledges is one the page actually showed them.
    """
    row = await app_settings_service.get_app_settings(session)
    permitted = auth_posture.methods_from_row(row)
    return PlatformAuthSettingsResponse(
        methods=[
            LoginMethodStatus(
                method=method,
                enabled=method in permitted,
                primary=method in PRIMARY_LOGIN_METHODS,
                answers_factor=method in FACTOR_METHODS,
                would_strand=await auth_posture.stranded_between(
                    session, current=permitted, requested=permitted - {method}
                ),
            )
            for method in LoginMethod
        ],
        guilds_requiring_sign_in=await auth_posture.guilds_requiring_sign_in(session),
        factor_methods_permitted=bool(permitted.intersection(FACTOR_METHODS)),
        session_max_hours=row.session_max_hours,
        session_idle_minutes=row.session_idle_minutes,
        second_factor_requirement=auth_posture.requirement_from_row(row),
        accounts_without_factor=AccountsWithoutFactor(
            platform_roles=await auth_posture.accounts_without_factor(
                session, level=SecondFactorRequirement.platform_roles
            ),
            everyone=await auth_posture.accounts_without_factor(
                session, level=SecondFactorRequirement.everyone
            ),
        ),
    )


@router.get("/auth/platform", response_model=PlatformAuthSettingsResponse)
async def get_platform_auth_settings(
    session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> PlatformAuthSettingsResponse:
    """Which ways in are permitted. System engine: the guard counts read
    ``auth_providers`` and ``federated_identities``, neither of which carries a
    request-path grant."""
    return await _platform_auth_payload(session)


@router.put("/auth/methods", response_model=PlatformAuthSettingsResponse)
async def update_login_methods(
    payload: LoginMethodsUpdate,
    session: SystemSessionDep,
    owner: ConfigManageDep,
) -> PlatformAuthSettingsResponse:
    """Set which ways in this deployment permits — at least one.

    Withdrawing one that is somebody's only way in is refused (409) with the
    count in ``X-Affected-Count``, and proceeds only when the caller echoes
    that exact number back in ``acknowledge_stranded``. Nobody is signed out
    either way."""
    await auth_posture.set_login_methods(
        session,
        methods=payload.methods,
        acknowledge_stranded=payload.acknowledge_stranded,
        actor_user_id=owner.id,
    )
    return await _platform_auth_payload(session)


@router.put(
    "/auth/second-factor-requirement", response_model=PlatformAuthSettingsResponse
)
async def update_second_factor_requirement(
    payload: SecondFactorRequirementUpdate,
    session: SystemSessionDep,
    owner: ConfigManageDep,
) -> PlatformAuthSettingsResponse:
    """Set who this deployment asks to hold a second factor.

    Two refusals on the way up, and none coming down. Asking for one while the
    deployment permits nothing that presents one is refused (409); so is
    asking while the account writing it does not meet the rule itself (400,
    naming the unmet method), which is the same "prove it before it binds
    anybody" a community's requirement makes.

    Nobody is signed out. An account the rule covers is asked at its next
    request and can answer it where it stands; a credential that cannot
    present one — the app on a phone, a personal API key — works again once
    its owner holds a factor.
    """
    await auth_posture.set_second_factor_requirement(
        session, level=payload.level, actor=owner
    )
    return await _platform_auth_payload(session)


@router.put("/auth/session-lifetime", response_model=PlatformAuthSettingsResponse)
async def update_session_lifetime(
    payload: SessionLifetimeUpdate,
    session: SystemSessionDep,
    owner: ConfigManageDep,
) -> PlatformAuthSettingsResponse:
    """Set how long somebody may stay signed in before signing in again.

    Separate from how long a session may be left alone, which the deployment's
    own configuration holds. A session already open keeps the terms it was
    opened under and takes the new figure at the next sign-in; a device token
    is brought under the new figure now, measured from when it was issued, so
    shortening the limit can end one on the spot.
    """
    row = await app_settings_service.get_app_settings(session)
    before = audit_service.snapshot(row, _SESSION_LIFETIME_FIELDS)
    row.session_max_hours = payload.session_max_hours
    row.session_idle_minutes = payload.session_idle_minutes
    session.add(row)
    await session.flush()
    # A device token carries its deadline in its own expiry, so the new figure
    # is written into the ones already issued rather than read back on every
    # native request.
    await session_lifetime.apply_to_device_tokens(session)
    changed = audit_service.changed_fields(
        before, audit_service.snapshot(row, _SESSION_LIFETIME_FIELDS)
    )
    if changed["changed"]:
        await audit_service.record(
            session,
            event_type=AuditEventType.PLATFORM_SETTINGS_CHANGED,
            actor_user_id=owner.id,
            detail={"area": "session_lifetime", **changed},
        )
    await session.commit()
    return await _platform_auth_payload(session)


async def _notification_payload(session) -> NotificationSettingsResponse:
    row = await app_settings_service.get_app_settings(session)
    return NotificationSettingsResponse(
        push_notifications_enabled=row.push_notifications_enabled,
        email_notifications_enabled=row.email_notifications_enabled,
        redact_notification_content=row.redact_notification_content,
    )


@router.get("/notifications", response_model=NotificationSettingsResponse)
async def get_notification_settings(
    session: UserSessionDep,
    _owner: ConfigManageDep,
) -> NotificationSettingsResponse:
    """What this deployment permits a notification to leave the app carrying."""
    return await _notification_payload(session)


@router.put("/notifications", response_model=NotificationSettingsResponse)
async def update_notification_settings(
    payload: NotificationSettingsUpdate,
    session: SystemSessionDep,
    owner: ConfigManageDep,
) -> NotificationSettingsResponse:
    """Decide what this deployment permits a notification to leave the app with.

    Every community is held to this as a ceiling: one may decline a channel the
    deployment permits, and none may take back one the deployment has declined.

    Switching push off drops the device tokens this deployment was holding, and
    the registration endpoint declines while it stays off — so the deployment
    stops sending and stops keeping the addresses it was sending to. Devices
    register again the next time the app starts, which is what restores
    delivery when it is switched back on.

    Switching email off stops notification email and nothing else: a sign-in
    code, an address to confirm, a password reset and the notices an account
    gets about itself keep going, because this must not lock anybody out of
    their account.
    """
    row = await app_settings_service.ensure_settings_row(session)
    before = audit_service.snapshot(row, _NOTIFICATION_FIELDS)
    dropping_push = row.push_notifications_enabled and not (
        payload.push_notifications_enabled
    )
    row.push_notifications_enabled = payload.push_notifications_enabled
    row.email_notifications_enabled = payload.email_notifications_enabled
    row.redact_notification_content = payload.redact_notification_content
    session.add(row)
    await session.flush()
    if dropping_push:
        dropped = await push_tokens.purge_all(session)
        logger.info("push notifications switched off; dropped %d token(s)", dropped)
    changed = audit_service.changed_fields(
        before, audit_service.snapshot(row, _NOTIFICATION_FIELDS)
    )
    if changed["changed"]:
        await audit_service.record(
            session,
            event_type=AuditEventType.PLATFORM_SETTINGS_CHANGED,
            actor_user_id=owner.id,
            detail={"area": "notifications", **changed},
        )
    await session.commit()
    return await _notification_payload(session)


@router.get("/interface", response_model=InterfaceSettingsResponse)
async def get_interface_settings(
    session: SessionDep,
) -> InterfaceSettingsResponse:
    settings_obj = await app_settings_service.get_app_settings(session)
    return InterfaceSettingsResponse(
        light_accent_color=settings_obj.light_accent_color,
        dark_accent_color=settings_obj.dark_accent_color,
        cookie_consent_enabled=settings_obj.cookie_consent_enabled,
    )


@router.put("/interface", response_model=InterfaceSettingsResponse)
async def update_interface_settings(
    payload: InterfaceSettingsUpdate,
    session: UserSessionDep,
    owner: ConfigManageDep,
) -> InterfaceSettingsResponse:
    settings_obj = await app_settings_service.update_interface_settings(
        session,
        light_accent_color=payload.light_accent_color,
        dark_accent_color=payload.dark_accent_color,
        cookie_consent_enabled=payload.cookie_consent_enabled,
        actor_user_id=owner.id,
    )
    return InterfaceSettingsResponse(
        light_accent_color=settings_obj.light_accent_color,
        dark_accent_color=settings_obj.dark_accent_color,
        cookie_consent_enabled=settings_obj.cookie_consent_enabled,
    )


@router.get("/community", response_model=CommunitySettingsResponse)
async def read_community_settings(
    session: UserSessionDep,
    _owner: ConfigManageDep,
) -> CommunitySettingsResponse:
    """The four community-wide decisions, for the owner's settings page.

    Three of them are also on ``GET /config``, which is where every signed-in
    page reads them. ``default_dm_policy`` is not: nothing in the SPA acts on it
    — the server applies it when an account is made — so it is served here,
    behind the capability that writes it, rather than added to everyone's boot
    payload.
    """
    settings_obj = await app_settings_service.get_app_settings(session)
    return CommunitySettingsResponse(
        community_directory_enabled=settings_obj.community_directory_enabled,
        age_gate_enabled=settings_obj.community_age_gate_enabled,
        default_dm_policy=settings_obj.default_dm_policy,
        direct_messages_enabled=settings_obj.direct_messages_enabled,
        deleted_community_retention_days=settings_obj.deleted_community_retention_days,
        deleted_account_retention_days=settings_obj.deleted_account_retention_days,
    )


@router.put("/community", response_model=CommunitySettingsResponse)
async def update_community_settings(
    payload: CommunitySettingsUpdate,
    session: UserSessionDep,
    owner: ConfigManageDep,
) -> CommunitySettingsResponse:
    """Turn the community directory on or off for the whole deployment.

    Write-only on purpose: the current value is public — every signed-in page
    needs it to decide whether to offer the directory — so it is served from
    ``GET /config`` with the rest of the SPA's boot configuration rather than
    from a second, capability-gated read of the same boolean.

    Switching it off hides the directory and refuses new listings; it does not
    clear the opt-in a guild already made, so switching it back on restores the
    same set of listed guilds.

    ``default_dm_policy`` is the third decision here and behaves like the
    second: omitted, it is left alone. It is the policy a newly created account
    starts on, and changing it moves no existing account.

    ``age_gate_enabled`` is the second switch: whether an account must confirm
    it belongs to somebody 16 or older before it takes a place in a listed
    guild. That join is all it gates; an invited guild asks nobody's age. Turning it off is the owner asserting that every account on this
    deployment already belongs to an adult, which is why it is a deliberate
    write and not a side effect of the first — omitting it leaves it alone.

    ``direct_messages_enabled`` is the fourth, and independent of the other
    three: a deployment can run a directory without messaging, or messaging
    without a directory. Off, My Messages is not offered and every
    direct-message route refuses; nothing is deleted, so turning it back on
    restores the channels people already had.

    ``deleted_community_retention_days`` is the fifth: how long a deleted
    community is kept before it is destroyed. ``null`` means never, which is
    the answer for a deployment that has undertaken to keep what its members
    put in it, so this field reads its presence rather than its value — omit it
    to leave the window alone. The figure is the deployment's; a community has
    no say in its own.
    """
    settings_obj = await app_settings_service.update_community_settings(
        session,
        community_directory_enabled=payload.community_directory_enabled,
        community_age_gate_enabled=payload.age_gate_enabled,
        default_dm_policy=payload.default_dm_policy,
        direct_messages_enabled=payload.direct_messages_enabled,
        deleted_community_retention_days=payload.deleted_community_retention_days,
        retention_provided="deleted_community_retention_days"
        in payload.model_fields_set,
        deleted_account_retention_days=payload.deleted_account_retention_days,
        account_retention_provided="deleted_account_retention_days"
        in payload.model_fields_set,
        actor_user_id=owner.id,
    )
    return CommunitySettingsResponse(
        community_directory_enabled=settings_obj.community_directory_enabled,
        age_gate_enabled=settings_obj.community_age_gate_enabled,
        default_dm_policy=settings_obj.default_dm_policy,
        direct_messages_enabled=settings_obj.direct_messages_enabled,
        deleted_community_retention_days=settings_obj.deleted_community_retention_days,
        deleted_account_retention_days=settings_obj.deleted_account_retention_days,
    )


@router.get("/email", response_model=EmailSettingsResponse)
async def get_email_settings(
    session: UserSessionDep,
    system_session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> EmailSettingsResponse:
    # Whether a password is stored is read on the system engine, which alone
    # holds app_setting_secrets.
    settings_obj = await app_settings_service.get_app_settings(session)
    secrets = await app_settings_service.get_app_setting_secrets(system_session)
    return _email_settings_payload(settings_obj, secrets)


@router.put("/email", response_model=EmailSettingsResponse)
async def update_email_settings(
    payload: EmailSettingsUpdate,
    session: UserSessionDep,
    system_session: SystemSessionDep,
    owner: ConfigManageDep,
) -> EmailSettingsResponse:
    # The settings row is written under the owner's tier; the password, when
    # one is sent, on the system engine.
    data = payload.model_dump(exclude_unset=True)
    password_provided = "password" in data
    updated, secrets = await app_settings_service.update_email_settings(
        session,
        system_session=system_session,
        host=payload.host,
        port=payload.port,
        secure=payload.secure,
        reject_unauthorized=payload.reject_unauthorized,
        username=payload.username,
        password=payload.password,
        password_provided=password_provided,
        from_address=payload.from_address,
        test_recipient=payload.test_recipient,
        actor_user_id=owner.id,
    )
    return _email_settings_payload(updated, secrets)


@router.post("/email/test")
async def send_test_email(
    payload: EmailTestRequest,
    session: UserSessionDep,
    _owner: ConfigManageDep,
) -> EmailTestResponse:
    settings_obj = await app_settings_service.get_app_settings(session)
    recipient = payload.recipient or settings_obj.smtp_test_recipient
    if not recipient:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.PROVIDE_TEST_EMAIL,
        )
    try:
        await email_service.send_test_email(session, recipient)
    except email_service.EmailNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.SMTP_INCOMPLETE,
        ) from None
    except RuntimeError as exc:
        # Log the real cause (may include SMTP host/port/server banner) for the
        # operator, but return only a generic machine-readable code so the
        # response never leaks internal mail-server details (pentest SEC-16).
        logger.warning("Test email delivery failed: %s", str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=SettingsMessages.EMAIL_SEND_FAILED,
        ) from exc
    return EmailTestResponse(status="sent")


# --- Object storage ---


def _storage_settings_payload(
    settings_obj: AppSetting, secrets: AppSettingSecret
) -> StorageSettingsResponse:
    backend = (settings_obj.storage_backend or "local").lower()
    return StorageSettingsResponse(
        backend="s3" if backend == "s3" else "local",
        s3_bucket=settings_obj.s3_bucket,
        s3_region=settings_obj.s3_region or "us-east-1",
        s3_endpoint_url=settings_obj.s3_endpoint_url,
        s3_access_key_id=settings_obj.s3_access_key_id,
        has_secret_access_key=bool(secrets.s3_secret_access_key_encrypted),
        s3_use_path_style=settings_obj.s3_use_path_style,
        s3_kms_key_id=settings_obj.s3_kms_key_id,
        s3_local_fallback=settings_obj.s3_local_fallback,
    )


@router.get("/storage", response_model=StorageSettingsResponse)
async def get_storage_settings(
    session: UserSessionDep,
    system_session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> StorageSettingsResponse:
    # Whether a secret key is stored is read on the system engine, which alone
    # holds app_setting_secrets.
    settings_obj = await app_settings_service.get_app_settings(session)
    secrets = await app_settings_service.get_app_setting_secrets(system_session)
    return _storage_settings_payload(settings_obj, secrets)


@router.put("/storage", response_model=StorageSettingsResponse)
async def update_storage_settings(
    payload: StorageSettingsUpdate,
    session: UserSessionDep,
    system_session: SystemSessionDep,
    owner: ConfigManageDep,
) -> StorageSettingsResponse:
    # The settings row is written under the owner's tier; the secret key, when
    # one is sent, on the system engine.
    data = payload.model_dump(exclude_unset=True)
    secret_provided = "s3_secret_access_key" in data
    updated, secrets = await app_settings_service.update_storage_settings(
        session,
        system_session=system_session,
        backend=payload.backend,
        s3_bucket=payload.s3_bucket,
        s3_region=payload.s3_region,
        s3_endpoint_url=payload.s3_endpoint_url,
        s3_access_key_id=payload.s3_access_key_id,
        s3_secret_access_key=payload.s3_secret_access_key,
        secret_provided=secret_provided,
        s3_use_path_style=payload.s3_use_path_style,
        s3_kms_key_id=payload.s3_kms_key_id,
        s3_local_fallback=payload.s3_local_fallback,
        actor_user_id=owner.id,
    )
    return _storage_settings_payload(updated, secrets)


@router.post("/storage/test", response_model=StorageTestResponse)
async def test_storage_connection(
    payload: StorageSettingsUpdate,
    _owner: ConfigManageDep,
) -> StorageTestResponse:
    # Test the submitted (possibly unsaved) config. If the owner left the secret
    # blank, fall back to the saved one so they can re-test without re-typing it
    # (read on the system engine, which alone holds app_setting_secrets).
    data = payload.model_dump(exclude_unset=True)
    secret = payload.s3_secret_access_key
    if "s3_secret_access_key" not in data or not secret:
        secret = await storage_config.resolve_saved_secret()
    candidate = storage_config.ResolvedStorageConfig(
        backend="s3" if payload.backend == "s3" else "local",
        bucket=(payload.s3_bucket or "").strip() or None,
        region=(payload.s3_region or "us-east-1").strip() or "us-east-1",
        endpoint_url=(payload.s3_endpoint_url or "").strip() or None,
        access_key_id=(payload.s3_access_key_id or "").strip() or None,
        secret_access_key=secret,
        use_path_style=bool(payload.s3_use_path_style),
        kms_key_id=(payload.s3_kms_key_id or "").strip() or None,
        local_fallback=bool(payload.s3_local_fallback),
    )
    ok, message = await storage_config.test_connection(candidate)
    return StorageTestResponse(success=ok, message=message)


def _backfill_payload(row: dict) -> StorageBackfillStatusResponse:
    started = row.get("started_at")
    finished = row.get("finished_at")
    return StorageBackfillStatusResponse(
        status=row["status"],
        copied=row["copied"],
        skipped=row["skipped"],
        failed=row["failed"],
        hash_mismatches=row["hash_mismatches"],
        failed_keys=list(row.get("failed_keys") or []),
        started_at=started.isoformat() if started else None,
        finished_at=finished.isoformat() if finished else None,
        error=row.get("error"),
    )


@router.post("/storage/backfill", response_model=StorageBackfillStatusResponse)
async def start_storage_backfill(
    session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> StorageBackfillStatusResponse:
    # The backfill writes to S3 via the saved credentials, so they must be set
    # (the documented flow runs it while still serving on "local").
    settings_obj = await app_settings_service.get_app_settings(session)
    if not settings_obj.s3_bucket:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.STORAGE_BACKFILL_NOT_CONFIGURED,
        )
    # Make sure the detached task resolves the freshly-saved S3 credentials.
    await storage_config.refresh_storage_config(session)
    try:
        row = await storage_backfill.start_backfill(session)
    except storage_backfill.BackfillAlreadyRunning:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=SettingsMessages.STORAGE_BACKFILL_RUNNING,
        ) from None
    return _backfill_payload(row)


@router.get("/storage/backfill", response_model=StorageBackfillStatusResponse)
async def get_storage_backfill_status(
    session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> StorageBackfillStatusResponse:
    return _backfill_payload(await storage_backfill.get_status(session))


# --- Registration captcha ---


def _captcha_payload(
    settings_obj: AppSetting, secrets: AppSettingSecret
) -> CaptchaSettingsResponse:
    has_secret = bool(secrets.captcha_secret_key_encrypted)
    provider = settings_obj.captcha_provider
    return CaptchaSettingsResponse(
        provider=provider,
        site_key=settings_obj.captcha_site_key,
        has_secret_key=has_secret,
        # The client cannot see the secret, so it cannot work out whether
        # enforcement is on. Answered here, by the same predicate the verifier
        # uses, so the page and the register endpoint agree.
        enforcing=captcha_service.is_configured(
            ResolvedCaptchaConfig(
                provider=provider,
                site_key=settings_obj.captcha_site_key,
                secret_key="stored" if has_secret else None,
            )
        ),
    )


@router.get("/captcha", response_model=CaptchaSettingsResponse)
async def get_captcha_settings(
    session: UserSessionDep,
    system_session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> CaptchaSettingsResponse:
    settings_obj = await app_settings_service.get_app_settings(session)
    secrets = await app_settings_service.get_app_setting_secrets(system_session)
    return _captcha_payload(settings_obj, secrets)


@router.put("/captcha", response_model=CaptchaSettingsResponse)
async def update_captcha_settings(
    payload: CaptchaSettingsUpdate,
    session: UserSessionDep,
    system_session: SystemSessionDep,
    owner: ConfigManageDep,
) -> CaptchaSettingsResponse:
    # An absent secret_key keeps the stored one; an explicit null or "" clears
    # it. Same contract as the storage page, so an owner can edit the site key
    # without re-typing a secret they cannot read back.
    data = payload.model_dump(exclude_unset=True)
    updated, secrets = await app_settings_service.update_captcha_settings(
        session,
        system_session=system_session,
        provider=payload.provider,
        site_key=payload.site_key,
        secret_key=payload.secret_key,
        secret_provided="secret_key" in data,
        actor_user_id=owner.id,
    )
    return _captcha_payload(updated, secrets)


# --- Push notifications (FCM) ---


def _push_payload(
    settings_obj: AppSetting, secrets: AppSettingSecret
) -> PushSettingsResponse:
    return PushSettingsResponse(
        enabled=settings_obj.fcm_enabled,
        project_id=settings_obj.fcm_project_id,
        application_id=settings_obj.fcm_application_id,
        api_key=settings_obj.fcm_api_key,
        sender_id=settings_obj.fcm_sender_id,
        has_service_account=bool(secrets.fcm_service_account_json_encrypted),
    )


@router.get("/push", response_model=PushSettingsResponse)
async def get_push_settings(
    session: UserSessionDep,
    system_session: SystemSessionDep,
    _owner: ConfigManageDep,
) -> PushSettingsResponse:
    settings_obj = await app_settings_service.get_app_settings(session)
    secrets = await app_settings_service.get_app_setting_secrets(system_session)
    return _push_payload(settings_obj, secrets)


@router.put("/push", response_model=PushSettingsResponse)
async def update_push_settings(
    payload: PushSettingsUpdate,
    session: UserSessionDep,
    system_session: SystemSessionDep,
    owner: ConfigManageDep,
) -> PushSettingsResponse:
    data = payload.model_dump(exclude_unset=True)
    updated, secrets = await app_settings_service.update_push_settings(
        session,
        system_session=system_session,
        enabled=payload.enabled,
        project_id=payload.project_id,
        application_id=payload.application_id,
        api_key=payload.api_key,
        sender_id=payload.sender_id,
        service_account_json=payload.service_account_json,
        secret_provided="service_account_json" in data,
        actor_user_id=owner.id,
    )
    return _push_payload(updated, secrets)


@router.get("/fcm-config", response_model=FCMConfigResponse)
@limiter.limit("20/minute")
async def get_fcm_config(request: Request) -> FCMConfigResponse:
    """Get public FCM configuration for mobile app initialization.

    This endpoint is public (no authentication required) and only exposes
    public fields needed by the mobile app to initialize Firebase.
    Service account credentials are NOT exposed.

    Rate limited to 20 requests per minute to prevent abuse.

    Read from the settings row (``push_config``), not the environment: an owner
    who turns push on in Settings has the mobile clients pick it up on their
    next launch rather than on the next redeploy. The resolver opens its own
    system-engine session, which is what lets this endpoint stay
    unauthenticated and sessionless.
    """
    cfg = await push_config.ensure_push_config_fresh()
    return FCMConfigResponse(
        enabled=cfg.enabled,
        project_id=cfg.project_id if cfg.enabled else None,
        application_id=cfg.application_id if cfg.enabled else None,
        api_key=cfg.api_key if cfg.enabled else None,
        sender_id=cfg.sender_id if cfg.enabled else None,
    )


# --- Guild storage limits (Operator dashboard → Guilds tab) ---


def _guild_purge_at(guild: Guild, retention: int | None) -> datetime | None:
    """When this guild is destroyed, or None if nothing will destroy it.

    ``status_changed_at`` is the deletion time for a deleted guild, so the date
    is derived from the columns already loaded rather than stored. ``retention``
    is the deployment's window; None there means it keeps deleted communities,
    and a community that is never destroyed has no date to show.
    """
    if guild.status != GuildStatus.deleted.value or guild.status_changed_at is None:
        return None
    if retention is None:
        return None
    return guild_purge.purge_at(guild.status_changed_at, retention)


def _guild_storage_read(
    guild: Guild,
    administration: GuildAdministration | None,
    *,
    member_count: int,
    has_seat: bool,
    retention: int | None,
) -> PlatformGuildStorageRead:
    """One row of the Guilds tab.

    ``administration`` is None only for a guild missing its companion row,
    which is listed with blank caps rather than dropped.
    """
    current = GuildStatus(guild.status)
    recorded = administration.billing_status if administration else None
    return PlatformGuildStorageRead(
        id=guild.id,
        name=guild.name,
        member_count=member_count,
        purge_at=_guild_purge_at(guild, retention),
        has_seat=has_seat,
        tier_name=administration.tier_name if administration else None,
        max_storage_bytes=(
            administration.max_storage_bytes if administration else None
        ),
        max_users=administration.max_users if administration else None,
        status=current,
        status_changed_at=guild.status_changed_at,
        status_choices=list(
            operator_status_choices(
                current,
                billing_status=GuildStatus(recorded) if recorded else None,
                billing_managed=billing_service.billing_managed(),
            )
        ),
        auth_options=sorted(administration.auth_options) if administration else [],
        banner_image_enabled=(
            administration.banner_image_enabled if administration else True
        ),
        support_enabled=administration.support_enabled if administration else False,
    )


async def _member_tallies() -> tuple[dict[int, int], set[int]]:
    """Each community's member count, and which communities hold their seat.

    Two grouped queries for the whole deployment, on the system engine: the
    platform tier reads no roster but its own memberships, and this list needs
    only the totals, not the rows behind them.
    """
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as system_session:
        counts = dict(
            (
                await system_session.exec(
                    select(GuildMembership.guild_id, func.count()).group_by(
                        GuildMembership.guild_id
                    )
                )
            ).all()
        )
        seated = set(
            (
                await system_session.exec(
                    select(GuildMembership.guild_id)
                    .where(GuildMembership.role == GuildRole.superadmin)
                    .distinct()
                )
            ).all()
        )
    return counts, seated


@router.get("/guilds", response_model=list[PlatformGuildStorageRead])
async def list_platform_guild_storage(
    session: UserSessionDep,
    _operator: GuildsManageDep,
) -> list[PlatformGuildStorageRead]:
    """List every guild with its storage cap, for the Operator dashboard Guilds tab.

    Operator/owner (``guilds.manage``). Reads only shared ``public`` tables. The
    guilds and their administration rows are read on the caller's platform
    tier, under the ``guilds.manage`` policies on both; the caps join in a
    single pass. Member counts and seats are totals read on the system engine
    (``_member_tallies``), one grouped query each rather than per guild.
    """
    # Outer join on purpose: this is the operator's view of *every* guild, and a
    # guild missing its companion row must still be listed (with blank caps) so
    # it stays manageable, rather than silently vanishing from the moderation
    # surface. Creation writes the pair together, so this is a floor, not a
    # normal case.
    rows = (
        await session.exec(
            select(Guild, GuildAdministration)
            .outerjoin(GuildAdministration, GuildAdministration.guild_id == Guild.id)
            .order_by(Guild.name)
        )
    ).all()
    retention = await guild_purge.retention_days(session)
    counts, seated = await _member_tallies()
    return [
        _guild_storage_read(
            g,
            administration,
            member_count=counts.get(g.id, 0),
            has_seat=g.id in seated,
            retention=retention,
        )
        for g, administration in rows
    ]


@router.patch("/guilds/{guild_id}", response_model=PlatformGuildStorageRead)
async def update_platform_guild_storage(
    guild_id: int,
    payload: PlatformGuildStorageUpdate,
    session: SystemSessionDep,
    operator: GuildsManageDep,
) -> PlatformGuildStorageRead:
    """Set a guild's storage/member caps and/or lifecycle status. Operator/owner.

    Writes only shared ``public`` columns — the caps and the sign-in entitlement
    on ``guild_administration``, the lifecycle ``status`` on ``guilds`` — so no
    guild-schema routing is needed. Both are system-engine writes: no
    request-path role holds INSERT/UPDATE on ``guild_administration`` at all.
    ``model_fields_set`` tells an omitted cap (leave untouched) from one sent as
    ``null`` (reset to unlimited). ``status`` (active / read_only / suspended) is
    a moderation action: it downgrades or cuts off member access on the request
    path (see ``_load_guild_context``) but never touches stored data, and PAM /
    break-glass grants override it so operators can't lock themselves out.
    Lowering a cap below current usage just blocks further uploads / new joins.

    Where billing sets plans (``billing_service.billing_managed``), the caps and
    entitlements are refused and the status may only move to one of the row's
    ``status_choices``; the triggers of migration 0364 hold the database to the
    same rule.
    """
    provided = payload.model_fields_set
    managed = billing_service.billing_managed()
    if managed and (
        "max_storage_bytes" in provided
        or "max_users" in provided
        or payload.auth_options is not None
        or payload.banner_image_enabled is not None
        or payload.support_enabled is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildMessages.GUILD_PLAN_SET_BY_BILLING,
        )
    before: dict[str, Any] = {}
    status_before: str | None = None
    status_after: str | None = None
    try:
        before = audit_service.snapshot(
            await guilds_service.get_administration(session, guild_id=guild_id),
            _GUILD_ADMINISTRATION_FIELDS,
        )
        guild = await guilds_service.update_guild(
            session,
            guild_id=guild_id,
            max_storage_bytes=payload.max_storage_bytes,
            max_storage_bytes_provided="max_storage_bytes" in provided,
            max_users=payload.max_users,
            max_users_provided="max_users" in provided,
            auth_options=payload.auth_options,
            banner_image_enabled=payload.banner_image_enabled,
            support_enabled=payload.support_enabled,
        )
        if payload.status is not None and guild.status != payload.status.value:
            recorded = (
                await guilds_service.get_administration(session, guild_id=guild_id)
            ).billing_status
            choices = operator_status_choices(
                GuildStatus(guild.status),
                billing_status=GuildStatus(recorded) if recorded else None,
                billing_managed=managed,
            )
            if payload.status not in choices:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        GuildMessages.GUILD_STATUS_SET_BY_BILLING
                        if managed
                        else GuildMessages.GUILD_STATUS_NOT_SETTABLE
                    ),
                )
            logger.info(
                "guild %s status %s -> %s by user %s",
                guild_id,
                guild.status,
                payload.status.value,
                operator.id,
            )
            status_before, status_after = guild.status, payload.status.value
            guild = await guilds_service.set_guild_status(
                session, guild_id=guild_id, status=payload.status
            )
    except guilds_service.SupportIntakeMissingError as exc:
        # Nowhere to send what the form would collect. The setup this asks for
        # is the operator's own, one page over.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.SUPPORT_INTAKE_NOT_CONFIGURED,
        ) from exc
    except ValueError as exc:
        # update_guild -> get_guild raises ValueError(GUILD_NOT_FOUND) when the row
        # is gone. Letting it own the existence check (rather than a separate
        # pre-SELECT) closes the TOCTOU window where a concurrent delete between
        # the two queries would otherwise surface as an unhandled 500.
        if str(exc) == GuildMessages.GUILD_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=GuildMessages.GUILD_NOT_FOUND,
            ) from exc
        raise
    administration = await guilds_service.get_administration(session, guild_id=guild_id)
    changed = audit_service.changed_fields(
        before, audit_service.snapshot(administration, _GUILD_ADMINISTRATION_FIELDS)
    )
    if changed["changed"]:
        await audit_service.record(
            session,
            event_type=AuditEventType.GUILD_SETTINGS_CHANGED,
            actor_user_id=operator.id,
            guild_id=guild_id,
            target_type="guild",
            target_id=guild_id,
            detail={"area": "administration", **changed},
        )
    if status_after is not None:
        await audit_service.record(
            session,
            event_type=AuditEventType.GUILD_STATUS_CHANGED,
            actor_user_id=operator.id,
            guild_id=guild_id,
            target_type="guild",
            target_id=guild_id,
            detail={"from": status_before, "to": status_after},
        )
    await session.commit()
    if status_after is not None:
        # Billing reads the new status for itself: a suspended community's
        # subscription is paused, and one that comes back is resumed.
        billing_ping.notify_lifecycle_changed(guild_id)
        if status_after == GuildStatus.on_hold.value:
            await guilds_service.announce_on_hold(session, guild_id)
            guild = await guilds_service.get_guild(session, guild_id=guild_id)
    return _guild_storage_read(
        guild,
        administration,
        member_count=await guilds_service.count_members(session, guild_id=guild_id),
        has_seat=await guilds_service.guild_has_seat(session, guild_id=guild.id),
        retention=await guild_purge.retention_days(session),
    )


@router.get("/guilds/{guild_id}/narrowings", response_model=list[GuildNarrowingPending])
async def read_guild_narrowings(
    guild_id: int,
    session: SystemSessionDep,
    operator: GuildsManageDep,
) -> list[GuildNarrowingPending]:
    """What this community says its own arrivals look like, and whether
    anybody has agreed.

    Operator/owner (``guilds.manage``). The community writes these values itself
    and nothing here can tell whether it holds the domain or tenant they name,
    so the answer is the deployment's. Support answers through the case raised
    when they are written; this is the same question where a deployment runs
    no intake, and the place to withdraw an answer either way.
    """
    return await narrowing_review.pending_for_guild(session, guild_id=guild_id)


@router.put(
    "/guilds/{guild_id}/narrowings/{connection_id}",
    response_model=GuildNarrowingPending,
)
async def agree_guild_narrowing(
    guild_id: int,
    connection_id: int,
    payload: GuildNarrowingAgreement,
    session: SystemSessionDep,
    operator: GuildsManageDep,
) -> GuildNarrowingPending:
    """Agree that these values are this community's, or withdraw that.

    Agreeing lets arrivals it counts as its own join on sight where the
    community asked for that. Withdrawing leaves the connection and its values
    as they are; what stops is joining people on arrival.
    """
    return await narrowing_review.agree(
        session,
        guild_id=guild_id,
        connection_id=connection_id,
        agreed=payload.agreed,
        actor_user_id=operator.id,
    )


@router.post("/guilds/{guild_id}/restore", response_model=PlatformGuildStorageRead)
async def restore_platform_guild(
    guild_id: int,
    payload: PlatformGuildRestore,
    session: SystemSessionDep,
    operator: GuildsManageDep,
) -> PlatformGuildStorageRead:
    """Bring a deleted guild back before its retention window runs out.

    Operator/owner (``guilds.manage``). Deleting a guild keeps it — the shared
    rows, the ``guild_<id>`` schema and the stored blobs all stay until
    ``guild_purge`` destroys them — so restoring is a status write plus, where
    the roster was emptied, seating somebody who can run the community again.

    The operator names the status it returns at, and must name a seat when the
    guild holds none. Both are re-checked in the service rather than trusted
    from the payload. What does *not* come back is the guild's app
    connections: those were revoked when it was deleted, and the community's
    superadmin reconnects them.

    Writes only shared ``public`` columns (``guilds.status`` and, for the seat,
    ``guild_memberships``), so no guild-schema routing is needed.
    """
    try:
        guild = await guilds_service.restore_guild(
            session,
            guild_id=guild_id,
            status=payload.status,
            seat_user_id=payload.seat_user_id,
            actor_user_id=operator.id,
        )
    except ValueError as exc:
        code = str(exc)
        if code == GuildMessages.GUILD_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=code
            ) from exc
        if code == GuildMessages.GUILD_NOT_DELETED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=code
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=code
        ) from exc
    logger.info(
        "guild %s restored as %s by user %s", guild_id, guild.status, operator.id
    )
    await session.commit()
    billing_ping.notify_lifecycle_changed(guild_id)
    administration = await guilds_service.get_administration(session, guild_id=guild_id)
    return _guild_storage_read(
        guild,
        administration,
        member_count=await guilds_service.count_members(session, guild_id=guild_id),
        has_seat=await guilds_service.guild_has_seat(session, guild_id=guild_id),
        retention=await guild_purge.retention_days(session),
    )


@router.post(
    "/guilds/{guild_id}/billing/service-handoff",
    response_model=BillingPortalHandoffResponse,
)
async def create_platform_guild_billing_service_handoff(
    guild_id: int,
    session: SystemSessionDep,
    operator: GuildsManageDep,
    console: Literal["support", "operator"] = "support",
    answer: SecondFactorAnswer | None = None,
) -> BillingPortalHandoffResponse:
    """Mint the operator handoff into the billing portal for one guild.

    Backs the Guilds tab's billing buttons. Operator/owner (``guilds.manage``).
    The token names the ``access_grants`` row that authorises the visit: a
    live billing grant is reused, otherwise one is self-issued — after the
    account's second factor, as breaking glass takes it — so the visit is
    recorded on both sides. A billing grant reaches the billing account and
    nothing in the guild; what it may do there is the billing service's to
    decide.
    """
    if not app_config.BILLING_URL:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BillingMessages.PORTAL_NOT_CONFIGURED,
        )

    guild_name = (
        await session.exec(select(Guild.name).where(Guild.id == guild_id))
    ).one_or_none()
    if guild_name is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.GUILD_NOT_FOUND,
        )

    grant = await access_grants_service.get_live_grant(
        session,
        user_id=operator.id,
        guild_id=guild_id,
        purpose=AccessGrantPurpose.billing,
    )
    if grant is None:
        await check_second_factor(
            session,
            actor=operator,
            answer=answer or SecondFactorAnswer(),
            during="billing_handoff",
        )
        try:
            grant = await access_grants_service.break_glass(
                session,
                actor=operator,
                # A visit to the portal, and nothing in the guild.
                level=AccessLevel.read.value,
                payload=BreakGlassCreate(
                    guild_id=guild_id,
                    reason=BILLING_PORTAL_GRANT_REASON,
                ),
                # Belonging to the guild says nothing about billing authority,
                # so a member still breaks glass for it.
                allow_member=True,
                purpose=AccessGrantPurpose.billing,
            )
        except access_grants_service.AccessGrantError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=BillingMessages.PORTAL_GRANT_UNAVAILABLE,
            ) from exc

    try:
        user_ref, guild_ref = await billing_refs(user_id=operator.id, guild_id=guild_id)
        token, expires_in_seconds = create_billing_support_handoff_token(
            grant_id=grant.id,
            user_ref=user_ref,
            guild_ref=guild_ref,
            guild_name=guild_name,
            approver_ref=(
                await billing_user_ref(user_id=grant.approved_by_id)
                if grant.approved_by_id is not None
                else None
            ),
            console=console,
        )
    except BillingSupportHandoffNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=BillingMessages.PORTAL_SIGNING_NOT_CONFIGURED,
        ) from exc

    await session.commit()
    logger.info(
        "billing portal: operator %s (%s) opened guild %s under grant %s",
        operator.id,
        operator.role.value,
        guild_id,
        grant.id,
    )
    return BillingPortalHandoffResponse(
        handoff_token=token,
        expires_in_seconds=expires_in_seconds,
    )

import json
import logging
from typing import Any, Dict, Optional

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.notification import NotificationType
from app.models.platform.push_token import PushToken
from app.services.platform import notification_policy, push_tokens

from app.services.platform import push_config
from app.services.platform.push_config import ResolvedPushConfig

logger = logging.getLogger(__name__)

# FCM API endpoint
FCM_API_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

# OAuth2 scopes required for FCM
FCM_SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]

# Android notification channel a given notification type is delivered on. The
# channel is what the user sees (and can mute) in the OS notification settings,
# so related types share one rather than getting a row each.
#
# These ids must exist in the installed app — see NotificationChannelManager in
# frontend/android, which registers exactly this set. A type absent here (the
# in-app-only ones, which never push) falls back to the general channel; adding
# a NEW channel id means a native release, so prefer an existing one.
DEFAULT_CHANNEL = "default"
PUSH_CHANNELS: dict[NotificationType, str] = {
    NotificationType.task_assignment: "task_assignment",
    NotificationType.overdue_tasks: "overdue_tasks",
    NotificationType.initiative_added: "initiative_added",
    # Join requests are initiative-membership news, so they ride the channel the
    # installed app already registers for it rather than asking for a new one
    # (a new channel id would mean a native release).
    NotificationType.initiative_join_requested: "initiative_added",
    NotificationType.initiative_join_approved: "initiative_added",
    NotificationType.initiative_join_denied: "initiative_added",
    NotificationType.project_added: "project_added",
    NotificationType.user_pending_approval: "user_pending_approval",
    NotificationType.mention: "mention",
    NotificationType.comment_on_task: "comments",
    NotificationType.comment_on_resource: "comments",
    NotificationType.comment_reply: "comments",
    NotificationType.direct_message: "messages",
    # Somebody asking to reach you, and the answer when you asked. Messaging
    # news, so it rides the channel the installed app already registers for
    # messages rather than asking for a new one — same reasoning as the join
    # requests above: a new channel id would mean a native release.
    NotificationType.message_request_received: "messages",
    NotificationType.message_request_accepted: "messages",
    NotificationType.connection_requested: "messages",
    NotificationType.connection_accepted: "messages",
    # Its own channel rather than one of the above. A post is a category of
    # its own — nothing already here describes it, and filing it under
    # initiative news would mean muting one to mute the other. A channel is
    # what the Android app offers a user to mute, so this is what it costs.
    NotificationType.post_published: "posts",
    # A reaction is comment news, so it rides the channel the installed app
    # already registers for comments — same reasoning as the join requests
    # above: a new channel id would mean a native release.
    NotificationType.comment_reaction: "comments",
    NotificationType.event_invitation: "calendar_events",
    NotificationType.event_updated: "calendar_events",
    NotificationType.event_cancelled: "calendar_events",
    NotificationType.event_rsvp: "calendar_events",
    NotificationType.event_reminder: "event_reminder",
    NotificationType.access_grant_requested: "access_grants",
    NotificationType.access_grant_approved: "access_grants",
    NotificationType.access_grant_denied: "access_grants",
    NotificationType.access_grant_revoked: "access_grants",
}


def channel_for(notification_type: Optional[NotificationType]) -> str:
    """Android channel id for a notification type."""
    if notification_type is None:
        return DEFAULT_CHANNEL
    return PUSH_CHANNELS.get(notification_type, DEFAULT_CHANNEL)


def _get_fcm_access_token(cfg: ResolvedPushConfig) -> Optional[str]:
    """Get OAuth2 access token from service account credentials.

    Returns None if FCM is not configured or credentials are invalid.

    ``cfg`` is passed in rather than read here: the credential lives on
    ``app_setting_secrets``, which only the system engine may read, so it is
    resolved by ``push_config`` on a session of its own before this
    synchronous call.
    """
    if not cfg.enabled or not cfg.service_account_json:
        return None

    try:
        # Parse service account JSON
        service_account_info = json.loads(cfg.service_account_json)

        # Create credentials
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=FCM_SCOPES,
        )

        # Refresh to get access token
        credentials.refresh(Request())

        return credentials.token
    except Exception as exc:
        logger.error(f"Failed to get FCM access token: {exc}", exc_info=True)
        return None


async def _send_to_fcm(
    token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    channel_id: Optional[str] = None,
) -> tuple[bool, bool]:
    """Send a push notification via FCM HTTP v1 API.

    Args:
        token: FCM registration token
        title: Notification title
        body: Notification body
        data: Optional data payload (must be string key-value pairs)
        channel_id: Android notification channel to deliver on

    Returns:
        Tuple of (success, should_delete_token):
        - success: True if notification was sent successfully
        - should_delete_token: True if token is invalid and should be deleted

    Error handling:
        - 404/410: Token invalid, should be deleted from database
        - 401: Credentials issue, logged as error
        - 5xx: Server error, logged as warning
        - Network errors: Logged as warning
    """
    cfg = await push_config.ensure_push_config_fresh()
    if not cfg.enabled or not cfg.project_id:
        logger.warning("FCM not enabled, skipping push notification")
        return (False, False)

    access_token = _get_fcm_access_token(cfg)
    if not access_token:
        logger.error("Failed to get FCM access token")
        return (False, False)

    # Build FCM message
    fcm_message: dict[str, Any] = {
        "token": token,
        "notification": {
            "title": title,
            "body": body,
        },
    }
    message = {"message": fcm_message}

    # Add Android-specific configuration for notification channels
    if channel_id:
        fcm_message["android"] = {
            "notification": {
                "channel_id": channel_id,
            }
        }

    # Add data payload if provided (convert all values to strings)
    if data:
        fcm_message["data"] = {k: str(v) for k, v in data.items()}

    # Send to FCM
    url = FCM_API_URL.format(project_id=cfg.project_id)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, json=message, headers=headers, timeout=10.0
            )

            if response.status_code == 200:
                logger.info(
                    f"Push notification sent successfully to token: {token[:20]}..."
                )
                return (True, False)
            elif response.status_code in (404, 410):
                # Token invalid or unregistered - should be deleted
                logger.warning(
                    f"FCM token invalid (status {response.status_code}): {token[:20]}..."
                )
                return (False, True)
            elif response.status_code == 401:
                # Credentials issue - don't delete token
                logger.error(
                    f"FCM authentication failed (status {response.status_code}): {response.text}"
                )
                return (False, False)
            else:
                # Other error - don't delete token (might be temporary)
                logger.error(
                    f"FCM request failed (status {response.status_code}): {response.text}"
                )
                return (False, False)

    except httpx.TimeoutException:
        logger.warning(f"FCM request timed out for token: {token[:20]}...")
        return (False, False)
    except Exception as exc:
        logger.error(f"Failed to send FCM notification: {exc}", exc_info=True)
        return (False, False)


async def send_push_notification(
    push_token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    platform: str = "android",
    channel_id: Optional[str] = None,
) -> tuple[bool, bool]:
    """Send a push notification to a single device.

    Args:
        push_token: FCM registration token
        title: Notification title
        body: Notification body
        data: Optional data payload
        platform: Platform identifier ('android' or 'ios')
        channel_id: Android notification channel to deliver on

    Returns:
        Tuple of (success, should_delete_token):
        - success: True if notification was sent successfully
        - should_delete_token: True if token is invalid and should be deleted
    """
    return await _send_to_fcm(push_token, title, body, data, channel_id)


async def _recipient_locale(user_id: int) -> str:
    """The language one recipient reads, read on the system engine.

    Only asked for when a redacted line has to be written and the caller had no
    locale in hand; the recipient's account is not the sending session's to
    read, the same way their notification settings are not.
    """
    from app.db.session import AdminSessionLocal
    from app.models.platform.user import User

    async with AdminSessionLocal() as admin_session:
        user = await admin_session.get(User, user_id)
        return (getattr(user, "locale", None) if user else None) or "en"


async def _recipient_tokens(user_id: int) -> list[PushToken]:
    """One recipient's registered devices, read on the system engine.

    The rows are the recipient's rather than the sending session's to read,
    the same way their account and notification settings are.
    """
    from app.db.session import AdminSessionLocal

    async with AdminSessionLocal() as admin_session:
        return await push_tokens.get_push_tokens_for_user(
            admin_session, user_id=user_id
        )


async def _record_delivery(
    user_id: int, *, delivered_ids: list[int], dead_tokens: list[str]
) -> None:
    """Write what a delivery learned back on the system engine, in one commit."""
    if not delivered_ids and not dead_tokens:
        return
    from app.db.session import AdminSessionLocal

    async with AdminSessionLocal() as admin_session:
        await push_tokens.record_delivery(
            admin_session,
            user_id=user_id,
            delivered_ids=delivered_ids,
            dead_tokens=dead_tokens,
        )
        await admin_session.commit()


async def send_push_to_user(
    session: AsyncSession,
    user_id: int,
    notification_type: NotificationType,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    only_device_token_ids: Optional[set[int]] = None,
    guild_id: Optional[int] = None,
    locale: Optional[str] = None,
    policy: Optional["notification_policy.NotificationPolicy"] = None,
) -> int:
    """Send push notification to all of a user's devices.

    Every push in the app leaves through here, which is where the deployment's
    and the community's answers about what may reach a phone are applied: one
    of them declining sends nothing, and either of them asking for a redacted
    notification replaces the wording with the kind of thing that happened.

    The recipient's device rows are read and written on the system engine
    rather than on ``session``, which is the caller's and often routed into a
    community; ``session`` is kept for the callers that pass it.

    Args:
        session: The caller's session (not used for the device rows)
        user_id: User ID
        notification_type: Type of notification (for logging/analytics)
        title: Notification title
        body: Notification body
        data: Optional data payload
        only_device_token_ids: Restrict delivery to these installations. Used by
            categories that only make sense on a device set up for them.
        guild_id: The community this notification belongs to, whose own answer
            applies alongside the deployment's. ``None`` for a notification that
            belongs to no community — a message, a connection, an account
            notice — which the deployment alone answers for.
        locale: The recipient's language, for a redacted line. Read from their
            account when a redacted line is needed and this was not given.
        policy: An answer the caller already resolved, for a fan-out that would
            otherwise ask once per recipient.

    Returns:
        Number of successful deliveries
    """
    if not (await push_config.ensure_push_config_fresh()).enabled:
        return 0

    tokens = await _recipient_tokens(user_id)
    if only_device_token_ids is not None:
        tokens = [
            token for token in tokens if token.device_token_id in only_device_token_ids
        ]

    if not tokens:
        logger.debug(f"No push tokens found for user {user_id}")
        return 0

    if policy is None:
        policy = await notification_policy.load(guild_id)
    if not policy.push:
        return 0
    if policy.redact:
        title, body = notification_policy.redacted_push(
            notification_type, locale or await _recipient_locale(user_id)
        )

    successful = 0
    delivered_ids: list[int] = []
    tokens_to_delete: list[str] = []

    channel_id = channel_for(notification_type)

    for token_record in tokens:
        success, should_delete = await send_push_notification(
            push_token=token_record.push_token,
            title=title,
            body=body,
            data=data,
            platform=token_record.platform,
            channel_id=channel_id,
        )

        if success:
            successful += 1
            if token_record.id is not None:
                delivered_ids.append(token_record.id)
        elif should_delete:
            # Token is invalid (404/410 from FCM), mark for deletion
            logger.info(
                f"Deleting invalid push token: {token_record.push_token[:20]}..."
            )
            tokens_to_delete.append(token_record.push_token)

    await _record_delivery(
        user_id, delivered_ids=delivered_ids, dead_tokens=tokens_to_delete
    )

    logger.info(
        f"Sent push notification to {successful}/{len(tokens)} devices "
        f"for user {user_id} (type: {notification_type})"
    )

    return successful

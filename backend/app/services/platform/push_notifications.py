import asyncio
import json
import logging
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, AsyncContextManager, Dict, Optional, Sequence

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


#: The service-account credential and the JSON it was built from. Google
#: access tokens last an hour, so one credential serves every push until it
#: nears expiry or the configured account changes.
_credentials: tuple[str, service_account.Credentials] | None = None
#: One refresh at a time; deliveries that queued behind it reuse its token.
_refresh_lock = asyncio.Lock()


async def _get_fcm_access_token(cfg: ResolvedPushConfig) -> Optional[str]:
    """An OAuth2 access token for the configured service account.

    Returns None if FCM is not configured or credentials are invalid.

    ``cfg`` is passed in rather than read here: the credential lives on
    ``app_setting_secrets``, which only the system engine may read, so it is
    resolved by ``push_config`` on a session of its own. The token is reused
    while it is valid; a refresh is a blocking HTTP call, so it runs on a
    worker thread.
    """
    global _credentials
    if not cfg.enabled or not cfg.service_account_json:
        return None

    try:
        if _credentials is None or _credentials[0] != cfg.service_account_json:
            _credentials = (
                cfg.service_account_json,
                service_account.Credentials.from_service_account_info(
                    json.loads(cfg.service_account_json), scopes=FCM_SCOPES
                ),
            )
        credentials = _credentials[1]
        if not credentials.valid:
            async with _refresh_lock:
                if not credentials.valid:
                    await asyncio.to_thread(credentials.refresh, Request())
        return credentials.token
    except Exception as exc:
        logger.error(f"Failed to get FCM access token: {exc}", exc_info=True)
        return None


async def send_push_notification(
    client: httpx.AsyncClient,
    *,
    push_token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    channel_id: Optional[str] = None,
) -> tuple[bool, bool]:
    """Send a push notification to one device via the FCM HTTP v1 API.

    Args:
        client: The HTTP client the whole fan-out shares
        push_token: FCM registration token
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

    access_token = await _get_fcm_access_token(cfg)
    if not access_token:
        logger.error("Failed to get FCM access token")
        return (False, False)

    # Build FCM message
    fcm_message: dict[str, Any] = {
        "token": push_token,
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

    url = FCM_API_URL.format(project_id=cfg.project_id)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        response = await client.post(url, json=message, headers=headers)

        if response.status_code == 200:
            logger.info(
                f"Push notification sent successfully to token: {push_token[:20]}..."
            )
            return (True, False)
        elif response.status_code in (404, 410):
            # Token invalid or unregistered - should be deleted
            logger.warning(
                f"FCM token invalid (status {response.status_code}): {push_token[:20]}..."
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
        logger.warning(f"FCM request timed out for token: {push_token[:20]}...")
        return (False, False)
    except Exception as exc:
        logger.error(f"Failed to send FCM notification: {exc}", exc_info=True)
        return (False, False)


async def _recipient_locale(user_id: int) -> str:
    """The language one recipient reads, read on the system engine.

    Only asked for when a redacted line has to be written and the caller had no
    locale in hand; the recipient's account is not the sending session's to
    read, the same way their notification settings are not.
    """
    from app.db.session import SystemSessionLocal
    from app.models.platform.user import User

    async with SystemSessionLocal() as system_session:
        user = await system_session.get(User, user_id)
        return (getattr(user, "locale", None) if user else None) or "en"


async def _recipient_tokens(user_id: int) -> list[PushToken]:
    """One recipient's devices whose sign-in still stands, read on the system
    engine.

    The rows are the recipient's rather than the sending session's to read,
    the same way their account and notification settings are.
    """
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as system_session:
        tokens = await push_tokens.live_for_user(system_session, user_id=user_id)
        await system_session.commit()
        return tokens


async def _record_delivery(
    user_id: int, *, delivered_ids: list[int], dead_tokens: list[str]
) -> None:
    """Write what a delivery learned back on the system engine, in one commit."""
    if not delivered_ids and not dead_tokens:
        return
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as system_session:
        await push_tokens.record_delivery(
            system_session,
            user_id=user_id,
            delivered_ids=delivered_ids,
            dead_tokens=dead_tokens,
        )
        await system_session.commit()


async def send_push_to_user(
    session: AsyncSession,
    user_id: int,
    notification_type: NotificationType,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    only_session_ids: Optional[set[uuid.UUID]] = None,
    guild_id: Optional[int] = None,
    locale: Optional[str] = None,
) -> int:
    """Send push notification to all of a user's devices.

    Every push in the app leaves through here, which is where the deployment's
    and the community's answers about what may reach a phone are applied: one
    of them declining sends nothing, and either of them asking for a redacted
    notification replaces the wording with the kind of thing that happened.

    The recipient's device rows are read and written on the system engine
    rather than on ``session``, which is the caller's and often routed into a
    community; ``session`` carries the resolved answers, so a fan-out on it
    reads them once per transaction.

    Args:
        session: The caller's session (not used for the device rows)
        user_id: User ID
        notification_type: Type of notification (for logging/analytics)
        title: Notification title
        body: Notification body
        data: Optional data payload
        only_session_ids: Restrict delivery to the devices these sign-ins
            registered. Used by categories that only make sense on a device set
            up for them.
        guild_id: The community this notification belongs to, whose own answer
            applies alongside the deployment's. ``None`` for a notification that
            belongs to no community — a message, a connection, an account
            notice — which the deployment alone answers for.
        locale: The recipient's language, for a redacted line. Read from their
            account when a redacted line is needed and this was not given.

    Returns:
        Number of successful deliveries
    """
    if not (await push_config.ensure_push_config_fresh()).enabled:
        return 0

    tokens = await _recipient_tokens(user_id)
    if only_session_ids is not None:
        tokens = [token for token in tokens if token.session_id in only_session_ids]

    if not tokens:
        logger.debug(f"No push tokens found for user {user_id}")
        return 0

    policy = await notification_policy.for_send(session, guild_id)
    if not policy.push:
        return 0
    if policy.redact:
        title, body = notification_policy.redacted_push(
            notification_type, locale or await _recipient_locale(user_id)
        )

    async with httpx.AsyncClient(timeout=10.0) as client:
        outcome = await _send_to_devices(
            client,
            tokens,
            title=title,
            body=body,
            data=data,
            channel_id=channel_for(notification_type),
        )

    await _record_delivery(
        user_id, delivered_ids=outcome.delivered_ids, dead_tokens=outcome.dead_tokens
    )

    logger.info(
        f"Sent push notification to {len(outcome.delivered_ids)}/{len(tokens)} "
        f"devices for user {user_id} (type: {notification_type})"
    )

    return len(outcome.delivered_ids)


@dataclass
class _Outcome:
    """What sending one push to one person's devices came to."""

    delivered_ids: list[int]
    dead_tokens: list[str]
    #: No device took it, and at least one send failed short of an answer —
    #: a timeout or a server error — so trying again later could still land.
    retry: bool


async def _send_to_devices(
    client: httpx.AsyncClient,
    tokens: Sequence[PushToken],
    *,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]],
    channel_id: str,
    gate: AsyncContextManager[Any] | None = None,
) -> _Outcome:
    """Send one push to each of these devices. ``gate`` bounds how many sends
    are in flight across a batch."""

    async def one(token: PushToken) -> tuple[bool, bool]:
        async with gate or nullcontext():
            return await send_push_notification(
                client,
                push_token=token.push_token,
                title=title,
                body=body,
                data=data,
                channel_id=channel_id,
            )

    results = await asyncio.gather(*(one(token) for token in tokens))
    outcome = _Outcome(delivered_ids=[], dead_tokens=[], retry=False)
    for token, (success, should_delete) in zip(tokens, results):
        if success:
            if token.id is not None:
                outcome.delivered_ids.append(token.id)
        elif should_delete:
            # Token is invalid (404/410 from FCM), mark for deletion
            logger.info(f"Deleting invalid push token: {token.push_token[:20]}...")
            outcome.dead_tokens.append(token.push_token)
        else:
            outcome.retry = True
    outcome.retry = outcome.retry and not outcome.delivered_ids
    return outcome


@dataclass(frozen=True)
class Push:
    """One push for one person, already worded and already allowed."""

    user_id: int
    notification_type: NotificationType
    title: str
    body: str
    data: Dict[str, Any]


#: How many FCM calls one batch keeps in flight at once.
CONCURRENT_SENDS = 16


async def send_pushes(session: AsyncSession, pushes: Sequence[Push]) -> list[bool]:
    """Send a batch of pushes at once, on the system engine's ``session``.

    For the notice worker, which has already applied the deployment's and the
    community's switches and each recipient's settings: this only finds each
    person's devices, sends, and records what FCM said. One HTTP client serves
    the batch and :data:`CONCURRENT_SENDS` calls are in flight at a time.

    Returns, for each push in order, whether it should be tried again: no device
    took it, and a send failed short of an answer. Does not commit.
    """
    if not pushes or not (await push_config.ensure_push_config_fresh()).enabled:
        return [False] * len(pushes)
    # One session, so the reads go one after another; the sends do not. Each
    # recipient's read and write is a savepoint of its own, so one that fails
    # costs that recipient's pushes alone.
    devices: dict[int, list[PushToken] | None] = {}
    for user_id in dict.fromkeys(push.user_id for push in pushes):
        try:
            async with session.begin_nested():
                devices[user_id] = await push_tokens.live_for_user(
                    session, user_id=user_id
                )
        except Exception:
            logger.exception("Could not read the devices of user %s", user_id)
            devices[user_id] = None
    gate = asyncio.Semaphore(CONCURRENT_SENDS)
    async with httpx.AsyncClient(timeout=10.0) as client:
        outcomes = await asyncio.gather(
            *(
                _send_to_devices(
                    client,
                    devices[push.user_id] or [],
                    title=push.title,
                    body=push.body,
                    data=push.data,
                    channel_id=channel_for(push.notification_type),
                    gate=gate,
                )
                for push in pushes
            )
        )
    for push, outcome in zip(pushes, outcomes):
        try:
            async with session.begin_nested():
                await push_tokens.record_delivery(
                    session,
                    user_id=push.user_id,
                    delivered_ids=outcome.delivered_ids,
                    dead_tokens=outcome.dead_tokens,
                )
        except Exception:
            # What was sent stays sent; only the bookkeeping is lost.
            logger.exception("Could not record a push for user %s", push.user_id)
    # A recipient whose devices could not be read was sent nothing.
    return [
        outcome.retry or devices[push.user_id] is None
        for push, outcome in zip(pushes, outcomes)
    ]

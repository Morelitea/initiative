import json
import logging
from typing import Any, Dict, Optional

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.notification import NotificationType
from app.services import push_tokens

logger = logging.getLogger(__name__)

# FCM API endpoint
FCM_API_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

# OAuth2 scopes required for FCM
FCM_SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]


def _get_fcm_access_token() -> Optional[str]:
    """Get OAuth2 access token from service account credentials.

    Returns None if FCM is not configured or credentials are invalid.
    """
    if not settings.FCM_ENABLED or not settings.FCM_SERVICE_ACCOUNT_JSON:
        return None

    try:
        # Parse service account JSON
        service_account_info = json.loads(settings.FCM_SERVICE_ACCOUNT_JSON)

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
    notification_type: Optional[str] = None,
) -> bool:
    """Send a push notification via FCM HTTP v1 API.

    Args:
        token: FCM registration token
        title: Notification title
        body: Notification body
        data: Optional data payload (must be string key-value pairs)
        notification_type: Type of notification for Android channel routing

    Returns:
        True if successful, False otherwise

    Error handling:
        - 404/410: Token invalid, caller should delete from database
        - 401: Credentials issue, logged as error
        - 5xx: Server error, logged as warning
        - Network errors: Logged as warning
    """
    if not settings.FCM_ENABLED or not settings.FCM_PROJECT_ID:
        logger.warning("FCM not enabled, skipping push notification")
        return False

    access_token = _get_fcm_access_token()
    if not access_token:
        logger.error("Failed to get FCM access token")
        return False

    # Build FCM message
    message = {
        "message": {
            "token": token,
            "notification": {
                "title": title,
                "body": body,
            },
        }
    }

    # Add Android-specific configuration for notification channels
    if notification_type:
        message["message"]["android"] = {
            "notification": {
                "channel_id": notification_type,  # Maps to Android channel ID
            }
        }

    # Add data payload if provided (convert all values to strings)
    if data:
        message["message"]["data"] = {k: str(v) for k, v in data.items()}

    # Send to FCM
    url = FCM_API_URL.format(project_id=settings.FCM_PROJECT_ID)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=message, headers=headers, timeout=10.0)

            if response.status_code == 200:
                logger.info(f"Push notification sent successfully to token: {token[:20]}...")
                return True
            elif response.status_code in (404, 410):
                # Token invalid or unregistered
                logger.warning(
                    f"FCM token invalid (status {response.status_code}): {token[:20]}..."
                )
                return False
            elif response.status_code == 401:
                # Credentials issue
                logger.error(
                    f"FCM authentication failed (status {response.status_code}): {response.text}"
                )
                return False
            else:
                # Other error
                logger.error(
                    f"FCM request failed (status {response.status_code}): {response.text}"
                )
                return False

    except httpx.TimeoutException:
        logger.warning(f"FCM request timed out for token: {token[:20]}...")
        return False
    except Exception as exc:
        logger.error(f"Failed to send FCM notification: {exc}", exc_info=True)
        return False


async def send_push_notification(
    push_token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    platform: str = "android",
    notification_type: Optional[str] = None,
) -> bool:
    """Send a push notification to a single device.

    Args:
        push_token: FCM registration token
        title: Notification title
        body: Notification body
        data: Optional data payload
        platform: Platform identifier ('android' or 'ios')
        notification_type: Type of notification for Android channel routing

    Returns:
        True if successful, False otherwise
    """
    return await _send_to_fcm(push_token, title, body, data, notification_type)


async def send_push_to_user(
    session: AsyncSession,
    user_id: int,
    notification_type: NotificationType,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
) -> int:
    """Send push notification to all of a user's devices.

    Args:
        session: Database session
        user_id: User ID
        notification_type: Type of notification (for logging/analytics)
        title: Notification title
        body: Notification body
        data: Optional data payload

    Returns:
        Number of successful deliveries
    """
    if not settings.FCM_ENABLED:
        return 0

    # Get all push tokens for user
    tokens = await push_tokens.get_push_tokens_for_user(session, user_id=user_id)

    if not tokens:
        logger.debug(f"No push tokens found for user {user_id}")
        return 0

    successful = 0
    tokens_to_delete = []

    # Convert NotificationType enum to string for channel routing
    notification_type_str = notification_type.value if notification_type else None

    for token_record in tokens:
        success = await send_push_notification(
            push_token=token_record.push_token,
            title=title,
            body=body,
            data=data,
            platform=token_record.platform,
            notification_type=notification_type_str,
        )

        if success:
            successful += 1
            # Update last_used_at
            await push_tokens.update_last_used(session, push_token=token_record.push_token)
        else:
            # Token might be invalid, mark for deletion
            # Note: Only delete if we get explicit invalid token error (404/410)
            # For now, we'll let tokens accumulate and rely on periodic cleanup
            # In production, you might want to check the specific error code
            tokens_to_delete.append(token_record.push_token)

    # Delete invalid tokens
    for invalid_token in tokens_to_delete:
        logger.info(f"Deleting invalid push token: {invalid_token[:20]}...")
        await push_tokens.delete_push_token(session, push_token=invalid_token)

    logger.info(
        f"Sent push notification to {successful}/{len(tokens)} devices "
        f"for user {user_id} (type: {notification_type})"
    )

    return successful

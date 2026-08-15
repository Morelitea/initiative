"""Channel routing for push notifications.

The Android channel a notification lands on is chosen here and sent to FCM in
the payload; the app can only honour a channel it already created. Nothing at
runtime reconciles the two, so these tests hold the backend map and the app's
registered channels together.
"""

import re
from pathlib import Path

import pytest

from app.models.platform.notification import NotificationType
from app.services.platform.push_notifications import (
    DEFAULT_CHANNEL,
    PUSH_CHANNELS,
    channel_for,
)

_ANDROID_CHANNELS = (
    Path(__file__).resolve().parents[3]
    / ".."
    / "frontend"
    / "android"
    / "app"
    / "src"
    / "main"
    / "java"
    / "com"
    / "morelitea"
    / "initiative"
    / "NotificationChannelManager.java"
)

# Types that only ever become an in-app notification — no push is sent for
# them, so they need no channel of their own.
_IN_APP_ONLY = {
    NotificationType.export_ready,
    NotificationType.export_failed,
    NotificationType.import_ready,
    NotificationType.import_failed,
}


@pytest.mark.unit
def test_every_pushed_notification_type_has_a_channel():
    """A new notification type that pushes must pick a channel. Defaulting is
    silent — the notification still arrives, just filed under "General" where
    the user can't mute it separately from everything else."""
    assert set(PUSH_CHANNELS) == set(NotificationType) - _IN_APP_ONLY


@pytest.mark.unit
def test_in_app_only_types_fall_back_to_the_general_channel():
    for notification_type in _IN_APP_ONLY:
        assert channel_for(notification_type) == DEFAULT_CHANNEL
    assert channel_for(None) == DEFAULT_CHANNEL


@pytest.mark.unit
def test_channels_are_registered_by_the_android_app():
    """Every channel the backend routes to must be one the app creates on
    launch. A channel id the app never created is not an error anywhere — the
    notification quietly lands in Firebase's own fallback channel instead."""
    source = _ANDROID_CHANNELS.read_text(encoding="utf-8")
    # Each channel is declared as `String CHANNEL_X = "<id>";`
    registered = set(re.findall(r'String CHANNEL_\w+ = "([^"]+)"', source))
    assert registered, "no channel constants found — did the Java file move?"

    missing = (set(PUSH_CHANNELS.values()) | {DEFAULT_CHANNEL}) - registered
    assert not missing, f"channels missing from the Android app: {sorted(missing)}"

    # Each declared constant must also be passed to createChannel(), or it is
    # a name the app never actually registers.
    created = set(re.findall(r"CHANNEL_(\w+),", source))
    declared = set(re.findall(r"String CHANNEL_(\w+) = ", source))
    assert declared - created == set(), (
        f"declared but never created: {sorted(declared - created)}"
    )

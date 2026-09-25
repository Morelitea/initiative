"""Channel routing for push notifications.

The Android channel a notification lands on is chosen here and sent to FCM in
the payload; the app can only honour a channel it already created. Nothing at
runtime reconciles the two, so these tests hold the backend map and the app's
registered channels together.
"""

import re
from pathlib import Path

from sqlalchemy import text
from sqlmodel import select

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
    # Sent when a moderator takes a profile picture down. It belongs in the
    # inbox, where it can be read next to the settings page that acts on it,
    # rather than as an interruption on a device.
    NotificationType.avatar_removed,
    # The other three moderation notices, for the same reason: they belong in
    # the inbox next to the settings page they are about, and none of them is
    # urgent enough to interrupt someone on a device.
    NotificationType.username_changed,
    NotificationType.account_suspended,
    NotificationType.account_unsuspended,
    # A community put on hold: an inbox notice beside its email, about paying
    # for it, which is no reason to interrupt someone on a device.
    NotificationType.guild_on_hold,
    # An app asking a member to consent: answered on the app's settings, where
    # it waits until they get to it.
    NotificationType.app_consent_requested,
    # A version of an installed app waiting for the seat: it waits on the
    # settings page until they get to it, so nothing is gained by interrupting
    # them on a device.
    NotificationType.app_update_pending,
}


def test_every_pushed_notification_type_has_a_channel():
    """A new notification type that pushes must pick a channel. Defaulting is
    silent — the notification still arrives, just filed under "General" where
    the user can't mute it separately from everything else."""
    assert set(PUSH_CHANNELS) == set(NotificationType) - _IN_APP_ONLY


def test_in_app_only_types_fall_back_to_the_general_channel():
    for notification_type in _IN_APP_ONLY:
        assert channel_for(notification_type) == DEFAULT_CHANNEL
    assert channel_for(None) == DEFAULT_CHANNEL


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


def test_the_manifest_falls_back_to_a_channel_the_app_creates():
    """The web bundle updates over the air; channels ship with the APK.

    So a server that has moved on can address a channel an installed build has
    never registered. Firebase then uses the manifest's fallback — and if that
    names nothing real either, it invents a "Miscellaneous" channel outside the
    app's own notification settings, where nothing the user has muted applies.
    """
    manifest = (
        _ANDROID_CHANNELS.parent.parent.parent.parent.parent / "AndroidManifest.xml"
    )
    source = manifest.read_text(encoding="utf-8")
    declared = re.search(
        r'android:name="com\.google\.firebase\.messaging\.default_notification_channel_id"\s*'
        r'android:value="([^"]+)"',
        source,
    )
    assert declared, "no Firebase fallback channel declared in the manifest"

    registered = set(
        re.findall(
            r'String CHANNEL_\w+ = "([^"]+)"',
            _ANDROID_CHANNELS.read_text(encoding="utf-8"),
        )
    )
    assert declared.group(1) in registered, (
        f"manifest falls back to {declared.group(1)!r}, which the app never creates"
    )


# --- the recipient's devices ---------------------------------------------------


async def _as_guild_floor(session) -> None:
    await session.exec(text("SELECT set_config('role', 'app_guild_base', false)"))


async def _reset_role(session) -> None:
    await session.exec(text("SELECT set_config('role', 'none', false)"))


async def test_delivery_reads_stamps_and_prunes_on_the_system_engine(
    session, monkeypatch
):
    """The caller's session holds nothing on ``push_tokens`` here, as a
    community-routed one does not: the recipient's rows are read, the delivered
    one stamped and the dead one dropped all the same. The same value
    registered by another account is left alone."""
    from app.models.platform.push_token import PushToken
    from app.services.platform import push_notifications, push_tokens
    from app.testing import create_user

    # FCM's switch moved onto the settings row in 0368, so the gate is the
    # resolved config rather than the env var. Patched here instead of seeded
    # through the cache so this test still asserts only what it is about --
    # which session the device rows are read on.
    from app.services.platform import push_config

    async def _enabled():
        return push_config.ResolvedPushConfig(
            enabled=True,
            project_id="test-project",
            application_id=None,
            api_key=None,
            sender_id=None,
            service_account_json=None,
        )

    monkeypatch.setattr(push_config, "ensure_push_config_fresh", _enabled)

    async def _send(
        push_token, title, body, data=None, platform="android", channel_id=None
    ):
        return (True, False) if push_token == "live" else (False, True)

    monkeypatch.setattr(push_notifications, "send_push_notification", _send)

    recipient = await create_user(session)
    bystander = await create_user(session)
    for user, value in ((recipient, "live"), (recipient, "gone"), (bystander, "gone")):
        await push_tokens.register_push_token(
            session, user_id=user.id, push_token=value, platform="android"
        )
    recipient_id, bystander_id = recipient.id, bystander.id

    await _as_guild_floor(session)
    try:
        sent = await push_notifications.send_push_to_user(
            session=session,
            user_id=recipient_id,
            notification_type=NotificationType.mention,
            title="t",
            body="b",
            locale="en",
        )
    finally:
        await _reset_role(session)
    assert sent == 1

    session.expire_all()
    rows = (
        await session.exec(
            select(PushToken).where(PushToken.user_id.in_([recipient_id, bystander_id]))
        )
    ).all()
    held = {(row.user_id, row.push_token): row for row in rows}
    assert set(held) == {(recipient_id, "live"), (bystander_id, "gone")}
    assert held[(recipient_id, "live")].last_used_at is not None
    assert held[(bystander_id, "gone")].last_used_at is None

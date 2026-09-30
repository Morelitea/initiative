"""Channel routing for push notifications.

The Android channel a notification lands on is chosen here and sent to FCM in
the payload; the app can only honour a channel it already created. Nothing at
runtime reconciles the two, so these tests hold the backend map and the app's
registered channels together.
"""

import re
from pathlib import Path

import pytest
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


@pytest.mark.always
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


@pytest.mark.always
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
    one stamped and the dead one dropped all the same. A device whose session
    has ended is not sent to and is dropped too. The same value registered by
    another account is left alone."""
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

    async def _send(client, push_token, title, body, data=None, channel_id=None):
        return (
            (True, False) if push_token in ("live", "unlinked-new") else (False, True)
        )

    monkeypatch.setattr(push_notifications, "send_push_notification", _send)

    from app.services.auth import sessions as session_service

    recipient = await create_user(session)
    bystander = await create_user(session)
    signed_in, signed_out, elsewhere = [
        (
            await session_service.create_session(
                session, user_id=user.id, amr=["pwd"], satisfied_providers=[]
            )
        ).session.id
        for user in (recipient, recipient, bystander)
    ]
    await session_service.revoke_session(session, session_id=signed_out)
    for user, value, sid in (
        (recipient, "live", signed_in),
        (recipient, "gone", signed_in),
        (recipient, "signed-out", signed_out),
        (recipient, "unlinked-new", None),
        (recipient, "unlinked-old", None),
        (bystander, "gone", elsewhere),
    ):
        await push_tokens.register_push_token(
            session,
            user_id=user.id,
            push_token=value,
            platform="android",
            session_id=sid,
        )
    recipient_id, bystander_id = recipient.id, bystander.id
    # Registered before rows named their sign-in: sent to for a grace period
    # after it was last registered.
    await session.exec(
        text(
            "UPDATE push_tokens SET updated_at = now() - interval '8 days' "
            "WHERE push_token = 'unlinked-old'"
        )
    )
    await session.commit()

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
    assert sent == 2

    session.expire_all()
    rows = (
        await session.exec(
            select(PushToken).where(PushToken.user_id.in_([recipient_id, bystander_id]))
        )
    ).all()
    held = {(row.user_id, row.push_token): row for row in rows}
    assert set(held) == {
        (recipient_id, "live"),
        (recipient_id, "unlinked-new"),
        (bystander_id, "gone"),
    }
    assert held[(recipient_id, "live")].last_used_at is not None
    assert held[(bystander_id, "gone")].last_used_at is None


async def test_access_token_is_reused_until_it_lapses(monkeypatch):
    """One credential per service account: refreshed when it is not valid,
    reused while it is, and rebuilt when the configured account changes."""
    from app.services.platform import push_config, push_notifications

    built: list[dict] = []
    made: list["_Credentials"] = []

    class _Credentials:
        def __init__(self, info):
            built.append(info)
            made.append(self)
            self.valid = False
            self.token = None
            self.refreshes = 0

        def refresh(self, _request):
            self.refreshes += 1
            self.valid = True
            self.token = f"token-{len(built)}"

    monkeypatch.setattr(
        push_notifications.service_account.Credentials,
        "from_service_account_info",
        lambda info, scopes: _Credentials(info),
    )
    monkeypatch.setattr(push_notifications, "_credentials", None)

    def _cfg(account: str) -> push_config.ResolvedPushConfig:
        return push_config.ResolvedPushConfig(
            enabled=True,
            project_id="p",
            application_id=None,
            api_key=None,
            sender_id=None,
            service_account_json=f'{{"account": "{account}"}}',
        )

    assert await push_notifications._get_fcm_access_token(_cfg("a")) == "token-1"
    assert await push_notifications._get_fcm_access_token(_cfg("a")) == "token-1"
    assert made[0].refreshes == 1

    made[0].valid = False
    assert await push_notifications._get_fcm_access_token(_cfg("a")) == "token-1"
    assert made[0].refreshes == 2

    assert await push_notifications._get_fcm_access_token(_cfg("b")) == "token-2"
    assert built == [{"account": "a"}, {"account": "b"}]


async def test_a_renewed_session_carries_its_device(session):
    """A refresh moves the device to the row that succeeds its session."""
    from app.services.auth import sessions as session_service
    from app.services.platform import push_tokens
    from app.testing import create_user

    user = await create_user(session)
    user_id = user.id
    issued = await session_service.create_session(
        session, user_id=user_id, amr=["pwd"], satisfied_providers=[]
    )
    await push_tokens.register_push_token(
        session,
        user_id=user_id,
        push_token="phone",
        platform="android",
        session_id=issued.session.id,
    )
    rotated = await session_service.rotate_session(
        session, raw_refresh_token=issued.refresh_token
    )
    renewed_id = rotated.issued.session.id
    await session.commit()

    (row,) = await push_tokens.get_push_tokens_for_user(session, user_id=user_id)
    await session.refresh(row)
    assert row.session_id == renewed_id

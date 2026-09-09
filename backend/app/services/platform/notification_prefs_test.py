"""Resolution order, the community level, and the quiet-hours window."""

from datetime import datetime, timezone

import pytest

from app.core.notification_categories import Channel
from app.models.platform.notification import NotificationType
from app.models.platform.user_notification_prefs import NotificationLevel
from app.services.platform.notification_prefs import (
    in_quiet_hours,
    level_for,
    quiet_hours,
    wants,
)

pytestmark = pytest.mark.unit


def test_empty_prefs_take_every_default():
    for channel in Channel:
        assert wants({}, notification_type=NotificationType.mention, channel=channel)
        assert wants(None, notification_type=NotificationType.mention, channel=channel)


def test_account_override_beats_the_default():
    prefs = {"categories": {"comments": {"in_app": False}}}
    assert not wants(
        prefs,
        notification_type=NotificationType.comment_on_task,
        channel=Channel.in_app,
    )
    # Only the channel named moves.
    assert wants(
        prefs, notification_type=NotificationType.comment_on_task, channel=Channel.email
    )
    # And only the category named — the split from mentions is the whole point.
    assert wants(
        prefs, notification_type=NotificationType.mention, channel=Channel.in_app
    )


def test_community_override_beats_the_account_default():
    prefs = {
        "categories": {"reactions": {"push": True}},
        "guilds": {"7": {"categories": {"reactions": {"push": False}}}},
    }
    assert not wants(
        prefs,
        notification_type=NotificationType.comment_reaction,
        channel=Channel.push,
        guild_id=7,
    )
    # A different community keeps the account default.
    assert wants(
        prefs,
        notification_type=NotificationType.comment_reaction,
        channel=Channel.push,
        guild_id=8,
    )


def test_the_bell_is_gateable():
    """The whole reason in_app exists as a channel."""
    prefs = {"categories": {"reactions": {"in_app": False}}}
    assert not wants(
        prefs,
        notification_type=NotificationType.comment_reaction,
        channel=Channel.in_app,
    )


def test_level_personal_keeps_only_what_names_you():
    prefs = {"guilds": {"7": {"level": NotificationLevel.personal.value}}}
    assert wants(
        prefs,
        notification_type=NotificationType.mention,
        channel=Channel.in_app,
        guild_id=7,
    )
    assert not wants(
        prefs,
        notification_type=NotificationType.comment_on_task,
        channel=Channel.in_app,
        guild_id=7,
    )


def test_level_nothing_means_nothing_including_a_mention():
    prefs = {"guilds": {"7": {"level": NotificationLevel.nothing.value}}}
    for notification_type in (
        NotificationType.mention,
        NotificationType.comment_reply,
        NotificationType.task_assignment,
        NotificationType.comment_on_task,
    ):
        for channel in Channel:
            assert not wants(
                prefs,
                notification_type=notification_type,
                channel=channel,
                guild_id=7,
            )


def test_a_level_cannot_reach_a_notification_that_has_no_community():
    """An account notice arrives however the communities are set."""
    prefs = {"guilds": {"7": {"level": NotificationLevel.nothing.value}}}
    assert wants(
        prefs,
        notification_type=NotificationType.account_suspended,
        channel=Channel.in_app,
        guild_id=7,
    )
    assert wants(
        prefs,
        notification_type=NotificationType.direct_message,
        channel=Channel.in_app,
        guild_id=None,
    )


def test_non_mutable_channels_ignore_overrides():
    prefs = {"categories": {"account": {"in_app": False}}}
    assert wants(
        prefs,
        notification_type=NotificationType.account_suspended,
        channel=Channel.in_app,
    )
    # The reachable channels are still the account's own choice.
    assert not wants(
        {"categories": {"account": {"email": False}}},
        notification_type=NotificationType.account_suspended,
        channel=Channel.email,
    )


def test_level_defaults_to_everything():
    assert level_for({}, 7) is NotificationLevel.everything
    assert level_for({"guilds": {"7": {}}}, 7) is NotificationLevel.everything
    assert level_for({"guilds": {"7": {"level": "nonsense"}}}, 7) is (
        NotificationLevel.everything
    )
    assert level_for({}, None) is NotificationLevel.everything


def test_quiet_hours_needs_both_ends_and_a_real_span():
    assert quiet_hours({}) is None
    assert quiet_hours({"quiet_hours": {"start": "22:00"}}) is None
    assert quiet_hours({"quiet_hours": {"start": "22:00", "end": "22:00"}}) is None
    assert quiet_hours({"quiet_hours": {"start": "boom", "end": "07:00"}}) is None
    assert quiet_hours({"quiet_hours": {"start": "22:00", "end": "07:00"}}) is not None


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 9, hour, minute, tzinfo=timezone.utc)


def test_quiet_hours_wraps_overnight():
    prefs = {"quiet_hours": {"start": "22:00", "end": "07:00"}}
    assert in_quiet_hours(prefs, tz_name="UTC", now=_at(23))
    assert in_quiet_hours(prefs, tz_name="UTC", now=_at(3))
    assert in_quiet_hours(prefs, tz_name="UTC", now=_at(22))
    assert not in_quiet_hours(prefs, tz_name="UTC", now=_at(7))
    assert not in_quiet_hours(prefs, tz_name="UTC", now=_at(12))


def test_quiet_hours_within_one_day():
    prefs = {"quiet_hours": {"start": "09:00", "end": "17:00"}}
    assert in_quiet_hours(prefs, tz_name="UTC", now=_at(12))
    assert not in_quiet_hours(prefs, tz_name="UTC", now=_at(20))


def test_quiet_hours_is_read_in_the_accounts_timezone():
    prefs = {"quiet_hours": {"start": "22:00", "end": "07:00"}}
    # 23:00 UTC is 19:00 in New York — inside the window in UTC, well outside
    # it there.
    assert in_quiet_hours(prefs, tz_name="UTC", now=_at(23))
    assert not in_quiet_hours(prefs, tz_name="America/New_York", now=_at(23))


def test_unknown_timezone_falls_back_rather_than_raising():
    prefs = {"quiet_hours": {"start": "22:00", "end": "07:00"}}
    assert in_quiet_hours(prefs, tz_name="Mars/Olympus", now=_at(23))

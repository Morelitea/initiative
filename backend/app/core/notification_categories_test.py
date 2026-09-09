"""The registry has to stay total over ``NotificationType``.

A new notification type with no category would resolve to nothing, and the
delivery path would have to guess — so this fails CI instead.
"""

import pytest

from app.core.notification_categories import (
    ALL_CHANNELS,
    CATEGORY_SPECS,
    PERSONAL_TYPES,
    Channel,
    NotificationCategory,
    category_of,
    is_personal,
    spec_of,
)
from app.models.platform.notification import NotificationType

pytestmark = pytest.mark.unit


def test_every_notification_type_has_exactly_one_category():
    covered = [
        notification_type
        for spec in CATEGORY_SPECS.values()
        for notification_type in spec.types
    ]
    assert set(covered) == set(NotificationType)
    # A type in two categories would resolve differently depending on which
    # was read first.
    assert len(covered) == len(set(covered))


def test_every_category_is_in_the_registry():
    assert set(CATEGORY_SPECS) == set(NotificationCategory)


def test_every_category_declares_a_default_for_every_channel():
    for category, spec in CATEGORY_SPECS.items():
        assert set(spec.defaults) == set(ALL_CHANNELS), category


def test_mutable_channels_are_real_channels():
    for category, spec in CATEGORY_SPECS.items():
        assert spec.mutable_channels <= set(ALL_CHANNELS), category


def test_account_and_approvals_keep_the_bell():
    """Being told your account was acted on, or that a queue is waiting on you,
    is not an opt-in."""
    for category in (NotificationCategory.account, NotificationCategory.approvals):
        spec = CATEGORY_SPECS[category]
        assert not spec.is_mutable(Channel.in_app)
        # The reachable channels stay the account's own choice.
        assert spec.is_mutable(Channel.email)
        assert spec.is_mutable(Channel.push)


def test_lookups_agree_with_the_registry():
    for category, spec in CATEGORY_SPECS.items():
        for notification_type in spec.types:
            assert category_of(notification_type) is category
            assert spec_of(notification_type) is spec
            assert is_personal(notification_type) is spec.personal


def test_personal_types_are_the_union_of_personal_categories():
    expected = {
        notification_type
        for spec in CATEGORY_SPECS.values()
        if spec.personal
        for notification_type in spec.types
    }
    assert PERSONAL_TYPES == expected
    # The "addressed to me" level would be meaningless at either extreme.
    assert expected
    assert expected != set(NotificationType)


def test_mentions_and_comments_are_separate_categories():
    """One switch used to gate both, so nobody could quieten ambient comment
    traffic without also losing being named."""
    assert category_of(NotificationType.mention) is NotificationCategory.mentions
    assert (
        category_of(NotificationType.comment_on_task) is NotificationCategory.comments
    )
    assert is_personal(NotificationType.mention)
    assert not is_personal(NotificationType.comment_on_task)


def test_direct_messages_and_account_are_not_guild_scoped():
    """They exist outside any community, so no per-community override or level
    can reach them."""
    for category in (
        NotificationCategory.direct_messages,
        NotificationCategory.connections,
        NotificationCategory.account,
    ):
        assert not CATEGORY_SPECS[category].guild_scoped

"""The canonical notification **category** registry.

Every ``NotificationType`` belongs to exactly one category, and the category —
not a hand-written list anywhere else — is what the preference storage, the
settings grid, the per-community level and the "addressed to me" filter all read.
``notification_categories_test.py`` asserts the mapping is exhaustive over
``NotificationType``, so a new type cannot ship without a category decision.

Two axes separate categories that otherwise look adjacent, and they are the
axes to apply when a new one is proposed:

``personal``
    The notification is addressed to this account **by another person**. This is
    what the ``personal`` community level keeps and what the inbox's "Mentions"
    filter shows. One flag, three surfaces.

``mutable_channels``
    Which channels the account may switch off. ``account`` and ``approvals``
    keep the in-app channel on: being told your account was suspended, or that
    somebody is waiting on your decision, is not a preference.

The difference between ``jobs`` and ``account`` is who started it. A job is your
own request finishing — you asked for the export, so being pinged about it is
entirely yours to switch off, and the file is in the jobs table either way. An
account notice is somebody else acting on your account, which is why it is not
optional. The same asymmetry puts ``access_grant_requested`` in ``approvals``
(waiting on your decision) and its resolutions in ``account`` (somebody else's
decision landing on you).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from app.models.platform.notification import NotificationType


class Channel(str, Enum):
    """How a notification reaches somebody.

    ``in_app`` is a real channel, not an always-on floor. Before it existed the
    bell was written unconditionally and only email and push could be turned
    down, which is the whole reason the surface felt loud.
    """

    in_app = "in_app"
    email = "email"
    push = "push"


ALL_CHANNELS: tuple[Channel, ...] = tuple(Channel)


class NotificationCategory(str, Enum):
    mentions = "mentions"
    replies = "replies"
    comments = "comments"
    reactions = "reactions"
    assignments = "assignments"
    due_dates = "due_dates"
    membership = "membership"
    approvals = "approvals"
    posts = "posts"
    events = "events"
    event_reminders = "event_reminders"
    direct_messages = "direct_messages"
    connections = "connections"
    jobs = "jobs"
    account = "account"


#: How the settings page groups the rows. Presentation only — nothing resolves
#: through it.
class CategoryGroup(str, Enum):
    addressed_to_me = "addressed_to_me"
    activity = "activity"
    community = "community"
    account = "account"


_ON = {Channel.in_app: True, Channel.email: True, Channel.push: True}


@dataclass(frozen=True)
class CategorySpec:
    """One category, described once."""

    types: frozenset[NotificationType]
    group: CategoryGroup
    #: Addressed to this account by another person.
    personal: bool
    #: Belongs to a community, so a per-community override and the community
    #: level apply. False for direct messages, connections and account notices,
    #: which exist outside any guild.
    guild_scoped: bool
    #: Channels the account may switch off.
    mutable_channels: frozenset[Channel]
    defaults: Mapping[Channel, bool]

    def is_mutable(self, channel: Channel) -> bool:
        return channel in self.mutable_channels


_ALL_MUTABLE = frozenset(ALL_CHANNELS)
#: In-app stays on; the reachable channels are still the account's own choice.
_KEEP_IN_APP = frozenset({Channel.email, Channel.push})


CATEGORY_SPECS: Mapping[NotificationCategory, CategorySpec] = {
    NotificationCategory.mentions: CategorySpec(
        types=frozenset({NotificationType.mention}),
        group=CategoryGroup.addressed_to_me,
        personal=True,
        guild_scoped=True,
        mutable_channels=_ALL_MUTABLE,
        defaults=_ON,
    ),
    NotificationCategory.replies: CategorySpec(
        types=frozenset({NotificationType.comment_reply}),
        group=CategoryGroup.addressed_to_me,
        personal=True,
        guild_scoped=True,
        mutable_channels=_ALL_MUTABLE,
        defaults=_ON,
    ),
    # Split from mentions deliberately. Being named is a deliberate act by
    # another person; a comment on something you happen to be assigned is
    # ambient traffic that scales with how busy the project is. One switch for
    # both meant nobody could turn the second off without losing the first.
    NotificationCategory.comments: CategorySpec(
        types=frozenset(
            {
                NotificationType.comment_on_task,
                NotificationType.comment_on_resource,
            }
        ),
        group=CategoryGroup.activity,
        personal=False,
        guild_scoped=True,
        mutable_channels=_ALL_MUTABLE,
        defaults=_ON,
    ),
    NotificationCategory.reactions: CategorySpec(
        types=frozenset({NotificationType.comment_reaction}),
        group=CategoryGroup.activity,
        personal=False,
        guild_scoped=True,
        mutable_channels=_ALL_MUTABLE,
        defaults=_ON,
    ),
    NotificationCategory.assignments: CategorySpec(
        types=frozenset({NotificationType.task_assignment}),
        group=CategoryGroup.addressed_to_me,
        personal=True,
        guild_scoped=True,
        mutable_channels=_ALL_MUTABLE,
        defaults=_ON,
    ),
    NotificationCategory.due_dates: CategorySpec(
        types=frozenset({NotificationType.overdue_tasks}),
        group=CategoryGroup.activity,
        personal=False,
        guild_scoped=True,
        mutable_channels=_ALL_MUTABLE,
        defaults=_ON,
    ),
    NotificationCategory.membership: CategorySpec(
        types=frozenset(
            {
                NotificationType.initiative_added,
                NotificationType.initiative_join_approved,
                NotificationType.initiative_join_denied,
                NotificationType.project_added,
            }
        ),
        group=CategoryGroup.community,
        personal=False,
        guild_scoped=True,
        mutable_channels=_ALL_MUTABLE,
        defaults=_ON,
    ),
    # Something is waiting on this account's decision, so the bell keeps it:
    # a queue nobody is told about is a queue nobody works.
    NotificationCategory.approvals: CategorySpec(
        types=frozenset(
            {
                NotificationType.initiative_join_requested,
                NotificationType.user_pending_approval,
                NotificationType.access_grant_requested,
            }
        ),
        group=CategoryGroup.community,
        personal=True,
        guild_scoped=True,
        mutable_channels=_KEEP_IN_APP,
        defaults=_ON,
    ),
    NotificationCategory.posts: CategorySpec(
        types=frozenset({NotificationType.post_published}),
        group=CategoryGroup.community,
        personal=False,
        guild_scoped=True,
        mutable_channels=_ALL_MUTABLE,
        defaults=_ON,
    ),
    NotificationCategory.events: CategorySpec(
        types=frozenset(
            {
                NotificationType.event_invitation,
                NotificationType.event_updated,
                NotificationType.event_cancelled,
                NotificationType.event_rsvp,
            }
        ),
        group=CategoryGroup.addressed_to_me,
        personal=True,
        guild_scoped=True,
        mutable_channels=_ALL_MUTABLE,
        defaults=_ON,
    ),
    NotificationCategory.event_reminders: CategorySpec(
        types=frozenset({NotificationType.event_reminder}),
        group=CategoryGroup.activity,
        personal=False,
        guild_scoped=True,
        mutable_channels=_ALL_MUTABLE,
        defaults=_ON,
    ),
    NotificationCategory.direct_messages: CategorySpec(
        types=frozenset(
            {
                NotificationType.direct_message,
                NotificationType.message_request_received,
                NotificationType.message_request_accepted,
            }
        ),
        group=CategoryGroup.addressed_to_me,
        personal=True,
        guild_scoped=False,
        mutable_channels=_ALL_MUTABLE,
        defaults=_ON,
    ),
    NotificationCategory.connections: CategorySpec(
        types=frozenset(
            {
                NotificationType.connection_requested,
                NotificationType.connection_accepted,
            }
        ),
        group=CategoryGroup.addressed_to_me,
        personal=True,
        guild_scoped=False,
        mutable_channels=_ALL_MUTABLE,
        defaults=_ON,
    ),
    # Work this account asked for, finished. Entirely theirs to switch off —
    # the export is in the jobs table whether or not they were pinged.
    NotificationCategory.jobs: CategorySpec(
        types=frozenset(
            {
                NotificationType.export_ready,
                NotificationType.export_failed,
                NotificationType.import_ready,
                NotificationType.import_failed,
            }
        ),
        group=CategoryGroup.account,
        personal=True,
        guild_scoped=True,
        mutable_channels=_ALL_MUTABLE,
        defaults=_ON,
    ),
    # Somebody else acted on this account. Being told is not a preference.
    NotificationCategory.account: CategorySpec(
        types=frozenset(
            {
                NotificationType.avatar_removed,
                NotificationType.username_changed,
                NotificationType.account_suspended,
                NotificationType.account_unsuspended,
                NotificationType.access_grant_approved,
                NotificationType.access_grant_denied,
                NotificationType.access_grant_revoked,
            }
        ),
        group=CategoryGroup.account,
        personal=True,
        guild_scoped=False,
        mutable_channels=_KEEP_IN_APP,
        defaults=_ON,
    ),
}


#: Type -> category, built from the registry so the two can never disagree.
CATEGORY_OF: Mapping[NotificationType, NotificationCategory] = {
    notification_type: category
    for category, spec in CATEGORY_SPECS.items()
    for notification_type in spec.types
}

#: The types the "addressed to me" level and the Mentions filter keep.
PERSONAL_TYPES: frozenset[NotificationType] = frozenset(
    notification_type
    for category, spec in CATEGORY_SPECS.items()
    if spec.personal
    for notification_type in spec.types
)


def category_of(notification_type: NotificationType) -> NotificationCategory:
    """The category a type belongs to. Total over ``NotificationType`` — the
    drift test is what keeps it that way."""
    return CATEGORY_OF[notification_type]


def spec_of(notification_type: NotificationType) -> CategorySpec:
    return CATEGORY_SPECS[CATEGORY_OF[notification_type]]


def is_personal(notification_type: NotificationType) -> bool:
    return notification_type in PERSONAL_TYPES

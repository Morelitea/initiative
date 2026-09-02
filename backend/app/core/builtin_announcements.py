"""Notices that ship in the app's own source rather than being written in it.

Some things have to be said by the release that changes them: a breaking
change, a migration someone has to run, a setting that moved. Those cannot wait
for an operator to notice and type them out — every deployment that upgrades
needs to see them, and a fresh install that starts on the new version needs to
not. So they are declared here, compiled into the image, and merged with the
authored ones by ``app.services.platform.announcements``.

They differ from authored announcements in three ways, all of them
consequences of living in source control:

* their key is ``builtin:<slug>`` rather than ``db:<id>``, so a read receipt
  survives a database that never held the announcement in the first place;
* they cannot be edited or deleted from the admin surface — the way to retire
  one is to remove it here and ship that;
* their pictures are static assets shipped with the SPA
  (``frontend/public/announcement-images/…``, served at
  ``/announcement-images/…``) rather than uploads, because at build time there
  is no database to upload one to.

Adding one:

.. code-block:: python

    BUILTIN_ANNOUNCEMENTS = (
        BuiltinAnnouncement(
            slug="0-65-guild-admin-settings-moved",
            title="Guild settings have moved",
            category=AnnouncementCategory.breaking,
            published_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
            guild_admins_only=True,
            dismissals_required=2,
            sections=(
                AnnouncementSection(
                    heading="Where they went",
                    body="Access and members now live under **Settings → Users**.",
                    image_url="/announcement-images/0-65-settings.png",
                    image_alt="The relocated settings page",
                ),
                # ``starts_page`` breaks the notice into pages the reader
                # steps through — the wizard shape.
                AnnouncementSection(
                    starts_page=True,
                    heading="What you have to do",
                    body="Re-check who can reach the community's data.",
                ),
            ),
        ),
    )

The slug is permanent: it is what a reader's dismissal is recorded against, so
changing it re-shows the notice to everyone who had already dealt with it.
Removing an entry is how a notice retires — the stale receipts it leaves behind
are harmless and cost one short row each.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.models.platform.announcement import (
    AnnouncementCategory,
    builtin_announcement_key,
)
from app.models.platform.user import UserRole
from app.schemas.platform.announcement import AnnouncementRead, AnnouncementSection


@dataclass(frozen=True)
class BuiltinAnnouncement:
    """One notice declared in source. Mirrors the authored row's fields."""

    slug: str
    title: str
    category: AnnouncementCategory
    published_at: datetime
    sections: tuple[AnnouncementSection, ...] = field(default_factory=tuple)
    #: Audience, read exactly as the authored table's two columns are.
    min_platform_role: UserRole = UserRole.member
    guild_admins_only: bool = False
    expires_at: datetime | None = None
    #: How many times it has to be acknowledged before it stops coming back.
    #: A breaking change nobody can afford to miss is the reason this exists.
    dismissals_required: int = 1
    #: Hold it until the reader opens a matching page, instead of queueing it
    #: on sight — in-context help rather than news.
    trigger_route: str | None = None

    @property
    def key(self) -> str:
        return builtin_announcement_key(self.slug)

    def to_read(self) -> AnnouncementRead:
        return AnnouncementRead(
            key=self.key,
            title=self.title,
            category=self.category,
            sections=list(self.sections),
            published_at=self.published_at,
            is_builtin=True,
            dismissals_required=self.dismissals_required,
            trigger_route=self.trigger_route,
        )


#: Every notice this version of the app carries. Empty is the normal state —
#: an entry is added by the release that needs one and removed once it is old
#: news.
BUILTIN_ANNOUNCEMENTS: tuple[BuiltinAnnouncement, ...] = (
    BuiltinAnnouncement(
        slug="0-65-admin-sidebar-lists-your-initiatives",
        title="Your sidebar now lists the initiatives you are in",
        category=AnnouncementCategory.breaking,
        published_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        # Only the people it changes anything for, and worth saying twice: an
        # admin who skims past it will conclude their initiatives are gone.
        guild_admins_only=True,
        dismissals_required=2,
        # Only inside a community. The notice is about the community sidebar,
        # and that sidebar is not on screen when someone lands on their own
        # task list at sign-in — a notice about a thing you cannot see is just
        # a thing in the way.
        trigger_route="/c/**",
        sections=(
            AnnouncementSection(
                heading="What changed",
                body=(
                    "Administering a community used to put **every** initiative in "
                    "it in your sidebar, whether you had anything to do with it or "
                    "not. Now your sidebar lists the initiatives you are actually a "
                    "member of, the same as everybody else's.\n\n"
                    "Nothing has been deleted, and nothing has been taken away from "
                    "you: as a community admin you can still reach and manage every "
                    "initiative in your community. The sidebar is a list of where "
                    "you work, not a list of what you are allowed to open."
                ),
                image_url="/announcement-images/admin-sidebar-initiatives.png",
                image_alt=(
                    "A community sidebar listing only the two initiatives this "
                    "admin belongs to"
                ),
            ),
            AnnouncementSection(
                starts_page=True,
                heading="Putting one back in your sidebar",
                body=(
                    "Open **Community settings → Initiatives**. Every initiative "
                    "in the community is listed there, whether you are in it or "
                    "not.\n\n"
                    "Set yourself as a **project manager** on the one you want, "
                    "and it appears in your sidebar with everything inside it."
                ),
                image_url="/announcement-images/admin-add-self-as-manager.png",
                image_alt=(
                    "The Initiatives tab of community settings, with the project "
                    "managers picker open on one initiative"
                ),
            ),
        ),
    ),
)


def builtin_by_key(key: str) -> BuiltinAnnouncement | None:
    """The builtin a read receipt's key names, if this version still has it."""
    for announcement in BUILTIN_ANNOUNCEMENTS:
        if announcement.key == key:
            return announcement
    return None

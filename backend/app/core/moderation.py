"""What can be reported, who handles it, and how a report is settled.

A **report** is what a person sends when they meet something wrong. Where it
goes is decided here and nowhere else — the client sends the same thing from
every surface, and the venue is derived from what was reported:

> A target that resolves to an initiative is that initiative's to moderate.
> Everything else is the platform's.

What may be reported is derived too. Community content is
:class:`~app.core.search.SearchEntityType`, which is already built from
:class:`~app.core.tools.Tool` plus the things that live inside one — so a new
tool becomes reportable with no edit here. Only the identity plane, which has
no tool behind it, is stated.
"""

from __future__ import annotations

from enum import Enum

from app.core.search import SearchEntityType
from app.core.tools import plural_of


class PlatformReportTarget(str, Enum):
    """Things a report can name that live outside any community.

    Identity and the platform plane. Adding a ``Tool`` never adds one of these,
    so stating them drifts against nothing.
    """

    user_profile = "user_profile"
    username = "username"
    avatar = "avatar"
    decoration = "decoration"
    directory_listing = "directory_listing"
    guild = "guild"

    # Direct messages are absent because **private conversations are not
    # moderated**. The server holds ciphertext and no key to it, so there is
    # nothing a report could show anybody — the same reason ``dm_transport``
    # has nothing to configure about retention, moderation or search.
    #
    # This is not a gap waiting to be filled. A member's recourse in a private
    # conversation is to block or ignore, which does not need us to read it.


#: Which shared table a platform target's id names. Every member resolves to
#: one of two, which is what lets a report about identity be checked to exist
#: before it becomes somebody's work. ``moderation_test`` holds this and the
#: enum in step, so a member added later cannot ship unresolvable.
PLATFORM_TARGET_TABLE: dict[PlatformReportTarget, str] = {
    PlatformReportTarget.user_profile: "users",
    PlatformReportTarget.username: "users",
    PlatformReportTarget.avatar: "users",
    PlatformReportTarget.decoration: "users",
    PlatformReportTarget.directory_listing: "guilds",
    PlatformReportTarget.guild: "guilds",
}


class ReportVenue(str, Enum):
    """Who handles a report."""

    #: The operations guild's moderation project, as an intake case.
    platform = "platform"
    #: A row in the initiative the target belongs to.
    initiative = "initiative"


class ReportReason(str, Enum):
    """Why somebody is reporting. Closed, so it can be counted and filtered."""

    spam = "spam"
    harassment = "harassment"
    hate = "hate"
    violence = "violence"
    sexual_content = "sexual_content"
    self_harm = "self_harm"
    illegal = "illegal"
    misinformation = "misinformation"
    other = "other"


class ReportOutcome(str, Enum):
    """How a report was settled. Every member closes it."""

    #: Looked at; nothing to do.
    dismissed = "dismissed"
    #: The reported thing was taken down.
    content_removed = "content_removed"
    #: Handled with the person.
    member_warned = "member_warned"
    #: Not this community's to settle — opens a platform case.
    escalated = "escalated"


def target_table(target: SearchEntityType) -> str:
    """The guild-schema table a community target's ids point at."""
    return plural_of(target.value)


def venue_for(target: SearchEntityType | PlatformReportTarget) -> ReportVenue:
    """Who handles a report about ``target``.

    Derived rather than tabulated: a community target is one whose table
    resolves to an initiative, which is the same registry
    (``app.db.initiative_rls.INITIATIVE_PATHS``) the RLS policies are rendered
    from. So a target's venue and its access gate cannot disagree, and a
    guild-level thing — a tag, which belongs to no initiative — falls to the
    platform without being named here.
    """
    if isinstance(target, PlatformReportTarget):
        return ReportVenue.platform

    from app.db.initiative_rls import INITIATIVE_PATHS

    if target_table(target) in INITIATIVE_PATHS:
        return ReportVenue.initiative
    return ReportVenue.platform


def parse_target(raw: str) -> SearchEntityType | PlatformReportTarget:
    """The target type a client named, or ``ValueError``."""
    try:
        return SearchEntityType(raw)
    except ValueError:
        return PlatformReportTarget(raw)

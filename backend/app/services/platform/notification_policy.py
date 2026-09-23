"""What a notification may leave the app carrying.

Three answers, each asked once of the deployment and once of the community the
notification belongs to, and resolved by taking the stricter of the pair:

``push``
    May it reach a phone. Off, nothing is sent to the device estate at all.

``email``
    May it reach a mailbox. The *notification* half of email only — a sign-in
    code, an address to confirm, a password reset and the notices an account
    gets about itself are not notifications and are unaffected.

``redact``
    May what it says name the thing it is about. Set, a notification that leaves
    the app reduces to the kind of thing that happened, and the app is where the
    rest of it is. The bell inside the app says everything either way.

Two levels because two parties know the answer. A deployment that is one
organisation is configured by its operator, once, for everybody on it; a
community sharing a deployment with others answers for itself. Either may
restrict; neither may relax what the other restricted.

A notification that belongs to no community — a direct message, a connection
request, a notice about an account — is answered by the deployment alone.

Read on the system engine, like the recipient's own settings next door: what
may leave is the deployment's answer and the community's, not a question for
whichever session happens to be sending.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.email_i18n import translate
from app.core.notification_categories import NotificationCategory, category_of
from app.models.platform.app_setting import AppSetting
from app.models.platform.guild import Guild
from app.models.platform.notification import NotificationType


@dataclass(frozen=True)
class NotificationPolicy:
    """The three answers, already resolved across both levels."""

    push: bool
    email: bool
    redact: bool

    def stricter_than(self, other: "NotificationPolicy") -> "NotificationPolicy":
        return NotificationPolicy(
            push=self.push and other.push,
            email=self.email and other.email,
            redact=self.redact or other.redact,
        )


#: What every deployment and community says until one of them says otherwise:
#: notifications reach both channels and name what they are about. Also what a
#: caller is served where the configuration cannot be read — the shape the app
#: had before any of this existed.
UNRESTRICTED = NotificationPolicy(push=True, email=True, redact=False)


def _platform_policy(row: AppSetting | None) -> NotificationPolicy:
    if row is None:
        return UNRESTRICTED
    return NotificationPolicy(
        push=row.push_notifications_enabled,
        email=row.email_notifications_enabled,
        redact=row.redact_notification_content,
    )


def _guild_policy(row: Guild | None) -> NotificationPolicy:
    if row is None:
        return UNRESTRICTED
    return NotificationPolicy(
        push=row.allow_push_notifications,
        email=row.allow_email_notifications,
        redact=row.redact_notification_content,
    )


async def resolve(session: AsyncSession, guild_id: int | None) -> NotificationPolicy:
    """Both levels, on a session that can read them, as one answer."""
    platform = _platform_policy(
        (await session.exec(select(AppSetting).where(AppSetting.id == 1))).one_or_none()
    )
    if guild_id is None:
        return platform
    guild = (
        await session.exec(select(Guild).where(Guild.id == guild_id))
    ).one_or_none()
    return platform.stricter_than(_guild_policy(guild))


async def resolve_many(
    session: AsyncSession, guild_ids: Iterable[int | None]
) -> Mapping[int | None, NotificationPolicy]:
    """The same answer for a set of communities, in one pass.

    What a digest needs: it gathers from every community an account is in, so
    each item it carries is answered by its own.
    """
    wanted = set(guild_ids)
    platform = _platform_policy(
        (await session.exec(select(AppSetting).where(AppSetting.id == 1))).one_or_none()
    )
    named = {gid for gid in wanted if gid is not None}
    rows = (
        (await session.exec(select(Guild).where(Guild.id.in_(named)))).all()
        if named
        else []
    )
    by_id = {row.id: row for row in rows}
    return {
        gid: platform
        if gid is None
        else platform.stricter_than(_guild_policy(by_id.get(gid)))
        for gid in wanted
    }


async def load(guild_id: int | None) -> NotificationPolicy:
    """The answer for one community, read on the system engine."""
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as system_session:
        return await resolve(system_session, guild_id)


async def load_many(
    guild_ids: Iterable[int | None],
) -> Mapping[int | None, NotificationPolicy]:
    """The answer for a set of communities, read on the system engine."""
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as system_session:
        return await resolve_many(system_session, guild_ids)


# --- What a redacted notification says ---------------------------------------


def _redacted_key(category: NotificationCategory, part: str) -> str:
    return f"redacted.{category.value}.{part}"


def redacted_push(notification_type: NotificationType, locale: str) -> tuple[str, str]:
    """The title and body a redacted push carries, as ``(title, body)``.

    Written per category rather than per type: the category is what the app
    already groups a notification under everywhere else, and the point of a
    redacted line is that it says the kind of thing and stops.
    """
    category = category_of(notification_type)
    return (
        translate(_redacted_key(category, "title"), locale, namespace="notifications"),
        translate(_redacted_key(category, "body"), locale, namespace="notifications"),
    )


def redacted_subject(category: NotificationCategory, locale: str) -> str:
    """The subject line a redacted notification email carries."""
    return translate(
        _redacted_key(category, "title"), locale, namespace="notifications"
    )


def redacted_body(category: NotificationCategory, locale: str) -> str:
    """The one sentence a redacted notification email carries."""
    return translate(_redacted_key(category, "body"), locale, namespace="notifications")

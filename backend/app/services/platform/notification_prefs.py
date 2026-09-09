"""Resolving "does this person want to hear about this, on this channel".

One function, one order, read by every delivery path. The settings document is
sparse, so almost every call falls through to a registry default without
touching a key.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.notification_categories import (
    CATEGORY_SPECS,
    Channel,
    NotificationCategory,
    category_of,
)
from app.models.platform.notification import NotificationType
from app.models.platform.user_notification_prefs import (
    NotificationLevel,
    UserNotificationPrefs,
)

#: An account with no row and no keys — every default, nothing overridden.
EMPTY: dict[str, Any] = {}


def _section(prefs: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = prefs.get(key)
    return value if isinstance(value, Mapping) else {}


def _guild_section(prefs: Mapping[str, Any], guild_id: int | None) -> Mapping[str, Any]:
    if guild_id is None:
        return {}
    # JSON object keys are strings, so the guild id is stringified on the way in
    # and on the way out.
    return _section(_section(prefs, "guilds"), str(guild_id))


def level_for(prefs: Mapping[str, Any], guild_id: int | None) -> NotificationLevel:
    """How much one community is allowed to say. ``everything`` unless the
    account has said otherwise, which is what makes a newly joined community
    need no write."""
    raw = _guild_section(prefs, guild_id).get("level")
    try:
        return NotificationLevel(raw)
    except ValueError:
        return NotificationLevel.everything


def _override(
    section: Mapping[str, Any],
    category: NotificationCategory,
    channel: Channel,
) -> Optional[bool]:
    value = _section(_section(section, "categories"), category.value).get(channel.value)
    return value if isinstance(value, bool) else None


def wants(
    prefs: Mapping[str, Any] | None,
    *,
    notification_type: NotificationType,
    channel: Channel,
    guild_id: int | None = None,
) -> bool:
    """Whether this account wants ``notification_type`` on ``channel``.

    Most specific first:

    1. the community's level, where the category belongs to a community
    2. a per-community override for this category and channel
    3. the account-wide override
    4. the category's default from the registry

    The level is checked before anything else because it is the account's
    deliberate statement about one community, and ``nothing`` means nothing —
    including a direct mention. It cannot reach a category that belongs to no
    community, so an account notice arrives however the communities are set.
    """
    prefs = prefs or EMPTY
    category = category_of(notification_type)
    spec = CATEGORY_SPECS[category]

    if spec.guild_scoped and guild_id is not None:
        level = level_for(prefs, guild_id)
        if level is NotificationLevel.nothing:
            return False
        if level is NotificationLevel.personal and not spec.personal:
            return False

    # A channel the account cannot switch off is on, and no override for it is
    # read — a stale key from an earlier shape must not decide anything.
    if not spec.is_mutable(channel):
        return True

    if spec.guild_scoped and guild_id is not None:
        override = _override(_guild_section(prefs, guild_id), category, channel)
        if override is not None:
            return override

    override = _override(prefs, category, channel)
    if override is not None:
        return override

    return spec.defaults[channel]


# --- Quiet hours -------------------------------------------------------------


def _parse_clock(raw: Any) -> Optional[time]:
    if not isinstance(raw, str):
        return None
    try:
        hour, minute = raw.split(":", 1)
        return time(hour=int(hour), minute=int(minute))
    except (ValueError, TypeError):
        return None


def quiet_hours(prefs: Mapping[str, Any] | None) -> Optional[tuple[time, time]]:
    """The account's nightly window, or None where it has not set one."""
    section = _section(prefs or EMPTY, "quiet_hours")
    start = _parse_clock(section.get("start"))
    end = _parse_clock(section.get("end"))
    if start is None or end is None or start == end:
        return None
    return start, end


def _resolve_timezone(value: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(value or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def in_quiet_hours(
    prefs: Mapping[str, Any] | None,
    *,
    tz_name: str | None,
    now: datetime | None = None,
) -> bool:
    """Whether ``now`` falls inside the account's window, in its own timezone.

    Overnight ranges are the normal case, so a window whose end is before its
    start wraps around midnight.
    """
    window = quiet_hours(prefs)
    if window is None:
        return False
    start, end = window
    moment = (now or datetime.now(timezone.utc)).astimezone(_resolve_timezone(tz_name))
    current = moment.time()
    if start < end:
        return start <= current < end
    return current >= start or current < end


#: The channels quiet hours holds back. The bell is not one of them: it
#: interrupts nobody, and it is what the account wakes up to.
QUIET_CHANNELS: frozenset[Channel] = frozenset({Channel.email, Channel.push})

#: How long after a window closes its summary is still worth sending. Past
#: this the news has kept until whenever the account next looks, and a
#: "while you were asleep" about the night before last is noise.
QUIET_SUMMARY_GRACE = timedelta(hours=6)


def last_window_close(
    prefs: Mapping[str, Any] | None,
    *,
    tz_name: str | None,
    now: datetime | None = None,
) -> Optional[tuple[datetime, datetime]]:
    """The window that most recently closed, as ``(opened_at, closed_at)``.

    Both are absolute instants, so the summary can ask for exactly what was
    held back. Returns None when there is no window, when the window has not
    closed within :data:`QUIET_SUMMARY_GRACE`, or when ``now`` is still inside
    it — a window that has not finished has nothing to summarise yet.
    """
    window = quiet_hours(prefs)
    if window is None:
        return None
    start, end = window
    tz = _resolve_timezone(tz_name)
    moment = (now or datetime.now(timezone.utc)).astimezone(tz)
    if in_quiet_hours(prefs, tz_name=tz_name, now=moment):
        return None

    closed = moment.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if closed > moment:
        closed -= timedelta(days=1)
    opened = closed.replace(hour=start.hour, minute=start.minute)
    if opened >= closed:
        # An overnight window opened the day before it closed.
        opened -= timedelta(days=1)

    if moment - closed > QUIET_SUMMARY_GRACE:
        return None
    return opened.astimezone(timezone.utc), closed.astimezone(timezone.utc)


# --- Loading -----------------------------------------------------------------


async def load_prefs_for_delivery(user_id: int) -> dict[str, Any]:
    """One recipient's settings, read on the system engine.

    Delivery decides what to send *somebody else*, from a session routed into
    the guild the content is in. That session is not the recipient, and their
    settings are not a guild's to read — the same reason recipients themselves
    are loaded this way (see ``accounts.load``). Reading them under the
    account's own rule would find nothing and quietly deliver every default.
    """
    from app.db.session import AdminSessionLocal

    async with AdminSessionLocal() as admin_session:
        return await load_prefs(admin_session, user_id)


async def load_prefs_for_delivery_many(
    user_ids: list[int],
) -> dict[int, dict[str, Any]]:
    """The same, for a whole audience in one query."""
    from app.db.session import AdminSessionLocal

    async with AdminSessionLocal() as admin_session:
        return await load_prefs_for(admin_session, user_ids)


async def load_prefs(session: AsyncSession, user_id: int) -> dict[str, Any]:
    """One account's settings document, or ``{}`` where it has none."""
    row = (
        await session.exec(
            select(UserNotificationPrefs).where(
                UserNotificationPrefs.user_id == user_id
            )
        )
    ).one_or_none()
    if row is None:
        return {}
    record = row[0] if isinstance(row, tuple) else row
    return dict(record.prefs or {})


async def load_prefs_for(
    session: AsyncSession, user_ids: list[int]
) -> dict[int, dict[str, Any]]:
    """The settings documents for a set of recipients, in one query.

    Fan-out resolves a whole audience at once, so this is what keeps preference
    resolution off the per-recipient path. Accounts with no row are absent from
    the result and read as all-defaults.
    """
    if not user_ids:
        return {}
    rows = (
        await session.exec(
            select(UserNotificationPrefs).where(
                UserNotificationPrefs.user_id.in_(user_ids)
            )
        )
    ).all()
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        record = row[0] if isinstance(row, tuple) else row
        out[record.user_id] = dict(record.prefs or {})
    return out


async def save_prefs(
    session: AsyncSession, user_id: int, prefs: Mapping[str, Any]
) -> UserNotificationPrefs:
    """Write an account's whole settings document, creating the row if needed."""
    row = (
        await session.exec(
            select(UserNotificationPrefs).where(
                UserNotificationPrefs.user_id == user_id
            )
        )
    ).one_or_none()
    record = (row[0] if isinstance(row, tuple) else row) if row is not None else None
    now = datetime.now(timezone.utc)
    if record is None:
        record = UserNotificationPrefs(
            user_id=user_id, prefs=dict(prefs), created_at=now, updated_at=now
        )
    else:
        record.prefs = dict(prefs)
        record.updated_at = now
    session.add(record)
    await session.flush()
    return record

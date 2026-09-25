"""The install index: which communities hold which app, without visiting them.

``public.app_installs`` mirrors three facts of each community's ``guild_apps``
rows: the listing an install came from, whether it is switched on, and the
value its app's vendor webhooks are routed to it by (``hook_route``). It is
written wherever those facts change — at install and uninstall, when the app
is switched on or off, and when the routed static connection's value is stored
or removed — and read by two things:

* :func:`page`, the app's own listing of its installs, a keyset page at a
  time;
* :func:`routed`, the installs a vendor delivery belongs to.

Every call runs on the system engine, which alone reaches the table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from cryptography.fernet import InvalidToken
from sqlalchemy import delete, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select

from app.core.encryption import SALT_APP_INSTALLS_CURSOR, decrypt_field, encrypt_field
from app.db import session as db_session
from app.models.platform.app_install import HOOK_ROUTE_MAX_LENGTH, AppInstall
from app.models.platform.guild import LIVE_STATUS_VALUES, Guild, GuildStatus
from app.models.tenant.guild_app import GuildApp

__all__ = [
    "PAGE_LIMIT",
    "IndexedInstall",
    "forget",
    "hook_route",
    "page",
    "record",
    "routed",
]

#: The most installs one page lists.
PAGE_LIMIT = 200


@dataclass(frozen=True)
class IndexedInstall:
    guild_id: int
    install_id: int
    #: Switched on, in a community in use.
    active: bool


def hook_route(app: GuildApp) -> Optional[str]:
    """The value this install's vendor webhooks are routed by: the stored
    field of the static connection its pinned ``webhooks.route`` names."""
    route = ((app.definition or {}).get("webhooks") or {}).get("route")
    if not isinstance(route, dict):
        return None
    stored = (app.config or {}).get(route.get("connection")) or {}
    value = stored.get(route.get("field")) if isinstance(stored, dict) else None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value)
    return text if text and len(text) <= HOOK_ROUTE_MAX_LENGTH else None


async def record(guild_id: int, app: GuildApp) -> None:
    """Write one install's row as ``app`` now stands."""
    if not app.listing_uid or app.id is None:
        return
    values = {
        "listing_uid": app.listing_uid,
        "enabled": bool(app.enabled),
        "hook_route": hook_route(app),
    }
    statement = (
        pg_insert(AppInstall)
        .values(guild_id=guild_id, install_id=app.id, **values)
        .on_conflict_do_update(
            index_elements=[AppInstall.guild_id, AppInstall.install_id], set_=values
        )
    )
    async with db_session.SystemSessionLocal() as session:
        await session.exec(statement)
        await session.commit()


async def forget(guild_id: int, install_id: int) -> None:
    """Remove one install's row."""
    async with db_session.SystemSessionLocal() as session:
        await session.exec(
            delete(AppInstall).where(
                AppInstall.guild_id == guild_id, AppInstall.install_id == install_id
            )
        )
        await session.commit()


def _encode_cursor(entry: IndexedInstall) -> str:
    """Where a page ended, sealed: the app never sees our ids."""
    return encrypt_field(
        f"{entry.guild_id}:{entry.install_id}", SALT_APP_INSTALLS_CURSOR
    )


def _decode_cursor(cursor: Optional[str]) -> Optional[tuple[int, int]]:
    """A cursor that does not open starts the list again."""
    if not cursor:
        return None
    try:
        guild, _, install = decrypt_field(cursor, SALT_APP_INSTALLS_CURSOR).partition(
            ":"
        )
        return int(guild), int(install)
    except (InvalidToken, ValueError):
        return None


async def page(
    listing_uid: str, *, cursor: Optional[str], limit: int
) -> tuple[list[IndexedInstall], Optional[str]]:
    """One page of a listing's installs, in (community, install) order, and
    the cursor for the next page, or ``None`` at the end."""
    statement = (
        select(
            AppInstall.guild_id,
            AppInstall.install_id,
            (
                AppInstall.enabled.is_(True)
                & Guild.status.in_(sorted(LIVE_STATUS_VALUES))
            ).label("active"),
        )
        .join(Guild, Guild.id == AppInstall.guild_id)
        .where(AppInstall.listing_uid == listing_uid)
        .order_by(AppInstall.guild_id, AppInstall.install_id)
        .limit(limit + 1)
    )
    after = _decode_cursor(cursor)
    if after is not None:
        statement = statement.where(
            tuple_(AppInstall.guild_id, AppInstall.install_id) > tuple_(*after)
        )
    async with db_session.SystemSessionLocal() as session:
        rows = (await session.exec(statement)).all()
    entries = [
        IndexedInstall(guild_id=row[0], install_id=row[1], active=bool(row[2]))
        for row in rows
    ]
    if len(entries) <= limit:
        return entries, None
    return entries[:limit], _encode_cursor(entries[limit - 1])


async def routed(listing_uid: str, route_value: str) -> list[IndexedInstall]:
    """The installs of a listing whose webhooks route by ``route_value``, one
    per community that connected it: switched on, in a community open to
    writes."""
    statement = (
        select(AppInstall.guild_id, AppInstall.install_id)
        .join(Guild, Guild.id == AppInstall.guild_id)
        .where(
            AppInstall.listing_uid == listing_uid,
            AppInstall.hook_route == route_value,
            AppInstall.enabled.is_(True),
            Guild.status == GuildStatus.active.value,
        )
        .order_by(AppInstall.guild_id)
    )
    async with db_session.SystemSessionLocal() as session:
        rows = (await session.exec(statement)).all()
    return [
        IndexedInstall(guild_id=row[0], install_id=row[1], active=True) for row in rows
    ]

"""Reading an account, where an account may be read.

``public.users`` holds two different kinds of thing: a few columns that say who
somebody is, and the account itself — credentials, address, notification
preferences, locale, interface settings. A guild-routed session reads the first
kind through ``public.guild_member_profiles`` and cannot reach the second at
all, which is the point.

Some work on the request path legitimately needs the second kind about somebody
else. Addressing a notification is the main one: whether they asked to hear
about this, which language to write it in, what clock to render a time against,
and the address itself, which is stored encrypted and decrypted in Python. The
export worker is another — it re-runs a job as the person who asked for it, and
needs their account to do so.

Those reads happen here, on the system engine, the way
``authenticate_api_key`` resolves a credential before a session exists.

The rows come back **detached**. Every column is loaded, so callers read them
exactly as they read a request-loaded row; what a detached row cannot do is
lazy-load a relationship or be written back, which is right for something the
caller is only reading facts off.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from sqlmodel import select

from app.models.platform.user import User

__all__ = ["load", "load_one", "load_all", "load_event_reminder_optins"]


async def load(user_ids: Iterable[int | None]) -> dict[int, User]:
    """The accounts behind ``user_ids``, keyed by id, detached.

    Ids with no account behind them are simply absent — an account can be
    erased between the content write and the notification, and having nobody to
    tell is not an error.
    """
    wanted = {user_id for user_id in user_ids if user_id is not None}
    if not wanted:
        return {}

    # Imported here: this module is pulled in by request-path services, and the
    # session module reaches back into configuration at import time.
    from app.db.session import AdminSessionLocal

    async with AdminSessionLocal() as admin_session:
        rows = list(
            (
                await admin_session.exec(select(User).where(User.id.in_(tuple(wanted))))
            ).all()
        )
        for row in rows:
            admin_session.expunge(row)
    return {row.id: row for row in rows if row.id is not None}


async def load_one(user_id: int | None) -> User | None:
    """One recipient, or ``None`` if there is nobody to tell."""
    if user_id is None:
        return None
    return (await load([user_id])).get(user_id)


async def load_all(user_ids: Sequence[int | None]) -> list[User]:
    """Recipients in the order asked for, skipping any that are gone."""
    targets = await load(user_ids)
    seen: set[int] = set()
    ordered: list[User] = []
    for user_id in user_ids:
        if user_id is None or user_id in seen:
            continue
        target = targets.get(user_id)
        if target is not None:
            seen.add(user_id)
            ordered.append(target)
    return ordered


async def load_event_reminder_optins() -> list[User]:
    """Everybody who asked to be reminded about events, detached.

    The reminder sweep walks each guild's schema in turn, so the session it
    holds is routed into one — and a routed session has no business reading an
    account's preferences. The question "who wants reminding" is about accounts
    rather than about any guild, so it is asked here, once, before the walk.
    """
    from app.db.session import AdminSessionLocal

    async with AdminSessionLocal() as admin_session:
        rows = list(
            (
                await admin_session.exec(
                    select(User).where(User.event_reminder_minutes_before.is_not(None))
                )
            ).all()
        )
        for row in rows:
            admin_session.expunge(row)
    return rows

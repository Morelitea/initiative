"""What to call a person, in server-generated text.

The one answer, so notification copy, exports and calendar files agree with
each other and with what the API ships. In a guild that is the display name the
person set there, and the handle where they set none.

A background job outside any guild therefore gets the handle, which is the
identifier that reads the same everywhere.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from app.core import usernames

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


class Nameable(Protocol):
    username: str
    discriminator: int


class Person(Nameable, Protocol):
    id: int | None


def display_name(user: Nameable | None, fallback: str = "") -> str:
    """What to call ``user`` here: their name if there is one, their handle
    otherwise.

    Whether there is one is the guild's answer, not this function's. A
    guild-routed session reads people through ``guild_member_profiles``, whose
    ``display_name`` is the name the person set in that guild — so where they
    set none, or where ``user`` is an account rather than a member, this has
    nothing to use and gives the handle.
    """
    if user is None:
        return fallback
    name = (getattr(user, "display_name", None) or "").strip()
    return name or handle_of(user)


def handle_of(user: Nameable) -> str:
    """``foobar#1234`` — the handle as one string, for plain text.

    The API ships the two fields separately so a client can mute the number;
    text has no styling to carry that, so it joins them.
    """
    return usernames.format_handle(user.username, user.discriminator)


async def name_here(session: AsyncSession, user: Person) -> str:
    """What the community ``session`` is routed into calls ``user``.

    For the code that holds an account — the signed-in ``User``, an export's
    creator — rather than a person loaded from guild content: it reads them
    back through ``guild_member_profiles`` on that session. A session routed
    nowhere gets the handle.
    """
    from app.models.platform.user_profile_view import MemberProfile

    if isinstance(user, MemberProfile):
        return display_name(user)
    member = await session.get(MemberProfile, user.id) if user.id else None
    return display_name(member, fallback=handle_of(user))

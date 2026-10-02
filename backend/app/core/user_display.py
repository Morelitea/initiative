"""What to call a person, in server-generated text.

The one answer, so notification copy, exports and calendar files agree with
each other and with what the API ships. In a guild that is the display name the
person set there, and the handle where they set none.

A background job outside any guild therefore gets the handle, which is the
identifier that reads the same everywhere.
"""

from __future__ import annotations

from typing import Protocol

from app.core import usernames


class Nameable(Protocol):
    username: str
    discriminator: int
    full_name: str | None


def display_name(user: Nameable | None, fallback: str = "") -> str:
    """What to call ``user`` here: their name if there is one, their handle
    otherwise.

    Whether there is one is the guild's answer, not this function's. A
    guild-routed session reads people through ``guild_member_profiles``, whose
    ``full_name`` is the display name the person set in that guild — so where
    they set none, this arrives with nothing to use and gives the handle.
    """
    if user is None:
        return fallback
    name = (getattr(user, "full_name", None) or "").strip()
    return name or handle_of(user)


def handle_of(user: Nameable) -> str:
    """``foobar#1234`` — the handle as one string, for plain text.

    The API ships the two fields separately so a client can mute the number;
    text has no styling to carry that, so it joins them.
    """
    return usernames.format_handle(user.username, user.discriminator)

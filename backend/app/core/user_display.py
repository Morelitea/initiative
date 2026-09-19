"""What to call a person, in server-generated text.

The one answer, so notification copy, exports and calendar files agree with
each other and with what the API ships. It reads the same request-scoped flag
the user schemas do: a guild that renders real names gets the name, everything
else gets the handle.

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
    guild-routed session reads people through ``guild_member_profiles``, which
    carries ``full_name`` only where that guild renders real names — so a guild
    that renders handles arrives here with nothing to use, and gets a handle
    without being asked about it.
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

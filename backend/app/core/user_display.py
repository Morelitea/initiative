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
from app.core.role_context import guild_shows_member_names


class Nameable(Protocol):
    username: str
    discriminator: int
    full_name: str | None


def handle_of(user: Nameable) -> str:
    """``foobar#1234`` — the handle as one string, for plain text.

    The API ships the two fields separately so a client can mute the number;
    text has no styling to carry that, so it joins them.
    """
    return usernames.format_handle(user.username, user.discriminator)


def display_name(user: Nameable | None, fallback: str = "") -> str:
    """What to call ``user`` here: their name where the guild shows names,
    their handle otherwise."""
    if user is None:
        return fallback
    if guild_shows_member_names():
        name = (getattr(user, "full_name", None) or "").strip()
        if name:
            return name
    return handle_of(user)

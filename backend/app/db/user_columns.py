"""Which columns of ``public.users`` leave the account they belong to.

An account row holds two different kinds of thing. A few columns say who a
person is — the handle they are known by, their name, their picture, how the
account stands, what they dressed the profile in. The rest is the account
itself: credentials, addresses, the session counter, every notification
preference, the interface settings, the digest bookkeeping.

The first kind is published; the second belongs to its holder and to the system
engine. This module is where that split is written down, and it is written down
once:

* ``PUBLIC_PROFILE_COLUMNS`` — what a profile is, anywhere in the platform.
  Behind ``public.user_profiles`` (migration 0214), read by the cross-guild
  profile page.
* ``GUILD_MEMBER_PROFILE_COLUMNS`` — the same plus ``full_name``. Behind
  ``public.guild_member_profiles``, read by every guild-routed request. The
  name is here and not above because a guild is where colleagues are named;
  the profile page is not in one.

Everything else is ``PRIVATE_COLUMNS``, which is *derived* rather than listed:
a column added to the model tomorrow is private because it is not in either
family, and ``user_columns_test`` fails if the families ever name a column the
model does not have. The request path holds no privilege on ``public.users``
itself, so a private column is not something a guild-routed query returns null
for — it is something it cannot name at all.

Same registry-vs-rendered split as ``system_grants.py``: this is the current
truth, the migrations remain the record of when it changed, and
``security_invariants_test`` compares both against the live catalog.
"""

from __future__ import annotations

from app.models.platform.user import User

__all__ = [
    "PUBLIC_PROFILE_COLUMNS",
    "GUILD_MEMBER_PROFILE_COLUMNS",
    "PUBLISHED_COLUMNS",
    "PRIVATE_COLUMNS",
    "all_user_columns",
]


#: What a profile is: the handle, the face, the standing, the status line, the
#: look, and when the account started. The column list of
#: ``public.user_profiles`` and the column grant behind it are this tuple.
PUBLIC_PROFILE_COLUMNS: tuple[str, ...] = (
    "id",
    "username",
    "discriminator",
    "avatar_url",
    "status",
    "custom_status",
    "profile_decorations",
    "created_at",
)

#: What a guild-routed request may read of somebody. The profile plus the real
#: name, which is what a roster, a picker and an @mention render in a guild
#: that asked for names — ``show_member_names`` still decides whether it is
#: *shown* (``GuildNameVisibility``).
GUILD_MEMBER_PROFILE_COLUMNS: tuple[str, ...] = (
    "id",
    "username",
    "discriminator",
    "full_name",
    "avatar_url",
    "status",
    "custom_status",
    "profile_decorations",
    "created_at",
)

#: Every column any request-path role can reach, by any route.
PUBLISHED_COLUMNS: frozenset[str] = frozenset(PUBLIC_PROFILE_COLUMNS) | frozenset(
    GUILD_MEMBER_PROFILE_COLUMNS
)


def all_user_columns() -> frozenset[str]:
    """Every mapped column of ``public.users``, from the model."""
    return frozenset(column.name for column in User.__table__.columns)


#: The rest of the account. Derived, so it grows by itself.
PRIVATE_COLUMNS: frozenset[str] = all_user_columns() - PUBLISHED_COLUMNS

"""The projections of ``public.users`` the request path reads.

``public.users`` itself is not readable on the request path. Two views over it
are, each owned by ``app_profile_reader`` — a NOLOGIN role holding a
column-scoped SELECT on the table — so what is public is decided by the
catalog rather than by whoever writes the next query:

* ``public.user_profiles`` (migration 0214) — the eight columns a profile is,
  read by the cross-guild profile page on a ``platform_base`` session.
* ``public.guild_member_profiles`` — those plus ``full_name``, read by every
  guild-routed session. A guild is where colleagues are named; the profile
  page is not in one, which is why the name is in this view and not that one.

Which columns those are lives in ``app.db.user_columns``.

Both tables live in their own ``MetaData``, deliberately: a view is not a
table, and putting one in ``SQLModel.metadata`` would make the table
classification and drift checks treat it as one and try to keep it in step with
a model.

``MemberProfile`` is the mapped class over the guild view. It is what every
tenant relationship that used to point at ``User`` points at now
(``Task.assignees``, ``InitiativeMember.user``, ``Comment.author``, …), so
loading a person from guild content yields a person, not an account. It is
mapped imperatively into SQLModel's own registry so those relationships can
still name it as a string, while its table stays out of ``SQLModel.metadata``.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Table,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlmodel import SQLModel

from app.models.platform.user import UserStatus

#: Not ``SQLModel.metadata`` — see the module docstring.
metadata = MetaData()


def _status_column() -> Column:
    """The real enum type, so a comparison against ``UserStatus`` binds as
    ``user_status`` rather than text."""
    return Column("status", ENUM(UserStatus, name="user_status", create_type=False))


user_profiles = Table(
    "user_profiles",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(32)),
    Column("discriminator", SmallInteger),
    Column("avatar_url", String),
    _status_column(),
    Column("custom_status", JSONB),
    Column("profile_decorations", JSONB),
    Column("created_at", DateTime(timezone=True)),
    schema="public",
)

guild_member_profiles = Table(
    "guild_member_profiles",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(32)),
    Column("discriminator", SmallInteger),
    Column("full_name", String),
    Column("avatar_url", String),
    _status_column(),
    Column("custom_status", JSONB),
    Column("profile_decorations", JSONB),
    Column("created_at", DateTime(timezone=True)),
    schema="public",
)


class MemberProfile:
    """A person, as guild content refers to them.

    Everything a roster, a picker, a mention, an assignee chip or a comment
    byline renders, and nothing else: the shapes in ``app.schemas`` that name a
    person (``UserPublic``, ``UserSummary``, ``CommentAuthor``,
    ``ReactionUser``, ``TaskAssigneeSummary``) validate straight off one of
    these.

    Reading an account's own settings — preferences, address, locale — is the
    account holder's own business or the system engine's, and goes through
    ``User`` on a session that may.
    """

    id: int
    username: str
    discriminator: int
    full_name: Optional[str]
    avatar_url: Optional[str]
    status: UserStatus
    custom_status: dict
    profile_decorations: dict
    created_at: datetime

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<MemberProfile {self.username}#{self.discriminator:04d}>"


# Into SQLModel's registry rather than a private one, so a relationship on a
# SQLModel table can name ``"MemberProfile"`` the way it named ``"User"``.
SQLModel._sa_registry.map_imperatively(MemberProfile, guild_member_profiles)

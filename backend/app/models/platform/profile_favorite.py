"""The people one account has starred on My Contacts.

A row is one person on one person's list. It is private and one-directional:
the list is the holder's, and who has starred *you* is not a question this
table answers for anybody.

The pair is the primary key, so starring somebody twice is a no-op by
constraint rather than by handler, and there is nothing on the row to edit —
an unstar is a delete.
"""

from datetime import datetime, timezone

from pydantic import ConfigDict
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
)
from sqlmodel import Field, SQLModel


class ProfileFavorite(SQLModel, table=True):
    __tablename__ = "profile_favorites"
    __table_args__ = (
        CheckConstraint(
            "user_id <> favorite_user_id", name="ck_profile_favorites_not_self"
        ),
        # The primary key covers ``user_id`` as a prefix, which is the read the
        # page makes. This is the other direction: every list an account
        # appears on, which is what erasure has to visit.
        Index("ix_profile_favorites_favorite_user", "favorite_user_id"),
    )
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    favorite_user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

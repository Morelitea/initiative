"""The name one installed app knows one member by.

Derived rather than random (see ``services.marketplace.app_subjects``), so this
table is an index into a computation rather than the only copy of it: losing a
row and re-deriving gives the same subject back, and no app believes it has met
a new person.

What the row buys is the *reverse* direction. The derivation is one-way, so a
delegation token naming a subject can only be resolved to a member by finding
the value we minted — which is this.

Guild-level: an install is guild-wide and this has no initiative. Unlike its
neighbours it carries **no** own-row policy, because it holds nothing about the
member beyond the link itself, and the two readers are the handoff mint and the
delegation resolver — both of which run on the system engine for a member who is
not the caller.
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import ConfigDict
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel


#: Characters of base64url. 32 of them is 192 bits of the digest — far past
#: collision concerns, and short enough to sit in a JWT claim and a URL.
SUBJECT_LENGTH = 32


class GuildAppSubject(SQLModel, table=True):
    __tablename__ = "guild_app_subjects"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    __table_args__ = (
        # One subject per member per install — the sector is the install, so
        # the same person at two installs is deliberately two rows.
        UniqueConstraint("app_id", "user_id", name="guild_app_subjects_unique_member"),
        # And the value resolves to exactly one of them, which is what the
        # delegation path depends on.
        UniqueConstraint("subject", name="guild_app_subjects_unique_subject"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)

    app_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guild_apps.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )

    #: What the app calls this person. Opaque to it, and unrelated to the value
    #: any other install derives for the same member.
    subject: str = Field(sa_column=Column(String(SUBJECT_LENGTH), nullable=False))

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

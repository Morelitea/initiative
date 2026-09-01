from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlmodel import Field, SQLModel


class ReactionDigestItem(SQLModel, table=True):
    """One queued "someone reacted to your comment" line.

    The same bookkeeping shape as ``TaskAssignmentDigestItem``: a row per
    (recipient, event), drained by the shared digest engine once the flurry has
    settled, then marked processed and GC'd. Denormalized on purpose — the
    digest reads it long after the fact and must not depend on the reaction
    still existing.
    """

    __tablename__ = "reaction_digest_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    #: The reaction row this came from, so un-reacting can withdraw a line that
    #: has not gone out yet. Nullable: the line outlives the gesture.
    reaction_id: Optional[int] = Field(default=None, nullable=True, index=True)
    target_type: str = Field(sa_column=Column(String(32), nullable=False))
    target_id: int = Field(sa_column=Column(Integer, nullable=False))
    emoji: str = Field(sa_column=Column(Text, nullable=False))
    #: Where the notification points, resolved when the reaction happened.
    target_path: str = Field(sa_column=Column(Text, nullable=False))
    #: What was reacted to, for the digest line ("your comment on X").
    context_title: str = Field(sa_column=Column(String(255), nullable=False))
    reactor_name: str = Field(sa_column=Column(String(255), nullable=False))
    reactor_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    processed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

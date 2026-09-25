"""One notification email, written down instead of sent.

Every notification email in the app lands here first. The request that caused
it writes a row and moves on; a worker decides when it goes and composes what
finally arrives. That split is what buys three things the synchronous send
could not have: SMTP leaves the request path, a failed send is retried instead
of logged and lost, and several rows for one person can arrive as one message.

A row holds **pieces, not a finished message** — a subject, a headline, an HTML
fragment and a link. On its own it renders exactly the email that used to be
sent inline; alongside others it becomes one section of a digest. Nothing is
re-rendered at send, so a line in a digest reads as its own email would have.

``deliver_after`` is computed once, at enqueue, from the recipient's cadence
and whatever holds them (see ``app.services.platform.notification_prefs``).
Changing a setting recomputes it for everything still pending, which is what
makes "resume" mean something.

The table is written from the request path and read by the worker, and its
grants say exactly that: INSERT for the request-path base roles, the full set
for the system engine, nothing for the bare login. There is no endpoint over
it; what the recipient sees is the email.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlmodel import Field, SQLModel


class EmailOutboxItem(SQLModel, table=True):
    __tablename__ = "email_outbox"
    __table_args__ = (
        # The worker's only scan: what is due, oldest first. Partial on the
        # unfinished rows because a settled one is never asked about again.
        Index(
            "ix_email_outbox_due",
            "deliver_after",
            postgresql_where=text("sent_at IS NULL AND failed_at IS NULL"),
        ),
        # The recompute (a setting moved) and the account cascade.
        Index("ix_email_outbox_user", "user_id"),
    )

    id: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
    )
    user_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        )
    )
    #: The bell line this is the email of, where one was written. It is what
    #: lets the worker drop a line the recipient has already read in the app.
    #: Nullable because a category with the bell switched off still emails.
    notification_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("notifications.id", ondelete="SET NULL"), nullable=True
        ),
    )
    #: A ``NotificationCategory`` value. Groups the digest, and is re-checked
    #: against the recipient's settings at send.
    category: str = Field(sa_column=Column(String(32), nullable=False))
    #: Which community this happened in, for the digest's headings. Null for
    #: the things that belong to no community — direct messages, connections,
    #: account notices.
    guild_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=True
        ),
    )
    #: What the pieces below were rendered in. The digest's own chrome uses the
    #: account's locale at send; these were fixed when the thing happened.
    locale: str = Field(
        default="en", sa_column=Column(String(10), nullable=False, server_default="en")
    )
    subject: str = Field(sa_column=Column(Text, nullable=False))
    headline: str = Field(sa_column=Column(Text, nullable=False))
    #: An HTML fragment. Its interpolated values were escaped when it was built.
    body: str = Field(sa_column=Column(Text, nullable=False))
    link: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    #: The call-to-action's wording, where the single-row layout draws a button.
    link_label: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    #: An account-security letter: sent at once, on its own, to every address
    #: the account has proved, whatever its notification settings.
    security: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    #: The earliest this may go out.
    deliver_after: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    #: Held by the pass that is sending it, so two workers cannot both send.
    #: Older than the lease means the pass that took it never finished.
    claimed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    attempts: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    sent_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: Set once the attempts are spent. Kept until the sweep, so "did that go
    #: out" has an answer for a while.
    failed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

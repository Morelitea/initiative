"""A pair of accounts with an open channel, and who is on it.

The conversation row carries an id and a creation time and nothing else. There
is no title, no last-message column and no unread count, because all three
would be facts about content the server does not hold.

``dm_conversation_members`` is exactly two rows. It is the roster the transport
routes on, and it is the reason a membership check cannot be a plain own-row
policy: knowing who the *other* party is requires reading a row that is not
yours. ``public.dm_in_conversation`` answers that question without handing the
row over, on the same ``SECURITY DEFINER`` pattern the rest of the DM rules use.
"""

import uuid
from datetime import datetime, timezone

from pydantic import ConfigDict
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Uuid,
    text,
)
from sqlmodel import Field, SQLModel


class DmConversation(SQLModel, table=True):
    __tablename__ = "dm_conversations"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(
            Uuid, primary_key=True, server_default=text("gen_random_uuid()")
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class DmConversationMember(SQLModel, table=True):
    __tablename__ = "dm_conversation_members"
    __table_args__ = (
        # "my conversations", which is the list page's only query.
        Index("ix_dm_conversation_members_user", "user_id"),
    )
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    conversation_id: uuid.UUID = Field(
        sa_column=Column(
            Uuid,
            ForeignKey("dm_conversations.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    joined_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

import uuid as uuid_module
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlmodel import Field, SQLModel


class AuthChallenge(SQLModel, table=True):
    """A sign-in that has proved one thing and is waiting on the next.

    Between a correct password and an accepted code there is a moment that has
    to be carried across two requests. It is carried here rather than in
    ``auth_sessions``, where every row means somebody is signed in.
    ``consumed_at`` spends the challenge, ``attempts`` counts refused answers
    against it, ``expires_at`` ends it, and a password change or a factor being
    removed deletes it.

    ``challenge_hash`` is SHA-256 of the value handed to the client, following
    ``auth_sessions.refresh_token_hash``. The raw value exists once, in the
    response that issues it.

    ``purpose`` names what the challenge is for, so passkeys and step-up reuse
    the table instead of adding one.
    """

    __tablename__ = "auth_challenges"

    id: Optional[uuid_module.UUID] = Field(
        default_factory=uuid_module.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )

    challenge_hash: bytes = Field(
        sa_column=Column(LargeBinary, nullable=False, unique=True)
    )

    #: The account the challenge belongs to, where one is known. A passkey
    #: sign-in begins from the credential rather than from an address, so the
    #: account is named by the assertion that answers rather than by the row.
    user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )

    purpose: str = Field(sa_column=Column(Text, nullable=False))

    attempts: int = Field(
        default=0, sa_column=Column(SmallInteger, nullable=False, server_default="0")
    )

    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )

    consumed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlmodel import Field, Relationship, SQLModel


class UserApiKey(SQLModel, table=True):
    __tablename__ = "user_api_keys"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    name: str = Field(nullable=False, max_length=100)
    token_prefix: str = Field(nullable=False, max_length=16, index=True)
    token_hash: str = Field(nullable=False, unique=True, max_length=128)
    is_active: bool = Field(default=True, nullable=False)
    # Least-privilege scoping for machine credentials (e.g. an MCP server).
    # ``read_only`` keys may only issue safe HTTP methods; a ``guild_id``-bound
    # key is pinned to that one guild. Both default to the legacy full-access
    # behavior so existing keys are unchanged.
    read_only: bool = Field(default=False, nullable=False)
    guild_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    last_used_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    expires_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    user: Optional["User"] = Relationship(back_populates="api_keys")


from app.models.platform.user import User  # noqa: E402

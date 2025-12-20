from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime
from sqlmodel import Field, Relationship, SQLModel


class UserApiKey(SQLModel, table=True):
    __tablename__ = "user_api_keys"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    name: str = Field(nullable=False, max_length=100)
    token_prefix: str = Field(nullable=False, max_length=16, index=True)
    token_hash: str = Field(nullable=False, unique=True, max_length=128)
    is_active: bool = Field(default=True, nullable=False)
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


from app.models.user import User  # noqa: E402


# Backwards compatibility alias
AdminApiKey = UserApiKey

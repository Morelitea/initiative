from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlmodel import Field, Index, SQLModel


class PushToken(SQLModel, table=True):
    """Push notification tokens for mobile devices.

    Stores FCM (Firebase Cloud Messaging) tokens for both Android and iOS.
    iOS tokens are forwarded through FCM to APNS.
    """

    __tablename__ = "push_tokens"
    __table_args__ = (
        # One row per (device, token): re-registering the same token for a user
        # updates the existing row rather than fanning out duplicate pushes.
        Index("ix_push_tokens_user_device_token", "user_id", "push_token", unique=True),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(
        foreign_key="users.id", ondelete="CASCADE", nullable=False, index=True
    )
    # Links to device authentication token (nullable for cases where device token is deleted)
    device_token_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("user_tokens.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    # FCM registration token (Android) or APNS device token (iOS)
    push_token: str = Field(
        sa_column=Column(String(512), nullable=False, index=True),
    )
    # Platform identifier: 'android' or 'ios'
    platform: str = Field(
        sa_column=Column(String(32), nullable=False),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    # Track last successful push delivery for monitoring
    last_used_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

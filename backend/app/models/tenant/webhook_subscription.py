"""Outbound webhook subscription model.

Each row is one auto-side consumer registering for events on this
service. The ``hmac_secret`` is opaque-random per subscription —
shared with the receiver out-of-band on the create-response (and
never returned again) so the receiver can verify the signature on
every inbound delivery without us holding their long-term secret.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, SQLModel


class WebhookSubscription(SQLModel, table=True):
    __tablename__ = "webhook_subscriptions"

    id: Optional[int] = Field(default=None, primary_key=True)

    guild_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    initiative_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    # Soft pointer back to the auto-side workflow this subscription was
    # created for. Not enforced by FK because the source of truth lives
    # in initiative-auto's DB.
    workflow_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )

    created_by_user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )

    target_url: str = Field(sa_column=Column(String(length=2048), nullable=False))
    # Stored opaque-random; never re-emitted after the create response.
    hmac_secret: str = Field(sa_column=Column(String(length=128), nullable=False))
    event_types: list[str] = Field(
        sa_column=Column(ARRAY(String(length=100)), nullable=False),
    )

    active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )

    # TZ-aware columns to match the migration.
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

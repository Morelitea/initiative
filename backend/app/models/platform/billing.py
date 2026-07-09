"""Shared tables backing the external billing service integration.

``BillingEventLog`` is the idempotency claim (UNIQUE ``event_id``, claimed
before the work) and the append-only, actor-attributed record of billing
writes. ``guild_id`` is a weak reference (no FK) so rows outlive the guild.

``BillingJti`` is the one-shot redemption blocklist for billing service
JWTs, mirroring ``auto_delegation_jti_blocklist``. ``expires_at`` mirrors
the JWT ``exp`` so a janitor can prune old rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String
from sqlmodel import Field, SQLModel


class BillingEventLog(SQLModel, table=True):
    __tablename__ = "billing_event_log"

    event_id: str = Field(sa_column=Column(String(length=128), primary_key=True))
    guild_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    op: str = Field(sa_column=Column(String(length=32), nullable=False))
    source: str = Field(sa_column=Column(String(length=32), nullable=False))
    actor: Optional[str] = Field(
        default=None, sa_column=Column(String(length=128), nullable=True)
    )
    applied_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class BillingJti(SQLModel, table=True):
    __tablename__ = "billing_jti_blocklist"

    jti: str = Field(sa_column=Column(String(length=64), primary_key=True))
    redeemed_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )

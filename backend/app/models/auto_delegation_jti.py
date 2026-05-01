"""Blocklist of redeemed delegation JWT ids minted by initiative-auto.

Each row corresponds to a one-time redemption of a delegation token.
A second presentation of the same ``jti`` must be rejected even though
the JWT itself is still within its 15-minute lifetime.

``expires_at`` mirrors the JWT's ``exp`` so a periodic janitor can
keep the table small.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, String
from sqlmodel import Field, SQLModel


class AutoDelegationJti(SQLModel, table=True):
    __tablename__ = "auto_delegation_jti_blocklist"

    # Columns are declared with explicit ``sa_column`` so the ORM emits
    # ``TIMESTAMP WITH TIME ZONE`` casts that match the migration. With a
    # naked ``datetime`` annotation SQLModel infers TZ-naive and asyncpg
    # refuses to bind the TZ-aware values produced by
    # ``datetime.now(timezone.utc)``.
    jti: str = Field(
        sa_column=Column(String(length=64), primary_key=True),
    )
    redeemed_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

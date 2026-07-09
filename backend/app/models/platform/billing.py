"""Shared tables backing the external billing service integration.

``BillingEventLog`` is the idempotency claim (UNIQUE ``event_id``, claimed
before the work) and the append-only, actor-attributed record of billing
writes. ``guild_id`` is a weak reference (no FK) so rows outlive the guild.

``BillingJti`` is the one-shot redemption blocklist for billing service
JWTs, mirroring ``auto_delegation_jti_blocklist``. ``expires_at`` mirrors
the JWT ``exp`` so the shared jti janitor can prune old rows
(``app.services.platform.jti_purge``).

``BillingOp`` / ``BillingSource`` are the closed audit vocabulary shared
with ``initiative_auto``'s ``billing_event_log`` so the two logs correlate
1:1. Values are enum members, never free strings; a value outside the
vocabulary is rejected at the payload layer. No pricing data, tier matrix,
or plan definitions may ever live in this repository — the billing service
owns plan math and pushes only computed numbers.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String
from sqlmodel import Field, SQLModel


class BillingOp(str, Enum):
    """Operations recorded in ``billing_event_log.op``.

    This boundary has exactly one write verb; ``initiative_auto`` carries the
    money-side verbs (``provision`` / ``set_subscription`` / ``add_seat`` /
    ``add_credits``) in its own log with the same source vocabulary.
    """

    guild_tier = "guild_tier"


class BillingSource(str, Enum):
    """Who initiated a billing write — must match ``initiative_auto`` exactly.

    ``support_manual`` is the human support path: it may only *raise* the
    storage cap and must name an ``actor``; the other two are the automated
    paths that alone may touch ``status``.
    """

    paddle_webhook = "paddle_webhook"
    platinum_invoice = "platinum_invoice"
    support_manual = "support_manual"


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

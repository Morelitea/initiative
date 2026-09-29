"""Vendor webhook deliveries an install has accepted.

Initiative receives a vendor's webhooks for an app and forwards each one to the
app's ``webhook`` hook, once for every community it belongs to. A delivery the
install accepted is recorded here by the vendor's delivery id, so a
redelivery is not forwarded to it again. A row lives 24 hours; the outbox
retention pass removes it after that.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlmodel import Field, SQLModel

#: The widest delivery id kept.
DELIVERY_ID_MAX_LENGTH = 200


class AppHookDelivery(SQLModel, table=True):
    __tablename__ = "app_hook_deliveries"

    install_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guild_apps.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    delivery_id: str = Field(
        sa_column=Column(String(length=DELIVERY_ID_MAX_LENGTH), primary_key=True)
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )

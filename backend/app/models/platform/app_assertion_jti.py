"""The ``jti`` of every client assertion an app has presented.

An app authenticates at the token endpoint with a short-lived JWT it signs
(RFC 7523 §2.2). Each assertion is usable once: its ``jti`` is recorded here
until the assertion's own ``exp``, and a second presentation of the same one
meets the primary key.

Keyed by (registration, jti), so each app has its own namespace, and the row
goes with its registration (``ON DELETE CASCADE``). ``expires_at`` mirrors the
assertion's ``exp``: an assertion past it is refused before this table is
consulted, so the shared jti janitor (:mod:`app.services.platform.jti_purge`)
prunes the row.

Lives in ``public`` beside the registrations it hangs off, and is reached only
by the system engine.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlmodel import Field, SQLModel

__all__ = ["AppAssertionJti", "ASSERTION_JTI_MAX_LENGTH"]

#: The widest ``jti`` an assertion may carry.
ASSERTION_JTI_MAX_LENGTH = 128


class AppAssertionJti(SQLModel, table=True):
    __tablename__ = "app_assertion_jtis"

    registration_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("app_service_registrations.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    jti: str = Field(
        sa_column=Column(String(length=ASSERTION_JTI_MAX_LENGTH), primary_key=True)
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )

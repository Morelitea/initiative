"""One-shot nonces spent by the app service request-signing channel.

Every call an app service makes into Initiative carries a signature over its
timestamp, a nonce, and the body. The signature proves the caller holds the
registration's shared secret; this table is what makes each signed request
usable exactly once, so a captured one cannot be presented again inside its
freshness window.

Two column choices carry the meaning:

* **The key is (registration, nonce), not the nonce alone.** Each app has its
  own namespace, so what one app spends never collides with — or consumes —
  another's. The row goes with its registration (``ON DELETE CASCADE``): a
  registration that no longer exists has no requests to guard.
* **``expires_at`` mirrors the end of the request's freshness window.** A
  request whose timestamp has aged out is refused before this table is
  consulted, so a spent row past that point constrains nothing and the shared
  jti janitor (:mod:`app.services.platform.jti_purge`) prunes it.

Lives in ``public``: registrations are platform-wide and carry no guild data.
Reached only by the system engine — the request path has no grant on it.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlmodel import Field, SQLModel

__all__ = ["AppServiceNonce"]


class AppServiceNonce(SQLModel, table=True):
    __tablename__ = "app_service_nonces"

    registration_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("app_service_registrations.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    #: The value the caller sent, bounded to the column width so an oversized
    #: one is refused while verifying rather than at the insert.
    nonce: str = Field(sa_column=Column(String(length=64), primary_key=True))
    # Explicit sa_column so the ORM emits TIMESTAMP WITH TIME ZONE, matching the
    # migration and the TZ-aware values the verifier produces.
    seen_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )

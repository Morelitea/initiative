"""Who publishes the apps this deployment registers.

An app's ``public_id`` is ``<prefix>.<slug>``, and the prefix names its
publisher. A publisher row gives that prefix a name people read, whether the
deployment has confirmed who stands behind it (``verified``), and a switch:
turning a publisher off makes every registration under its prefix not live, in
the same statement that asks whether each one is.

Every registration belongs to exactly one publisher (``publisher_id``). The
deployment's own publisher is seeded at boot; an operator adds one for a
private app's prefix, or it is added, unverified, when a registration names a
prefix no row has yet.

Lives in ``public``: a publisher is deployment configuration and carries no
guild data. It is written on the system engine only. An installed app's
standing reads ``id`` and ``enabled`` of its own registration's publisher.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, String
from sqlmodel import Field, SQLModel

__all__ = [
    "FIRST_PARTY_PUBLISHER_NAME",
    "FIRST_PARTY_PUBLISHER_PREFIX",
    "PUBLISHER_PREFIX_MAX_LENGTH",
    "Publisher",
    "publisher_prefix",
]

#: The widest prefix a publisher may have.
PUBLISHER_PREFIX_MAX_LENGTH = 120

#: The publisher of the apps this project ships, seeded at boot.
FIRST_PARTY_PUBLISHER_PREFIX = "morelitea"
FIRST_PARTY_PUBLISHER_NAME = "Morelitea"


def publisher_prefix(public_id: str) -> str:
    """The publisher half of a ``<prefix>.<slug>`` app id."""
    return public_id.split(".", 1)[0]


class Publisher(SQLModel, table=True):
    """One publisher of app services on this deployment."""

    __tablename__ = "publishers"

    id: Optional[int] = Field(default=None, primary_key=True)
    # The ``public_id`` prefix this publisher's apps carry. Unique: one
    # publisher per prefix.
    prefix: str = Field(
        sa_column=Column(
            String(PUBLISHER_PREFIX_MAX_LENGTH), nullable=False, unique=True
        )
    )
    display_name: str = Field(sa_column=Column(String(200), nullable=False))
    # Whether the deployment has confirmed who this publisher is.
    verified: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # The kill switch for every app under this prefix.
    enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

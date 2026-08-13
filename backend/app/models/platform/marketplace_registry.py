"""State the registry client keeps between refreshes.

Two `public` tables, both operator/system state rather than tenant data:

* :class:`MarketplaceRegistryState` — one row per registry URL, recording the
  last index this deployment accepted. The serial and the index digest live
  here rather than in process memory because they are what makes a replay of an
  older index detectable: a value that resets whenever the process restarts
  would answer "is this index newer than the last one?" with "yes" every boot,
  and a rolling deploy would answer differently on every replica.
* :class:`MarketplaceMedia` — the artwork a verified index named, mirrored
  locally and addressed by its own SHA-256. Listing media is served from this
  deployment, so a stored listing never carries a URL pointing at somebody
  else's host.

Neither table names a guild — like the catalog they describe, both are
platform-wide, and their only writer is the system engine.
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import ConfigDict
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlmodel import Field, SQLModel

#: A hex SHA-256 digest is always this long, and the columns holding one are
#: sized to it exactly.
DIGEST_LENGTH = 64


class MarketplaceRegistryState(SQLModel, table=True):
    """What this deployment last accepted from one registry."""

    __tablename__ = "marketplace_registry_state"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    # Which registry this row is about. Unique, so pointing a deployment at a
    # different registry starts from a clean slate rather than inheriting
    # another registry's serial — serials are only comparable within the
    # publisher that issues them.
    registry_url: str = Field(
        sa_column=Column(String(2000), nullable=False, unique=True)
    )
    # The key id that signed the last accepted index. Recorded so an operator
    # can see which key is live, and so a rotation is visible after the fact.
    key_id: Optional[str] = Field(default=None, sa_column=Column(String(128)))

    # The index counter, as published. Must not go backwards.
    last_serial: Optional[int] = Field(default=None, sa_column=Column(BigInteger))
    # SHA-256 of the accepted index bytes. Together with the serial this
    # distinguishes "the same index again" (nothing to do) from "different
    # content published under a serial that was already used".
    last_index_sha256: Optional[str] = Field(
        default=None, sa_column=Column(String(DIGEST_LENGTH))
    )
    # The index's own timestamp, as published.
    last_generated_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )

    # When a refresh last ran, whatever its outcome.
    last_fetched_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    # When a refresh last completed with every listing in the index ingested.
    last_success_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    # Message code of the last refusal, or NULL after a clean run. A non-NULL
    # value also tells the next refresh to re-ingest the same serial rather
    # than treat it as already applied.
    last_error: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    # How many listings the last accepted index carried.
    listing_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class MarketplaceMedia(SQLModel, table=True):
    """One mirrored listing image, addressed by the digest of its bytes.

    Content-addressed, so re-publishing an unchanged image is a no-op and the
    serving URL can be cached forever. The bytes are small (icons and
    screenshots) and platform-wide rather than per-guild, which is why they
    live in Postgres beside the catalog rather than in the guild blob store.
    """

    __tablename__ = "marketplace_media"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    sha256: str = Field(
        sa_column=Column(String(DIGEST_LENGTH), nullable=False, unique=True)
    )
    # Taken from the signed index, not from the response that delivered the
    # bytes, and restricted to a small set of raster image types.
    content_type: str = Field(sa_column=Column(String(64), nullable=False))
    byte_size: int = Field(sa_column=Column(Integer, nullable=False))
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    # Where the bytes came from, for support questions about a mirrored image.
    source_url: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

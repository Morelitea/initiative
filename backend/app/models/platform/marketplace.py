"""The marketplace catalog — what is *installable*, platform-wide.

Two `public` tables. They hold catalog metadata only: a listing's identity,
its artwork, and the reference definition at each published version. There is
deliberately **no `guild_id` column anywhere here** — installs are per-guild
data and stay in the guild's own schema, so the catalog carries none of it.

Guild-schema serials restart per guild, so a shared surface cannot key anything
off a local id. `uid` is the catalog's answer: a publisher-assigned, immutable
14-character code that means the same listing on every deployment carrying that
catalog. Instances need no uid — one is already addressable as
`/g/{guild_id}/dashboards/{id}` — they just store `listing_uid` to point back at
where they came from, which is what keeps provenance across an export/import.

Writes happen on the system-engine path only (boot seeding, and later the
registry refresh). A user request reads the catalog and writes its own guild
schema; nothing about installing a listing writes here.
"""

from datetime import datetime, timezone
from typing import Any, List, Optional, TYPE_CHECKING

from pydantic import ConfigDict
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:  # pragma: no cover
    pass

#: Length of a listing uid. Crockford base32 at 14 characters is short enough to
#: read aloud or print, and long enough that codes are not guessable.
UID_LENGTH = 14

#: Crockford base32 minus the letters it treats as ambiguous (I, L, O, U), so a
#: code can be transcribed by hand without a legend.
UID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class MarketplaceListing(SQLModel, table=True):
    """One installable product, at whatever versions it has published."""

    __tablename__ = "marketplace_listings"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    # The catalog UPC. Assigned by the publisher and carried in the manifest —
    # minting it per deployment would make the code deployment-specific, so a
    # shared link or a printed code would resolve to nothing anywhere else.
    # UNIQUE and never reassigned: a uid keeps meaning the listing it was first
    # published for.
    uid: str = Field(sa_column=Column(String(UID_LENGTH), nullable=False, unique=True))
    # Human-readable identity: 'core.project-health', '<publisher>.<slug>'.
    public_id: str = Field(sa_column=Column(String(120), nullable=False, unique=True))
    kind: str = Field(sa_column=Column(String(16), nullable=False, index=True))
    source: str = Field(sa_column=Column(String(16), nullable=False))

    name: str = Field(sa_column=Column(String(200), nullable=False))
    # Who publishes it, and the namespace it publishes under. Required, so the
    # question "who is this from?" is answered before install rather than after;
    # NOT NULL, so the requirement holds at the database as well as in the
    # validator. A registry binds this prefix to the key that signed its index.
    publisher: str = Field(sa_column=Column(String(200), nullable=False))
    description: str = Field(sa_column=Column(String(500), nullable=False))
    long_description: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    # Custom art, required: a listing is branded, not a default icon.
    avatar_url: str = Field(sa_column=Column(String(2000), nullable=False))
    images: List[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
    )

    latest_version_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            # SET NULL rather than CASCADE: losing the pointer must never take
            # the listing with it.
            ForeignKey(
                "marketplace_listing_versions.id",
                ondelete="SET NULL",
                # The two tables point at each other, so neither can be created
                # with both constraints in place; `use_alter` adds this one
                # afterwards, which is what the migration does by hand.
                use_alter=True,
                name="fk_marketplace_listings_latest_version",
            ),
            nullable=True,
        ),
    )
    # A cumulative count of installs on this deployment. Just the number: no
    # guild is recorded. Uninstalling does not decrement.
    installs_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    # Set on a dashboard listing an app ships with itself; NULL on anything
    # published on its own.
    #
    # A bundled dashboard is an ordinary listing in every other respect — same
    # kind, same uid rules, installed by the same call — because a dashboard
    # somebody publishes to share and a dashboard that arrives with an app are
    # the same thing to the guild installing it. This column carries the two
    # ways they differ: it is offered only to guilds that have that app, and it
    # is published and withdrawn with the app rather than on its own.
    #
    # The uid rather than a foreign key. Both rows come from one manifest, and a
    # referential cascade here would be a second mechanism for a lifecycle the
    # publish already owns.
    bundled_with_uid: Optional[str] = Field(
        default=None,
        sa_column=Column(String(UID_LENGTH), nullable=True, index=True),
    )
    # False once a registry withdraws a listing. Never deleted: installed
    # instances keep working and keep their provenance.
    available: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    versions: List["MarketplaceListingVersion"] = Relationship(
        back_populates="listing",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "foreign_keys": "MarketplaceListingVersion.listing_id",
        },
    )


class MarketplaceListingVersion(SQLModel, table=True):
    """One published version of a listing, with the definition it ships.

    The definition lives here so the catalog is self-describing and installing is
    a pure server-side copy — nothing a client sends decides what gets stored.
    The installed instance keeps its own snapshot, so a new version reaches a
    guild only when someone there chooses it.
    """

    __tablename__ = "marketplace_listing_versions"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)
    __table_args__ = (
        # A listing publishes each version string once.
        UniqueConstraint("listing_id", "version"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    listing_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("marketplace_listings.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    version: str = Field(sa_column=Column(String(32), nullable=False))
    definition: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    release_notes: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    # Compared against this deployment's VERSION. A version that needs a newer
    # app is hidden from browse and refused on upgrade, rather than installing
    # something that cannot render.
    min_app_version: Optional[str] = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )
    published_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    listing: Optional[MarketplaceListing] = Relationship(
        back_populates="versions",
        sa_relationship_kwargs={"foreign_keys": "MarketplaceListingVersion.listing_id"},
    )

"""Deployment-level registrations for external app services.

A marketplace **listing** says what an app is and what it declares. A
**registration** is the separate, operator-owned statement that a particular
deployment has wired that app up: which listing it is, where it lives, the
public keys it signs with, and the powers the operator confers on it. Nothing
in this table can be claimed by a manifest — a publisher describes their app,
an operator decides what this deployment does with it.

A registration holds no secret. Every call the app makes to Initiative is a
JWT it signs with a key published here (``jwks``, or ``jwks_uri`` on its own
origin), and every call Initiative makes to the app is a JWT under the app
platform's own key.

Some columns exist only because of that split:

* ``listing_uid`` — the catalog listing this registration speaks for, stated
  by whoever registers the app. It is what ties the registration to the
  installs it may reach.
* ``publisher_id`` — the publisher the ``public_id`` prefix names
  (:mod:`app.models.platform.publisher`). Its switch outranks the
  registration's own.
* ``grants`` — powers beyond what any app gets by default, from a closed
  vocabulary. Conferring one is an operator edit; revoking it is the same edit
  in reverse.

  * ``delegation`` — the holder may call Initiative's API as a real user, under
    that user's own gates.
  * ``app_directory`` — the holder may ask where *another* installed app's
    service answers. Separate from ``delegation`` because the two confer
    different things: an app that acts for its own members has no call to read
    another app's address. An automation service holds both, because acting on
    one app's behalf at another is what it is for.
* ``scope_ceiling`` — the most any install of this app may be granted, from
  the app scope vocabulary (``app.core.app_scopes``). A community's seat grants
  within it; nothing outside it can be granted. Empty means nothing may be.
* ``mandatory`` — the deployment asserts this app is part of what it *is*, so
  every guild has it and guild admins cannot remove it. The operator's kill
  switch (``enabled``) still outranks it.

**Live** is one rule, stated once in :func:`registration_live_sql`: the
registration is enabled, its publisher is enabled, it has a location, and it
has a key set to verify against. The install standing, the registration
snapshot and every channel that reads a single row ask it in that form.

**Where it came from** is ``source``. An operator's row (``apps.manage``
endpoints, or ``APP_SERVICES_CONFIG`` at boot) is theirs entirely. A registry
row (``source='registry'``) is written by the registry refresh from a verified
listing: the listing it speaks for, its keys, its ceiling, its reference
sectors, and either the image it runs (a container) or where it is hosted. The
operator keeps the kill switch, the grants, the mandatory flag, the origin
list and, for a container, its location.

Lives in ``public``: a registration is platform-wide and carries no guild data.
It is written on the system engine by ``apps.manage`` (owner) endpoints, by
boot reconciliation from ``APP_SERVICES_CONFIG``, and by the registry refresh.
"""

from datetime import datetime, timezone
from typing import List, Optional, Protocol

from pydantic import ConfigDict
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlmodel import Field, SQLModel

from app.models.platform.identity_ref import IdentityPurpose

__all__ = [
    "APP_SERVICE_GRANTS",
    "IMAGE_REFERENCE_MAX_LENGTH",
    "MAX_APP_ID_LENGTH",
    "REFERENCE_SECTORS",
    "AppServiceRegistration",
    "BrowserAddressed",
    "RegistrationSource",
    "browser_base",
    "registration_live_sql",
]

#: The closed vocabulary of operator-conferred powers. A value outside this set
#: is refused on write rather than stored as something no code resolves — the
#: same "declare it or it does not exist" rule the listing validator applies.
APP_SERVICE_GRANTS: frozenset[str] = frozenset({"delegation", "app_directory"})

#: The widest ``public_id`` a registration may carry. An app id longer than
#: this cannot name a registration, so it is refused without a query.
MAX_APP_ID_LENGTH = 120

#: The widest container image reference stored.
IMAGE_REFERENCE_MAX_LENGTH = 500

#: The sectors a registration may name in ``reference_sectors``: the other
#: parties this deployment keeps its own reference for a community in, which
#: an app may be allowed to learn. A sector outside this set is dropped.
REFERENCE_SECTORS: frozenset[str] = frozenset({IdentityPurpose.billing.value})


class RegistrationSource:
    """Where a registration row came from."""

    #: The ``apps.manage`` endpoints or ``APP_SERVICES_CONFIG``.
    OPERATOR = "operator"
    #: The registry refresh, from a verified listing.
    REGISTRY = "registry"


def registration_live_sql(
    registration: str = "app_service_registrations", publisher: str = "publishers"
) -> str:
    """Whether a registration is live, as a SQL boolean over one registration
    row and its publisher's row, named by ``registration`` and ``publisher``.

    Enabled, its publisher enabled, a location, and a key set to verify
    against: a pasted set with at least one key, or a key set address. ``-> 0``
    reads the first key and is null for an empty or absent set.

    Only a registry container registration can lack a location: the registry
    names the image, and the operator says where it runs.
    """
    return (
        f"({registration}.enabled AND {publisher}.enabled"
        f" AND {registration}.base_url IS NOT NULL"
        f" AND ({registration}.jwks_uri IS NOT NULL"
        f" OR {registration}.jwks -> 'keys' -> 0 IS NOT NULL))"
    )


class AppServiceRegistration(SQLModel, table=True):
    """One app service this deployment has wired up."""

    __tablename__ = "app_service_registrations"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    # '<publisher>.<slug>', matching the listing's public_id. Unique: one
    # registration per app per deployment.
    public_id: str = Field(
        sa_column=Column(String(MAX_APP_ID_LENGTH), nullable=False, unique=True)
    )
    # The catalog uid of the listing this registration speaks for, stated by
    # whoever registers the app. Nullable only for rows that predate the rule
    # and never named one; such a row reaches no install.
    listing_uid: Optional[str] = Field(
        default=None, sa_column=Column(String(14), nullable=True, index=True)
    )
    # The publisher the public_id's prefix names.
    publisher_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("publishers.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
    )
    # Base of the service's wire surface: its data and lifecycle endpoints
    # hang off it, and a ``jwks_uri`` must share its origin. Every consumer of
    # this column is Initiative's own server calling the app. NULL only on a
    # registry container registration the operator has not placed yet, which
    # is not live until they do.
    base_url: Optional[str] = Field(
        default=None, sa_column=Column(String(1000), nullable=True)
    )
    # Base of the service's browser surface: the iframe an embed opens and the
    # page a member is sent to for an interactive connection. Unset means the
    # app answers both surfaces at one address, which is the ordinary case and
    # what every registration written before this column existed says.
    embed_origin: Optional[str] = Field(
        default=None, sa_column=Column(String(1000), nullable=True)
    )
    # Origins this app's embedded surfaces may be framed from and postMessage'd
    # to. Defaults to the browser base's own origin.
    allowed_origins: List[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
    )
    # Operator-conferred powers (see module docstring). Validated against
    # APP_SERVICE_GRANTS on every write.
    grants: List[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
    )
    # Public half of the keys this app signs with, in JWKS shape: the client
    # assertions it presents at the token endpoint, and its delegation tokens.
    # A set rather than one key because an app rotates by publishing the
    # replacement alongside the current entry while JWTs signed by the first
    # drain out; every entry carries a ``kid``, which is what a JWT names.
    # Public keys only. Null on an app that has not been provisioned with one.
    jwks: Optional[dict] = Field(default=None, sa_column=Column(JSONB, nullable=True))
    # Where the app publishes that key set instead, on ``base_url``'s own
    # origin over https. Fetched and cached for a minute; either or both may
    # be set, and a key found in either verifies.
    jwks_uri: Optional[str] = Field(
        default=None, sa_column=Column(String(1000), nullable=True)
    )
    # The most an install of this app may be granted (see module docstring).
    # Validated against ``app.core.app_scopes`` on every write.
    scope_ceiling: List[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, server_default=text("'{}'")),
    )
    # Auto-installed into every guild and not removable by guild admins.
    mandatory: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # The operator's kill switch. False stops every channel this app has.
    enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    # Where the row came from (``RegistrationSource``).
    source: str = Field(
        default=RegistrationSource.OPERATOR,
        sa_column=Column(String(16), nullable=False, server_default="operator"),
    )
    # The container image a registry listing names, pinned by digest
    # (``<repository>@sha256:<hex>``). NULL for every other registration.
    image_digest: Optional[str] = Field(
        default=None,
        sa_column=Column(String(IMAGE_REFERENCE_MAX_LENGTH), nullable=True),
    )
    # Which of this deployment's other sectors the app may learn a community's
    # reference in. Written only by the registry; empty everywhere else.
    reference_sectors: List[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, server_default=text("'{}'")),
    )
    # Whether the registry listing behind this row was verified under the root
    # shipped in the image. Reference sectors are honoured only when it was.
    root_is_builtin: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class BrowserAddressed(Protocol):
    """Anything carrying a registration's two addresses.

    The row and the request path's snapshot of it both do, and both need the
    same answer, so the rule that relates them is written once.
    """

    base_url: str
    embed_origin: Optional[str]


def browser_base(registration: BrowserAddressed) -> str:
    """The base a person's browser resolves for this app's surfaces.

    ``embed_origin`` when the deployment gave one, ``base_url`` otherwise — an
    app reachable at a single address needs no second field to say so.
    """
    return registration.embed_origin or registration.base_url

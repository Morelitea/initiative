"""Deployment-level registrations for external app services.

A marketplace **listing** says what an app is and what it declares. A
**registration** is this deployment's record that it runs that app. Every app
splits the same way, whatever published its listing:

* **App facts** come from the app's listing, and only a listing apply writes
  them: ``listing_uid``, ``scope_ceiling``, ``image_digest``,
  ``reference_sectors`` and ``compose``. Every source reads the same
  ``registration`` block (the registry, a local upload, the operator's catalog
  directory, the build).
* **Deployment facts** come from the operator, through ``PLUGIN_SERVICES_CONFIG``
  or the settings form: where the app runs, the public keys its container signs
  with, its vendor values, the switch, the mandatory flag and the origins.

A registration holds no secret beyond its vendor values. Every call the app
makes to Initiative is a JWT it signs with a key published here (``jwks``, or
``jwks_uri`` on its own origin), and every call Initiative makes to the app is
a JWT under the app platform's own key.

Some columns exist only because of that split:

* ``listing_uid`` — the catalog listing this registration's app facts come
  from. It is what ties the registration to the installs it may reach. Null on
  a registration the operator set up before its listing arrived.
* ``publisher_id`` — the publisher the ``public_id`` prefix names
  (:mod:`app.models.platform.publisher`). Its switch outranks the
  registration's own.
* ``scope_ceiling`` — the most any install of this app may be granted, from
  the app scope vocabulary (``app.core.plugin_scopes``). A community's seat grants
  within it; nothing outside it can be granted. Empty means nothing may be.
* ``mandatory`` — the deployment asserts this app is part of what it *is*, so
  every guild has it and guild admins cannot remove it. The operator's kill
  switch (``enabled``) still outranks it.

* ``vendor_values`` — what the operator supplies for the app's vendor client,
  as the listing's manifest declares it under ``vendor``: one Fernet
  ciphertext per field. ``vendor_ready`` is whether every field the manifest
  requires (``vendor_required``) holds one, computed by the database.

* ``kind`` — ``container`` for an app Initiative calls, ``declarative`` for
  one whose calls Initiative makes itself from its manifest. A declarative
  app's registration has no location and no keys.

**Live** is one rule, stated once in :func:`registration_live_sql`: the
registration is enabled, its publisher is enabled, its required vendor values
are set and, for a container, it has a location and a key set to verify
against.
The install standing, the registration snapshot and every channel that reads
a single row ask it in that form.

**Where its app facts came from** is ``source``: ``registry`` for a listing
the registry signed, ``operator`` for a listing this deployment published
itself, or for a registration whose listing has not arrived yet.

Lives in ``public``: a registration is platform-wide and carries no guild data.
It is written on the system engine by ``apps.manage`` (owner) endpoints, by
boot reconciliation from ``PLUGIN_SERVICES_CONFIG``, and by listing applies.
"""

from datetime import datetime, timezone
from typing import List, Optional, Protocol

from pydantic import ConfigDict
from sqlalchemy import (
    Boolean,
    Column,
    Computed,
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
    "IMAGE_REFERENCE_MAX_LENGTH",
    "LISTING_STATED_FIELDS",
    "MAX_PLUGIN_ID_LENGTH",
    "REFERENCE_SECTORS",
    "PluginServiceRegistration",
    "RegistrationKind",
    "BrowserAddressed",
    "RegistrationSource",
    "browser_base",
    "registration_live_sql",
]

#: The widest ``public_id`` a registration may carry. An app id longer than
#: this cannot name a registration, so it is refused without a query.
MAX_PLUGIN_ID_LENGTH = 120

#: The widest container image reference stored.
IMAGE_REFERENCE_MAX_LENGTH = 500

#: The sectors a registration may name in ``reference_sectors``: the other
#: parties this deployment keeps its own reference for a community in, which
#: an app may be allowed to learn. A sector outside this set is dropped.
REFERENCE_SECTORS: frozenset[str] = frozenset({IdentityPurpose.billing.value})

#: What only an app's listing states. An ``PLUGIN_SERVICES_CONFIG`` entry or a
#: settings request naming one is refused: it gives deployment facts only.
LISTING_STATED_FIELDS: tuple[str, ...] = (
    "listing_uid",
    "kind",
    "scope_ceiling",
    "image",
    "image_digest",
    "reference_sectors",
    "registry",
    "compose",
)


class RegistrationKind:
    """Which kind of app a registration is for, as its listing says."""

    #: Initiative calls the app's container.
    CONTAINER = "container"
    #: Initiative makes the app's calls itself, from its manifest.
    DECLARATIVE = "declarative"


class RegistrationSource:
    """Where a registration's app facts came from."""

    #: A listing this deployment published itself, or none yet.
    OPERATOR = "operator"
    #: A listing the registry signed.
    REGISTRY = "registry"


def registration_live_sql(
    registration: str = "plugin_service_registrations", publisher: str = "publishers"
) -> str:
    """Whether a registration is live, as a SQL boolean over one registration
    row and its publisher's row, named by ``registration`` and ``publisher``.

    Enabled, its publisher enabled, and every required vendor value set; and
    for a container, a location and a key set to verify against (a pasted set
    with at least one key, or a key set address). ``-> 0`` reads the first key
    and is null for an empty or absent set.

    A container's registration lacks both until the operator gives them: its
    listing names the app, and the operator says where it runs and which keys
    it signs with. A declarative app runs nowhere and signs nothing.
    """
    return (
        f"({registration}.enabled AND {publisher}.enabled"
        f" AND {registration}.vendor_ready"
        f" AND ({registration}.kind = '{RegistrationKind.DECLARATIVE}'"
        f" OR ({registration}.base_url IS NOT NULL"
        f" AND ({registration}.jwks_uri IS NOT NULL"
        f" OR {registration}.jwks -> 'keys' -> 0 IS NOT NULL))))"
    )


class PluginServiceRegistration(SQLModel, table=True):
    """One app service this deployment has wired up."""

    __tablename__ = "plugin_service_registrations"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    # '<publisher>.<slug>', matching the listing's public_id. Unique: one
    # registration per app per deployment.
    public_id: str = Field(
        sa_column=Column(String(MAX_PLUGIN_ID_LENGTH), nullable=False, unique=True)
    )
    # The catalog uid of the listing this registration's app facts come from,
    # written by that listing's apply. Null until the listing arrives; such a
    # row reaches no install.
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
    # this column is Initiative's own server calling the app. NULL until the
    # operator places it, and not live until they do.
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
    # Public half of the keys this app signs with, in JWKS shape: the client
    # assertions it presents at the token endpoint.
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
    # The most an install of this app may be granted (see module docstring),
    # from its listing. Only scopes ``app.core.plugin_scopes`` defines are kept.
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
    # Which kind of app it is for (``RegistrationKind``), from its listing.
    kind: str = Field(
        default=RegistrationKind.CONTAINER,
        sa_column=Column(String(16), nullable=False, server_default="container"),
    )
    # Where its app facts came from (``RegistrationSource``).
    source: str = Field(
        default=RegistrationSource.OPERATOR,
        sa_column=Column(String(16), nullable=False, server_default="operator"),
    )
    # The container image its listing names, pinned by digest
    # (``<repository>@sha256:<hex>``). NULL when the listing names none.
    image_digest: Optional[str] = Field(
        default=None,
        sa_column=Column(String(IMAGE_REFERENCE_MAX_LENGTH), nullable=True),
    )
    # Which of this deployment's other sectors the app may learn a community's
    # reference in. Honoured only from a registry listing; empty otherwise.
    reference_sectors: List[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, server_default=text("'{}'")),
    )
    # The Compose service its listing's publisher wrote for running the app
    # beside Initiative: ``{"service": <YAML text>, "base_url": <address on
    # the Compose network>}``, its placeholders unfilled. NULL when the listing
    # carries none.
    compose: Optional[dict] = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    # Whether the registry listing behind this row was verified under the root
    # shipped in the image. Reference sectors are honoured only when it was.
    root_is_builtin: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # What the operator supplies for the app's vendor client, by the key the
    # listing's manifest declares under ``vendor``. Every value is a Fernet
    # ciphertext under ``SALT_PLUGIN_VENDOR``, secret or not.
    vendor_values: dict = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )
    # The keys the listing's manifest marks required, kept in step whenever the
    # registration or its listing is written.
    vendor_required: List[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, server_default=text("'{}'")),
    )
    # Whether every required key holds a value. Computed by the database.
    vendor_ready: Optional[bool] = Field(
        default=None,
        sa_column=Column(
            Boolean,
            Computed("vendor_values ?& vendor_required", persisted=True),
            nullable=False,
        ),
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

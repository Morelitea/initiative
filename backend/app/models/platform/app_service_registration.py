"""Deployment-level registrations for external app services.

A marketplace **listing** says what an app is and what it declares. A
**registration** is the separate, operator-owned statement that a particular
deployment has wired that app up: where it lives, the shared secret both ends
hold, and the powers the operator confers on it. Nothing in this table can be
claimed by a manifest — a publisher describes their app, an operator decides
what this deployment does with it.

Two columns exist only because of that split:

* ``grants`` — powers beyond what any app gets by default, from a closed
  vocabulary. Conferring one is an operator edit; revoking it is the same edit
  in reverse.

  * ``delegation`` — the holder may call Initiative's API as a real user, under
    that user's own gates.
  * ``app_directory`` — the holder may ask where *another* installed app's
    service answers. Separate from ``delegation`` because they are different
    powers: an app that acts for its own members has no call to learn the
    deployment's wiring for anybody else's app. An automation service holds
    both, because acting on one app's behalf at another is what it is for.
* ``mandatory`` — the deployment asserts this app is part of what it *is*, so
  every guild has it and guild admins cannot remove it. The operator's kill
  switch (``enabled``) still outranks it.

Lives in ``public``: a registration is platform-wide and carries no guild data.
It is written on the system engine by ``apps.manage`` (owner) endpoints and by
boot reconciliation from ``APP_SERVICES_CONFIG``.
"""

from datetime import datetime, timezone
from typing import List, Optional, Protocol

from pydantic import ConfigDict
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

__all__ = [
    "APP_SERVICE_GRANTS",
    "APP_SERVICE_STATUSES",
    "AppServiceRegistration",
    "AppServiceStatus",
    "BrowserAddressed",
    "ServiceState",
    "browser_base",
    "is_live",
]


class AppServiceStatus:
    """What the last verification attempt concluded.

    ``unverified`` is the resting state of a row that has never completed a
    handshake — a declaratively wired app whose container has not booted yet is
    the ordinary case, not an error.
    """

    UNVERIFIED = "unverified"
    OK = "ok"
    #: The service could not be reached, or answered in a shape that is not a
    #: manifest document at all.
    UNREACHABLE = "unreachable"
    #: A manifest was served but this build will not accept it, or its hash no
    #: longer matches the one recorded at registration.
    MANIFEST_MISMATCH = "manifest_mismatch"
    #: The challenge came back signed with a different secret than ours.
    SIGNATURE_MISMATCH = "signature_mismatch"


#: Every value ``status`` may hold.
APP_SERVICE_STATUSES: frozenset[str] = frozenset(
    {
        AppServiceStatus.UNVERIFIED,
        AppServiceStatus.OK,
        AppServiceStatus.UNREACHABLE,
        AppServiceStatus.MANIFEST_MISMATCH,
        AppServiceStatus.SIGNATURE_MISMATCH,
    }
)

#: The closed vocabulary of operator-conferred powers. A value outside this set
#: is refused on write rather than stored as something no code resolves — the
#: same "declare it or it does not exist" rule the listing validator applies.
APP_SERVICE_GRANTS: frozenset[str] = frozenset({"delegation", "app_directory"})


class AppServiceRegistration(SQLModel, table=True):
    """One app service this deployment has wired up."""

    __tablename__ = "app_service_registrations"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    # '<publisher>.<slug>', matching the listing's public_id. Unique: one
    # registration per app per deployment.
    public_id: str = Field(sa_column=Column(String(120), nullable=False, unique=True))
    # The catalog uid the served manifest claims. Recorded on the first
    # successful handshake, so it is unset on a row that has never verified.
    listing_uid: Optional[str] = Field(
        default=None, sa_column=Column(String(14), nullable=True, index=True)
    )
    # Base of the service's wire surface: the well-known manifest, the
    # handshake, and later the data/lifecycle endpoints all hang off it. Every
    # consumer of this column is Initiative's own server calling the app.
    base_url: str = Field(sa_column=Column(String(1000), nullable=False))
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
    # Fernet ciphertext of the shared HMAC secret. Nullable so an operator can
    # clear it without deleting the row; a registration with no secret cannot
    # complete a handshake.
    secret_encrypted: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    # sha256 of the canonical manifest bytes at the last successful handshake.
    manifest_hash: Optional[str] = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    protocol_version: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    # Operator-conferred powers (see module docstring). Validated against
    # APP_SERVICE_GRANTS on every write.
    grants: List[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
    )
    # Public half of the key this app signs delegation tokens with, in JWKS
    # shape. A set rather than one key because an app rotates by publishing the
    # replacement alongside the current entry while tokens signed by the first
    # drain out; every entry carries a ``kid``, which is what a token names.
    # Public keys only. Null on an app that does not delegate: the column is
    # kept only while ``grants`` holds ``delegation``, so taking the grant away
    # takes the keys with it rather than leaving a set nothing displays.
    delegation_jwks: Optional[dict] = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
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
    status: str = Field(
        default=AppServiceStatus.UNVERIFIED,
        sa_column=Column(String(32), nullable=False, server_default="unverified"),
    )
    last_verified_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
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


class ServiceState(Protocol):
    """Anything carrying a registration's two state columns.

    Like :class:`BrowserAddressed`, satisfied by both the row and the request
    path's snapshot of it, so the rule below is written once and every channel
    reads the same answer.
    """

    enabled: bool
    status: str


def is_live(registration: ServiceState) -> bool:
    """Whether anything may flow through this app right now.

    Two conditions, and both are the operator's: the kill switch is on, and the
    last verification concluded that the service answering is the one this
    deployment registered. A row that has never handshaken is ``unverified`` and
    is not live — there is no confirmed manifest behind it to have declared
    anything.
    """
    return registration.enabled and registration.status == AppServiceStatus.OK

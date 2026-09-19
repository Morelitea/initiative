from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlmodel import Field, SQLModel


class AuthProviderKind(str, Enum):
    """Which relying-party flow an auth provider speaks.

    ``oidc`` — a standards-compliant OpenID Connect provider (discovery + PKCE).
    ``oauth2`` — a plain OAuth2 provider without OIDC discovery (e.g. GitHub).
    ``broker`` — a federation broker that fronts many upstream IdPs (cloud);
    carries a ``connection_claim`` naming the tenant it authenticated.
    """

    oidc = "oidc"
    oauth2 = "oauth2"
    broker = "broker"


# Mirror the CHECK constraint declared in the migration. Keep in sync with
# ``20260705_0131_create_auth_identity_tables.py``.
AUTH_PROVIDER_KINDS: tuple[str, ...] = tuple(k.value for k in AuthProviderKind)


class AuthProvider(SQLModel, table=True):
    """A configured identity source Initiative acts as a relying party to.

    Every row is the **operator's**. A community does not own a provider; it
    owns a :class:`~app.models.platform.guild_provider_connection.GuildProviderConnection`
    to one, optionally narrowed to its own tenant. So the operator says *this
    deployment can sign people in with Google*, and a community says *our
    members come in through that, and only our workspace*.

    A community bringing its own identity provider is the same shape: the
    operator registers it when they onboard them, and the community connects.
    That way nobody outside this registry supplies an issuer, a client id or a
    secret.

    Metadata only — the client *secret* lives in a separate, ``app_admin``-only
    companion table; nothing here is sensitive (``issuer``/``client_id`` are
    public in OIDC).
    """

    __tablename__ = "auth_providers"
    __table_args__ = (
        # One registry, so one namespace. A slug is in the sign-in URLs, so it
        # never changes once saved.
        UniqueConstraint("slug", name="uq_auth_providers_slug"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    slug: str = Field(sa_column=Column(String(64), nullable=False))
    display_name: str = Field(sa_column=Column(String(128), nullable=False))
    kind: str = Field(
        sa_column=Column(
            String(16), nullable=False, server_default=AuthProviderKind.oidc.value
        )
    )
    enabled: bool = Field(
        sa_column=Column(Boolean, nullable=False, server_default=text("false"))
    )

    # OIDC / OAuth2 discovery + client identity (non-secret).
    issuer: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    client_id: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    scopes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    role_claim_path: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # Broker only: the claim carrying the upstream tenant id (e.g. organization_id).
    connection_claim: Optional[str] = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )

    # Just-in-time provisioning of unknown users on first login.
    allow_jit: bool = Field(
        sa_column=Column(Boolean, nullable=False, server_default=text("true"))
    )

    # Login-button rendering.
    icon: Optional[str] = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    button_style: Optional[str] = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        # onupdate (Python-side, no DDL) so provider CRUD in Phase 1 bumps this
        # automatically — the codebase otherwise sets updated_at in the service,
        # which a future endpoint could forget.
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            onupdate=lambda: datetime.now(timezone.utc),
        ),
    )

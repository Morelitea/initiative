from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, Text
from sqlmodel import Field, SQLModel


class AuthProviderSecret(SQLModel, table=True):
    """The client secret for one auth provider — kept OUT of ``auth_providers``.

    A companion table read and written only by the system engine. Provider
    metadata (``issuer``/``client_id`` — public in OIDC) stays on
    ``auth_providers``; only the secret lives here.

    1:1 with the provider — ``provider_id`` is the PK and an FK to
    ``auth_providers.id`` (``ON DELETE CASCADE``, declared in the migration).
    ``client_secret_encrypted`` is Fernet-encrypted at rest with
    ``SALT_OIDC_CLIENT_SECRET`` (registered in the secret-key rotation registry);
    it is ``NULL`` for public / PKCE-only providers with no secret.
    """

    __tablename__ = "auth_provider_secrets"

    # PK + FK to auth_providers (ON DELETE CASCADE declared in the migration).
    provider_id: int = Field(sa_column=Column(Integer, primary_key=True))

    client_secret_encrypted: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        # onupdate (Python-side, no DDL) so secret rotation via the provider-CRUD
        # service bumps this without the endpoint having to remember.
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            onupdate=lambda: datetime.now(timezone.utc),
        ),
    )

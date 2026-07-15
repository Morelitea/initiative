from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, Text
from sqlmodel import Field, SQLModel


class FederatedIdentitySecret(SQLModel, table=True):
    """The IdP refresh token for one federated identity.

    A companion table to ``federated_identities`` (the ``auth_provider_secrets``
    pattern): link metadata stays on the main table, the token lives here and is
    read and written only by the system engine.

    1:1 with the identity link — ``identity_id`` is the PK and an FK to
    ``federated_identities.id`` (``ON DELETE CASCADE``, declared in the
    migration). ``refresh_token_encrypted`` is Fernet-encrypted at rest and
    registered in the secret-key rotation registry; it is ``NULL`` when the IdP
    issued no refresh token or the token was revoked.
    """

    __tablename__ = "federated_identity_secrets"

    # PK + FK to federated_identities (ON DELETE CASCADE declared in the migration).
    identity_id: int = Field(sa_column=Column(Integer, primary_key=True))

    refresh_token_encrypted: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        # onupdate (Python-side, no DDL) so token rotation in the background
        # re-sync bumps this without the caller having to remember.
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            onupdate=lambda: datetime.now(timezone.utc),
        ),
    )

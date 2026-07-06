import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    ARRAY,
    Column,
    DateTime,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlmodel import Field, Index, SQLModel


class AuthSession(SQLModel, table=True):
    """A server-side session backing one login — the rotating-refresh anchor.

    The access JWT is stateless (verified locally, no per-request DB hit); this
    row is what makes the refresh side revocable. ``id`` is the JWT ``sid`` — a
    uuid, so it is non-enumerable and leaks no session count. ``satisfied_providers``
    / ``amr`` record which providers/factors this session authenticated against,
    mirrored into the access token so the per-guild auth-policy gate and step-up
    read them locally without a lookup.

    **app_admin-only.** Session validation is a pre-auth lookup *by refresh-token
    hash* (the user is unknown until it resolves), so it structurally cannot run
    under own-row RLS — it runs on the system engine, exactly like access_grants.
    "List/revoke my sessions" also runs on the system engine (``AdminSessionDep``)
    filtered by the authenticated user, so the refresh-token hash never crosses the
    request path. The schema-default request-path DML is REVOKEd in the migration.
    """

    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint(
            "refresh_token_hash", name="uq_auth_sessions_refresh_token_hash"
        ),
        Index("ix_auth_sessions_user_id", "user_id"),
        # Supports the background expiry sweep (GC of past-expiry sessions).
        Index("ix_auth_sessions_expires_at", "expires_at"),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(
            Uuid, primary_key=True, server_default=text("gen_random_uuid()")
        ),
    )
    # FK declared in the migration (ON DELETE CASCADE).
    user_id: int = Field(sa_column=Column(Integer, nullable=False))

    # SHA-256 of the raw refresh token — deterministic so a presented token maps
    # to one session by index lookup. The raw token is never stored.
    refresh_token_hash: bytes = Field(sa_column=Column(LargeBinary, nullable=False))

    # Providers/factors this session satisfied — drives the guild auth-policy gate
    # and step-up; mirrored into the access JWT so the check stays local.
    satisfied_providers: list[int] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Integer), nullable=False, server_default=text("'{}'")),
    )
    amr: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, server_default=text("'{}'")),
    )

    # Rotation chain: each refresh mints a new row pointing at the one it replaced;
    # reuse of an already-rotated token revokes the whole chain (theft detection).
    # Plain uuid, app-managed — no self-FK.
    parent_id: Optional[uuid.UUID] = Field(
        default=None, sa_column=Column(Uuid, nullable=True)
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    last_used_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # Set by the service to now + REFRESH_TTL at creation (no default here).
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    revoked_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    # Audit / "your active sessions" UX.
    user_agent: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    ip: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    device_name: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

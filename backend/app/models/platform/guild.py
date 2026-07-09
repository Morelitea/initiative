from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Column, DateTime, String, Integer
from sqlmodel import Field, SQLModel, Enum as SQLEnum, Relationship
from pydantic import ConfigDict

if TYPE_CHECKING:  # pragma: no cover
    from app.models.platform.user import User
    from app.models.tenant.initiative import Initiative
    from app.models.tenant.guild_setting import GuildSetting


class GuildStatus(str, Enum):
    """Operator-set lifecycle status of a guild (platform `guilds.manage`).

    - ``active``: normal operation.
    - ``read_only``: members keep read access to content but writes are denied
      at the Postgres role level (routed into ``guild_<id>_ro``).
    - ``suspended``: soft delete — members lose all content access and the
      guild vanishes from their guild list. Guild admins keep the settings
      surface (billing / data ownership / danger zone) under every status.

    PAM/break-glass grants deliberately override all of this: a grantee
    behaves exactly as against an active guild (the resolver's grant branch
    never consults the status), so suspending a guild can never lock the
    platform operators out. The status is not serialized to guild members.
    """

    active = "active"
    read_only = "read_only"
    suspended = "suspended"


class Guild(SQLModel, table=True):
    __tablename__ = "guilds"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)
    description: Optional[str] = Field(default=None)
    icon_base64: Optional[str] = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    # Max total stored blob bytes for this guild. NULL = unlimited (default).
    max_storage_bytes: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    # Max number of members allowed in this guild. NULL = unlimited (default).
    max_users: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    tier_name: Optional[str] = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    # Lifecycle status (see GuildStatus). Stored as a plain string with a CHECK
    # constraint (the access_grants pattern) rather than a Postgres enum.
    status: str = Field(
        default=GuildStatus.active.value,
        sa_column=Column(
            String(16), nullable=False, server_default=GuildStatus.active.value
        ),
    )
    # When the status last changed; NULL until the first operator change.
    status_changed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    members: List["GuildMembership"] = Relationship(
        back_populates="guild",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    initiatives: List["Initiative"] = Relationship(back_populates="guild")
    settings: Optional["GuildSetting"] = Relationship(
        back_populates="guild",
        sa_relationship_kwargs={"uselist": False},
    )


class GuildRole(str, Enum):
    admin = "admin"
    member = "member"
    # A time-bound PAM/support access grantee acting inside a guild they are
    # NOT a member of. Synthesized for the request only — never a persisted
    # ``guild_memberships`` row (the Postgres ``guild_role`` enum has only
    # admin/member, and the member-role endpoints reject assigning it). Unlike
    # ``admin``, ``support`` is bound by its grant's read/write level: it can
    # always reach the guild settings surface, with writes allowed only under a
    # ``read_write`` grant (enforced at the Postgres role level — a read grant
    # assumes ``guild_<id>_ro``). Break-glass grantees are ``admin``, not this.
    support = "support"


class GuildMembership(SQLModel, table=True):
    __tablename__ = "guild_memberships"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    guild_id: int = Field(foreign_key="guilds.id", primary_key=True)
    user_id: int = Field(foreign_key="users.id", primary_key=True)
    role: GuildRole = Field(
        default=GuildRole.member,
        sa_column=Column(
            SQLEnum(GuildRole, name="guild_role"),
            nullable=False,
            server_default=GuildRole.member.value,
        ),
    )
    joined_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    position: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    oidc_managed: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )

    guild: Optional[Guild] = Relationship(back_populates="members")
    user: Optional["User"] = Relationship(back_populates="guild_memberships")


class GuildInvite(SQLModel, table=True):
    __tablename__ = "guild_invites"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True, nullable=False, max_length=64)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False)
    created_by_user_id: Optional[int] = Field(foreign_key="users.id", nullable=True)
    expires_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    max_uses: Optional[int] = Field(default=1, nullable=True)
    uses: int = Field(default=0, nullable=False)
    invitee_email_encrypted: Optional[str] = Field(
        default=None, sa_column=Column(String(2000), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    @property
    def invitee_email(self) -> Optional[str]:
        """Return the decrypted invitee email, or None if not set."""
        if not self.invitee_email_encrypted:
            return None
        from app.core.encryption import decrypt_field, SALT_EMAIL

        return decrypt_field(self.invitee_email_encrypted, SALT_EMAIL)

    guild: Optional[Guild] = Relationship()

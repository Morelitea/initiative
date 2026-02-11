from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, String, Integer
from sqlmodel import Field, SQLModel, Enum as SQLEnum, Relationship
from pydantic import ConfigDict

if TYPE_CHECKING:  # pragma: no cover
    from app.models.user import User
    from app.models.initiative import Initiative
    from app.models.guild_setting import GuildSetting


class Guild(SQLModel, table=True):
    __tablename__ = "guilds"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)
    description: Optional[str] = Field(default=None)
    icon_base64: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
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
    expires_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    max_uses: Optional[int] = Field(default=1, nullable=True)
    uses: int = Field(default=0, nullable=False)
    invitee_email: Optional[str] = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    guild: Optional[Guild] = Relationship()

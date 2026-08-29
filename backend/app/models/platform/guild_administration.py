from typing import Optional, TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Column, ForeignKey, Integer, String
from sqlmodel import Field, SQLModel, Relationship
from pydantic import ConfigDict

if TYPE_CHECKING:  # pragma: no cover
    from app.models.platform.guild import Guild


class GuildAdministration(SQLModel, table=True):
    """The operator-set half of a guild, kept off the guild row itself.

    ``public.guilds`` is a guild's **identity** — id, name, description, icon.
    Those are not private: an invite preview shows them before sign-in, every
    member's sidebar renders them, and a public directory listing will read them
    without any membership at all. This table holds what identity is not: the
    caps a deployment sets, the plan label a billing service writes, and the
    per-guild sign-in entitlement. Splitting them means "who may read a guild"
    and "who may read its limits" are two separate questions with two separate
    answers, decided by table grants rather than by which fields a serializer
    remembers to omit.

    One row per guild, created with the guild and dropped with it. No request
    path writes it: the operator endpoints run on the system engine and the
    verified billing path holds its own column-scoped grant. A guild's own
    admins read it (their settings page shows usage against the caps) and can
    write none of it.

    ``status`` deliberately stays on ``guilds``: it is consulted on every single
    guild request, and paying for a join there is not worth it.
    """

    __tablename__ = "guild_administration"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    # The row is meaningless without its guild, and one guild has exactly one of
    # these — so NOT NULL, UNIQUE, and dropped with the guild.
    guild_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        )
    )
    # Max total stored blob bytes for this guild. NULL = unlimited (default).
    max_storage_bytes: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    # Max number of members allowed in this guild. NULL = unlimited (default).
    max_users: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    # Display/audit label of the paid tier (NULL = none). CONTRACT: never an
    # enforcement input — enforcement reads only max_storage_bytes / max_users
    # / guilds.status, so the FOSS app enforces numbers, not plans. A test pins
    # tier_name to the billing surface (billing_foss_test.py).
    tier_name: Optional[str] = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    # Operator entitlement: may this guild configure its own per-guild sign-in?
    # Set from the platform Guilds dashboard. Default off: turning it ON opens
    # the guild's auth-config surface and lets new accounts onboard through its
    # IdP. Turning it OFF never deletes providers or signs existing members out
    # — it only closes the config surface and stops NEW-account provisioning;
    # members with a linked identity keep signing in and any existing sign-in
    # requirement stays enforced. Irrelevant under platform AUTH_SCOPE (the
    # whole guild-auth surface is dormant then).
    guild_auth_enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # Operator entitlement: may this guild upload banner artwork? Default ON,
    # so a self-hosted install has it without anyone deciding anything. Where
    # an operator turns it off, the guild's banner is the flat colour on
    # ``guilds.banner_color`` — the surface stays, only the upload half of it
    # goes, and a banner uploaded before the change keeps being served. Like
    # the caps above.
    banner_image_enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )

    guild: Optional["Guild"] = Relationship(
        back_populates="administration",
        sa_relationship_kwargs={"uselist": False},
    )

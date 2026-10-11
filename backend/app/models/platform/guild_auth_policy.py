from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlmodel import Field, SQLModel

from app.core.login_methods import LoginMethod


@dataclass(frozen=True)
class SignInHalf:
    """One half of a community's sign-in requirement: its members' or its
    guests'. The same four facts either way."""

    policy: str
    provider_id: Optional[int]
    provider_slug: Optional[str]
    require_methods: tuple[str, ...]


class GuildAuthPolicy(SQLModel, table=True):
    """Per-guild sign-in requirement.

    Lives in ``public`` — the guild-access gate reads it before any guild
    context exists. No row means ``open``: any authenticated session reaches
    the guild. ``required`` names the provider a session must have satisfied
    (its id must appear in the session's ``sat`` set); ``provider_slug`` is a
    denormalized copy so the step-up response can name the provider without a
    registry read (slugs are immutable, so it cannot drift).

    Enforced by ``public.guild_auth_satisfied()``, which the standing statement
    asks for every request into the community: an unsatisfied session sees no
    rows, and the guild-context gate answers it with the step-up 401.

    The row has two halves. The first is what the community asks of its
    members; the ``guest_*`` columns are what it asks of its guests, who are
    routed as guests and asked that half instead. Each half is ``open`` or
    ``required`` on its own, and the row is kept while either is required.
    """

    __tablename__ = "guild_auth_policies"

    guild_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guilds.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )

    # 'open' | 'required' ('managed' arrives with the broker phase).
    policy: str = Field(sa_column=Column(String(16), nullable=False))

    # RESTRICT: deleting a provider a guild requires must surface the conflict,
    # never silently reopen the guild.
    provider_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("auth_providers.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    provider_slug: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    #: What this guild asks for beyond naming one provider, from the same
    #: vocabulary as the platform's own checklist. ``sso`` means the guild's own
    #: single sign-on, whichever of its providers serves it — read from the
    #: markers the session records when it does. ``totp`` means the session
    #: carried the account's second factor. Empty asks nothing. ``password`` is
    #: refused by a CHECK: whether passwords exist is the deployment's
    #: question, not a guild's.
    #:
    #: Drawn from :class:`LoginMethod` rather than spelled out, so a value
    #: added there reaches this column without a second edit — which is how
    #: this one came to know only two.
    require_methods: list[str] = Field(
        default_factory=list,
        sa_column=Column(
            ARRAY(PGEnum(LoginMethod, name="login_method", create_type=False)),
            nullable=False,
            server_default="{}",
        ),
    )

    # What the community asks of its guests, as the four columns above ask of
    # its members. Open by default: somebody from outside cannot be expected to
    # come in through the community's own sign-in.
    guest_policy: str = Field(
        default="open",
        sa_column=Column(String(16), nullable=False, server_default="open"),
    )
    guest_provider_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("auth_providers.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    guest_provider_slug: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    guest_require_methods: list[str] = Field(
        default_factory=list,
        sa_column=Column(
            ARRAY(PGEnum(LoginMethod, name="login_method", create_type=False)),
            nullable=False,
            server_default="{}",
        ),
    )

    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            onupdate=lambda: datetime.now(timezone.utc),
        ),
    )

    def half(self, guest: bool) -> SignInHalf:
        """What this row asks of a member, or of a guest."""
        if guest:
            return SignInHalf(
                self.guest_policy,
                self.guest_provider_id,
                self.guest_provider_slug,
                tuple(self.guest_require_methods or ()),
            )
        return SignInHalf(
            self.policy,
            self.provider_id,
            self.provider_slug,
            tuple(self.require_methods or ()),
        )

    def set_half(self, guest: bool, half: SignInHalf) -> None:
        """Write one half, leaving the other as it is."""
        prefix = "guest_" if guest else ""
        setattr(self, f"{prefix}policy", half.policy)
        setattr(self, f"{prefix}provider_id", half.provider_id)
        setattr(self, f"{prefix}provider_slug", half.provider_slug)
        setattr(self, f"{prefix}require_methods", list(half.require_methods))

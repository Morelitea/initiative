from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlmodel import Field, SQLModel

from app.core.login_methods import LoginMethod


class GuildAuthPolicy(SQLModel, table=True):
    """Per-guild sign-in requirement (history/auth-detailed-design.md §2.4).

    Lives in ``public`` — the guild-access gate reads it before any guild
    context exists. No row means ``open``: any authenticated session reaches
    the guild. ``required`` names the provider a session must have satisfied
    (its id must appear in the session's ``sat`` set); ``provider_slug`` is a
    denormalized copy so the step-up response can name the provider without a
    registry read (slugs are immutable, so it cannot drift).

    Enforced by ``public.guild_auth_satisfied()``, which the standing statement
    asks for every request into the community: an unsatisfied session sees no
    rows, and the guild-context gate answers it with the step-up 401.
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

    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            onupdate=lambda: datetime.now(timezone.utc),
        ),
    )

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlmodel import Field, SQLModel


class GuildAuthPolicy(SQLModel, table=True):
    """Per-guild sign-in requirement (history/auth-detailed-design.md §2.4).

    Lives in ``public`` — the guild-access gate reads it before any guild
    context exists. No row means ``open``: any authenticated session reaches
    the guild. ``required`` names the provider a session must have satisfied
    (its id must appear in the session's ``sat`` set); ``provider_slug`` is a
    denormalized copy so the step-up response can name the provider without a
    registry read (slugs are immutable, so it cannot drift).

    Enforced twice: the guild-context gate (step-up 401) and, at the database
    layer, ``public.guild_auth_satisfied()`` inside the guild RLS — an
    unsatisfied session sees no rows even if an app path skips the gate.
    """

    __tablename__ = "guild_auth_policies"

    # FK to guilds.id (ON DELETE CASCADE) declared in the migration.
    guild_id: int = Field(sa_column=Column(Integer, primary_key=True))

    # 'open' | 'required' ('managed' arrives with the broker phase).
    policy: str = Field(sa_column=Column(String(16), nullable=False))

    # FK to auth_providers.id (ON DELETE RESTRICT — deleting a provider a
    # guild requires must surface the conflict, never silently reopen the
    # guild) declared in the migration.
    provider_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    provider_slug: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            onupdate=lambda: datetime.now(timezone.utc),
        ),
    )

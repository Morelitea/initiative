"""What an app calls a person, and what it must not let it work out.

An app has to be able to name a member: to store their preferences, to say
"this is you" across two visits, and to act as them. Handing it the row id does
that and two other things nobody asked for — two apps can compare notes and
discover they are talking to the same human, and one app installed in two guilds
can link those guilds to one person. Neither is visible to the member or the
operator.

The specified answer is **OpenID Connect Core §8.1 pairwise pseudonymous
identifiers**: a subject that is stable for one *sector* and unrelated across
them. Here the sector is the **install**, matching ``connection_ref``'s
precedent of being minted per (install, connection, member) and matching the
fact that apps are guild-pinned everywhere else — an app sees an unrelated
identifier for the same person in each guild it is installed in.

§8.1 allows a pairwise subject to be **stored rather than computed**, and that
is what this does, for a reason worth stating: a value derived from a key is
only stable while that key is. This deployment rotates ``SECRET_KEY``
(``app.db.secret_key_rotation``), and a subject that moved on rotation would
strand every ``sub`` an app had stored as its key for a person — silently, and
with no way for either side to notice. So the row is the identifier, minted once
and never recomputed.

Random rather than derived for the same reason: with the row authoritative there
is nothing for a derivation to buy, and a random value cannot be reproduced by
anybody who later learns the inputs.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.guild_app_subject import SUBJECT_LENGTH, GuildAppSubject

__all__ = [
    "SUBJECT_LENGTH",
    "ensure_subject",
    "mint_subject",
    "resolve_subject",
]

#: ``token_urlsafe(24)`` renders as 32 characters, which is the column width —
#: the same size and alphabet ``connection_ref`` uses, and safe in both a JWT
#: claim and a URL.
_SUBJECT_ENTROPY_BYTES = 24


def mint_subject() -> str:
    """A fresh subject. Random, not derived from anything about the person."""
    return secrets.token_urlsafe(_SUBJECT_ENTROPY_BYTES)


async def ensure_subject(
    session: AsyncSession, *, app_install_id: int, guild_id: int, user_id: int
) -> str:
    """This member's subject at this install, minting one the first time.

    Idempotent under concurrency: two callers racing the same first handoff
    both insert, one loses on the unique constraint, and both read back the
    same row — so a member never ends up with two identifiers, and neither
    caller fails.
    """
    existing = await _subject_row(
        session, app_install_id=app_install_id, user_id=user_id
    )
    if existing is not None:
        return existing.subject

    # `ON CONFLICT DO NOTHING` rather than a second SELECT-then-INSERT: the gap
    # between checking and inserting is exactly where the race lives.
    await session.exec(
        pg_insert(GuildAppSubject.__table__)
        .values(
            guild_id=guild_id,
            app_id=app_install_id,
            user_id=user_id,
            subject=mint_subject(),
            # Supplied rather than left to the model: this is a core-level
            # insert, so SQLModel's default factory does not run.
            created_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(constraint="guild_app_subjects_unique_member")
    )

    # Read back rather than returning what was offered: on a lost race the
    # stored value is the winner's, and that is the one the app must be told.
    stored = await _subject_row(session, app_install_id=app_install_id, user_id=user_id)
    if stored is None:  # pragma: no cover — the insert either landed or lost
        raise RuntimeError("subject was neither inserted nor found")
    return stored.subject


async def _subject_row(
    session: AsyncSession, *, app_install_id: int, user_id: int
) -> GuildAppSubject | None:
    return (
        await session.exec(
            select(GuildAppSubject).where(
                GuildAppSubject.app_id == app_install_id,
                GuildAppSubject.user_id == user_id,
            )
        )
    ).first()


async def resolve_subject(
    session: AsyncSession, *, subject: str
) -> GuildAppSubject | None:
    """Who a subject names, within the guild the session is routed to.

    Returns the row rather than the user id so the caller can also check the
    install it belongs to — a subject minted for one app must not resolve for
    another, and the schema boundary alone does not say which app it was for.

    The session must already be routed into the guild.
    """
    if not subject or len(subject) > SUBJECT_LENGTH:
        return None
    return (
        await session.exec(
            select(GuildAppSubject).where(GuildAppSubject.subject == subject)
        )
    ).first()

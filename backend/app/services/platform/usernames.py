"""Handing out handles: which name part, and which number behind it.

The vocabulary — what a name part may be, how one is derived, how a number is
drawn — is ``app.core.usernames``. This is the half that has to look at the
table.
"""

from __future__ import annotations

import secrets

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import usernames
from app.core.usernames import UsernameError
from app.models.platform.user import User

# How many random draws to try before asking the table which numbers are free.
# A name almost always has ~10,000 slots open, so the first draw lands; the
# scan is for the handful of names a whole deployment has piled onto.
_DRAW_ATTEMPTS = 8


async def _taken(session: AsyncSession, name: str) -> set[int]:
    result = await session.exec(
        select(User.discriminator).where(func.lower(User.username) == name)
    )
    return {row for row in result.all()}


async def allocate(session: AsyncSession, *, name: str) -> tuple[str, int]:
    """Return ``(name, discriminator)`` for a free slot behind ``name``.

    Raises :class:`UsernameError` if the name is unusable, or if all of its
    numbers are spoken for.

    The unique index is the real arbiter — two registrations racing for the
    same slot end with one of them retrying — so this reads to pick a likely
    number rather than to guarantee one.
    """
    validated = usernames.validate(name)

    taken = await _taken(session, validated)
    for _ in range(_DRAW_ATTEMPTS):
        candidate = usernames.random_discriminator()
        if candidate not in taken:
            return validated, candidate

    free = [
        number
        for number in range(
            usernames.DISCRIMINATOR_MIN, usernames.DISCRIMINATOR_MAX + 1
        )
        if number not in taken
    ]
    if not free:
        raise UsernameError("USERNAME_UNAVAILABLE")
    return validated, secrets.choice(free)


async def allocate_from_seed(
    session: AsyncSession, *, seed: str | None = None
) -> tuple[str, int]:
    """Allocate a handle for an account that did not pick one.

    Tries the seed (a display name, a ``preferred_username`` claim) and falls
    back to a generated name, so this always returns something storable.
    """
    candidate = usernames.slugify(seed)
    if candidate is not None:
        try:
            return await allocate(session, name=candidate)
        except UsernameError:
            pass
    while True:
        try:
            return await allocate(session, name=usernames.random_name())
        except UsernameError:  # pragma: no cover - a full name is vanishingly rare
            continue


async def has_free_slot(session: AsyncSession, *, name: str) -> bool:
    """Whether ``name`` can still be handed out.

    The availability check behind registration. It answers about the name part
    only, and answers yes unless the name is reserved, malformed, or has all
    10,000 of its numbers taken.
    """
    try:
        validated = usernames.validate(name)
    except UsernameError:
        return False
    return len(await _taken(session, validated)) < usernames.DISCRIMINATOR_SPACE


# How many numbers to try when the caller cannot read what is taken.
_CLAIM_ATTEMPTS = 12


async def claim_for_user(session: AsyncSession, *, user: User, name: str) -> None:
    """Give ``user`` a handle behind ``name``, and mark it chosen.

    Unlike :func:`allocate`, this does not read which numbers are taken: an
    ordinary member's session sees only their own row. The unique index is the
    arbiter either way, so this draws a number, tries it in a savepoint, and
    draws again if the pair was spoken for.
    """
    validated = usernames.validate(name)
    for _ in range(_CLAIM_ATTEMPTS):
        candidate = usernames.random_discriminator()
        try:
            async with session.begin_nested():
                user.username = validated
                user.discriminator = candidate
                user.username_chosen = True
                session.add(user)
                await session.flush()
        except IntegrityError:
            continue
        return
    raise UsernameError("USERNAME_UNAVAILABLE")

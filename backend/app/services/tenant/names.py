"""The names a row is known by: slugs, and names that must not repeat.

A slug is an address, so its rule is stated once here and every place that
derives one (a wiki page, a filter preset, an import) spells it the same way.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

#: Slugs are addresses, so they are bounded by what stays readable in a URL
#: rather than by the column, which is wider.
MAX_SLUG_LENGTH = 120

#: The slug alphabet. Stated as the set of characters that survive rather than
#: as a pattern of ones that do not, so what a slug may contain is readable
#: here instead of inferred from a negation.
_SLUG_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")


def slugify(text: str, *, fallback: str, max_length: int = MAX_SLUG_LENGTH) -> str:
    """Kebab-case ``text`` down to the slug alphabet.

    Anything outside the alphabet becomes a separator, runs of separators
    collapse, and the result is trimmed to length. Text made entirely of
    characters that do not survive — a page called "???" — yields ``fallback``
    rather than an empty address.
    """
    out: list[str] = []
    for char in text.strip().lower():
        if char in _SLUG_CHARS:
            out.append(char)
        elif out and out[-1] != "-":
            out.append("-")
    slug = "".join(out).strip("-")[:max_length].strip("-")
    return slug or fallback


def unique_slug(
    base: str, taken: Collection[str], *, max_length: int = MAX_SLUG_LENGTH
) -> str:
    """The first of ``base``, ``base-2``, ``base-3``, … not in ``taken``.

    ``base`` is shortened to make room for the suffix, so a suffixed slug stays
    within ``max_length``.
    """
    candidate, suffix = base, 2
    while candidate in taken:
        candidate = f"{base[: max_length - len(str(suffix)) - 1].strip('-')}-{suffix}"
        suffix += 1
    return candidate


async def ensure_name_free(
    session: AsyncSession, column: Any, name: str, *where: Any, detail: str
) -> None:
    """Refuse with 409 ``detail`` when a row matching ``where`` already holds
    ``name`` in ``column``, compared case-insensitively and trimmed."""
    statement = select(column).where(func.lower(column) == name.strip().lower(), *where)
    if (await session.exec(statement.limit(1))).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

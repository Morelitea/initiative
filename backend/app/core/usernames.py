"""Handles: the name part a person picks, and the number that makes it unique.

A handle is two values — ``users.username`` and ``users.discriminator`` —
rendered ``foobar#1234``. Uniqueness is on the pair, so ten thousand people can
hold the same name part and nobody has to accept ``foobar7`` because ``foobar``
was gone.

This module is the whole vocabulary: what a name part may contain, how one is
derived from something a person already typed, and how a number is drawn. The
allocation that talks to the database lives in
``app.services.platform.usernames``.
"""

from __future__ import annotations

import secrets
import unicodedata
from typing import Final

MIN_LENGTH: Final = 3
MAX_LENGTH: Final = 32

DISCRIMINATOR_MIN: Final = 0
DISCRIMINATOR_MAX: Final = 9999
DISCRIMINATOR_SPACE: Final = DISCRIMINATOR_MAX - DISCRIMINATOR_MIN + 1

_LOWER: Final = frozenset("abcdefghijklmnopqrstuvwxyz")
_DIGITS: Final = frozenset("0123456789")
_SEPARATORS: Final = frozenset("-_")
_ALLOWED: Final = _LOWER | _DIGITS | _SEPARATORS

# Reserved for the platform itself: a handle names a person on it.
RESERVED: Final = frozenset(
    {
        "admin",
        "administrator",
        "anonymous",
        "api",
        "deleted",
        "everyone",
        "guild",
        "here",
        "initiative",
        "me",
        "moderator",
        "operator",
        "owner",
        "root",
        "staff",
        "support",
        "system",
        "user",
    }
)

# Word lists for a handle nobody seeded — short, concrete and pronounceable, so
# an assigned handle reads as a name rather than as a serial number.
_ADJECTIVES: Final = (
    "amber",
    "arctic",
    "bold",
    "brass",
    "brave",
    "bright",
    "calm",
    "clever",
    "copper",
    "coral",
    "crimson",
    "curious",
    "dawn",
    "eager",
    "early",
    "fair",
    "gentle",
    "glad",
    "golden",
    "hardy",
    "hazel",
    "indigo",
    "ivory",
    "jade",
    "keen",
    "lively",
    "lucky",
    "merry",
    "mellow",
    "noble",
    "olive",
    "opal",
    "patient",
    "quiet",
    "rapid",
    "royal",
    "sable",
    "sage",
    "scarlet",
    "silver",
    "smooth",
    "solar",
    "spry",
    "steady",
    "sunny",
    "swift",
    "teal",
    "tidy",
    "velvet",
    "vivid",
    "warm",
    "willow",
    "witty",
    "zesty",
)
_NOUNS: Final = (
    "alder",
    "anchor",
    "arrow",
    "aspen",
    "badger",
    "beacon",
    "birch",
    "bison",
    "bramble",
    "cedar",
    "comet",
    "cove",
    "crane",
    "dahlia",
    "delta",
    "ember",
    "falcon",
    "fern",
    "finch",
    "harbor",
    "heron",
    "ibis",
    "juniper",
    "kestrel",
    "lantern",
    "lark",
    "lichen",
    "lotus",
    "lynx",
    "maple",
    "marten",
    "meadow",
    "otter",
    "pine",
    "quarry",
    "quill",
    "raven",
    "reef",
    "ridge",
    "sable",
    "sparrow",
    "spruce",
    "summit",
    "thistle",
    "thrush",
    "trellis",
    "vale",
    "walnut",
    "willow",
    "wren",
)


class UsernameError(ValueError):
    """A name part that cannot be stored, carrying a flat reason code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def validate(name: str) -> str:
    """Return ``name`` normalized, or raise :class:`UsernameError`.

    An explicit character-set check rather than a pattern: the allowed set is
    the specification, and reading it should not mean reading a regex.
    """
    candidate = (name or "").strip().lower()

    if len(candidate) < MIN_LENGTH:
        raise UsernameError("USERNAME_TOO_SHORT")
    if len(candidate) > MAX_LENGTH:
        raise UsernameError("USERNAME_TOO_LONG")

    for character in candidate:
        if character not in _ALLOWED:
            raise UsernameError("USERNAME_INVALID_CHARACTERS")

    if candidate[0] not in _LOWER:
        raise UsernameError("USERNAME_MUST_START_WITH_LETTER")
    if candidate[-1] in _SEPARATORS:
        raise UsernameError("USERNAME_INVALID_CHARACTERS")
    if any(
        first in _SEPARATORS and second in _SEPARATORS
        for first, second in zip(candidate, candidate[1:])
    ):
        raise UsernameError("USERNAME_INVALID_CHARACTERS")
    if candidate in RESERVED:
        raise UsernameError("USERNAME_RESERVED")

    return candidate


def is_valid(name: str) -> bool:
    try:
        validate(name)
    except UsernameError:
        return False
    return True


def slugify(seed: str | None) -> str | None:
    """Turn something a person already typed into a usable name part.

    Returns ``None`` when nothing usable survives — an empty name, a string of
    punctuation, or an email address, which is never the source of a handle.
    """
    if not seed:
        return None
    text = seed.strip()
    if not text or "@" in text:
        return None

    # Fold accents to their base letters so a name in any Latin script keeps
    # its shape instead of collapsing to nothing.
    decomposed = unicodedata.normalize("NFKD", text)
    folded = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()

    kept: list[str] = []
    for character in folded:
        if character in _LOWER or character in _DIGITS:
            kept.append(character)
        elif character in _SEPARATORS or character.isspace():
            if kept and kept[-1] != "-":
                kept.append("-")

    slug = "".join(kept).strip("-")[:MAX_LENGTH].rstrip("-")
    # A name has to start with a letter, and digits alone would read as a
    # discriminator rather than a name.
    while slug and slug[0] not in _LOWER:
        slug = slug[1:]
    if len(slug) < MIN_LENGTH or slug in RESERVED:
        return None
    return slug


def from_full_name(full_name: str | None) -> str | None:
    """A handle offered from a display name: first initial, then last name.

    ``Jordan Janzen`` -> ``jjanzen``. A single-word name has no last name to
    join, so it stands on its own. ``None`` when nothing usable survives —
    including an address, which is never the source of a handle.
    """
    text = (full_name or "").strip()
    if not text:
        return None
    tokens = text.split()
    if len(tokens) == 1:
        return slugify(tokens[0])
    # Joined before slugifying, so accent folding and the length and reserved
    # rules all apply to the finished handle rather than to its halves.
    return slugify(f"{tokens[0][0]}{tokens[-1]}")


def random_name() -> str:
    """A pronounceable name part for an account that seeded none."""
    return f"{secrets.choice(_ADJECTIVES)}-{secrets.choice(_NOUNS)}"


def random_discriminator() -> int:
    """A number drawn at random rather than counted.

    Random rather than sequential so the number says nothing about how many
    people share a name or in what order they arrived.
    """
    return secrets.randbelow(DISCRIMINATOR_SPACE) + DISCRIMINATOR_MIN


def format_handle(name: str, discriminator: int) -> str:
    """``foobar#1234`` — for plain text, where nothing can be styled.

    The API ships the two fields separately; a caller that renders them wants
    the number in its own weight, which a joined string cannot carry.
    """
    return f"{name}#{discriminator:04d}"


def parse_handle(term: str) -> tuple[str, str | None]:
    """Split a search term into its name part and any number typed after ``#``.

    ``foobar`` → ``("foobar", None)``; ``foobar#12`` → ``("foobar", "12")``.
    The number comes back as text because a partial one is a prefix, not a
    value.
    """
    name, separator, number = term.partition("#")
    if not separator:
        return term.strip(), None
    digits = number.strip()
    if digits and not all(c in _DIGITS for c in digits):
        return term.strip(), None
    return name.strip(), digits or None

"""What counts as an emoji, for every column that stores one.

A reaction, a project's icon, the line a person puts on their profile — all
store whatever the client rendered, and all want the same answer to "is this
one emoji or is it text?". The rule lives here so the platform and tenant
schemas can both ask it without importing each other.
"""

from __future__ import annotations

import unicodedata

#: An emoji is one grapheme cluster, but a cluster can be long: a ZWJ family
#: sequence or a flag runs to several codepoints plus joiners and modifiers.
MAX_EMOJI_CODEPOINTS = 12

#: Unicode general categories an emoji's codepoints may come from: symbols
#: (So), modifier symbols (Sk, skin tones), non-spacing marks and format
#: characters (Mn/Cf — variation selectors and ZWJ), and the digits/hash/star
#: that lead a keycap sequence.
_ALLOWED_CATEGORIES = frozenset({"So", "Sk", "Mn", "Me", "Cf", "Nd"})
_ALLOWED_CHARS = frozenset("#*")


def validate_emoji(value: str) -> str:
    """Return ``value`` if it is a plausible single emoji, else raise.

    Deliberately a shape check rather than a lookup against an emoji table: the
    column stores whatever the client rendered, and a codepoint-category rule
    keeps out the thing that actually matters — text (a nickname, a URL, markup)
    smuggled in where a UI will render it as a label.
    """
    emoji = value.strip()
    if not emoji:
        raise ValueError("Emoji is required")
    if len(emoji) > MAX_EMOJI_CODEPOINTS:
        raise ValueError("Emoji is too long")
    for char in emoji:
        if char in _ALLOWED_CHARS:
            continue
        if unicodedata.category(char) not in _ALLOWED_CATEGORIES:
            raise ValueError("Not an emoji")
    return emoji

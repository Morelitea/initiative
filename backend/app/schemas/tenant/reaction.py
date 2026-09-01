"""Reaction payloads.

The read shape is a *summary*, not a row list: what a client renders is one
chip per distinct emoji, carrying how many people picked it, whether the
current user is one of them, and a few names for the tooltip. Sending the raw
rows would make every thread O(reactions) and leak nothing useful.
"""

from __future__ import annotations

import unicodedata
from typing import Optional

from pydantic import ConfigDict, Field, field_validator

from app.core.reactions import ReactionTarget
from app.schemas.base import SanitizedBaseModel
from app.schemas.platform.user import GuildNameVisibility

#: The suggested set every surface offers first — GitHub's, which is the set
#: people already recognize. Not a whitelist: any emoji validates, these are
#: just what the picker shows without searching.
SUGGESTED_EMOJI: tuple[str, ...] = (
    "\N{HEAVY BLACK HEART}\N{VARIATION SELECTOR-16}",
    "\N{THUMBS UP SIGN}",
    "\N{THUMBS DOWN SIGN}",
    "\N{SMILING FACE WITH OPEN MOUTH AND SMILING EYES}",
    "\N{PARTY POPPER}",
    "\N{CONFUSED FACE}",
    "\N{EYES}",
    "\N{ROCKET}",
)

#: A reaction is one grapheme cluster, but a cluster can be long: a ZWJ family
#: sequence or a flag runs to several codepoints plus joiners and modifiers.
MAX_EMOJI_CODEPOINTS = 12

#: Unicode general categories a reaction's codepoints may come from: symbols
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


class ReactionUser(GuildNameVisibility):
    """Who reacted, named the way comment authors are named."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    discriminator: int
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None


class ReactionGroup(SanitizedBaseModel):
    """One emoji on one target, and who chose it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    emoji: str
    count: int
    #: Whether the requesting user is one of the reactors — what decides
    #: whether the chip renders as pressed and what the toggle will do.
    reacted: bool = False
    #: The first few reactors for the hover tooltip, oldest first. Capped, so a
    #: heavily reacted post stays a small response; ``count`` is the total.
    users: list[ReactionUser] = Field(default_factory=list)


class ReactionToggle(SanitizedBaseModel):
    """The body of the toggle route: which emoji to add or take back."""

    emoji: str

    @field_validator("emoji")
    @classmethod
    def _check_emoji(cls, value: str) -> str:
        return validate_emoji(value)


class ReactionSummary(SanitizedBaseModel):
    """Every reaction on one target, newest emoji last."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    target_type: ReactionTarget
    target_id: int
    groups: list[ReactionGroup] = Field(default_factory=list)

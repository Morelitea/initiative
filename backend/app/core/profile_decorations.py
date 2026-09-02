"""What a profile can be dressed in, and which of it ships with the app.

A decoration is named by an **id** — ``core.aurora`` — and belongs to a slot:
one banner, one frame, any number of trophies. The id is all the server holds.
The artwork it names is the client's business (``frontend/src/lib/
profileDecorations.ts`` maps an id to a file under ``public/decorations``), so
a decoration a build has no artwork for simply isn't drawn.

Two sources, one vocabulary:

* what ships with the app — :data:`SHIPPED_DECORATIONS`, which every account
  has and nobody had to acquire;
* what an account acquired — rows in ``public.user_decorations``, written when
  a marketplace pack is installed.

They are unioned by ``app.services.platform.profile_decorations``, which is
the one place that answers "what may this person wear". Shipped decorations are
deliberately *not* rows: they are universal, so a row per account per
decoration would be a fan-out over every user for something nobody chose, and
another one every time the app ships a new default.
"""

from __future__ import annotations

#: What a decoration id may be made of. An explicit set rather than a pattern:
#: the id is spliced into the path of a local asset by the client, so the
#: characters it may contain are worth reading at a glance.
_DECORATION_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-_")

#: How long one id may be.
DECORATION_ID_MAX_LENGTH = 64


def validate_decoration_id(value: str) -> str:
    """Return ``value`` if it is shaped like a catalog id, else raise.

    A catalog id is a flat, lowercase name — ``core.aurora`` — and this holds
    it to that vocabulary. Lives here rather than beside the profile schema so
    the marketplace validator, which admits a pack's ids at publish time, and
    the write path, which admits them at wear time, ask the same question.
    """
    identifier = value.strip()
    if not identifier:
        raise ValueError("Decoration id is required")
    if len(identifier) > DECORATION_ID_MAX_LENGTH:
        raise ValueError("Decoration id is too long")
    if not all(char in _DECORATION_ID_CHARS for char in identifier):
        raise ValueError("Decoration id has characters that are not allowed")
    return identifier


#: The slots a profile has. One banner and one frame, because a profile has one
#: of each; trophies are a row, so there are several.
BANNER = "banner"
FRAME = "frame"
TROPHY = "trophy"

DECORATION_KINDS: frozenset[str] = frozenset({BANNER, FRAME, TROPHY})

#: The shipped frames whose colour the wearer picks, and how many colours each
#: one takes. Only what ships with the app: a pack's artwork is the pack's, and
#: a publisher who wanted it recoloured would have shipped it that way.
TINTABLE_FRAMES: dict[str, int] = {
    "core.gold": 1,
    "core.split": 2,
}

#: How many colours any frame may take. The bound the write path checks.
MAX_FRAME_TINTS = 2


def validate_tint(value: str) -> str:
    """Return ``value`` if it is a ``#rrggbb`` colour, else raise.

    Six digits and a hash, nothing else: the value is written into a fill on a
    rendered frame, so the vocabulary is worth reading at a glance.
    """
    colour = value.strip()
    if len(colour) != 7 or colour[0] != "#":
        raise ValueError("Colour must be #rrggbb")
    if not all(char in "0123456789abcdefABCDEF" for char in colour[1:]):
        raise ValueError("Colour must be #rrggbb")
    return "#" + colour[1:].lower()


#: What ships with the app: id -> slot. Every account has these. The artwork
#: lives in the frontend catalog under the same ids; an id here with no artwork
#: there is simply never drawn, which is the same tolerance a pack's id gets.
SHIPPED_DECORATIONS: dict[str, str] = {
    "core.aurora": BANNER,
    "core.ember": BANNER,
    "core.parchment": BANNER,
    "core.gold": FRAME,
    "core.split": FRAME,
    # One trophy, and it is the app's own rather than any community's: a
    # trophy is a mark of belonging to something, and the thing everyone here
    # belongs to is Initiative. Every other trophy is acquired.
    "core.fan": TROPHY,
}

"""What a profile can be dressed in, and which of it ships with the app.

A decoration is named by an **id** — ``core.aurora`` — and belongs to a slot:
one banner, one frame, any number of badges. The id is all the server holds.
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

#: The slots a profile has. One banner and one frame, because a profile has one
#: of each; badges are a row, so there are several.
BANNER = "banner"
FRAME = "frame"
BADGE = "badge"

DECORATION_KINDS: frozenset[str] = frozenset({BANNER, FRAME, BADGE})

#: What ships with the app: id -> slot. Every account has these. The artwork
#: lives in the frontend catalog under the same ids; an id here with no artwork
#: there is simply never drawn, which is the same tolerance a pack's id gets.
SHIPPED_DECORATIONS: dict[str, str] = {
    "core.aurora": BANNER,
    "core.ember": BANNER,
    "core.parchment": BANNER,
    "core.gold": FRAME,
    "core.arcane": FRAME,
    "core.founder": BADGE,
    "core.storyteller": BADGE,
    "core.trailblazer": BADGE,
}

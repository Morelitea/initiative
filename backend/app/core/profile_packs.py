"""The packs a profile's decorations come in.

A pack is a set of decorations you take or leave together — the way a store
sells a theme rather than a pixel. Installing one writes its decorations into
the account's library (``public.user_decorations``) with ``source`` set to the
pack's id; removing it takes exactly those rows back out.

These ship with the app, so the registry is code rather than rows: there is one
catalog per build, the same for every deployment, and it changes when the app
does. A pack published from outside would arrive as rows with its own ``source``
and needs nothing here.

What a pack is *called* is not here either. The artwork lives in the frontend
catalog (``frontend/src/lib/profileDecorations.ts``) and the words live in its
``profiles`` translations, in every language the app speaks — a server-side
English name would only be a second, worse source for both.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.profile_decorations import BADGE, BANNER, FRAME


@dataclass(frozen=True)
class ProfilePack:
    """One installable set of decorations."""

    #: Also the ``source`` written on every row it grants, and the namespace
    #: its decoration ids are under — so what a pack granted is answerable
    #: from either end.
    id: str
    #: decoration id -> slot.
    decorations: dict[str, str]


def _pack(pack_id: str, decorations: dict[str, str]) -> ProfilePack:
    assert all(
        decoration_id.startswith(f"{pack_id}.") for decoration_id in decorations
    ), f"{pack_id} grants a decoration from outside its own namespace"
    return ProfilePack(id=pack_id, decorations=decorations)


#: Every pack this build ships, by id. Each is a community rather than a colour
#: scheme: the badge is the thing its people would recognise on sight.
PROFILE_PACKS: dict[str, ProfilePack] = {
    pack.id: pack
    for pack in (
        _pack(
            "ttrpg",
            {
                "ttrpg.dicetower": BANNER,
                "ttrpg.natural20": FRAME,
                "ttrpg.d20": BADGE,
            },
        ),
        _pack(
            "music",
            {
                "music.soundcheck": BANNER,
                "music.vinyl": FRAME,
                "music.cassette": BADGE,
            },
        ),
        _pack(
            "science",
            {
                "science.observatory": BANNER,
                "science.orbital": FRAME,
                "science.flask": BADGE,
            },
        ),
    )
}

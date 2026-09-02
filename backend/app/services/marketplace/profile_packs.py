"""What a profile-pack listing is allowed to publish.

A pack is a set of profile decorations sold together — a banner, a frame, the
trophy its community recognises. The listing carries the words (name, publisher,
description) like any other; this validates the part that is particular to a
pack: which decorations it grants, and which slot each one goes in.

The artwork is deliberately not here. A decoration is an **id**, and what it
looks like is resolved by whoever renders it — the client ships art for the
ids this build knows, and an id it has no art for is simply not drawn. That is
what lets a catalog name a decoration without every deployment having to hold
its picture.
"""

from __future__ import annotations

from typing import Any

from app.core.profile_decorations import DECORATION_KINDS, validate_decoration_id
from app.services.marketplace.manifest_values import (
    MAX_NAME_LENGTH,
    ListingDefinitionError,
    check_single_line,
    clean_text,
    fail,
    require_list,
    require_mapping,
)

__all__ = ["MAX_PACK_DECORATIONS", "normalize_profile_pack_definition"]

#: How many decorations one pack may grant. A themed set is usually three or
#: four; a set whose whole idea is breadth — a flag for every country somebody
#: in the room is from — runs to a hundred and keeps growing. Still bounded, so
#: a pack cannot be a way to bulk-load a library.
MAX_PACK_DECORATIONS = 160


def _decoration(raw: Any, *, index: int, seen: set[str]) -> dict[str, str]:
    entry = require_mapping(raw, f"decorations[{index}]")

    try:
        decoration_id = validate_decoration_id(str(entry.get("id", "")))
    except ValueError as exc:
        fail(f"decorations[{index}].id: {exc}")
    if decoration_id in seen:
        fail(f"decorations[{index}].id: {decoration_id!r} appears twice")
    seen.add(decoration_id)

    slot = str(entry.get("slot", ""))
    if slot not in DECORATION_KINDS:
        fail(
            f"decorations[{index}].slot: {slot!r} is not one of "
            f"{sorted(DECORATION_KINDS)}"
        )

    # Named by its publisher, because nobody else can name it: a pack from
    # outside this build has no translation here to fall back on.
    name = clean_text(
        entry.get("name"),
        what=f"decorations[{index}].name",
        limit=MAX_NAME_LENGTH,
        required=True,
    )
    return {
        "id": decoration_id,
        "slot": slot,
        "name": check_single_line(name, what=f"decorations[{index}].name"),
    }


def normalize_profile_pack_definition(definition: Any) -> dict[str, Any]:
    """Validate and canonicalize a profile pack's definition."""
    body = require_mapping(definition, "definition")

    schema_version = body.get("schema_version")
    if schema_version != 1:
        raise ListingDefinitionError(
            f"unsupported profile pack schema_version {schema_version!r}"
        )
    kind = body.get("kind")
    if kind != "profile_pack":
        raise ListingDefinitionError(
            f"definition.kind {kind!r} does not match the listing kind"
        )

    raw = require_list(body.get("decorations"), "decorations", MAX_PACK_DECORATIONS)
    if not raw:
        raise ListingDefinitionError("a pack grants at least one decoration")

    seen: set[str] = set()
    decorations = [
        _decoration(entry, index=index, seen=seen) for index, entry in enumerate(raw)
    ]
    return {
        "schema_version": 1,
        "kind": "profile_pack",
        "decorations": decorations,
    }

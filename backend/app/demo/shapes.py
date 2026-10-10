"""The shapes a pitch is made from, kept where an import can read them.

The loader stores each shape's bundle in the operations community's storage,
beside one index naming the shapes and the pitch editors. A pitch made later
reads a bundle back the way an import reads a staged payload
(``import_engine.open_payload``).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from app.demo.manifest import Handle, Shape
from app.services.storage import get_guild_storage

LIBRARY_KEY = "demo-shapes.json"


def bundle_key(shape_key: str) -> str:
    """Where a shape's bundle is stored."""
    return f"demo-shape-{shape_key}.zip"


class ShapeLibrary(BaseModel):
    #: Each shape with ``bundle`` naming its stored bundle.
    shapes: list[Shape] = []
    #: The fixed accounts made admins of every pitch.
    editors: list[Handle] = []


def write_library(
    guild_id: int, shapes: list[Shape], editors: list[str], base: Path
) -> None:
    """Store every shape's bundle, read from ``base``, then the index naming
    them. Blocking; run it in a thread."""
    storage = get_guild_storage(guild_id)
    stored = []
    for shape in shapes:
        key = bundle_key(shape.key)
        storage.write_file(key, base / shape.bundle, content_type="application/zip")
        stored.append(shape.model_copy(update={"bundle": key}))
    library = ShapeLibrary(shapes=stored, editors=editors)
    storage.write(
        LIBRARY_KEY,
        library.model_dump_json().encode(),
        content_type="application/json",
    )


def read_library(guild_id: int) -> ShapeLibrary | None:
    """The stored index, or ``None`` when the loader has stored none. Blocking."""
    from app.services.import_engine.engine import read_payload

    raw = read_payload(guild_id, LIBRARY_KEY)
    return ShapeLibrary.model_validate_json(raw) if raw is not None else None

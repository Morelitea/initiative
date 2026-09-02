"""What can be referred to, and how a reference is written down.

A reference names one thing: ``task:12``. Everything that points at work is
built on it — a `#` link, a `[[ ]]` link, an `@` mention, and the smart chips
that add a fact about the thing on top.

This module owns the vocabulary because it belongs to all of those shapes and
to none of them in particular. What a reference RESOLVES to — the column
holding the name, the resource whose sharing gates it — is derived from the
search registry in :mod:`app.db.reference_targets`, which needs the models.
"""

from enum import Enum

from app.core.search import SearchEntityType

#: How the parts of a reference are joined: ``task:12``, ``task:12:status``.
REF_SEPARATOR = ":"

#: Indexed kinds that are not things you point at mid-sentence.
#:
#: A comment is a remark ON something — the thing it is on is what a reader
#: wants — and it has an opening line rather than a name. A decision about what
#: a reference means, rather than a fact about the database.
NOT_REFERENCEABLE: frozenset[SearchEntityType] = frozenset({SearchEntityType.comment})

#: Everything a reference can name. Derived, so a tool added to ``Tool`` can be
#: linked, mentioned and chipped without an edit here.
REFERENCEABLE_TYPES: tuple[SearchEntityType, ...] = tuple(
    entity_type
    for entity_type in SearchEntityType
    if entity_type not in NOT_REFERENCEABLE
)


def is_referenceable(entity_type: SearchEntityType) -> bool:
    """Whether a reference may name this kind."""
    return entity_type not in NOT_REFERENCEABLE


def format_ref(
    entity_type: SearchEntityType, entity_id: int, aspect: Enum | None = None
) -> str:
    """A reference as it is stored and asked for.

    ``task:12`` names the thing, which resolves to what it is called now.
    ``task:12:status`` names a fact about it.
    """
    parts = [entity_type.value, str(entity_id)]
    if aspect is not None:
        parts.append(aspect.value)
    return REF_SEPARATOR.join(parts)

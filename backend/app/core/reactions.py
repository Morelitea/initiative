"""What a reaction can be attached to — the one place a target kind is declared.

A reaction is deliberately NOT a comment feature: the row names its target by
``(target_type, target_id)``, the same polymorphic shape ``recent_views`` and
``search_entries`` use, so the next thing worth reacting to (a feed post, say)
joins by adding one member here plus the table it resolves through.

This module is dependency-free (no models, no SQLAlchemy) so ``app.db``'s
registry layer can import it alongside ``app.core.tools``.
"""

from __future__ import annotations

from enum import Enum


class ReactionTarget(str, Enum):
    """A kind of thing reactions hang off. The value is stored verbatim in
    ``reactions.target_type`` and appears in the API path."""

    comment = "comment"

    @property
    def table(self) -> str:
        """The guild-schema table a target of this kind lives in."""
        return _TARGET_TABLES[self]


#: target kind -> the table its ids point at. Kept beside the enum so the RLS
#: renderer and the service resolve the same table for a given kind.
_TARGET_TABLES: dict[ReactionTarget, str] = {
    ReactionTarget.comment: "comments",
}

#: Every target kind, in enum order — the CHECK constraint's vocabulary.
REACTION_TARGETS: tuple[ReactionTarget, ...] = tuple(ReactionTarget)

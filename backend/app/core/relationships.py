"""How two things connect — the vocabulary of edges, declared once.

A relationship is ``source -> relationship_type -> target`` between any two
addressable things in a guild. This module owns three declarations and nothing
else:

* :class:`RelationshipType` — the primitives, each with a fixed reading;
* :class:`RelationshipSpec` — what is TRUE of each one, in the standard
  vocabulary of binary relations;
* :data:`ENDPOINT_KINDS` — what may sit on either end, and the permanent code
  that turns a ``(kind, id)`` pair into one integer.

It is dependency-free (no models, no SQLAlchemy) so ``app.db``'s registry layer
can import it alongside :mod:`app.core.tools`, the same way
:mod:`app.core.reactions` is imported.

What is deliberately NOT here: any statement about who may write an edge. That
falls out of what the edge describes — see :class:`RelationshipSpec`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.core.references import REFERENCEABLE_TYPES
from app.core.search import SearchEntityType
from app.core.tools import plural_of


class RelationshipType(str, Enum):
    """The primitives. Small, stable, and each one carries a rule or a weight.

    A member earns its place by something depending on telling it apart from
    its neighbours — a read, a rule, an adjacency weight — not by a model being
    able to learn it. Finer words that obey an existing primitive's rule are
    :data:`SUBTYPES`, not members here: splitting a primitive later is
    impossible, because the fact that would distinguish the halves was never
    recorded, while merging two is one UPDATE.
    """

    #: A project and a document placed together. Symmetric: it describes the
    #: pair, not either end.
    attached = "attached"
    #: X cannot proceed until Y. Precedence.
    depends_on = "depends_on"
    #: X is a piece of Y. Composition — a different fact from precedence, and
    #: they predict different things.
    part_of = "part_of"
    #: X carries the label Y. Directional: a tag is a label, so the edge
    #: describes the thing carrying it.
    tagged_with = "tagged_with"
    #: These belong together and there is no better word for it.
    related_to = "related_to"


@dataclass(frozen=True)
class RelationshipSpec:
    """What is true of this relation. Nothing else.

    These are the standard **property characteristics** of a binary relation —
    the algebra of relations, which OWL spells ``SymmetricProperty`` /
    ``TransitiveProperty`` / ``AsymmetricProperty``. Standard names mean the
    semantics need no explaining, and each one drives a specific derivation:

    ``symmetric``
        The row is stored once, in node-id order, and a write asks only READ on
        both ends — a relation that describes neither endpoint modifies
        neither.
    ``transitive``
        A walk past one hop is meaningful. Walking a non-transitive relation to
        depth N returns nonsense that reads like a result, so the service
        refuses it.
    ``asymmetric``
        An observed 2-cycle is a contradiction, which is what makes it
        *detectable*. Note this is declared **intent**, not a constraint: the
        table records the contradiction anyway, because two people saying
        neither of two tasks can go first is the strongest coupling evidence
        the system will ever get.

    There is deliberately **no authorization field**. Direction is chosen so
    the source is the end the edge describes, which makes who-may-write
    derivable: write on the source and read on the target, or — where there is
    no described end — read on both.
    """

    symmetric: bool = False
    transitive: bool = False
    asymmetric: bool = False


#: What is true of each primitive. The RLS renderer, the walk endpoint and the
#: service all read this rather than restating any of it.
SPECS: dict[RelationshipType, RelationshipSpec] = {
    RelationshipType.attached: RelationshipSpec(symmetric=True),
    RelationshipType.depends_on: RelationshipSpec(transitive=True, asymmetric=True),
    RelationshipType.part_of: RelationshipSpec(transitive=True, asymmetric=True),
    RelationshipType.tagged_with: RelationshipSpec(asymmetric=True),
    RelationshipType.related_to: RelationshipSpec(symmetric=True),
}

#: Types stored once per unordered pair, in node-id order.
SYMMETRIC_TYPES: frozenset[RelationshipType] = frozenset(
    t for t, spec in SPECS.items() if spec.symmetric
)

#: Types a walk may follow past a single hop.
TRANSITIVE_TYPES: frozenset[RelationshipType] = frozenset(
    t for t, spec in SPECS.items() if spec.transitive
)

#: Finer words for an edge that obeys its primitive's rule — ``impeded_by``
#: under ``depends_on``, ``uses`` under ``attached``. A subtype is a word the UI
#: may show and a feature a scorer may read; rules, adjacency weights and the
#: RLS legs read the PRIMITIVE only, so this can grow forever without ever
#: re-partitioning the primitive pool.
#:
#: Ships EMPTY. The column exists from the first release so the API and read
#: schemas do not move later; the first member lands when a surface asks for it.
SUBTYPES: dict[str, RelationshipType] = {}


class Provenance(str, Enum):
    """How we know about an edge — orthogonal to what it means.

    Not decoration: it is the sample weight any future scoring reads, and it
    decides whether a removal is worth remembering. A person taking a link back
    is a deliberate negative; a link vanishing because somebody edited the
    sentence that implied it asserts nothing.

    Server-assigned per code path, never taken from a request.
    """

    #: A person, through the API.
    manual = "manual"
    #: The save path, from a reference in a body.
    content = "content"
    #: A person accepting a suggestion. Nothing writes this but the accept path.
    inferred = "inferred"


PROVENANCES: tuple[Provenance, ...] = tuple(Provenance)


@dataclass(frozen=True)
class EndpointKind:
    """A kind of thing an edge may name, and how it is addressed.

    ``code`` is **permanent**. It is the high bits of every node id derived from
    this kind, so changing one silently re-encodes every stored row of that kind
    while leaving the old rows behind: no error, no drift test in the database,
    just two encodings of the same thing. Codes are assigned once, never
    reordered, never reused — the discipline an announcement slug takes, for the
    same reason.
    """

    kind: SearchEntityType
    code: int

    @property
    def table(self) -> str:
        """The guild-schema table ids of this kind point at."""
        return plural_of(self.kind.value)


#: Permanent kind codes. Append-only: a new kind takes the next unused number,
#: and no existing number ever moves. The initial set was assigned in
#: alphabetical order, which is where the resemblance to alphabetical order
#: ends — sorting is not how these are derived, because a derived ordinal
#: changes under you the first time a member is added in the middle.
_KIND_CODES: dict[str, int] = {
    "calendar": 1,
    "calendar_event": 2,
    "counter": 3,
    "counter_group": 4,
    "dashboard": 5,
    "document": 6,
    "gallery": 7,
    "gallery_image": 8,
    "post": 9,
    "project": 10,
    "queue": 11,
    "queue_item": 12,
    "tag": 13,
    "task": 14,
}

#: What may sit on either end of an edge, keyed by kind. Derived from
#: ``REFERENCEABLE_TYPES`` — if a reference can name it, an edge can too, and
#: the resolvers a reference already needs are the ones an endpoint needs.
ENDPOINT_KINDS: dict[SearchEntityType, EndpointKind] = {
    kind: EndpointKind(kind=kind, code=_KIND_CODES[kind.value])
    for kind in REFERENCEABLE_TYPES
    if kind.value in _KIND_CODES
}

#: The CHECK constraint's vocabulary, in a stable order.
ENDPOINT_KIND_VALUES: tuple[str, ...] = tuple(
    sorted(kind.value for kind in ENDPOINT_KINDS)
)

#: How many low bits of a node id hold the entity id. Entity ids are ``int4``,
#: so 31 bits are in use and 32 is the natural boundary; the kind code occupies
#: the bits above. 14 kinds need 4 bits, leaving a bigint's remaining range
#: spare for both to grow.
NODE_ID_SHIFT = 32


def node_id(kind: SearchEntityType, entity_id: int) -> int:
    """One integer addressing one thing, derived rather than registered.

    Every graph algorithm — a recursive walk, a component pass, anything
    off-the-shelf — addresses nodes as integers, and ours are ``(kind, id)``
    pairs. Packing the pair is reversible and needs nothing stored, where a
    registry table would be a second source of truth written on every entity
    insert and able to drift.

    The database computes the same value in a generated column, so SQL and
    Python agree by construction rather than by convention.
    """
    return (ENDPOINT_KINDS[kind].code << NODE_ID_SHIFT) | entity_id


def decode_node_id(value: int) -> tuple[SearchEntityType, int]:
    """``node_id`` backwards: the kind and the id it was built from."""
    code = value >> NODE_ID_SHIFT
    entity_id = value & ((1 << NODE_ID_SHIFT) - 1)
    for kind, endpoint in ENDPOINT_KINDS.items():
        if endpoint.code == code:
            return kind, entity_id
    raise ValueError(f"no endpoint kind has code {code}")


def is_symmetric(relationship_type: RelationshipType) -> bool:
    """Whether this relation is stored once per unordered pair."""
    return SPECS[relationship_type].symmetric


def is_transitive(relationship_type: RelationshipType) -> bool:
    """Whether a walk along this relation may go past one hop."""
    return SPECS[relationship_type].transitive

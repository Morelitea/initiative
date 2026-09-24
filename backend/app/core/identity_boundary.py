"""What a person and a community are called at the edge of a request.

Inside, a person is a row id and so is a community. An installed app is never
handed either: it knows each person by a reference minted for its own install,
and its community by one more (``history/opaque-identity-design.md``,
``history/app-principal-design.md`` §D7). A request and a response carry the
two in fields typed :data:`PersonId` and :data:`GuildId`, and those two types
are where the translation happens.

For a person, nothing changes: both are ``int`` on the way in and on the way
out, with ``int``'s JSON schema.

For an install, each request passes through three phases, held on an
:class:`InstallBoundary` that the route's scope dependency sets up once the
install's standing is in:

- **input**: the request's own path, query and body are validated. A field of
  either type accepts only a reference, looked up in what the standing
  statement resolved for this request (:attr:`InstallBoundary.named`). A row
  id, or a reference that names nobody in this install's sector, is a 422
  (``APP_REFERENCE_UNKNOWN``).
- **handler**: the route's own code runs. Both types behave as ``int``, so a
  model built from rows and a payload stored as JSON hold row ids.
- **response**: the route's return value is serialized. A :data:`GuildId`
  becomes the install's community reference when the standing returned one;
  anything else becomes a marker carrying a per-request nonce, and the route
  class (``app.api.actor_route.ActorRoute``) resolves the markers after
  serialization and writes the references in.

The boundary lives in a context variable that ``ActorRoute`` opens per request,
so it never outlives the request that set it.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Any, Optional

from pydantic import PlainSerializer, WithJsonSchema, WrapValidator
from pydantic_core import PydanticCustomError, core_schema

from app.core.messages import AppMessages
from app.models.platform.identity_ref import IdentityEntity

__all__ = [
    "BoundaryPhase",
    "GuildId",
    "InstallBoundary",
    "PersonId",
    "UNKNOWN_REFERENCE_ERROR",
    "admit_install",
    "boundary_scope",
    "current_install_boundary",
]


class BoundaryPhase(str, Enum):
    """Where an install's request is: see the module docstring."""

    input = "input"
    handler = "handler"
    response = "response"


#: The pydantic error type a reference that names nobody raises under.
UNKNOWN_REFERENCE_ERROR = "app_reference_unknown"


def _unknown() -> PydanticCustomError:
    return PydanticCustomError(UNKNOWN_REFERENCE_ERROR, AppMessages.REFERENCE_UNKNOWN)


@dataclass
class InstallBoundary:
    """One installed app's request, as the identity types see it.

    Built by the scope dependency from the install's completed standing:
    ``guild_id`` and ``install_id`` are the routed community and install,
    ``guild_ref`` what the install calls that community, and ``named`` the
    references the request named that resolve in the install's sector.
    ``session`` is the request's routed session, on which the route class
    resolves what the response names.
    """

    guild_id: int
    install_id: int
    guild_ref: Optional[str]
    named: Mapping[str, tuple[IdentityEntity, int]]
    session: Any = None
    phase: BoundaryPhase = BoundaryPhase.input
    #: Marks a value the response names. Random per request, so nothing a
    #: route returns can be read as one.
    nonce: str = field(default_factory=lambda: secrets.token_hex(16))
    #: What the response named, as ``(entity, row id)``.
    wanted: set[tuple[IdentityEntity, int]] = field(default_factory=set)

    def resolve(self, value: Any, entity: IdentityEntity) -> int:
        """The row id a reference in the request names, or a 422.

        A reference is a string; a row id is not accepted from an install. A
        community reference must name the routed community.
        """
        if not isinstance(value, str):
            raise _unknown()
        found = self.named.get(value)
        if found is None or found[0] is not entity:
            raise _unknown()
        entity_id = found[1]
        if entity is IdentityEntity.guild and entity_id != self.guild_id:
            raise _unknown()
        return entity_id

    def mark(self, entity: IdentityEntity, entity_id: int) -> str:
        """The marker a response carries for ``entity_id`` until the route
        class writes its reference in."""
        if entity is IdentityEntity.guild and entity_id != self.guild_id:
            # A response to an install names its own community and no other.
            raise ValueError("a response to an install names only its community")
        self.wanted.add((entity, entity_id))
        return f"{self.nonce}:{entity.code}:{entity_id}"


class _Slot:
    """The request's place for a boundary. Opened by the route class; filled
    by the scope dependency when the request is an install's."""

    __slots__ = ("boundary",)

    def __init__(self) -> None:
        self.boundary: Optional[InstallBoundary] = None


_SLOT: ContextVar[Optional[_Slot]] = ContextVar("identity_boundary", default=None)


@contextmanager
def boundary_scope() -> Iterator[_Slot]:
    """Open a request's slot for the rest of the request, and close it after."""
    slot = _Slot()
    token = _SLOT.set(slot)
    try:
        yield slot
    finally:
        _SLOT.reset(token)


def admit_install(boundary: InstallBoundary) -> None:
    """Record ``boundary`` as the request's. Refuses outside an open slot: a
    route that admits an installed app is served by ``ActorRoute``."""
    slot = _SLOT.get()
    if slot is None:
        raise RuntimeError(
            "an installed app's request is served by ActorRoute; this route's "
            "router does not use it"
        )
    slot.boundary = boundary


def current_install_boundary() -> Optional[InstallBoundary]:
    """The install boundary of the request in progress, or ``None``."""
    slot = _SLOT.get()
    return None if slot is None else slot.boundary


def _boundary_in(phase: BoundaryPhase) -> Optional[InstallBoundary]:
    boundary = current_install_boundary()
    if boundary is None or boundary.phase is not phase:
        return None
    return boundary


# --- The two types --------------------------------------------------------------


def _validator(entity: IdentityEntity):
    def validate(value: Any, handler: core_schema.ValidatorFunctionWrapHandler) -> int:
        boundary = _boundary_in(BoundaryPhase.input)
        if boundary is None:
            return handler(value)
        return boundary.resolve(value, entity)

    return validate


def _serializer(entity: IdentityEntity):
    def serialize(value: int) -> int | str:
        boundary = _boundary_in(BoundaryPhase.response)
        if boundary is None:
            return value
        if (
            entity is IdentityEntity.guild
            and boundary.guild_ref is not None
            and value == boundary.guild_id
        ):
            return boundary.guild_ref
        return boundary.mark(entity, value)

    return serialize


#: The schema both types publish, in both modes: what a person sends and
#: receives, unchanged.
_INTEGER_SCHEMA = WithJsonSchema({"type": "integer"})

#: A person's id in a request or response schema. ``int`` for a person; the
#: install's reference for an installed app.
PersonId = Annotated[
    int,
    WrapValidator(_validator(IdentityEntity.user)),
    PlainSerializer(_serializer(IdentityEntity.user), return_type=Any),
    _INTEGER_SCHEMA,
]

#: A community's id in a request or response schema. ``int`` for a person; the
#: install's community reference for an installed app.
GuildId = Annotated[
    int,
    WrapValidator(_validator(IdentityEntity.guild)),
    PlainSerializer(_serializer(IdentityEntity.guild), return_type=Any),
    _INTEGER_SCHEMA,
]

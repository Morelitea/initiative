"""The wire shape of an edge.

An endpoint is named the way a ``#`` link names one — ``task:12``, the string
``core.references.format_ref`` produces — so one spelling addresses a thing
across references, search and this. Node ids are an internal addressing detail
and never appear here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import ConfigDict, field_validator

from app.core.references import REF_SEPARATOR
from app.core.relationships import ENDPOINT_KINDS, RelationshipType
from app.core.search import SearchEntityType
from app.schemas.base import SanitizedBaseModel


class EndpointRef(SanitizedBaseModel):
    """One end of an edge: what kind of thing, and which one."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    type: SearchEntityType
    id: int

    @field_validator("type")
    @classmethod
    def _must_be_an_endpoint(cls, value: SearchEntityType) -> SearchEntityType:
        if value not in ENDPOINT_KINDS:
            raise ValueError(f"{value.value} cannot sit on a relationship")
        return value

    @property
    def ref(self) -> str:
        return f"{self.type.value}{REF_SEPARATOR}{self.id}"


class RelationshipCreate(SanitizedBaseModel):
    """Make one edge. Provenance is not here — it is the code path's to state,
    never a request's, because it is the weight any later scoring reads."""

    source: EndpointRef
    relationship_type: RelationshipType
    target: EndpointRef


class RelatedEnd(SanitizedBaseModel):
    """The far end of an edge, as the caller's side sees it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    type: SearchEntityType
    id: int
    title: Optional[str] = None
    initiative_id: Optional[int] = None
    #: When the far end last changed, for the surfaces that order by recency.
    #: None for a kind that records no such moment.
    updated_at: Optional[datetime] = None


class RelationshipRead(SanitizedBaseModel):
    """One edge, rendered from the asking entity's side.

    ``direction`` is which way it runs relative to the entity asked about, so a
    caller never has to know that a symmetric edge is stored in node-id order.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    relationship_type: RelationshipType
    direction: str
    other: RelatedEnd
    provenance: str
    confidence: Optional[float] = None
    created_by: Optional[int] = None
    created_at: datetime

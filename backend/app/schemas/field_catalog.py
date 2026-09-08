"""What the field registry tells a client.

A description, never a resolver: what a field compiles to is the server's, and
what it is called, what it holds, and what picks it are the client's. Nothing
here is tenant data — the same answer for every guild on a deployment — so it is
served off the platform path rather than a guild one.

Every field is typed as the enum it actually is, so the generated client gets
real unions rather than bare strings and a client cannot name a control or an
operator this build does not have.
"""

from typing import List

from app.schemas.base import SanitizedBaseModel
from app.schemas.query import FilterOp
from app.services.fields.spec import ControlKind, FieldType


class FieldDescription(SanitizedBaseModel):
    """One field a client may offer for filtering."""

    #: The name a stored condition uses.
    name: str
    #: What the value is, for comparison and formatting.
    type: FieldType
    #: Which control picks a value — a member picker, a date picker, a tag
    #: picker. The client maps this to a component; the server never names one.
    kind: ControlKind
    #: The operators this control offers. Already narrowed to what the engine
    #: accepts, so anything here compiles.
    ops: List[FilterOp]
    #: Whether the control picks several values at once.
    multiple: bool
    #: Whether a list may be ordered by this field.
    sortable: bool
    #: The values this field accepts, when it accepts a closed set of them —
    #: read off the column that stores them. A client offers these rather than
    #: keeping its own copy, so a value added by a migration shows up on its
    #: own. Empty for a field whose values a lookup has to enumerate.
    options: List[str] = []


class FieldCatalogResponse(SanitizedBaseModel):
    """Every field a dataset offers, in the order a client lists them."""

    dataset: str
    fields: List[FieldDescription]

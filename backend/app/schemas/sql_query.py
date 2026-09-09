"""What a reader sends the query surface, and what comes back.

Rows are positional against ``columns`` rather than keyed by name, because a
query may name two columns the same thing — ``SELECT t.id, p.id`` is legal and
gives both the name ``id``. A mapping would keep one of the two.
"""

from typing import Any, List

from pydantic import Field

from app.schemas.base import SanitizedBaseModel


class QueryRequest(SanitizedBaseModel):
    """One statement to read."""

    #: The statement. Bounded so that reading it is bounded: everything this
    #: surface accepts fits comfortably, and a payload past it is not a query
    #: anybody wrote by hand.
    sql: str = Field(min_length=1, max_length=20_000)


class QueryResponse(SanitizedBaseModel):
    """What the statement returned."""

    #: Output names, in order. Not necessarily distinct.
    columns: List[str]
    #: One list per row, positional against ``columns``.
    rows: List[List[Any]]
    #: Whether there were more rows than one query returns.
    truncated: bool

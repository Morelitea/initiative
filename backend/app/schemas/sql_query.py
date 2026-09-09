"""What a reader sends the query surface, and what comes back.

Rows are positional against ``columns`` rather than keyed by name, because a
query may name two columns the same thing — ``SELECT t.id, p.id`` is legal and
gives both the name ``id``. A mapping would keep one of the two.
"""

from typing import Any, List, Optional

from pydantic import Field

from app.schemas.base import SanitizedBaseModel
from app.schemas.query import FilterOp
from app.services.fields.spec import FieldType


class QueryRequest(SanitizedBaseModel):
    """One statement to read."""

    #: The statement. Bounded so that reading it is bounded: everything this
    #: surface accepts fits comfortably, and a payload past it is not a query
    #: anybody wrote by hand.
    sql: str = Field(min_length=1, max_length=20_000)
    #: Which initiative the answer is about. A statement names datasets, not a
    #: scope, so a surface that belongs to one initiative says so and the rows
    #: come back narrowed to it. Omitted means the whole guild the reader
    #: reaches.
    initiative_id: Optional[int] = Field(default=None, gt=0)


class QueryColumnDescription(SanitizedBaseModel):
    """One output column, as the database describes it before running."""

    name: str
    #: The same vocabulary the field registry uses, so a client reading a
    #: query's shape and a client reading a dataset's fields read one thing.
    type: FieldType


class QueryShapeResponse(SanitizedBaseModel):
    """What a statement would return, without returning it."""

    columns: List[QueryColumnDescription]
    #: The datasets the statement reads.
    relations: List[str]


class QueryResponse(SanitizedBaseModel):
    """What the statement returned."""

    #: The output columns, in order, named and typed. Names are not necessarily
    #: distinct; the statement is prepared to run either way, so saying what it
    #: returns costs nothing extra here.
    columns: List[QueryColumnDescription]
    #: One list per row, positional against ``columns``.
    rows: List[List[Any]]
    #: Whether there were more rows than one query returns.
    truncated: bool
    #: The datasets the statement read.
    relations: List[str]


class QueryColumnSpec(SanitizedBaseModel):
    """One thing a built query returns."""

    field: str = Field(min_length=1, max_length=100)
    #: Reduce the column across the group rather than returning it as it is.
    aggregate: Optional[str] = Field(default=None, max_length=20)
    #: Round a date down before grouping by it.
    bucket: Optional[str] = Field(default=None, max_length=20)
    alias: Optional[str] = Field(default=None, max_length=100)


class QueryConditionSpec(SanitizedBaseModel):
    """One comparison, in the vocabulary the filter DSL already uses."""

    field: str = Field(min_length=1, max_length=100)
    op: FilterOp = FilterOp.eq
    value: Any = None


class QuerySortSpec(SanitizedBaseModel):
    field: str = Field(min_length=1, max_length=100)
    descending: bool = False


class QueryBuildRequest(SanitizedBaseModel):
    """What somebody clicked, before it is a statement.

    The builder describes; the server writes the SQL. A statement built by
    clicking is therefore always one this surface will run, because it is built
    in the parse tree rather than assembled as text.
    """

    dataset: str = Field(min_length=1, max_length=100)
    columns: List[QueryColumnSpec] = Field(min_length=1, max_length=20)
    where: List[QueryConditionSpec] = Field(default_factory=list, max_length=20)
    group_by: List[str] = Field(default_factory=list, max_length=10)
    order_by: Optional[QuerySortSpec] = None
    limit: Optional[int] = Field(default=None, gt=0, le=10_000)
    #: Which initiative the answer is about. A statement names datasets, not a
    #: scope, so a surface that belongs to one initiative says so and the rows
    #: come back narrowed to it. Omitted means the whole guild the reader
    #: reaches.
    initiative_id: Optional[int] = Field(default=None, gt=0)


class QueryBuildResponse(SanitizedBaseModel):
    """The statement, and what it would return."""

    sql: str
    columns: List[QueryColumnDescription]
    relations: List[str]

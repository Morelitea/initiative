"""Shared query schemas for filtering, sorting, and pagination."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from app.schemas.base import SanitizedBaseModel


class FilterOp(str, Enum):
    """Comparison operators for filter conditions.

    Negation is handled by the ``negate`` flag on FilterCondition,
    not by separate operators.
    """

    eq = "eq"
    lt = "lt"
    lte = "lte"
    gt = "gt"
    gte = "gte"
    in_ = "in_"
    ilike = "ilike"
    is_null = "is_null"


class SortDir(str, Enum):
    asc = "asc"
    desc = "desc"


class FilterCondition(SanitizedBaseModel):
    """A single field comparison.

    Set ``negate=True`` to invert the result::

        # name != 'bob'
        FilterCondition(field="name", value="bob", negate=True)

        # priority NOT IN ('low', 'medium')
        FilterCondition(field="priority", op=FilterOp.in_, value=["low", "medium"], negate=True)
    """

    field: str
    op: FilterOp = FilterOp.eq
    value: Any = None
    negate: bool = False


class FilterGroup(SanitizedBaseModel):
    """Group of conditions combined with AND or OR logic.

    Set ``negate=True`` to invert the entire group::

        # NOT (status = 'archived' OR status = 'deleted')
        FilterGroup(
            logic="or",
            negate=True,
            conditions=[
                FilterCondition(field="status", value="archived"),
                FilterCondition(field="status", value="deleted"),
            ],
        )

    Groups can be nested::

        # is_active = true AND (role = 'admin' OR role = 'owner')
        FilterGroup(
            logic="and",
            conditions=[
                FilterCondition(field="is_active", value=True),
                FilterGroup(
                    logic="or",
                    conditions=[
                        FilterCondition(field="role", value="admin"),
                        FilterCondition(field="role", value="owner"),
                    ],
                ),
            ],
        )
    """

    logic: Literal["and", "or"] = "and"
    negate: bool = False
    conditions: list[FilterCondition | FilterGroup]


class SortField(SanitizedBaseModel):
    field: str
    dir: SortDir = SortDir.asc

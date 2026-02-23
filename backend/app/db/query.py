"""Reusable query utilities for filtering, sorting, and pagination.

Provides composable functions that transform SQLAlchemy Select statements:
- parse_conditions: safely parses a JSON string into FilterCondition list
- apply_filters: adds WHERE clauses from FilterCondition/FilterGroup lists
- apply_sorting: adds ORDER BY clauses from SortField list or comma-separated strings
- apply_pagination: adds OFFSET/LIMIT
- paginated_query: executes count + data queries, clamps page, returns (items, total, page)
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Select, and_, asc, desc, not_, or_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.schemas.query import FilterCondition, FilterGroup, FilterOp, SortField, SortDir


# Hard limits to prevent abuse via oversized payloads.
_MAX_CONDITIONS = 50
_MAX_SORT_FIELDS = 10
_MAX_RAW_LENGTH = 10_000


def parse_conditions(
    raw: str | None,
    *,
    max_conditions: int = _MAX_CONDITIONS,
    max_length: int = _MAX_RAW_LENGTH,
) -> list[FilterCondition]:
    """Safely parse a JSON-encoded list of filter conditions.

    Designed for use with query parameters that carry structured filters as a
    JSON string.  Applies size and count limits before touching the payload so
    an attacker cannot exhaust memory or CPU with a crafted input.

    Returns an empty list when *raw* is ``None`` or empty.

    Raises :class:`ValueError` on any validation failure — callers should catch
    this and convert to an appropriate HTTP error.
    """
    if not raw:
        return []

    if len(raw) > max_length:
        raise ValueError("conditions payload exceeds size limit")

    try:
        items = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("conditions is not valid JSON") from exc

    if not isinstance(items, list):
        raise ValueError("conditions must be a JSON array")

    if len(items) > max_conditions:
        raise ValueError(f"too many conditions (max {max_conditions})")

    try:
        return [FilterCondition(**item) for item in items]
    except (ValidationError, TypeError) as exc:
        raise ValueError("invalid condition structure") from exc


def parse_sort_fields(
    raw: str | None,
    *,
    max_fields: int = _MAX_SORT_FIELDS,
    max_length: int = _MAX_RAW_LENGTH,
) -> list[SortField]:
    """Safely parse a JSON-encoded list of sort fields.

    Mirrors :func:`parse_conditions` with the same security hardening.
    Returns an empty list when *raw* is ``None`` or empty.

    Raises :class:`ValueError` on any validation failure.
    """
    if not raw:
        return []

    if len(raw) > max_length:
        raise ValueError("sort fields payload exceeds size limit")

    try:
        items = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("sorting is not valid JSON") from exc

    if not isinstance(items, list):
        raise ValueError("sorting must be a JSON array")

    if len(items) > max_fields:
        raise ValueError(f"too many sort fields (max {max_fields})")

    try:
        return [SortField(**item) for item in items]
    except (ValidationError, TypeError) as exc:
        raise ValueError("invalid sort field structure") from exc


def extract_condition_value(
    conditions: list[FilterCondition],
    field: str,
) -> Any:
    """Return the ``value`` for the first condition matching *field*, or ``None``."""
    for cond in conditions:
        if cond.field == field:
            return cond.value
    return None


def apply_filters(
    statement: Select,
    model: Any,
    conditions: list[FilterCondition | FilterGroup],
    allowed_fields: dict[str, Any] | None = None,
) -> Select:
    """Apply filter conditions to a Select statement.

    ``conditions`` can contain flat :class:`FilterCondition` items (implicitly
    AND-ed) or :class:`FilterGroup` items for explicit AND/OR logic.

    Both :class:`FilterCondition` and :class:`FilterGroup` support a ``negate``
    flag that wraps the resulting clause in ``NOT(...)``.

    ``allowed_fields`` maps field names to SQLAlchemy column expressions **or
    callables**.  A callable value receives ``(op, value)`` and must return a
    SA clause element (or *None* to skip).  Negation is still handled
    uniformly by ``_resolve_condition``.

    If *None*, uses ``getattr(model, field)`` directly.
    Unknown fields are silently skipped (defense in depth).
    """
    for cond in conditions:
        clause = _resolve_condition(cond, model, allowed_fields)
        if clause is not None:
            statement = statement.where(clause)

    return statement


def _resolve_condition(
    cond: FilterCondition | FilterGroup,
    model: Any,
    allowed_fields: dict[str, Any] | None,
):
    """Recursively resolve a condition or group into a SA clause element."""
    if isinstance(cond, FilterGroup):
        return _resolve_group(cond, model, allowed_fields)

    # Leaf FilterCondition
    if allowed_fields is not None:
        col_or_handler = allowed_fields.get(cond.field)
    else:
        col_or_handler = getattr(model, cond.field, None)

    if col_or_handler is None:
        return None

    if callable(col_or_handler):
        clause = col_or_handler(cond.op, cond.value)
    else:
        clause = _build_filter_clause(col_or_handler, cond.op, cond.value)

    if clause is None:
        return None

    return not_(clause) if cond.negate else clause


def _resolve_group(
    group: FilterGroup,
    model: Any,
    allowed_fields: dict[str, Any] | None,
):
    """Resolve a FilterGroup into a SA and_()/or_() expression, optionally negated."""
    clauses = []
    for cond in group.conditions:
        clause = _resolve_condition(cond, model, allowed_fields)
        if clause is not None:
            clauses.append(clause)

    if not clauses:
        return None

    if len(clauses) == 1:
        combined = clauses[0]
    elif group.logic == "or":
        combined = or_(*clauses)
    else:
        combined = and_(*clauses)

    return not_(combined) if group.negate else combined


def _build_filter_clause(col: Any, op: FilterOp, value: Any):
    """Return a single WHERE clause for *col* with the given operator.

    Negation is handled by the caller via ``FilterCondition.negate``,
    not by separate operators.
    """
    if op == FilterOp.eq:
        return col == value
    if op == FilterOp.lt:
        return col < value
    if op == FilterOp.lte:
        return col <= value
    if op == FilterOp.gt:
        return col > value
    if op == FilterOp.gte:
        return col >= value
    if op == FilterOp.in_:
        if not value:
            return None
        return col.in_(tuple(value) if not isinstance(value, tuple) else value)
    if op == FilterOp.ilike:
        return col.ilike(f"%{value}%")
    if op == FilterOp.is_null:
        return col.is_(None) if value else col.is_not(None)
    return None


def apply_sorting(
    statement: Select,
    model: Any,
    sort_fields: list[SortField] | None = None,
    allowed_fields: dict[str, Any] | None = None,
    default_sort: list[tuple[Any, str]] | None = None,
    *,
    sort_by: str | None = None,
    sort_dir: str | None = None,
) -> Select:
    """Apply ORDER BY clauses to a Select statement.

    Accepts either structured ``sort_fields`` or comma-separated ``sort_by``/``sort_dir``
    strings (the current endpoint convention). When both are provided, ``sort_fields`` wins.

    ``allowed_fields`` maps field names to SA column expressions. If *None*, uses
    ``getattr(model, field)`` directly.

    ``default_sort`` is applied when no valid sort fields are found.
    """
    fields_to_apply = _resolve_sort_fields(sort_fields, sort_by, sort_dir)

    has_valid = False
    for sf in fields_to_apply:
        if allowed_fields is not None:
            col = allowed_fields.get(sf.field)
        else:
            col = getattr(model, sf.field, None)

        if col is None:
            continue

        order = desc(col) if sf.dir == SortDir.desc else asc(col)
        statement = statement.order_by(order.nulls_last())
        has_valid = True

    if not has_valid and default_sort:
        for col, direction in default_sort:
            order = desc(col) if direction == "desc" else asc(col)
            statement = statement.order_by(order)
        return statement

    if has_valid:
        # Add model PK as tiebreaker if model has an 'id' attribute
        pk = getattr(model, "id", None)
        if pk is not None:
            statement = statement.order_by(asc(pk))

    return statement


def _resolve_sort_fields(
    sort_fields: list[SortField] | None,
    sort_by: str | None,
    sort_dir: str | None,
) -> list[SortField]:
    """Convert comma-separated sort_by/sort_dir into SortField list, or use sort_fields."""
    if sort_fields:
        return sort_fields

    if not sort_by:
        return []

    fields = [f.strip() for f in sort_by.split(",") if f.strip()]
    dirs = [d.strip() for d in (sort_dir or "").split(",")]

    result = []
    for i, field_name in enumerate(fields):
        direction = dirs[i] if i < len(dirs) else "asc"
        try:
            dir_enum = SortDir(direction)
        except ValueError:
            dir_enum = SortDir.asc
        result.append(SortField(field=field_name, dir=dir_enum))

    return result


def apply_pagination(
    statement: Select,
    page: int = 1,
    page_size: int = 20,
) -> Select:
    """Apply OFFSET/LIMIT. ``page_size=0`` means no pagination (all rows)."""
    if page_size <= 0:
        return statement
    return statement.offset((page - 1) * page_size).limit(page_size)


def _clamp_page(page: int, page_size: int, total_count: int) -> int:
    """Reset page to 1 if it overshoots the available results.

    This handles the case where filters/sort changed and the current page
    no longer exists (e.g. user was on page 5, but new filters only yield 2 pages).
    """
    if page_size <= 0:
        return 1
    if total_count == 0:
        return 1
    import math
    total_pages = math.ceil(total_count / page_size)
    if page > total_pages:
        return 1
    return page


async def paginated_query(
    session: AsyncSession,
    data_stmt: Select,
    count_stmt: Select,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list, int, int]:
    """Execute count + data queries with automatic page clamping.

    Returns ``(items, total_count, actual_page)`` where *actual_page* may
    differ from the requested *page* if it overshot the result set.
    """
    total_count = (await session.exec(count_stmt)).one()

    page = _clamp_page(page, page_size, total_count)

    data_stmt = apply_pagination(data_stmt, page, page_size)
    result = await session.exec(data_stmt)
    items = list(result.all())

    return items, total_count, page


def build_paginated_response(
    items: list,
    total_count: int,
    page: int,
    page_size: int,
    **extra: Any,
) -> dict:
    """Build a dict suitable for unpacking into a concrete response model.

    Computes ``has_next`` and ``has_prev`` automatically from the inputs.
    """
    if page_size <= 0:
        effective_page = 1
        has_next = False
        has_prev = False
    else:
        effective_page = page
        has_next = page * page_size < total_count
        has_prev = page > 1

    return {
        "items": items,
        "total_count": total_count,
        "page": effective_page,
        "page_size": page_size,
        "has_next": has_next,
        "has_prev": has_prev,
        **extra,
    }

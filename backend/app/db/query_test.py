"""Unit tests for the reusable query utility functions."""

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Boolean, Float, Table
from sqlmodel import select

from app.db.query import (
    _clamp_page,
    apply_filters,
    apply_sorting,
    apply_pagination,
    build_paginated_response,
    extract_condition_value,
    parse_conditions,
    parse_sort_fields,
)
from app.schemas.query import FilterCondition, FilterGroup, FilterOp, SortField, SortDir


# ---------------------------------------------------------------------------
# Dummy table for testing (not persisted — we only inspect generated SQL)
# ---------------------------------------------------------------------------

_test_metadata = MetaData()
_dummy_table = Table(
    "dummy_items",
    _test_metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100)),
    Column("priority", String(20)),
    Column("score", Float),
    Column("is_active", Boolean),
)


class _DummyModel:
    """Attribute-access wrapper around the dummy table columns."""
    id = _dummy_table.c.id
    name = _dummy_table.c.name
    priority = _dummy_table.c.priority
    score = _dummy_table.c.score
    is_active = _dummy_table.c.is_active


# ---------------------------------------------------------------------------
# apply_filters
# ---------------------------------------------------------------------------

class TestApplyFilters:
    """Tests for apply_filters."""

    def test_eq_filter(self):
        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="name", op=FilterOp.eq, value="alice")]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "name = 'alice'" in sql

    def test_negate_eq(self):
        """negate=True on eq negates the comparison."""
        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="name", op=FilterOp.eq, value="bob", negate=True)]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        # SA optimizes NOT(x = y) into x != y
        assert "name != 'bob'" in sql

    def test_negate_in(self):
        """negate=True on in negates the IN clause."""
        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="priority", op=FilterOp.in_, value=["low", "medium"], negate=True)]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True})).upper()
        # SA may render as NOT IN or NOT (... IN ...)
        assert "NOT" in sql or "NOT IN" in sql
        assert "'LOW'" in sql

    def test_negate_gt(self):
        """negate=True on gt negates to <= (SA optimizes)."""
        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="score", op=FilterOp.gt, value=5, negate=True)]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        # SA optimizes NOT(score > 5) into score <= 5
        assert "score <= 5" in sql

    def test_negate_false_is_normal(self):
        """negate=False (default) behaves like a normal filter."""
        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="name", op=FilterOp.eq, value="alice", negate=False)]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "name = 'alice'" in sql

    def test_lt_lte_gt_gte_filters(self):
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(field="score", op=FilterOp.gt, value=5),
            FilterCondition(field="score", op=FilterOp.lte, value=100),
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "score > 5" in sql
        assert "score <= 100" in sql

    def test_in_filter(self):
        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="priority", op=FilterOp.in_, value=["high", "urgent"])]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "IN" in sql
        assert "'high'" in sql
        assert "'urgent'" in sql

    def test_in_filter_empty_list_skipped(self):
        """An in_ filter with an empty list should produce no WHERE clause."""
        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="priority", op=FilterOp.in_, value=[])]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "WHERE" not in sql

    def test_ilike_filter(self):
        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="name", op=FilterOp.ilike, value="test")]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True})).lower()
        assert "ilike" in sql or "like" in sql

    def test_is_null_true(self):
        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="name", op=FilterOp.is_null, value=True)]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "IS NULL" in sql.upper()

    def test_is_null_false(self):
        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="name", op=FilterOp.is_null, value=False)]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "IS NOT NULL" in sql.upper()

    def test_unknown_field_skipped(self):
        """Fields not in allowed_fields should be silently ignored."""
        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="nonexistent", op=FilterOp.eq, value="x")]
        allowed = {"name": _DummyModel.name}
        result = apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "WHERE" not in sql

    def test_allowed_fields_whitelist(self):
        """Only fields in the whitelist should be applied."""
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(field="name", op=FilterOp.eq, value="alice"),
            FilterCondition(field="priority", op=FilterOp.eq, value="high"),
        ]
        allowed = {"name": _DummyModel.name}  # priority not allowed
        result = apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "name = 'alice'" in sql
        # priority should appear in SELECT but not in WHERE
        where_clause = sql.split("WHERE", 1)[1] if "WHERE" in sql else ""
        assert "priority" not in where_clause

    def test_multiple_conditions(self):
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(field="name", op=FilterOp.eq, value="alice"),
            FilterCondition(field="score", op=FilterOp.gte, value=10),
            FilterCondition(field="is_active", op=FilterOp.eq, value=True),
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "name" in sql
        assert "score" in sql
        assert "is_active" in sql

    def test_no_conditions_returns_original(self):
        stmt = select(_dummy_table)
        result = apply_filters(stmt, _DummyModel, [])
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "WHERE" not in sql


# ---------------------------------------------------------------------------
# FilterGroup (and / or)
# ---------------------------------------------------------------------------

class TestFilterGroup:
    """Tests for AND/OR grouping via FilterGroup."""

    def test_or_same_field(self):
        """OR two values for the same field: name = 'alice' OR name = 'bob'."""
        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="or",
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="alice"),
                    FilterCondition(field="name", op=FilterOp.eq, value="bob"),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "OR" in sql
        assert "'alice'" in sql
        assert "'bob'" in sql

    def test_and_group(self):
        """Explicit AND group: name = 'alice' AND score > 5."""
        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="and",
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="alice"),
                    FilterCondition(field="score", op=FilterOp.gt, value=5),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "name = 'alice'" in sql
        assert "score > 5" in sql

    def test_or_with_allowed_fields(self):
        """OR group respects allowed_fields whitelist."""
        stmt = select(_dummy_table)
        allowed = {"name": _DummyModel.name}
        conditions = [
            FilterGroup(
                logic="or",
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="alice"),
                    FilterCondition(field="score", op=FilterOp.gt, value=5),  # not allowed
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        # Only name should be in the WHERE clause, score is filtered out
        assert "'alice'" in sql
        where_clause = sql.split("WHERE", 1)[1] if "WHERE" in sql else ""
        assert "score" not in where_clause

    def test_nested_groups(self):
        """Nested: is_active = true AND (name = 'alice' OR name = 'bob')."""
        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(field="is_active", op=FilterOp.eq, value=True),
            FilterGroup(
                logic="or",
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="alice"),
                    FilterCondition(field="name", op=FilterOp.eq, value="bob"),
                ],
            ),
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "is_active" in sql
        assert "OR" in sql
        assert "'alice'" in sql
        assert "'bob'" in sql

    def test_or_three_values(self):
        """OR across three values for the same field."""
        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="or",
                conditions=[
                    FilterCondition(field="priority", op=FilterOp.eq, value="low"),
                    FilterCondition(field="priority", op=FilterOp.eq, value="medium"),
                    FilterCondition(field="priority", op=FilterOp.eq, value="high"),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "OR" in sql
        assert "'low'" in sql
        assert "'medium'" in sql
        assert "'high'" in sql

    def test_or_different_ops(self):
        """OR with different operators: score > 90 OR score IS NULL."""
        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="or",
                conditions=[
                    FilterCondition(field="score", op=FilterOp.gt, value=90),
                    FilterCondition(field="score", op=FilterOp.is_null, value=True),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True})).upper()
        assert "OR" in sql
        assert "SCORE > 90" in sql
        assert "IS NULL" in sql

    def test_empty_group_skipped(self):
        """A group with no valid conditions should not add a WHERE clause."""
        stmt = select(_dummy_table)
        allowed = {"name": _DummyModel.name}
        conditions = [
            FilterGroup(
                logic="or",
                conditions=[
                    FilterCondition(field="unknown1", op=FilterOp.eq, value="x"),
                    FilterCondition(field="unknown2", op=FilterOp.eq, value="y"),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "WHERE" not in sql

    def test_single_condition_group_unwrapped(self):
        """A group with one valid condition should not wrap in AND/OR."""
        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="or",
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="alice"),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "name = 'alice'" in sql
        assert "OR" not in sql

    def test_negate_or_group(self):
        """NOT (status = 'archived' OR status = 'deleted')."""
        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="or",
                negate=True,
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="archived"),
                    FilterCondition(field="name", op=FilterOp.eq, value="deleted"),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True})).upper()
        assert "NOT" in sql
        assert "OR" in sql
        assert "'ARCHIVED'" in sql
        assert "'DELETED'" in sql

    def test_negate_and_group(self):
        """NOT (name = 'alice' AND score > 5) — negate an AND group."""
        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="and",
                negate=True,
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="alice"),
                    FilterCondition(field="score", op=FilterOp.gt, value=5),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True})).upper()
        assert "NOT" in sql
        assert "'ALICE'" in sql
        assert "SCORE > 5" in sql

    def test_negate_single_condition_group(self):
        """NOT (name = 'alice') via a negated group with one condition."""
        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="or",
                negate=True,
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="alice"),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        # SA optimizes NOT(name = 'alice') into name != 'alice'
        assert "name != 'alice'" in sql

    def test_negate_false_group_is_normal(self):
        """negate=False (default) on a group behaves normally."""
        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="or",
                negate=False,
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="alice"),
                    FilterCondition(field="name", op=FilterOp.eq, value="bob"),
                ],
            )
        ]
        result = apply_filters(stmt, _DummyModel, conditions)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "OR" in sql
        assert "NOT" not in sql.upper()


# ---------------------------------------------------------------------------
# Callable filter handlers
# ---------------------------------------------------------------------------

class TestCallableFilterHandler:
    """Tests for callable handler support in allowed_fields."""

    def test_callable_handler_basic(self):
        """A callable handler returning an IN clause is applied."""
        def status_handler(op, value):
            return _dummy_table.c.priority.in_(tuple(value))

        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="status_category", op=FilterOp.in_, value=["active", "done"])]
        allowed = {"status_category": status_handler}
        result = apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "IN" in sql
        assert "'active'" in sql
        assert "'done'" in sql

    def test_callable_handler_negate(self):
        """negate=True wraps the handler result in NOT."""
        def handler(op, value):
            return _dummy_table.c.name == value

        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="custom", op=FilterOp.eq, value="alice", negate=True)]
        allowed = {"custom": handler}
        result = apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "name != 'alice'" in sql

    def test_callable_handler_returns_none_skipped(self):
        """When handler returns None, no WHERE clause is added."""
        def handler(op, value):
            return None

        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="custom", op=FilterOp.eq, value="x")]
        allowed = {"custom": handler}
        result = apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "WHERE" not in sql

    def test_callable_handler_in_or_group(self):
        """Callable inside a FilterGroup with OR logic."""
        def handler(op, value):
            return _dummy_table.c.score > value

        stmt = select(_dummy_table)
        conditions = [
            FilterGroup(
                logic="or",
                conditions=[
                    FilterCondition(field="name", op=FilterOp.eq, value="alice"),
                    FilterCondition(field="high_score", op=FilterOp.gt, value=90),
                ],
            )
        ]
        allowed = {"name": _DummyModel.name, "high_score": handler}
        result = apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "OR" in sql
        assert "'alice'" in sql
        assert "score > 90" in sql

    def test_callable_mixed_with_column(self):
        """Dict with both column refs and callables works together."""
        def handler(op, value):
            return _dummy_table.c.score >= value

        stmt = select(_dummy_table)
        conditions = [
            FilterCondition(field="name", op=FilterOp.eq, value="bob"),
            FilterCondition(field="min_score", op=FilterOp.gte, value=50),
        ]
        allowed = {"name": _DummyModel.name, "min_score": handler}
        result = apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "name = 'bob'" in sql
        assert "score >= 50" in sql

    def test_callable_receives_correct_args(self):
        """Handler receives the exact op and value from the FilterCondition."""
        received = {}

        def handler(op, value):
            received["op"] = op
            received["value"] = value
            return _dummy_table.c.id == 1  # dummy clause

        stmt = select(_dummy_table)
        conditions = [FilterCondition(field="custom", op=FilterOp.in_, value=[10, 20])]
        allowed = {"custom": handler}
        apply_filters(stmt, _DummyModel, conditions, allowed_fields=allowed)
        assert received["op"] == FilterOp.in_
        assert received["value"] == [10, 20]


# ---------------------------------------------------------------------------
# apply_sorting
# ---------------------------------------------------------------------------

class TestApplySorting:
    """Tests for apply_sorting."""

    def test_sort_by_string_asc(self):
        stmt = select(_dummy_table)
        result = apply_sorting(stmt, _DummyModel, sort_by="name", sort_dir="asc")
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "ORDER BY" in sql
        assert "name" in sql

    def test_sort_by_string_desc(self):
        stmt = select(_dummy_table)
        result = apply_sorting(stmt, _DummyModel, sort_by="score", sort_dir="desc")
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "ORDER BY" in sql
        assert "DESC" in sql

    def test_multi_sort_by_string(self):
        stmt = select(_dummy_table)
        result = apply_sorting(stmt, _DummyModel, sort_by="name,score", sort_dir="asc,desc")
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "ORDER BY" in sql
        assert "name" in sql
        assert "score" in sql

    def test_sort_fields_structured(self):
        stmt = select(_dummy_table)
        fields = [
            SortField(field="name", dir=SortDir.asc),
            SortField(field="score", dir=SortDir.desc),
        ]
        result = apply_sorting(stmt, _DummyModel, sort_fields=fields)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "ORDER BY" in sql
        assert "name" in sql
        assert "score" in sql

    def test_default_sort_used_when_no_fields(self):
        stmt = select(_dummy_table)
        default = [(_DummyModel.score, "desc"), (_DummyModel.id, "asc")]
        result = apply_sorting(stmt, _DummyModel, default_sort=default)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "ORDER BY" in sql
        assert "score" in sql

    def test_default_sort_not_used_when_fields_provided(self):
        stmt = select(_dummy_table)
        default = [(_DummyModel.score, "desc")]
        result = apply_sorting(
            stmt, _DummyModel,
            sort_by="name", sort_dir="asc",
            default_sort=default,
        )
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "name" in sql

    def test_unknown_sort_field_falls_back_to_default(self):
        stmt = select(_dummy_table)
        allowed = {"name": _DummyModel.name}
        default = [(_DummyModel.id, "asc")]
        result = apply_sorting(
            stmt, _DummyModel,
            sort_by="nonexistent", sort_dir="asc",
            allowed_fields=allowed,
            default_sort=default,
        )
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "ORDER BY" in sql

    def test_id_tiebreaker_added(self):
        stmt = select(_dummy_table)
        result = apply_sorting(stmt, _DummyModel, sort_by="name", sort_dir="asc")
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        # Should have id as tiebreaker at the end
        assert "id" in sql

    def test_no_sort_no_default_returns_unmodified(self):
        stmt = select(_dummy_table)
        result = apply_sorting(stmt, _DummyModel)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "ORDER BY" not in sql


# ---------------------------------------------------------------------------
# apply_pagination
# ---------------------------------------------------------------------------

class TestApplyPagination:
    """Tests for apply_pagination."""

    def test_first_page(self):
        stmt = select(_dummy_table)
        result = apply_pagination(stmt, page=1, page_size=20)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "LIMIT" in sql
        assert "OFFSET" in sql

    def test_second_page(self):
        stmt = select(_dummy_table)
        result = apply_pagination(stmt, page=2, page_size=10)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "LIMIT" in sql
        assert "10" in sql

    def test_page_size_zero_no_pagination(self):
        stmt = select(_dummy_table)
        result = apply_pagination(stmt, page=1, page_size=0)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "LIMIT" not in sql
        assert "OFFSET" not in sql

    def test_negative_page_size_no_pagination(self):
        stmt = select(_dummy_table)
        result = apply_pagination(stmt, page=1, page_size=-1)
        sql = str(result.compile(compile_kwargs={"literal_binds": True}))
        assert "LIMIT" not in sql


# ---------------------------------------------------------------------------
# build_paginated_response
# ---------------------------------------------------------------------------

class TestBuildPaginatedResponse:
    """Tests for build_paginated_response helper."""

    def test_basic_response(self):
        result = build_paginated_response(
            items=["a", "b", "c"],
            total_count=50,
            page=2,
            page_size=20,
        )
        assert result["items"] == ["a", "b", "c"]
        assert result["total_count"] == 50
        assert result["page"] == 2
        assert result["page_size"] == 20
        assert result["has_next"] is True
        assert result["has_prev"] is True

    def test_first_page_no_prev(self):
        result = build_paginated_response(
            items=["a", "b"],
            total_count=5,
            page=1,
            page_size=3,
        )
        assert result["has_next"] is True
        assert result["has_prev"] is False

    def test_last_page_no_next(self):
        result = build_paginated_response(
            items=["e"],
            total_count=5,
            page=2,
            page_size=4,
        )
        assert result["has_next"] is False
        assert result["has_prev"] is True

    def test_single_page(self):
        result = build_paginated_response(
            items=["a", "b"],
            total_count=2,
            page=1,
            page_size=20,
        )
        assert result["has_next"] is False
        assert result["has_prev"] is False

    def test_extra_fields(self):
        result = build_paginated_response(
            items=[],
            total_count=0,
            page=1,
            page_size=20,
            sort_by="name",
            sort_dir="asc",
        )
        assert result["sort_by"] == "name"
        assert result["sort_dir"] == "asc"
        assert result["has_next"] is False
        assert result["has_prev"] is False

    def test_page_size_zero_resets_page(self):
        result = build_paginated_response(
            items=["a"],
            total_count=1,
            page=5,
            page_size=0,
        )
        assert result["page"] == 1
        assert result["has_next"] is False
        assert result["has_prev"] is False


# ---------------------------------------------------------------------------
# _clamp_page
# ---------------------------------------------------------------------------

class TestClampPage:
    """Tests for page clamping when page overshoots results."""

    def test_valid_page_unchanged(self):
        assert _clamp_page(2, 10, 50) == 2

    def test_page_beyond_total_resets_to_1(self):
        # 50 items, 20 per page = 3 pages. Page 5 is out of range.
        assert _clamp_page(5, 20, 50) == 1

    def test_last_page_is_valid(self):
        # 50 items, 20 per page = 3 pages. Page 3 is valid.
        assert _clamp_page(3, 20, 50) == 3

    def test_zero_total_resets_to_1(self):
        assert _clamp_page(3, 20, 0) == 1

    def test_page_size_zero_returns_1(self):
        assert _clamp_page(5, 0, 100) == 1

    def test_page_1_always_valid(self):
        assert _clamp_page(1, 20, 1) == 1

    def test_exact_boundary(self):
        # 20 items, 20 per page = 1 page. Page 1 is valid, page 2 is not.
        assert _clamp_page(1, 20, 20) == 1
        assert _clamp_page(2, 20, 20) == 1


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestSchemas:
    """Tests for query schema validation."""

    def test_pagination_params_defaults(self):
        from app.schemas.query import PaginationParams
        params = PaginationParams()
        assert params.page == 1
        assert params.page_size == 20

    def test_pagination_params_validation(self):
        from app.schemas.query import PaginationParams
        with pytest.raises(Exception):
            PaginationParams(page=0)  # ge=1

    def test_pagination_params_max_page_size(self):
        from app.schemas.query import PaginationParams
        with pytest.raises(Exception):
            PaginationParams(page_size=101)  # le=100

    def test_filter_condition_defaults(self):
        cond = FilterCondition(field="name", value="test")
        assert cond.op == FilterOp.eq
        assert cond.negate is False

    def test_sort_field_defaults(self):
        sf = SortField(field="name")
        assert sf.dir == SortDir.asc


# ---------------------------------------------------------------------------
# parse_conditions (security & validation)
# ---------------------------------------------------------------------------

class TestParseConditions:
    """Tests for parse_conditions including security hardening."""

    def test_none_returns_empty(self):
        assert parse_conditions(None) == []

    def test_empty_string_returns_empty(self):
        assert parse_conditions("") == []

    def test_valid_single_condition(self):
        raw = '[{"field": "name", "op": "eq", "value": "alice"}]'
        result = parse_conditions(raw)
        assert len(result) == 1
        assert result[0].field == "name"
        assert result[0].op == FilterOp.eq
        assert result[0].value == "alice"

    def test_valid_multiple_conditions(self):
        raw = '[{"field": "a", "op": "eq", "value": 1}, {"field": "b", "op": "gt", "value": 5}]'
        result = parse_conditions(raw)
        assert len(result) == 2

    def test_defaults_applied(self):
        """op defaults to eq, negate defaults to False."""
        raw = '[{"field": "name", "value": "test"}]'
        result = parse_conditions(raw)
        assert result[0].op == FilterOp.eq
        assert result[0].negate is False

    def test_negate_preserved(self):
        raw = '[{"field": "name", "op": "eq", "value": "x", "negate": true}]'
        result = parse_conditions(raw)
        assert result[0].negate is True

    def test_rejects_oversized_payload(self):
        with pytest.raises(ValueError, match="size limit"):
            parse_conditions("x" * 10_001)

    def test_custom_max_length(self):
        with pytest.raises(ValueError, match="size limit"):
            parse_conditions("x" * 101, max_length=100)

    def test_rejects_invalid_json(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            parse_conditions("{not json}")

    def test_rejects_non_array(self):
        with pytest.raises(ValueError, match="must be a JSON array"):
            parse_conditions('{"field": "name"}')

    def test_rejects_too_many_conditions(self):
        items = [{"field": "f", "value": i} for i in range(51)]
        import json
        with pytest.raises(ValueError, match="too many conditions"):
            parse_conditions(json.dumps(items))

    def test_custom_max_conditions(self):
        items = [{"field": "f", "value": i} for i in range(3)]
        import json
        with pytest.raises(ValueError, match="too many conditions"):
            parse_conditions(json.dumps(items), max_conditions=2)

    def test_rejects_invalid_structure(self):
        with pytest.raises(ValueError, match="invalid condition structure"):
            parse_conditions('[{"bad_key": "value"}]')

    def test_rejects_invalid_op(self):
        with pytest.raises(ValueError, match="invalid condition structure"):
            parse_conditions('[{"field": "name", "op": "DROP TABLE", "value": "x"}]')

    def test_at_exact_limit_succeeds(self):
        items = [{"field": "f", "value": i} for i in range(50)]
        import json
        result = parse_conditions(json.dumps(items))
        assert len(result) == 50


# ---------------------------------------------------------------------------
# extract_condition_value
# ---------------------------------------------------------------------------

class TestExtractConditionValue:
    """Tests for extract_condition_value helper."""

    def test_finds_matching_field(self):
        conditions = [
            FilterCondition(field="status", op=FilterOp.eq, value="active"),
            FilterCondition(field="priority", op=FilterOp.in_, value=["high"]),
        ]
        assert extract_condition_value(conditions, "priority") == ["high"]

    def test_returns_first_match(self):
        conditions = [
            FilterCondition(field="name", value="first"),
            FilterCondition(field="name", value="second"),
        ]
        assert extract_condition_value(conditions, "name") == "first"

    def test_returns_none_when_not_found(self):
        conditions = [FilterCondition(field="name", value="test")]
        assert extract_condition_value(conditions, "missing") is None

    def test_empty_list_returns_none(self):
        assert extract_condition_value([], "anything") is None


# ---------------------------------------------------------------------------
# parse_sort_fields (security & validation)
# ---------------------------------------------------------------------------

class TestParseSortFields:
    """Tests for parse_sort_fields including security hardening."""

    def test_none_returns_empty(self):
        assert parse_sort_fields(None) == []

    def test_empty_string_returns_empty(self):
        assert parse_sort_fields("") == []

    def test_valid_single_field(self):
        raw = '[{"field": "due_date", "dir": "desc"}]'
        result = parse_sort_fields(raw)
        assert len(result) == 1
        assert result[0].field == "due_date"
        assert result[0].dir == SortDir.desc

    def test_valid_multiple_fields(self):
        raw = '[{"field": "date_group", "dir": "asc"}, {"field": "due_date", "dir": "desc"}]'
        result = parse_sort_fields(raw)
        assert len(result) == 2
        assert result[0].field == "date_group"
        assert result[1].dir == SortDir.desc

    def test_defaults_dir_to_asc(self):
        raw = '[{"field": "title"}]'
        result = parse_sort_fields(raw)
        assert result[0].dir == SortDir.asc

    def test_rejects_oversized_payload(self):
        with pytest.raises(ValueError, match="size limit"):
            parse_sort_fields("x" * 10_001)

    def test_rejects_invalid_json(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            parse_sort_fields("{not json}")

    def test_rejects_non_array(self):
        with pytest.raises(ValueError, match="must be a JSON array"):
            parse_sort_fields('{"field": "name"}')

    def test_rejects_too_many_fields(self):
        items = [{"field": f"f{i}"} for i in range(11)]
        import json
        with pytest.raises(ValueError, match="too many sort fields"):
            parse_sort_fields(json.dumps(items))

    def test_rejects_invalid_structure(self):
        with pytest.raises(ValueError, match="invalid sort field structure"):
            parse_sort_fields('[{"bad_key": "value"}]')

    def test_rejects_invalid_dir(self):
        with pytest.raises(ValueError, match="invalid sort field structure"):
            parse_sort_fields('[{"field": "name", "dir": "RANDOM"}]')

    def test_at_exact_limit_succeeds(self):
        items = [{"field": f"f{i}"} for i in range(10)]
        import json
        result = parse_sort_fields(json.dumps(items))
        assert len(result) == 10

    def test_custom_max_fields(self):
        items = [{"field": f"f{i}"} for i in range(3)]
        import json
        with pytest.raises(ValueError, match="too many sort fields"):
            parse_sort_fields(json.dumps(items), max_fields=2)

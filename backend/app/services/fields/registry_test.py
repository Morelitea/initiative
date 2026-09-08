"""The registry expresses what the task filter path already did.

This phase re-points an existing surface at a new declaration, so the only
interesting question is whether anything changed. Two halves answer it: the set
of filterable names has to match what the endpoint's builder produced, and each
virtual field has to compile to the same clause it always did.

The endpoint tests are the other half — they exercise these fields through real
requests, and they were not touched.
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from app.models.tenant.task import Task
from app.schemas.query import FilterOp
from app.services.fields import (
    FieldContext,
    allowed_fields,
    allowed_ops,
    dataset,
    describe,
    sort_fields,
)

pytestmark = pytest.mark.unit


def _ctx(
    *,
    guild_id: int = 7,
    user_id: int = 42,
    property_definitions: dict | None = None,
    tz: str | None = None,
) -> FieldContext:
    """Named explicitly rather than **kwargs: a context this helper does not
    know about should be a TypeError, not a silently dropped argument."""
    return FieldContext(
        guild_id=guild_id,
        user_id=user_id,
        property_definitions=property_definitions or {},
        tz=tz,
    )


def _sql(clause) -> str:
    return str(
        clause.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


#: What ``_build_task_filter_fields`` produced before the registry: every column
#: on the model, plus these five. Spelled out rather than derived, so a field
#: quietly disappearing from the declaration fails here.
VIRTUAL_FIELDS = {
    "status_category",
    "assignee_ids",
    "tag_ids",
    "initiative_ids",
    "property_values",
}


class TestCoverage:
    def test_every_model_column_is_filterable(self):
        """The old builder auto-populated from the model. So does this."""
        resolved = allowed_fields("tasks", _ctx())
        for col in Task.__table__.columns:
            assert col.name in resolved, f"{col.name} lost its filter field"

    def test_the_virtual_fields_are_all_present(self):
        resolved = allowed_fields("tasks", _ctx())
        assert VIRTUAL_FIELDS <= set(resolved)

    def test_nothing_else_crept_in(self):
        """The set is exactly the columns plus the five — a field nobody asked
        for is as much a change as a missing one."""
        resolved = set(allowed_fields("tasks", _ctx()))
        expected = {c.name for c in Task.__table__.columns} | VIRTUAL_FIELDS
        assert resolved == expected

    def test_columns_pass_through_and_virtuals_are_callable(self):
        resolved = allowed_fields("tasks", _ctx())
        assert resolved["title"] is Task.title
        for name in VIRTUAL_FIELDS:
            assert callable(resolved[name])


class TestVirtualFields:
    """Each compiles to the clause it compiled to before."""

    def test_status_category_matches_statuses_in_those_categories(self):
        clause = allowed_fields("tasks", _ctx())["status_category"](
            FilterOp.in_, ["done"]
        )
        sql = _sql(clause)
        assert "task_status_id IN" in sql
        assert "'done'" in sql

    def test_status_category_ignores_an_empty_list(self):
        assert (
            allowed_fields("tasks", _ctx())["status_category"](FilterOp.in_, []) is None
        )

    def test_assignee_me_resolves_to_the_requesting_user(self):
        clause = allowed_fields("tasks", _ctx(user_id=99))["assignee_ids"](
            FilterOp.in_, ["me"]
        )
        assert "99" in _sql(clause)

    def test_assignee_mixes_me_with_real_ids(self):
        clause = allowed_fields("tasks", _ctx(user_id=99))["assignee_ids"](
            FilterOp.in_, ["me", "5"]
        )
        sql = _sql(clause)
        assert "99" in sql and "5" in sql

    def test_assignee_is_null_true_means_unassigned(self):
        clause = allowed_fields("tasks", _ctx())["assignee_ids"](FilterOp.is_null, True)
        assert "NOT" in _sql(clause).upper()

    def test_assignee_is_null_false_means_has_any_assignee(self):
        clause = allowed_fields("tasks", _ctx())["assignee_ids"](
            FilterOp.is_null, False
        )
        assert "NOT" not in _sql(clause).upper()

    def test_a_non_numeric_assignee_is_refused(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as excinfo:
            allowed_fields("tasks", _ctx())["assignee_ids"](FilterOp.in_, ["nope"])
        assert excinfo.value.status_code == 400

    def test_tags_are_scoped_to_the_requesting_guild(self):
        """The guild leg is what stops a tag id from another community
        matching; it comes from the context, not from the filter."""
        clause = allowed_fields("tasks", _ctx(guild_id=1234))["tag_ids"](
            FilterOp.in_, [1]
        )
        assert "1234" in _sql(clause)

    def test_initiative_ids_resolve_through_projects(self):
        clause = allowed_fields("tasks", _ctx())["initiative_ids"](FilterOp.in_, [3])
        sql = _sql(clause)
        assert "project_id IN" in sql
        assert "initiative_id IN" in sql

    def test_an_unknown_property_contributes_nothing(self):
        clause = allowed_fields("tasks", _ctx())["property_values"](
            FilterOp.eq, {"property_id": 1, "value": "x"}
        )
        assert clause is None

    def test_a_malformed_property_payload_contributes_nothing(self):
        resolve = allowed_fields("tasks", _ctx())["property_values"]
        assert resolve(FilterOp.eq, "not a dict") is None
        assert resolve(FilterOp.eq, {"property_id": "abc"}) is None


#: What ``_task_sort_fields`` offered before the registry.
SORTABLE_FIELDS = {
    "position",
    "title",
    "due_date",
    "start_date",
    "priority",
    "created_at",
    "updated_at",
    "date_group",
}


class TestSorting:
    def test_the_sortable_set_is_unchanged(self):
        assert set(sort_fields("tasks", _ctx())) == SORTABLE_FIELDS

    def test_a_sortable_column_orders_by_itself(self):
        assert sort_fields("tasks", _ctx())["title"] is Task.title

    def test_date_group_is_an_expression_not_a_column(self):
        """It is a CASE over two dates, so there is no column to hand back."""
        expression = sort_fields("tasks", _ctx())["date_group"]
        assert "CASE" in _sql(expression)

    def test_date_group_follows_the_readers_timezone(self):
        """The same row groups differently depending on whose day it is."""
        naive = _sql(sort_fields("tasks", _ctx())["date_group"])
        aware = _sql(sort_fields("tasks", _ctx(tz="America/New_York"))["date_group"])
        assert "AT TIME ZONE" not in naive
        assert "America/New_York" in aware

    def test_most_columns_are_filterable_without_being_sortable(self):
        """Sortability is opt-in: a field list nobody can read is not a
        feature, and most columns narrow usefully without ordering usefully."""
        filterable = set(allowed_fields("tasks", _ctx()))
        assert SORTABLE_FIELDS - {"date_group"} < filterable

    def test_date_group_is_sort_only(self):
        assert "date_group" not in allowed_fields("tasks", _ctx())


#: What the frontend's hand-kept ``TASK_FILTER_FIELDS`` offered before this
#: became derived. Everything here must survive, or a filter somebody built
#: stops being offered.
PREVIOUSLY_OFFERED = {
    "status_category": (["in_"], True),
    "task_status_id": (["in_"], True),
    "priority": (["in_"], True),
    "assignee_ids": (["in_", "is_null"], True),
    "tag_ids": (["in_"], True),
    "project_id": (["eq"], False),
    "due_date": (["gt", "gte", "is_null", "lt", "lte"], False),
    "start_date": (["gt", "gte", "is_null", "lt", "lte"], False),
    "completed_at": (["gt", "gte", "is_null", "lt", "lte"], False),
    "created_at": (["gt", "gte", "lt", "lte"], False),
    "is_archived": (["eq"], False),
    "title": (["ilike"], False),
}

#: Added when the two lists became one — fields the engine always accepted and
#: no control ever offered.
NEWLY_OFFERED = {"description", "updated_at", "created_by", "property_values"}


class TestDescription:
    def test_everything_the_old_frontend_list_offered_still_is(self):
        by_name = {entry["name"]: entry for entry in describe("tasks")}
        for name, (ops, multiple) in PREVIOUSLY_OFFERED.items():
            assert name in by_name, f"{name} stopped being offered"
            assert by_name[name]["ops"] == ops, name
            assert by_name[name]["multiple"] is multiple, name

    def test_the_offered_set_is_the_old_one_plus_the_agreed_additions(self):
        offered = {entry["name"] for entry in describe("tasks")}
        assert offered == set(PREVIOUSLY_OFFERED) | NEWLY_OFFERED

    def test_bookkeeping_is_hidden_everywhere_rather_than_per_dataset(self):
        """Soft-delete columns, the surrogate key, the tenant key and the
        ordering float mean nothing to somebody building a filter, and every
        table has them."""
        offered = {entry["name"] for entry in describe("tasks")}
        assert offered.isdisjoint(
            {"id", "guild_id", "position", "deleted_at", "deleted_by", "purge_at"}
        )

    def test_a_hidden_field_is_still_filterable_by_a_stored_definition(self):
        """Hiding governs what a control offers, never what the engine accepts."""
        resolved = allowed_fields("tasks", _ctx())
        assert "initiative_ids" in resolved
        assert "updated_at" in resolved

    def test_an_entry_carries_what_a_control_needs(self):
        by_name = {entry["name"]: entry for entry in describe("tasks")}
        assert by_name["priority"]["kind"] == "priority"
        assert by_name["assignee_ids"]["kind"] == "member"
        assert by_name["due_date"]["type"] == "date"

    def test_it_carries_no_resolvers(self):
        """What a field compiles to is ours; a client gets the description."""
        for entry in describe("tasks"):
            assert not any(callable(value) for value in entry.values())


class TestOperatorEnforcement:
    def test_a_field_declares_only_operators_its_resolver_handles(self):
        """``_status_category`` and ``_tag_ids`` build an ``IN`` over their
        value, so ``in_`` is the one operator each of them answers."""
        ops = allowed_ops("tasks")
        assert ops["status_category"] == {FilterOp.in_}
        assert ops["tag_ids"] == {FilterOp.in_}

    def test_the_one_computed_field_that_handles_emptiness_declares_it(self):
        assert FilterOp.is_null in allowed_ops("tasks")["assignee_ids"]

    def test_a_control_never_offers_an_operator_the_engine_refuses(self):
        engine = allowed_ops("tasks")
        for entry in describe("tasks"):
            offered = {FilterOp(op) for op in entry["ops"]}
            assert offered <= engine[entry["name"]], entry["name"]

    def test_is_empty_is_offered_only_where_a_value_can_be_empty(self):
        by_name = {entry["name"]: entry for entry in describe("tasks")}
        # created_at is NOT NULL; due_date is not.
        assert "is_null" not in by_name["created_at"]["ops"]
        assert "is_null" in by_name["due_date"]["ops"]


class TestDeclaration:
    def test_a_field_is_a_column_or_a_computation_never_both(self):
        for spec in dataset("tasks").fields:
            assert not (spec.column is not None and spec.resolve is not None)

    def test_every_field_declares_some_way_to_be_used(self):
        for spec in dataset("tasks").fields:
            assert spec.filterable or spec.sortable

    def test_a_field_cannot_claim_a_use_it_cannot_perform(self):
        for spec in dataset("tasks").fields:
            if spec.filterable:
                assert spec.column is not None or spec.resolve is not None
            if spec.sortable:
                assert spec.column is not None or spec.sort is not None

    def test_the_dataset_takes_its_name_from_the_tool_where_it_can(self):
        from app.core.tools import Tool

        assert dataset("tasks").tool is Tool.project

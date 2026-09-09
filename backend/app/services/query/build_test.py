"""What a builder describes, and the statement it becomes.

The point of building in the parse tree rather than as text is that quoting and
spelling stop being ours to get right. So the assertions that matter are the
hostile ones: a literal that would close a string early, and an alias somebody
chose, both come out as one statement the validator accepts.
"""

from __future__ import annotations

import pytest

from app.core.messages import QueryMessages
from app.schemas.query import FilterOp
from app.services.query import QueryError
from app.services.query.build import (
    Column,
    Condition,
    QuerySpec,
    Sort,
    build,
    build_and_resolve,
)

pytestmark = pytest.mark.unit


def test_a_grouped_count_is_the_shape_a_chart_wants():
    sql, _ = build_and_resolve(
        QuerySpec(
            dataset="tasks",
            columns=(
                Column(field="priority"),
                Column(field="*", aggregate="count", alias="tasks"),
            ),
            group_by=("priority",),
            order_by=Sort(field="tasks", descending=True),
            limit=10,
        )
    )
    assert "count(*) AS tasks" in sql
    assert "GROUP BY 1" in sql
    assert "ORDER BY 2 DESC" in sql
    assert "LIMIT 10" in sql


def test_a_bare_column_is_not_aliased_to_itself():
    """Postgres names an output after the column it read, so an alias there
    would read as ``priority AS priority``."""
    assert build(QuerySpec(dataset="tasks", columns=(Column(field="priority"),))) == (
        "SELECT priority FROM tasks"
    )


def test_a_date_is_rounded_before_it_is_grouped():
    sql, _ = build_and_resolve(
        QuerySpec(
            dataset="tasks",
            columns=(
                Column(field="completed_at", bucket="day", alias="day"),
                Column(field="*", aggregate="count", alias="done"),
            ),
            where=(Condition(field="completed_at", op=FilterOp.is_null, value=False),),
            group_by=("day",),
        )
    )
    assert "date_trunc('day', completed_at) AS day" in sql
    assert "completed_at IS NOT NULL" in sql


@pytest.mark.parametrize(
    "value",
    [
        "it's",
        "'; DROP TABLE tasks; --",
        "'''",
        "line\nbreak",
        "trailing backslash \\",
    ],
)
def test_a_value_stays_one_value(value):
    """A literal is written into the tree, not into the text, so what it
    contains is the deparser's business. Each of these comes back as one
    statement the surface will run."""
    sql, resolved = build_and_resolve(
        QuerySpec(
            dataset="tasks",
            columns=(Column(field="title"),),
            where=(Condition(field="title", op=FilterOp.ilike, value=value),),
        )
    )
    assert sql.startswith("SELECT title FROM tasks WHERE")
    # Resolution binds it, so the value reaches Postgres as a parameter.
    assert resolved.parameters == (value,)


def test_an_alias_somebody_chose_stays_one_name():
    sql, _ = build_and_resolve(
        QuerySpec(
            dataset="tasks",
            columns=(Column(field="title", alias='weird" name'),),
        )
    )
    assert sql.count("SELECT") == 1
    assert '"weird"" name"' in sql


def test_several_conditions_are_all_required():
    sql, _ = build_and_resolve(
        QuerySpec(
            dataset="tasks",
            columns=(Column(field="title"),),
            where=(
                Condition(field="is_archived", op=FilterOp.eq, value=False),
                Condition(field="priority", op=FilterOp.in_, value=["high", "urgent"]),
            ),
        )
    )
    assert "AND" in sql
    assert "IN" in sql


class TestWhatItRefuses:
    def test_a_dataset_nobody_declared(self):
        with pytest.raises(QueryError) as refused:
            build(QuerySpec(dataset="pg_shadow", columns=(Column(field="usename"),)))
        assert refused.value.code == QueryMessages.UNKNOWN_RELATION

    def test_a_field_the_dataset_does_not_have(self):
        with pytest.raises(QueryError) as refused:
            build(QuerySpec(dataset="tasks", columns=(Column(field="nope"),)))
        assert refused.value.code == QueryMessages.UNKNOWN_FIELD

    def test_a_function_that_is_not_an_aggregate(self):
        with pytest.raises(QueryError) as refused:
            build(
                QuerySpec(
                    dataset="tasks",
                    columns=(Column(field="title", aggregate="pg_sleep"),),
                )
            )
        assert refused.value.code == QueryMessages.UNSUPPORTED_FUNCTION

    def test_a_bucket_that_is_not_a_bucket(self):
        with pytest.raises(QueryError) as refused:
            build(
                QuerySpec(
                    dataset="tasks",
                    columns=(Column(field="due_date", bucket="fortnight"),),
                )
            )
        assert refused.value.code == QueryMessages.UNSUPPORTED_SYNTAX

    def test_grouping_by_something_the_statement_does_not_return(self):
        with pytest.raises(QueryError) as refused:
            build(
                QuerySpec(
                    dataset="tasks",
                    columns=(Column(field="title"),),
                    group_by=("priority",),
                )
            )
        assert refused.value.code == QueryMessages.UNKNOWN_FIELD

    def test_a_statement_with_nothing_in_it(self):
        with pytest.raises(QueryError):
            build(QuerySpec(dataset="tasks", columns=()))


class TestReachingThroughARelation:
    """A dataset declares what it can be read alongside, and both ways of
    asking write the same joins from the same declaration."""

    def test_a_related_field_writes_its_joins(self):
        sql = build(
            QuerySpec(
                dataset="tasks",
                columns=(
                    Column(field="assignee.display_name", alias="person"),
                    Column(field="*", aggregate="count", alias="tasks"),
                ),
                group_by=("person",),
            )
        )
        assert "JOIN task_assignees" in sql
        assert "JOIN members AS assignee" in sql
        assert "assignee.display_name AS person" in sql

    def test_what_it_writes_is_a_statement_the_surface_runs(self):
        """The point of building the tree rather than the text: the validator
        reads what comes out, joins and all."""
        _sql, resolved = build_and_resolve(
            QuerySpec(
                dataset="tasks",
                columns=(
                    Column(field="assignee.display_name", alias="person"),
                    Column(field="*", aggregate="count", alias="n"),
                ),
                group_by=("person",),
            )
        )
        assert set(resolved.relations) == {"tasks", "task_assignees", "members"}

    def test_a_relation_nobody_declared_is_refused(self):
        with pytest.raises(QueryError) as refused:
            build(
                QuerySpec(
                    dataset="tasks",
                    columns=(Column(field="nowhere.name"),),
                )
            )
        assert refused.value.code == QueryMessages.UNKNOWN_RELATION

    def test_a_field_the_relation_does_not_reach_is_refused(self):
        with pytest.raises(QueryError) as refused:
            build(
                QuerySpec(
                    dataset="tasks",
                    columns=(Column(field="assignee.nonsense"),),
                )
            )
        assert refused.value.code == QueryMessages.UNKNOWN_FIELD

    def test_a_relation_is_joined_once_however_often_it_is_named(self):
        sql = build(
            QuerySpec(
                dataset="tasks",
                columns=(
                    Column(field="assignee.display_name", alias="person"),
                    Column(field="assignee.username", alias="handle"),
                ),
            )
        )
        assert sql.count("JOIN members AS assignee") == 1

    def test_a_filter_may_reach_through_one_too(self):
        sql = build(
            QuerySpec(
                dataset="tasks",
                columns=(Column(field="title"),),
                where=(Condition(field="status.category", value="done"),),
            )
        )
        assert "JOIN task_statuses AS status" in sql
        assert "status.category" in sql


class TestPickingYourself:
    """A member picker offers the reader themselves, and what that builds is
    the token rather than a value — so the tile answers per person."""

    def test_a_person_field_takes_the_reader(self):
        sql = build(
            QuerySpec(
                dataset="tasks",
                columns=(Column(field="*", aggregate="count", alias="n"),),
                where=(Condition(field="created_by", op=FilterOp.eq, value="me"),),
            )
        )
        assert sql.endswith("WHERE created_by = me")

    def test_it_reaches_through_a_relation(self):
        sql = build(
            QuerySpec(
                dataset="tasks",
                columns=(Column(field="*", aggregate="count", alias="n"),),
                where=(Condition(field="assignee.id", op=FilterOp.eq, value="me"),),
            )
        )
        assert sql.endswith("WHERE assignee.id = me")

    def test_a_list_takes_it_beside_real_people(self):
        sql = build(
            QuerySpec(
                dataset="tasks",
                columns=(Column(field="*", aggregate="count", alias="n"),),
                where=(
                    Condition(field="created_by", op=FilterOp.in_, value=["me", 7]),
                ),
            )
        )
        assert sql.endswith("WHERE created_by IN (me, 7)")

    def test_anywhere_else_it_is_just_a_word(self):
        """A title may be the word "me", and comparing against it is a text
        comparison like any other."""
        sql = build(
            QuerySpec(
                dataset="tasks",
                columns=(Column(field="title"),),
                where=(Condition(field="title", op=FilterOp.eq, value="me"),),
            )
        )
        assert sql.endswith("WHERE title = 'me'")

    def test_what_it_builds_is_a_statement_the_validator_takes(self):
        _, resolved = build_and_resolve(
            QuerySpec(
                dataset="tasks",
                columns=(Column(field="*", aggregate="count", alias="n"),),
                where=(Condition(field="created_by", op=FilterOp.eq, value="me"),),
            )
        )
        assert "app.current_user_id" in resolved.sql
        assert resolved.parameters == ()

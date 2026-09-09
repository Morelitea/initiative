"""The one-off that rewrote every stored dashboard binding as a statement.

A migration runs once, against rows CI never has: a fresh install carries
nothing, so the whole generator is dead code to every test that builds from
empty. What it produces is pure, though, and that is what these check — every
binding the old shape could hold, against the validator the new one has to pass.

The rule worth reading first is the last: a filter this cannot say in SQL leaves
its widget alone. A rewritten widget that quietly dropped somebody's filter
would answer a broader question than the one they saved, and look right doing
it.
"""

import importlib.util
from pathlib import Path

import pytest

from app.services.query.resolve import QueryError, resolve
from app.services.tenant.dashboard_definition import WIDGET_SPECS

pytestmark = pytest.mark.unit

_REVISION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260909_0241_dashboard_bindings_become_queries.py"
)


def _cutover():
    """The revision module, loaded by path — it is not an importable package,
    and naming the file is what ties this to the revision it checks."""
    spec = importlib.util.spec_from_file_location("dashboard_cutover", _REVISION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cutover = _cutover()

#: Every source the old shape had, with the parameters each of them took.
LEGACY_BINDINGS = [
    {"source": "tasks"},
    {"source": "tasks", "project_id": 3},
    {
        "source": "tasks",
        "conditions": [{"field": "priority", "op": "eq", "value": "x"}],
    },
    {"source": "tasks", "conditions": [{"field": "due_date", "op": "is_null"}]},
    {
        "source": "tasks",
        "conditions": [{"field": "task_status_id", "op": "in_", "value": [1, 2]}],
    },
    {"source": "task_counts"},
    *(
        {"source": "task_counts", "bucket": bucket}
        for bucket in (
            "status_category",
            "status",
            "priority",
            "project",
            "day",
            "assignee",
        )
    ),
    {"source": "task_counts", "bucket": "day", "day_field": "created", "project_id": 9},
    *(
        {
            "source": "task_counts",
            "bucket": bucket,
            "project_id": 4,
            "conditions": [{"field": "is_archived", "op": "eq", "value": False}],
        }
        for bucket in ("status_category", "status", "priority", "project", "day")
    ),
    {"source": "projects"},
    {"source": "calendar_entries"},
    {"source": "calendar_entries", "calendar_id": 2, "window_days": 30},
    {"source": "counter", "counter_id": 7},
    {"source": "counter_group", "counter_group_id": 8},
]

#: Filters the DSL answered with machinery a statement has no form for.
UNTRANSLATABLE = [
    # A computed field: reached through a join the DSL built at fetch time.
    [{"field": "status_category", "op": "eq", "value": "done"}],
    # A relative date, kept relative in the definition.
    [{"field": "due_date", "op": "lt", "value": {"relative": 30}}],
    # A group rather than a leaf.
    [{"logic": "or", "conditions": [{"field": "priority", "op": "eq", "value": "x"}]}],
    # Negation, which is a flag rather than an operator.
    [{"field": "priority", "op": "eq", "value": "x", "negate": True}],
]


class TestEveryLegacyBindingBecomesAStatementTheSurfaceRuns:
    @pytest.mark.parametrize("binding", LEGACY_BINDINGS)
    @pytest.mark.parametrize("widget_type", sorted(WIDGET_SPECS))
    def test_it_resolves(self, binding, widget_type):
        sql = cutover._statement(binding, widget_type)
        assert sql, f"{binding} on {widget_type} produced nothing"
        try:
            resolve(sql)
        except QueryError as refused:
            pytest.fail(f"{sql!r} refused: {refused}")

    def test_a_widget_that_draws_one_number_gets_one_number(self):
        """A stat handed a grouped series shows the first group, not the
        total — the grouping was the source's question, not the widget's."""
        binding = {"source": "task_counts", "bucket": "priority"}
        assert cutover._statement(binding, "stat") == (
            "SELECT count(*) AS tasks FROM tasks"
        )
        assert "GROUP BY" in cutover._statement(binding, "chart")

    def test_a_filter_is_spelled_the_way_its_own_statement_spells_tasks(self):
        """Some buckets join tasks under an alias and some read it plainly."""
        filtered = {
            "source": "task_counts",
            "conditions": [{"field": "is_archived", "op": "eq", "value": False}],
        }
        joined = cutover._statement({**filtered, "bucket": "status"}, "chart")
        flat = cutover._statement({**filtered, "bucket": "priority"}, "chart")
        assert "t.is_archived = false" in joined
        assert "WHERE is_archived = false" in flat

    def test_a_value_carrying_a_quote_stays_one_value(self):
        sql = cutover._statement(
            {
                "source": "tasks",
                "conditions": [{"field": "title", "op": "ilike", "value": "o'brien%"}],
            },
            "table",
        )
        assert resolve(sql).parameters == ("o'brien%",)

    def test_a_window_stays_relative_to_now(self):
        """A dashboard asking for the last 30 days is asking a standing
        question, not about the days this migration happened to run between."""
        sql = cutover._statement(
            {"source": "calendar_entries", "window_days": 30}, "table"
        )
        assert "now() - CAST('30 days' AS interval)" in sql
        assert resolve(sql)


class TestAFilterThatDoesNotTranslateLeavesItsWidgetAlone:
    @pytest.mark.parametrize("conditions", UNTRANSLATABLE)
    @pytest.mark.parametrize("widget_type", ["stat", "chart", "table"])
    def test_nothing_is_generated(self, conditions, widget_type):
        binding = {"source": "tasks", "conditions": conditions}
        assert cutover._statement(binding, widget_type) is None

    def test_the_widget_keeps_its_binding_and_is_reported(self):
        definition = {
            "widgets": [
                {"id": "w1", "type": "stat", "binding": {"source": "tasks"}},
                {
                    "id": "w2",
                    "type": "chart",
                    "binding": {"source": "tasks", "conditions": UNTRANSLATABLE[0]},
                },
            ]
        }
        rewritten, _config, changed, skipped = cutover._rewrite(definition, {})
        assert changed == 1
        assert skipped == ["w2"]
        assert rewritten["widgets"][0]["binding"]["source"] == "query"
        assert rewritten["widgets"][1]["binding"] == {
            "source": "tasks",
            "conditions": UNTRANSLATABLE[0],
        }


class TestTheIdsAnInstallSupplied:
    """A listing leaves the ids it cannot know for its guild to fill, and they
    live in the dashboard's config rather than its definition."""

    def test_an_id_from_the_config_reaches_the_statement(self):
        definition = {
            "widgets": [
                {"id": "w1", "type": "chart", "binding": {"source": "counter_group"}}
            ]
        }
        config = {"widgets": {"w1": {"counter_group_id": 12}}}
        rewritten, pruned, changed, _skipped = cutover._rewrite(definition, config)
        assert changed == 1
        assert "counter_group_id = 12" in rewritten["widgets"][0]["binding"]["sql"]
        # Spent: the statement carries it now, so nothing reads it any more.
        assert pruned["widgets"] == {}

    def test_a_config_entry_for_another_widget_is_left_alone(self):
        definition = {
            "widgets": [{"id": "w1", "type": "chart", "binding": {"source": "app"}}]
        }
        config = {"widgets": {"w1": {"endpoint_id": "app.x.y"}}}
        _rewritten, pruned, changed, _skipped = cutover._rewrite(definition, config)
        assert changed == 0
        assert pruned["widgets"] == {"w1": {"endpoint_id": "app.x.y"}}


@pytest.mark.parametrize("source", ["query", "sheet_range", "app"])
def test_a_binding_already_in_the_new_shape_is_untouched(source):
    binding = {"source": source, "sql": "SELECT count(*) AS n FROM tasks"}
    definition = {"widgets": [{"id": "w1", "type": "stat", "binding": dict(binding)}]}
    rewritten, _config, changed, skipped = cutover._rewrite(definition, {})
    assert (changed, skipped) == (0, [])
    assert rewritten["widgets"][0]["binding"] == binding


def test_every_bucket_the_generator_knows_says_how_it_reads_tasks():
    """One declaration, not two: a bucket that groups and a bucket that
    narrows have to agree about whether tasks carries an alias."""
    assert set(cutover._TASK_PREFIX) == set(cutover._COUNT_BY) | {"day"}
    assert set(cutover._GROUP_BY) == set(cutover._COUNT_BY)


@pytest.mark.parametrize("widget_type", sorted(cutover._SINGLE_VALUE))
def test_a_widget_given_one_number_is_one_that_draws_one(widget_type):
    """The generator names the widgets it hands a total to. They have to be
    real widgets, and each has to have somewhere to put the number."""
    shape = WIDGET_SPECS[widget_type].shape
    assert any(slot.name == "value" for slot in shape)

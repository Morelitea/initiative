"""The one-off that rewrote every stored dashboard binding as a statement.

A migration runs once, against rows CI never has: a fresh install carries
nothing, so the whole generator is dead code to every test that builds from
empty. What it produces is pure, though, and that is what these check — every
binding the old shape could hold, against the validator the new one has to pass.

The rule worth reading first is the last: a filter this cannot say in SQL
leaves its widget with no statement rather than a broader one. A widget that
quietly dropped somebody's filter would answer a question they never asked and
look right doing it; one with no statement asks to be pointed somewhere.
"""

import importlib.util
from pathlib import Path

import pytest

from app.services.query.resolve import QueryError, resolve
from app.services.tenant.dashboard_definition import (
    WIDGET_SPECS,
    normalize_dashboard_definition,
)

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
            "conditions": [{"field": "archived_at", "op": "is_null", "value": True}],
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
            "conditions": [{"field": "archived_at", "op": "is_null", "value": True}],
        }
        joined = cutover._statement({**filtered, "bucket": "status"}, "chart")
        flat = cutover._statement({**filtered, "bucket": "priority"}, "chart")
        assert "t.archived_at IS NULL" in joined
        assert "WHERE archived_at IS NULL" in flat

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


class TestAFilterThatDoesNotTranslateLeavesItsWidgetUnbound:
    @pytest.mark.parametrize("conditions", UNTRANSLATABLE)
    @pytest.mark.parametrize("widget_type", ["stat", "chart", "table"])
    def test_nothing_is_generated(self, conditions, widget_type):
        binding = {"source": "tasks", "conditions": conditions}
        assert cutover._statement(binding, widget_type) is None

    def test_the_widget_is_left_with_no_statement_and_is_reported(self):
        """A source nothing fetches any more would take the whole dashboard
        with it — the definition would stop validating on the next save. The
        widget goes to the unconfigured state instead, which is storable and
        says what it needs."""
        legacy = {"source": "tasks", "conditions": UNTRANSLATABLE[0]}
        definition = {
            "widgets": [
                {"id": "w1", "type": "stat", "binding": {"source": "tasks"}},
                {"id": "w2", "type": "chart", "binding": dict(legacy)},
            ]
        }
        rewritten, _config, changed, unbound = cutover._rewrite(definition, {})
        assert changed == 1
        assert unbound == ["w2"]
        assert rewritten["widgets"][0]["binding"]["source"] == "query"
        assert rewritten["widgets"][1]["binding"] == {
            "source": "query",
            "legacy": {"binding": legacy},
        }

    def test_what_it_could_not_say_still_normalizes(self):
        """The whole point of the unconfigured state: the dashboard is still
        storable afterwards."""
        definition = {
            "widgets": [
                {
                    "id": "w1",
                    "type": "chart",
                    "grid": {"x": 0, "y": 0, "w": 6, "h": 4},
                    "binding": {"source": "tasks", "conditions": UNTRANSLATABLE[0]},
                }
            ]
        }
        rewritten, _config, _changed, _unbound = cutover._rewrite(definition, {})
        normalized = normalize_dashboard_definition(rewritten)
        assert normalized["widgets"][0]["binding"]["source"] == "query"
        assert "sql" not in normalized["widgets"][0]["binding"]


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
        rewritten, pruned, changed, _unbound = cutover._rewrite(definition, config)
        assert changed == 1
        assert "counter_group_id = 12" in rewritten["widgets"][0]["binding"]["sql"]
        # Spent: the statement carries it now, so nothing reads it any more.
        assert pruned["widgets"] == {}

    def test_a_config_entry_for_another_widget_is_left_alone(self):
        definition = {
            "widgets": [{"id": "w1", "type": "chart", "binding": {"source": "app"}}]
        }
        config = {"widgets": {"w1": {"endpoint_id": "app.x.y"}}}
        _rewritten, pruned, changed, _unbound = cutover._rewrite(definition, config)
        assert changed == 0
        assert pruned["widgets"] == {"w1": {"endpoint_id": "app.x.y"}}


class TestTheDowngradePutsThemBack:
    """A statement carries no record of what it was written from, so the
    upgrade keeps one. That is the whole of what makes this reversible."""

    @staticmethod
    def _round_trip(definition, config=None):
        rewritten, pruned, _changed, _unbound = cutover._rewrite(
            definition, config or {}
        )
        return cutover._restore(rewritten, pruned)

    def test_a_rewritten_binding_goes_back_as_it_was(self):
        was = {"source": "task_counts", "bucket": "priority", "project_id": 4}
        definition = {"widgets": [{"id": "w1", "type": "chart", "binding": dict(was)}]}
        restored, _config, count = self._round_trip(definition)
        assert count == 1
        assert restored["widgets"][0]["binding"] == was

    def test_one_that_could_not_be_rewritten_goes_back_too(self):
        was = {"source": "tasks", "conditions": UNTRANSLATABLE[0]}
        definition = {"widgets": [{"id": "w1", "type": "chart", "binding": dict(was)}]}
        restored, _config, count = self._round_trip(definition)
        assert count == 1
        assert restored["widgets"][0]["binding"] == was

    def test_an_id_the_install_supplied_goes_back_to_the_config(self):
        """Which half an id came from is the difference between a listing's own
        definition and one guild's answer to it. Restoring the merge would put
        the guild's answer where the next version of the listing overwrites
        it."""
        definition = {
            "widgets": [
                {"id": "w1", "type": "chart", "binding": {"source": "counter_group"}}
            ]
        }
        config = {"widgets": {"w1": {"counter_group_id": 12}}}
        restored, put_back, count = self._round_trip(definition, config)
        assert count == 1
        assert restored["widgets"][0]["binding"] == {"source": "counter_group"}
        assert put_back["widgets"] == {"w1": {"counter_group_id": 12}}

    def test_a_widget_written_afterwards_is_left_alone(self):
        """It has no older shape to go back to."""
        binding = {"source": "query", "sql": "SELECT count(*) AS n FROM tasks"}
        definition = {
            "widgets": [{"id": "w1", "type": "stat", "binding": dict(binding)}]
        }
        restored, _config, count = cutover._restore(definition, {})
        assert count == 0
        assert restored["widgets"][0]["binding"] == binding

    def test_a_statement_somebody_has_rebuilt_is_theirs(self):
        """The marker rides along on the binding, so an author who rebuilds a
        migrated widget still carries it. What says their work is theirs is
        that the statement is no longer the one this revision wrote."""
        definition = {
            "widgets": [
                {"id": "w1", "type": "chart", "binding": {"source": "task_counts"}}
            ]
        }
        rewritten, pruned, _changed, _unbound = cutover._rewrite(definition, {})
        mine = "SELECT priority, count(*) AS n FROM tasks GROUP BY priority"
        rewritten["widgets"][0]["binding"]["sql"] = mine

        restored, _config, count = cutover._restore(rewritten, pruned)
        assert count == 0
        assert restored["widgets"][0]["binding"]["sql"] == mine

    def test_a_statement_built_where_there_was_none_is_theirs_too(self):
        """The same, for a widget the upgrade left unconfigured."""
        definition = {
            "widgets": [
                {
                    "id": "w1",
                    "type": "chart",
                    "binding": {"source": "tasks", "conditions": UNTRANSLATABLE[0]},
                }
            ]
        }
        rewritten, pruned, _changed, unbound = cutover._rewrite(definition, {})
        assert unbound == ["w1"]
        rewritten["widgets"][0]["binding"]["sql"] = "SELECT count(*) AS n FROM tasks"

        _restored, _config, count = cutover._restore(rewritten, pruned)
        assert count == 0


@pytest.mark.parametrize("source", ["query", "sheet_range", "app"])
def test_a_binding_already_in_the_new_shape_is_untouched(source):
    binding = {"source": source, "sql": "SELECT count(*) AS n FROM tasks"}
    definition = {"widgets": [{"id": "w1", "type": "stat", "binding": dict(binding)}]}
    rewritten, _config, changed, unbound = cutover._rewrite(definition, {})
    assert (changed, unbound) == (0, [])
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

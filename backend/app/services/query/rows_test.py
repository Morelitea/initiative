"""A statement over rows an app returned.

Two things are worth testing separately, because they fail differently. What
the *planner* refuses is refused while somebody is looking at it, so it has to
name what is wrong. What the *evaluator* answers is what a tile draws, so it
has to agree with what Postgres would have said about the same rows — the
whole point being that a widget cannot tell the two apart.
"""

import pytest

from app.core.messages import QueryMessages
from app.services.fields.spec import FieldType
from app.services.query.resolve import QueryError
from app.services.query.rows import RowColumn, evaluate, plan

pytestmark = pytest.mark.unit

READS = (
    RowColumn("shop", FieldType.text),
    RowColumn("revenue", FieldType.number),
    RowColumn("at", FieldType.date),
    RowColumn("open", FieldType.boolean),
)

ROWS = [
    {"shop": "north", "revenue": 10, "at": "2026-01-05T00:00:00Z", "open": True},
    {"shop": "north", "revenue": 5, "at": "2026-01-06T00:00:00Z", "open": False},
    {"shop": "south", "revenue": 7, "at": "2026-02-01T00:00:00Z", "open": True},
    {"shop": "south", "revenue": None, "at": None, "open": None},
]


def run(sql: str, rows=ROWS):
    return evaluate(plan(sql, READS), rows)


class TestWhatThePlannerRefuses:
    def test_a_column_the_endpoint_does_not_return(self):
        """The whole reason an app declares its output: this is refused while
        its author is looking at it, not on the tile afterwards."""
        with pytest.raises(QueryError) as refused:
            plan("SELECT margin FROM rows", READS)
        assert refused.value.code == QueryMessages.UNKNOWN_FIELD
        assert "margin" in refused.value.subject

    def test_a_relation_that_is_not_the_rows_it_fetched(self):
        with pytest.raises(QueryError) as refused:
            plan("SELECT shop FROM tasks", READS)
        assert refused.value.code == QueryMessages.UNKNOWN_RELATION

    def test_a_join(self):
        """There is one relation. A second thing to join does not exist."""
        with pytest.raises(QueryError):
            plan("SELECT shop FROM rows a JOIN rows b ON a.shop = b.shop", READS)

    @pytest.mark.parametrize(
        "sql",
        [
            "DELETE FROM rows",
            "SELECT shop FROM rows UNION SELECT shop FROM rows",
            "SELECT pg_sleep(10) AS v FROM rows",
            "SELECT * FROM rows",
            "SELECT shop FROM rows; SELECT shop FROM rows",
        ],
    )
    def test_the_same_things_the_postgres_path_refuses(self, sql):
        """The allow-lists are shared, so this is not a second opinion about
        what a statement may contain."""
        with pytest.raises(QueryError):
            plan(sql, READS)

    def test_a_qualified_name_is_the_rows(self):
        assert plan("SELECT rows.shop FROM rows", READS).columns[0].name == "shop"

    def test_an_alias_may_be_ordered_by(self):
        planned = plan(
            "SELECT shop, sum(revenue) AS total FROM rows GROUP BY shop ORDER BY total",
            READS,
        )
        assert [column.name for column in planned.columns] == ["shop", "total"]


class TestWhatItSaysItReturns:
    """Known without running anything, because every column it can name was
    declared. The shape contract reads this the way it reads Postgres's."""

    @pytest.mark.parametrize(
        "expression,expected",
        [
            ("shop", FieldType.text),
            ("revenue", FieldType.number),
            ("at", FieldType.date),
            ("open", FieldType.boolean),
            ("count(*)", FieldType.number),
            ("sum(revenue)", FieldType.number),
            ("avg(revenue)", FieldType.number),
            ("min(at)", FieldType.date),
            ("max(shop)", FieldType.text),
            ("date_trunc('day', at)", FieldType.date),
            ("lower(shop)", FieldType.text),
            ("length(shop)", FieldType.number),
            ("revenue + 1", FieldType.number),
            ("revenue > 1", FieldType.boolean),
            ("coalesce(revenue, 0)", FieldType.number),
        ],
    )
    def test_the_type_of_an_output(self, expression, expected):
        assert (
            plan(f"SELECT {expression} AS v FROM rows", READS).columns[0].type
            == expected
        )

    def test_an_unaliased_column_keeps_its_name(self):
        assert plan("SELECT shop FROM rows", READS).columns[0].name == "shop"


class TestWhatItAnswers:
    def test_a_plain_read(self):
        assert run("SELECT shop FROM rows WHERE revenue > 6") == (
            ("north",),
            ("south",),
        )

    def test_counting_everything_answers_once(self):
        """An aggregate with no grouping is one group over every row, not one
        answer per row."""
        assert run("SELECT count(*) AS n FROM rows") == ((4,),)

    def test_counting_a_column_skips_the_rows_without_one(self):
        assert run("SELECT count(revenue) AS n FROM rows") == ((3,),)

    def test_grouping_and_totalling(self):
        assert run(
            "SELECT shop, sum(revenue) AS total FROM rows GROUP BY shop ORDER BY shop"
        ) == (("north", 15.0), ("south", 7.0))

    def test_a_group_of_nothing_but_nulls_totals_to_nothing(self):
        rows = [{"shop": "west", "revenue": None, "at": None, "open": None}]
        assert run("SELECT sum(revenue) AS total FROM rows", rows) == ((None,),)

    def test_ordering_descending(self):
        assert run(
            "SELECT shop, sum(revenue) AS total FROM rows "
            "GROUP BY shop ORDER BY sum(revenue) DESC"
        ) == (("north", 15.0), ("south", 7.0))

    def test_ordering_by_an_output_it_computed(self):
        assert run(
            "SELECT shop, sum(revenue) AS total FROM rows GROUP BY shop ORDER BY total DESC"
        ) == (("north", 15.0), ("south", 7.0))

    def test_a_limit(self):
        assert run("SELECT shop FROM rows ORDER BY shop LIMIT 1") == (("north",),)

    def test_nothing_sorts_against_a_missing_value(self):
        """Absent goes last rather than raising, whichever way it is sorted."""
        assert run("SELECT revenue FROM rows ORDER BY revenue")[-1] == (None,)

    def test_a_bucketed_date_groups_by_its_bucket(self):
        answered = run(
            "SELECT date_trunc('month', at) AS month, count(*) AS n FROM rows "
            "WHERE at IS NOT NULL GROUP BY date_trunc('month', at) ORDER BY 1"
        )
        assert [row[1] for row in answered] == [2, 1]

    def test_a_moment_comes_back_the_way_postgres_sends_one(self):
        """Epoch milliseconds, which is the one spelling the widgets take."""
        answered = run("SELECT at FROM rows WHERE at IS NOT NULL ORDER BY at")
        assert all(isinstance(row[0], int) for row in answered)

    @pytest.mark.parametrize(
        "predicate,expected",
        [
            ("shop = 'north'", 2),
            ("shop <> 'north'", 2),
            ("shop ILIKE 'NOR%'", 2),
            ("shop LIKE 'nor%'", 2),
            ("shop LIKE 'NOR%'", 0),
            ("shop IN ('north', 'west')", 2),
            ("revenue IS NULL", 1),
            ("revenue IS NOT NULL", 3),
            ("revenue > 5 AND shop = 'north'", 1),
            ("revenue > 5 OR shop = 'south'", 3),
            ("NOT (shop = 'north')", 2),
            ("open IS TRUE", 2),
        ],
    )
    def test_a_predicate(self, predicate, expected):
        assert len(run(f"SELECT shop FROM rows WHERE {predicate}")) == expected

    def test_a_pattern_means_only_what_like_means(self):
        """``%`` and ``_``, and nothing else — a pattern is walked rather than
        compiled, so what looks like a regex is matched literally."""
        rows = [
            {"shop": "a.c", "revenue": 1, "at": None, "open": None},
            {"shop": "abc", "revenue": 1, "at": None, "open": None},
        ]
        assert len(run("SELECT shop FROM rows WHERE shop LIKE 'a.c'", rows)) == 1
        assert len(run("SELECT shop FROM rows WHERE shop LIKE 'a_c'", rows)) == 2

    def test_a_case_expression(self):
        answered = run(
            "SELECT CASE WHEN revenue > 6 THEN 'big' ELSE 'small' END AS size FROM rows"
        )
        assert [row[0] for row in answered] == ["big", "small", "big", "small"]

    def test_rows_the_app_left_a_column_out_of(self):
        """An app is not a table: a key it did not send reads as absent rather
        than failing the whole read."""
        assert run("SELECT revenue FROM rows", [{"shop": "west"}]) == ((None,),)


class TestItAgreesWithPostgres:
    """The clauses the validator admits, and the truth values SQL has.

    Each of these was accepted by the planner and then quietly ignored or got
    wrong by the evaluator, which is the one failure mode worth most: the same
    statement over a task list and over an app's rows answering differently.
    """

    def test_distinct_returns_each_row_once(self):
        assert run("SELECT DISTINCT shop FROM rows") == (("north",), ("south",))

    def test_distinct_on_is_refused_rather_than_ignored(self):
        """It picks one row per key by an ordering this does not own."""
        with pytest.raises(QueryError):
            plan("SELECT DISTINCT ON (shop) shop FROM rows", READS)

    def test_offset_skips_before_the_limit_takes(self):
        assert run("SELECT shop FROM rows ORDER BY shop, revenue LIMIT 2 OFFSET 1") == (
            ("north",),
            ("south",),
        )

    def test_having_filters_the_groups(self):
        counted = "SELECT shop, count(*) AS n FROM rows GROUP BY shop HAVING count(*)"
        assert run(f"{counted} > 1") == (("north", 2), ("south", 2))
        assert run(f"{counted} > 2") == ()

    def test_grouping_by_an_ordinal_groups_by_that_output(self):
        """``GROUP BY 1`` names the first output's expression, not the number
        one — which would put every row in one group."""
        assert run("SELECT shop, count(*) AS n FROM rows GROUP BY 1") == (
            ("north", 2),
            ("south", 2),
        )

    def test_grouping_by_an_alias_groups_by_what_it_names(self):
        assert run("SELECT lower(shop) AS s, count(*) AS n FROM rows GROUP BY s") == (
            ("north", 2),
            ("south", 2),
        )

    @pytest.mark.parametrize(
        "predicate,expected",
        [
            # `NOT unknown` is unknown, not true, so the row with no revenue is
            # not brought back by negating a comparison against it.
            ("NOT (revenue = 10)", 2),
            ("revenue NOT IN (10, NULL)", 0),
            ("revenue IN (10, NULL)", 1),
            ("NOT (revenue > 100)", 3),
            ("revenue > 6 OR shop = 'south'", 3),
            ("revenue > 6 AND shop = 'south'", 1),
        ],
    )
    def test_a_missing_value_makes_a_predicate_unknown(self, predicate, expected):
        assert len(run(f"SELECT shop FROM rows WHERE {predicate}")) == expected

    @pytest.mark.parametrize(
        "clause,expected",
        [
            # Absent sorts as though larger than anything: last going up, first
            # coming down, unless the statement says otherwise.
            ("revenue", [5, 7, 10, None]),
            ("revenue DESC", [None, 10, 7, 5]),
            ("revenue NULLS FIRST", [None, 5, 7, 10]),
            ("revenue DESC NULLS LAST", [10, 7, 5, None]),
        ],
    )
    def test_where_a_missing_value_sorts(self, clause, expected):
        answered = run(f"SELECT revenue FROM rows ORDER BY {clause}")
        assert [row[0] for row in answered] == expected

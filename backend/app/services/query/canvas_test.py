"""What a canvas compiles to, read off the statement it writes."""

from app.services.query import resolve
from app.services.query.canvas import compile_canvas


def _compiled(*statements: str):
    return compile_canvas([resolve(s) for s in statements], row_limit=11)


def test_a_dataset_two_widgets_read_is_read_once_with_only_their_columns():
    compiled = _compiled(
        "SELECT count(*) AS n FROM tasks",
        "SELECT title FROM tasks ORDER BY due_date LIMIT 5",
    )
    assert compiled.shared == ("tasks",)
    assert compiled.sql.startswith(
        'WITH "tasks" AS MATERIALIZED (SELECT "due_date", "id", "title" FROM "tasks") '
    )


def test_a_dataset_one_widget_reads_is_left_to_its_indexes():
    compiled = _compiled(
        "SELECT count(*) AS n FROM tasks",
        "SELECT count(*) AS n FROM projects",
    )
    assert compiled.shared == ()
    assert not compiled.sql.startswith("WITH")


def test_an_output_alias_is_not_taken_for_a_column():
    compiled = _compiled(
        "SELECT priority, count(*) AS n FROM tasks GROUP BY priority ORDER BY n",
        "SELECT count(*) AS n FROM tasks",
    )
    assert '"n"' not in compiled.sql.split(") SELECT")[0]


def test_parameters_are_numbered_across_the_canvas():
    compiled = _compiled(
        "SELECT title FROM tasks WHERE priority = 'high' LIMIT 3",
        "SELECT title FROM tasks WHERE priority = 'low' LIMIT 4",
    )
    first, second = (
        resolve(s)
        for s in (
            "SELECT title FROM tasks WHERE priority = 'high' LIMIT 3",
            "SELECT title FROM tasks WHERE priority = 'low' LIMIT 4",
        )
    )
    assert compiled.parameters == first.parameters + second.parameters
    offset = len(first.parameters)
    for number in range(1, len(second.parameters) + 1):
        assert f"${number + offset}" in compiled.sql.split("AS w1")[0].split("AS w0")[1]


def test_each_widget_is_one_output_column_capped_at_the_row_limit():
    compiled = _compiled(
        "SELECT count(*) AS n FROM tasks", "SELECT 1 AS one FROM tasks"
    )
    assert compiled.sql.count("LIMIT 11) AS q)") == 2
    assert compiled.sql.endswith("AS w1")

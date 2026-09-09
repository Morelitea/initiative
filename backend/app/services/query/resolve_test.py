"""What the query surface accepts, and what it refuses.

The interesting assertion is never "this query works" — it is that everything
else is refused *by name*, so a construct nobody considered cannot arrive by
being unconsidered. Each refusal is checked for its code, because the code is
what a client shows the person who has to change the query.
"""

from __future__ import annotations

import pytest

from app.core.messages import QueryMessages
from app.services.query import QueryError, resolve

#: The function spellings this surface supports, as a reader writes them.
#: Postgres reports the name it resolved, so a spelling that is really a node
#: of its own (``coalesce``) or that arrives qualified (``extract``) is still
#: covered here — the assertion is that the spelling works, not what it
#: becomes.
SUPPORTED_CALLS = (
    "count(1)",
    "sum(1)",
    "avg(1)",
    "min(1)",
    "max(1)",
    "coalesce(1, 2)",
    "nullif(1, 2)",
    "greatest(1, 2)",
    "least(1, 2)",
    "abs(1)",
    "round(1)",
    "length('a')",
    "lower('a')",
    "upper('a')",
    "concat('a', 'b')",
    "date_trunc('day', now())",
    "extract(year from now())",
    "now()",
)

pytestmark = pytest.mark.unit


def refusal(sql: str) -> str:
    with pytest.raises(QueryError) as caught:
        resolve(sql)
    return caught.value.code


class TestOnlyAReadIsAdmitted:
    @pytest.mark.parametrize(
        "sql",
        [
            "DROP TABLE tasks",
            "DELETE FROM tasks",
            "UPDATE tasks SET title = 'x'",
            "INSERT INTO tasks (title) VALUES ('x')",
            "TRUNCATE tasks",
            "CREATE TABLE evil (id int)",
            "ALTER TABLE tasks ADD COLUMN evil int",
            "GRANT SELECT ON tasks TO PUBLIC",
        ],
    )
    def test_a_statement_that_is_not_a_select_is_refused(self, sql):
        assert refusal(sql) == QueryMessages.READ_ONLY

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT title FROM tasks; DROP TABLE tasks",
            "SELECT title FROM tasks; SELECT title FROM tasks",
        ],
    )
    def test_a_second_statement_is_refused(self, sql):
        assert refusal(sql) == QueryMessages.ONE_STATEMENT_ONLY

    def test_a_trailing_semicolon_is_not_a_second_statement(self):
        assert resolve("SELECT title FROM tasks;").sql

    @pytest.mark.parametrize(
        "sql",
        [
            "COPY tasks TO '/tmp/out'",
            "SET work_mem = '1GB'",
            "BEGIN",
        ],
    )
    def test_no_command_but_a_query(self, sql):
        assert refusal(sql) in {
            QueryMessages.READ_ONLY,
            QueryMessages.UNPARSEABLE,
        }

    def test_a_lock_is_not_a_read(self):
        assert refusal("SELECT title FROM tasks FOR UPDATE") == (
            QueryMessages.UNSUPPORTED_SYNTAX
        )

    def test_set_operations_are_not_accepted(self):
        """Read-only, but the surface admits one SELECT and this is two."""
        assert refusal("SELECT 1 UNION SELECT 2") == (QueryMessages.UNSUPPORTED_SYNTAX)


class TestNamesResolveThroughTheRegistry:
    def test_a_relation_the_registry_does_not_offer(self):
        assert refusal("SELECT id FROM users") == QueryMessages.UNKNOWN_RELATION

    def test_a_schema_qualified_relation(self):
        """A relation is named on its own; the search path decides where it
        lives, and it is set to one guild's schema."""
        assert refusal("SELECT usename FROM pg_catalog.pg_user") == (
            QueryMessages.QUALIFIED_RELATION
        )
        assert refusal("SELECT id FROM public.users") == (
            QueryMessages.QUALIFIED_RELATION
        )

    def test_a_field_the_dataset_does_not_have(self):
        assert refusal("SELECT nope FROM tasks") == QueryMessages.UNKNOWN_FIELD

    def test_a_computed_field_has_no_column_to_name(self):
        """``status_category`` is a subquery the filter path builds, not a
        column, so there is nothing for a SELECT to read yet."""
        assert refusal("SELECT status_category FROM tasks") == (
            QueryMessages.FIELD_NOT_SELECTABLE
        )

    def test_an_unqualified_column_with_two_relations_in_scope(self):
        sql = "SELECT id FROM tasks JOIN projects ON tasks.project_id = projects.id"
        assert refusal(sql) == QueryMessages.AMBIGUOUS_FIELD

    def test_one_relation_needs_no_qualifier(self):
        assert "title" in resolve("SELECT title FROM tasks").sql

    def test_two_relations_may_not_share_an_alias(self):
        sql = "SELECT t.id FROM tasks t JOIN projects t ON true"
        assert refusal(sql) == QueryMessages.DUPLICATE_ALIAS

    def test_a_wildcard_is_not_a_column_list(self):
        """``*`` means whatever the table happens to hold, which is not
        something a saved tile can rely on."""
        assert refusal("SELECT * FROM tasks") == QueryMessages.STAR_NOT_ALLOWED
        assert refusal("SELECT t.* FROM tasks t") == QueryMessages.STAR_NOT_ALLOWED

    def test_count_of_everything_names_no_column(self):
        assert resolve("SELECT count(*) AS n FROM tasks").sql

    def test_an_output_alias_is_a_name_where_the_output_exists(self):
        """``ORDER BY n`` and ``GROUP BY n`` are resolved against the select
        list, so the alias is not looked up as a column."""
        resolved = resolve("SELECT count(*) AS n FROM tasks GROUP BY title ORDER BY n")
        assert "ORDER BY n" in resolved.sql

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT title AS n FROM tasks WHERE n = 'x'",
            "SELECT count(*) AS n FROM tasks GROUP BY title HAVING n > 1",
        ],
    )
    def test_an_output_alias_is_a_column_everywhere_else(self, sql):
        """WHERE and HAVING are evaluated before the output exists, so a name
        there has to be a column and this one is not."""
        assert refusal(sql) == QueryMessages.UNKNOWN_FIELD

    def test_the_relations_read_are_reported(self):
        """The caller decides whether this reader may read them, so it has to
        be told which they are."""
        sql = "SELECT p.name FROM projects p JOIN tasks k ON k.project_id = p.id"
        assert resolve(sql).relations == ("projects", "tasks")


class TestStructuralCost:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT tasks.id FROM tasks, projects",
            "SELECT tasks.id FROM tasks CROSS JOIN projects",
            "SELECT tasks.id FROM tasks JOIN projects ON true",
        ],
    )
    def test_a_join_needs_something_joining_it(self, sql):
        """Every row against every row is the one shape whose cost grows
        faster than the data, and it is visible before anything is planned."""
        assert refusal(sql) in {
            QueryMessages.JOIN_WITHOUT_CONDITION,
            QueryMessages.UNSUPPORTED_SYNTAX,
        }

    def test_a_condition_that_pairs_nothing_is_not_a_join(self):
        """``ON true`` reads as a join and behaves as a cross product."""
        sql = "SELECT tasks.id FROM tasks JOIN projects ON true"
        assert refusal(sql) == QueryMessages.JOIN_WITHOUT_CONDITION

    def test_a_condition_naming_only_one_side_is_not_a_join(self):
        sql = "SELECT tasks.id FROM tasks JOIN projects ON tasks.id > 0"
        assert refusal(sql) == QueryMessages.JOIN_WITHOUT_CONDITION

    def test_naming_both_sides_without_relating_them_is_not_a_join(self):
        """Two predicates that each filter one relation still pair every
        surviving row with every other."""
        sql = "SELECT t.id FROM tasks t JOIN projects p ON t.id > 0 AND p.id > 0"
        assert refusal(sql) == QueryMessages.JOIN_WITHOUT_CONDITION

    def test_a_relating_predicate_alongside_a_filter_is_a_join(self):
        sql = (
            "SELECT t.id FROM tasks t JOIN projects p "
            "ON t.project_id = p.id AND p.is_archived = false"
        )
        assert resolve(sql).relations == ("projects", "tasks")

    def test_a_later_join_must_tie_in_what_it_adds(self):
        """The third join's condition relates the first two relations, so the
        one it adds is joined to nothing and multiplies the result."""
        sql = (
            "SELECT a.id FROM tasks a "
            "JOIN tasks b ON a.id = b.id "
            "JOIN tasks c ON a.id = b.id"
        )
        assert refusal(sql) == QueryMessages.JOIN_WITHOUT_CONDITION

    def test_a_chain_of_joins_each_tying_in_is_accepted(self):
        sql = (
            "SELECT a.id FROM tasks a "
            "JOIN tasks b ON a.project_id = b.project_id "
            "JOIN projects c ON b.project_id = c.id"
        )
        assert resolve(sql).relations == ("projects", "tasks")

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT a.title FROM tasks a JOIN tasks b USING (id)",
            "SELECT a.title FROM tasks a JOIN tasks b USING (nope)",
            "SELECT a.title FROM tasks a JOIN tasks b USING (status_category)",
        ],
    )
    def test_using_is_not_accepted(self, sql):
        """It names columns positionally rather than as column references, so
        the resolving pass never sees them. ON says the same thing in a form
        that resolves."""
        assert refusal(sql) == QueryMessages.UNSUPPORTED_SYNTAX

    def test_a_join_that_pairs_rows_is_accepted(self):
        sql = "SELECT p.name FROM projects p JOIN tasks k ON k.project_id = p.id"
        assert resolve(sql).relations == ("projects", "tasks")

    def test_a_self_join_is_bound_by_its_aliases(self):
        sql = "SELECT a.title FROM tasks a JOIN tasks b ON a.project_id = b.project_id"
        assert resolve(sql).sql

    def test_a_statement_may_name_only_so_many_relations(self):
        joins = " ".join(
            f"JOIN tasks t{i} ON t{i}.project_id = p.id" for i in range(1, 6)
        )
        assert refusal(f"SELECT p.name FROM projects p {joins}") == (
            QueryMessages.TOO_MANY_RELATIONS
        )


class TestNothingOfTheOriginalTravels:
    def test_the_statement_is_generated_not_forwarded(self):
        """Physical names, and only names the registry produced."""
        resolved = resolve("SELECT title FROM tasks WHERE priority = 'urgent'")
        assert resolved.sql == "SELECT title FROM tasks WHERE priority = $1"
        assert resolved.parameters == ("urgent",)

    def test_comments_do_not_survive(self):
        """Comments are dropped when the statement is generated."""
        resolved = resolve("SELECT title /* a note */ FROM tasks -- trailing\n")
        assert "note" not in resolved.sql
        assert "trailing" not in resolved.sql

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT title /* /* x */ */ FROM tasks",
            "SELECT title /* /* */ , evil */ FROM tasks",
        ],
    )
    def test_a_nested_comment_is_read_the_way_the_server_reads_it(self, sql):
        """Postgres nests block comments, so all of that is one comment and
        ``evil`` is inside it. A parser that did not nest them would end the
        comment at the first ``*/`` and read the rest as part of the
        statement; this is the case the server's own grammar settles."""
        assert resolve(sql).sql == "SELECT title FROM tasks"

    def test_literals_leave_as_parameters(self):
        resolved = resolve("SELECT title FROM tasks WHERE title = 'x' AND id > 3")
        assert resolved.parameters == ("x", 3)
        assert "'x'" not in resolved.sql

    def test_a_quote_in_a_literal_is_a_value_not_syntax(self):
        resolved = resolve("SELECT title FROM tasks WHERE title = 'it''s; DROP--'")
        assert "DROP" not in resolved.sql
        assert resolved.parameters == ("it's; DROP--",)

    def test_an_ordinal_stays_an_ordinal(self):
        """``GROUP BY 1`` selects the first output column; a parameter there
        would be the number one."""
        resolved = resolve("SELECT title, count(*) AS n FROM tasks GROUP BY 1")
        assert "GROUP BY 1" in resolved.sql
        assert not resolved.parameters


class TestTheFunctionSurface:
    @pytest.mark.parametrize(
        "call",
        [
            "pg_read_file('/etc/passwd')",
            "pg_sleep(10)",
            "current_setting('app.current_user_id')",
            "pg_ls_dir('.')",
            "dblink('', '')",
            "query_to_xml('SELECT 1', true, true, '')",
            "lo_import('/etc/passwd')",
        ],
    )
    def test_a_function_nobody_listed_is_refused(self, call):
        assert refusal(f"SELECT {call} FROM tasks") == (
            QueryMessages.UNSUPPORTED_FUNCTION
        )

    @pytest.mark.parametrize("call", SUPPORTED_CALLS)
    def test_every_supported_call_is_accepted(self, call):
        """The declared spellings and the accepted node types are the same
        set, which is the point of deriving one from the other."""
        assert resolve(f"SELECT {call} AS v FROM tasks").sql

    def test_structure_that_the_parser_calls_a_function_still_works(self):
        """``AND`` and ``CASE`` are a kind of function to this parser, and
        they are plainly structure."""
        sql = (
            "SELECT CASE WHEN is_archived THEN 'old' ELSE 'live' END AS bucket "
            "FROM projects WHERE is_archived = false AND is_template = false"
        )
        assert resolve(sql).sql


class TestShapesATileAsks:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT count(*) AS n FROM tasks",
            "SELECT title, due_date FROM tasks WHERE due_date < now() ORDER BY due_date",
            "SELECT date_trunc('month', created_at) AS m, count(*) AS n "
            "FROM tasks GROUP BY m ORDER BY m",
            "SELECT p.name, count(*) AS n FROM projects p "
            "JOIN tasks k ON k.project_id = p.id "
            "WHERE p.is_archived = false GROUP BY p.name ORDER BY n DESC LIMIT 10",
            "SELECT title FROM tasks WHERE title ILIKE '%bug%' LIMIT 50",
            "SELECT count(*) AS n FROM tasks "
            "WHERE due_date BETWEEN '2026-01-01' AND '2026-12-31'",
        ],
    )
    def test_it_resolves(self, sql):
        assert resolve(sql).sql


class TestSubqueriesAreNotAcceptedYet:
    """Deny-by-default means these are refused rather than half-supported;
    admitting them is adding a scope to resolve against, not removing a check."""

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT title FROM tasks WHERE id IN (SELECT id FROM projects)",
            "WITH t AS (SELECT id FROM tasks) SELECT id FROM t",
            "SELECT (SELECT count(*) FROM tasks) AS n FROM projects",
        ],
    )
    def test_refused(self, sql):
        assert refusal(sql) in {
            QueryMessages.UNSUPPORTED_SYNTAX,
            QueryMessages.UNKNOWN_RELATION,
        }

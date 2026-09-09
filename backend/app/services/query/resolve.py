"""Parse a reader's SQL, admit only a read of declared names, and rewrite it.

Three things happen here, over the parsed statement:

**Admit only a read.** The statement must be a single ``SELECT``. Every node in
it must be one this surface accepts, and every function must be one it names —
both allow-lists, so a construct nobody considered is refused rather than
carried through.

**Resolve every name.** Relations resolve through the field registry to the
model behind them; columns resolve to the field's own column. The statement
handed back is written out from the parsed tree rather than forwarded, so it
carries only names the registry produced.

**Refuse what is structurally expensive.** A join whose condition pairs nothing
pairs every row with every row; a statement may name only so many relations.
Both are answered from the parsed statement, before anything is planned.

This layer is where a refusal gets a *reason*: a machine code and the word that
has to change. Execution settles the rest — the transaction, the role and the
cost ceiling are the executor's, and are described there.

The parser is PostgreSQL's own, through ``pglast``. That matters most where a
grammar is surprising: ``/* /* x */ */`` is one comment to Postgres and to this,
``EXTRACT`` arrives already rewritten to ``pg_catalog.extract``, and ``coalesce``
is not a function call but a node of its own. Reading a statement the way the
server reads it is what lets the rules below be written against what will run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pglast import ast, parse_sql
from pglast.enums import SetOperation
from pglast.parser import ParseError
from pglast.stream import RawStream
from pglast.visitors import Visitor

from app.core.messages import QueryMessages
from app.services.fields import dataset
from app.services.fields.registry import dataset_names

#: How many relations one statement may name. A dashboard tile asks about one
#: thing, sometimes joined to a second; the ceiling is what keeps a statement's
#: cost proportional to a guild's data rather than a power of it.
MAX_RELATIONS = 4


class QueryError(Exception):
    """A query this surface will not run, and the word that has to change."""

    def __init__(self, code: str, subject: str = "") -> None:
        super().__init__(f"{code}: {subject}" if subject else code)
        self.code = code
        self.subject = subject


@dataclass(frozen=True)
class ResolvedQuery:
    """A statement built from declared names, ready to be planned."""

    #: The statement, written out from the tree. Physical names, ``$1``-style
    #: parameters, and nothing of the reader's own text.
    sql: str
    #: The literal values, in the order the parameters number them.
    parameters: tuple[Any, ...] = ()
    #: The datasets this statement reads, for the caller that decides whether
    #: the reader may read them.
    relations: tuple[str, ...] = ()


# --- what the surface accepts ------------------------------------------------

#: Node types a statement may contain. An allow-list: a construct absent here
#: is refused by name, which is what keeps "we did not think about it" from
#: meaning "it runs". Subqueries and CTEs are absent deliberately — admitting
#: them is adding a scope to resolve names against.
_ALLOWED_NODES: frozenset[type] = frozenset(
    {
        # shape
        ast.SelectStmt,
        ast.ResTarget,
        ast.RangeVar,
        ast.Alias,
        ast.JoinExpr,
        ast.SortBy,
        # names and values
        ast.ColumnRef,
        ast.A_Const,
        ast.ParamRef,
        ast.String,
        ast.Integer,
        ast.Float,
        ast.Boolean,
        # predicates and arithmetic
        ast.A_Expr,
        ast.BoolExpr,
        ast.NullTest,
        ast.BooleanTest,
        # things Postgres parses as their own node rather than a call
        ast.CaseExpr,
        ast.CaseWhen,
        ast.CoalesceExpr,
        ast.MinMaxExpr,
        ast.TypeCast,
        ast.TypeName,
        # calls, checked by name below
        ast.FuncCall,
    }
)

#: Functions a query may call. Postgres reports the name it resolved, so these
#: are the names as the server sees them — ``extract`` arrives qualified with
#: ``pg_catalog`` because the grammar rewrites it, and ``coalesce`` never
#: arrives at all because it is a node rather than a call.
_ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {
        "count",
        "sum",
        "avg",
        "min",
        "max",
        "abs",
        "round",
        "length",
        "lower",
        "upper",
        "concat",
        "date_trunc",
        "extract",
        "now",
    }
)

#: The only schema a function name may carry. It is the one Postgres itself
#: puts there when it rewrites a spelling into a call.
_FUNCTION_SCHEMA = "pg_catalog"


def _name_parts(parts: Any) -> list[str]:
    """The words of a dotted name, as the parser reports them.

    A node's name list is optional in the grammar's own types, so a name that
    is not there reads as no words and is refused by the caller rather than
    assumed to be well formed.
    """
    return [part.sval for part in (parts or ()) if isinstance(part, ast.String)]


def _physical_table(dataset_name: str) -> str:
    return dataset(dataset_name).model.__table__.name


def _physical_column(dataset_name: str, field_name: str) -> str:
    spec = dataset(dataset_name).by_name.get(field_name)
    if spec is None:
        raise QueryError(QueryMessages.UNKNOWN_FIELD, f"{dataset_name}.{field_name}")
    if spec.column is None:
        raise QueryError(
            QueryMessages.FIELD_NOT_SELECTABLE, f"{dataset_name}.{field_name}"
        )
    return spec.column.property.columns[0].name


def _parse(sql: str) -> ast.SelectStmt:
    try:
        statements = parse_sql(sql)
    except ParseError as err:
        raise QueryError(QueryMessages.UNPARSEABLE, str(err).splitlines()[0]) from err
    if not statements:
        raise QueryError(QueryMessages.UNPARSEABLE)
    if len(statements) > 1:
        raise QueryError(QueryMessages.ONE_STATEMENT_ONLY)
    root = statements[0].stmt
    if not isinstance(root, ast.SelectStmt):
        raise QueryError(QueryMessages.READ_ONLY, type(root).__name__)
    _check_select_shape(root)
    return root


def _check_select_shape(select: ast.SelectStmt) -> None:
    """The parts of a SELECT this surface does not take."""
    if select.op != SetOperation.SETOP_NONE:
        raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "SET_OPERATION")
    for attribute, name in (
        ("withClause", "WITH"),
        ("lockingClause", "LOCKING"),
        ("intoClause", "INTO"),
        ("valuesLists", "VALUES"),
    ):
        if getattr(select, attribute, None):
            raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, name)


def _relations(select: ast.SelectStmt) -> dict[str, str]:
    """The relations in scope, by the name a column may qualify with.

    Rewrites each to the table behind it as it goes, so the tree carries
    physical names by the time it is written out.
    """
    if not select.fromClause:
        raise QueryError(QueryMessages.MISSING_RELATION)
    if len(select.fromClause) > 1:
        # Relations listed side by side, which pairs every row with every row.
        raise QueryError(QueryMessages.JOIN_WITHOUT_CONDITION, "FROM")

    known = set(dataset_names())
    scope: dict[str, str] = {}

    joins: list[ast.JoinExpr] = []

    def visit(node: Any) -> None:
        if isinstance(node, ast.JoinExpr):
            if node.usingClause:
                # ``USING`` names columns positionally rather than as column
                # references, so the resolving pass below never sees them.
                # ``ON`` says the same thing in a form that resolves.
                raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "USING")
            joins.append(node)
            visit(node.larg)
            visit(node.rarg)
            return
        if not isinstance(node, ast.RangeVar):
            raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, type(node).__name__)
        if node.schemaname or node.catalogname:
            raise QueryError(QueryMessages.QUALIFIED_RELATION, node.relname)
        if node.relname not in known:
            raise QueryError(QueryMessages.UNKNOWN_RELATION, node.relname)
        handle = node.alias.aliasname if node.alias else node.relname
        if handle in scope:
            raise QueryError(QueryMessages.DUPLICATE_ALIAS, handle)
        scope[handle] = node.relname
        node.relname = _physical_table(node.relname)

    visit(select.fromClause[0])

    # After the relations, so a statement gets the more specific answer: an
    # alias used twice is named as that, not as the join it sits in.
    for join in joins:
        if not _join_is_bound(join):
            raise QueryError(QueryMessages.JOIN_WITHOUT_CONDITION, "JOIN")

    if len(scope) > MAX_RELATIONS:
        raise QueryError(QueryMessages.TOO_MANY_RELATIONS, str(len(scope)))
    return scope


def _relations_named(node: Any) -> set[str]:
    """The relations one side of a comparison reads from."""
    named: set[str] = set()

    class Qualifiers(Visitor):
        def visit_ColumnRef(self, ancestors: Any, inner: ast.ColumnRef) -> None:
            parts = _name_parts(inner.fields)
            if len(parts) > 1:
                named.add(parts[0])

    if node is not None:
        Qualifiers()(node)
    return named


def _join_is_bound(join: ast.JoinExpr) -> bool:
    """Whether a join's condition actually pairs its rows with something.

    The test is one comparison whose two sides read from *different*
    relations — which is what relates a row to a row. Mentioning two relations
    somewhere in the condition is not enough: ``ON tasks.id > 0 AND
    projects.id > 0`` names both and still pairs every row with every row, and
    so do ``ON true`` and ``ON tasks.id > 0``.
    """
    if join.quals is None:
        return False
    relating = False

    class Relating(Visitor):
        def visit_A_Expr(self, ancestors: Any, node: ast.A_Expr) -> None:
            nonlocal relating
            left = _relations_named(node.lexpr)
            right = _relations_named(node.rexpr)
            if left and right and left.isdisjoint(right):
                relating = True

    Relating()(join.quals)
    return relating


def _check_nodes(select: ast.SelectStmt) -> None:
    class Check(Visitor):
        def visit(self, ancestors: Any, node: Any) -> None:
            if type(node) not in _ALLOWED_NODES:
                raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, type(node).__name__)

        def visit_FuncCall(self, ancestors: Any, node: ast.FuncCall) -> None:
            names = _name_parts(node.funcname)
            if not names:
                raise QueryError(QueryMessages.UNSUPPORTED_FUNCTION)
            if len(names) > 2 or (len(names) == 2 and names[0] != _FUNCTION_SCHEMA):
                raise QueryError(QueryMessages.UNSUPPORTED_FUNCTION, ".".join(names))
            if names[-1] not in _ALLOWED_FUNCTIONS:
                raise QueryError(QueryMessages.UNSUPPORTED_FUNCTION, names[-1])

        def visit_A_Star(self, ancestors: Any, node: ast.A_Star) -> None:
            # A query names the columns it wants; ``*`` would mean whatever the
            # table happens to hold, which is not something a saved tile can
            # rely on. ``count(*)`` carries a flag rather than a column, so it
            # never reaches here.
            raise QueryError(QueryMessages.STAR_NOT_ALLOWED)

    Check()(select)


def _output_aliases(select: ast.SelectStmt) -> frozenset[str]:
    return frozenset(
        target.name
        for target in (select.targetList or ())
        if isinstance(target, ast.ResTarget) and target.name
    )


def _alias_positions(select: ast.SelectStmt) -> set[int]:
    """Where an output alias is a name a column reference may use.

    Postgres resolves ``ORDER BY n`` and ``GROUP BY n`` against the select
    list. ``WHERE`` and ``HAVING`` are evaluated before the output exists, so a
    name there is a column and has to resolve as one.
    """
    marked: set[int] = set()

    class Mark(Visitor):
        def visit_ColumnRef(self, ancestors: Any, node: ast.ColumnRef) -> None:
            marked.add(id(node))

    for clause in (select.sortClause or (), select.groupClause or ()):
        for entry in clause:
            Mark()(entry)
    return marked


def _resolve_columns(select: ast.SelectStmt, scope: dict[str, str]) -> None:
    aliases = _output_aliases(select)
    alias_positions = _alias_positions(select)
    only = next(iter(scope.values())) if len(scope) == 1 else None

    class Resolve(Visitor):
        def visit_ColumnRef(self, ancestors: Any, node: ast.ColumnRef) -> None:
            names = _name_parts(node.fields)
            if not names:
                raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "ColumnRef")
            if len(names) > 2:
                raise QueryError(QueryMessages.QUALIFIED_RELATION, ".".join(names))
            if len(names) == 2:
                dataset_name = scope.get(names[0])
                if dataset_name is None:
                    raise QueryError(QueryMessages.UNKNOWN_RELATION, names[0])
                column = _physical_column(dataset_name, names[1])
                node.fields = (ast.String(sval=names[0]), ast.String(sval=column))
                return
            if names[0] in aliases and id(node) in alias_positions:
                # An output alias: ``ORDER BY n`` names the count, and no table
                # has a column for it.
                return
            if only is None:
                raise QueryError(QueryMessages.AMBIGUOUS_FIELD, names[0])
            node.fields = (ast.String(sval=_physical_column(only, names[0])),)

    Resolve()(select)


def _ordinals(select: ast.SelectStmt) -> set[int]:
    """Numbers that are part of the grammar rather than values.

    ``GROUP BY 1`` and ``ORDER BY 1`` select an output column; a parameter
    there would be the number one.
    """
    marked: set[int] = set()
    for entry in select.groupClause or ():
        if isinstance(entry, ast.A_Const):
            marked.add(id(entry))
    for entry in select.sortClause or ():
        if isinstance(entry, ast.SortBy) and isinstance(entry.node, ast.A_Const):
            marked.add(id(entry.node))
    return marked


def _bind_literals(select: ast.SelectStmt) -> tuple[Any, ...]:
    ordinals = _ordinals(select)
    values: list[Any] = []

    class Bind(Visitor):
        def visit_A_Const(self, ancestors: Any, node: ast.A_Const) -> Any:
            if id(node) in ordinals or node.isnull:
                return None
            values.append(_value(node))
            return ast.ParamRef(number=len(values))

    Bind()(select)
    return tuple(values)


def _value(node: ast.A_Const) -> Any:
    held = node.val
    if isinstance(held, ast.Integer):
        return held.ival
    if isinstance(held, ast.Float):
        return float(held.fval)
    if isinstance(held, ast.Boolean):
        return held.boolval
    if isinstance(held, ast.String):
        return held.sval
    raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, type(held).__name__)


def resolve(sql: str) -> ResolvedQuery:
    """Read *sql*, and return the statement this surface will run instead.

    Raises :class:`QueryError` naming what has to change.
    """
    select = _parse(sql)
    _check_nodes(select)
    scope = _relations(select)
    _resolve_columns(select, scope)
    parameters = _bind_literals(select)
    return ResolvedQuery(
        sql=RawStream()(select),
        parameters=parameters,
        relations=tuple(sorted(set(scope.values()))),
    )

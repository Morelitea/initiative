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
from app.services.fields.spec import FieldType

#: ``EXPLAIN``'s options, as the grammar spells them.
_EXPLAIN_JSON = (ast.DefElem(defname="format", arg=ast.String(sval="json")),)

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
    #: What the registry calls each output column, by position, where it can
    #: name one. ``None`` where the output is an expression rather than a
    #: field, and the database is the one to describe it.
    column_types: tuple[FieldType | None, ...] = ()

    def explain(self) -> str:
        """This statement, asking for its plan instead of its rows.

        ``EXPLAIN`` takes a statement where a value would go, so there is no
        parameter to bind it as. It is built in the tree and written out by the
        deparser that wrote the statement, rather than composed around the text
        of one — the same deparser, over one tree, saying both things.
        """
        root = ast.ExplainStmt(query=parse_sql(self.sql)[0].stmt, options=_EXPLAIN_JSON)
        return RawStream()(root)


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

    # Each join, with the relations on either side of it. A join is bound by a
    # condition relating what it *adds* to what was already there, so knowing
    # which relations those are is part of reading the tree.
    joins: list[tuple[ast.JoinExpr, set[str], set[str]]] = []

    def visit(node: Any) -> set[str]:
        if isinstance(node, ast.JoinExpr):
            if node.usingClause:
                # ``USING`` names columns positionally rather than as column
                # references, so the resolving pass below never sees them.
                # ``ON`` says the same thing in a form that resolves.
                raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "USING")
            left = visit(node.larg)
            right = visit(node.rarg)
            joins.append((node, left, right))
            return left | right
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
        return {handle}

    visit(select.fromClause[0])

    # After the relations, so a statement gets the more specific answer: an
    # alias used twice is named as that, not as the join it sits in.
    for join, left, right in joins:
        if not _join_is_bound(join, left, right):
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


def _join_is_bound(join: ast.JoinExpr, left: set[str], right: set[str]) -> bool:
    """Whether a join's condition ties what it adds to what was already there.

    The test is one comparison reading a relation from each side of *this*
    join. Weaker readings each let a cross product through:

    * "the condition is not empty" admits ``ON true``;
    * "it mentions two relations" admits ``ON tasks.id > 0 AND
      projects.id > 0``, which filters each relation and still pairs every
      surviving row with every other;
    * "it relates some two relations" admits a third join whose condition
      relates the first two, leaving the one being added unconstrained.
    """
    if join.quals is None:
        return False
    relating = False

    class Relating(Visitor):
        def visit_A_Expr(self, ancestors: Any, node: ast.A_Expr) -> None:
            nonlocal relating
            near = _relations_named(node.lexpr)
            far = _relations_named(node.rexpr)
            if (near & left and far & right) or (near & right and far & left):
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


def _output_types(
    select: ast.SelectStmt, scope: dict[str, str]
) -> tuple[FieldType | None, ...]:
    """What the registry calls each output column.

    A target that is a field and nothing else *is* that field, and carries the
    registry's answer about it — an id that names a person is a person on the
    way out as much as on the way in, where the type it is stored as says only
    that it is a whole number. Read before the names are rewritten, because the
    registry is asked by the name the reader wrote.

    Anything built from a field rather than being one has no field to ask, and
    is left ``None`` for the database to describe.
    """
    only = next(iter(scope.values())) if len(scope) == 1 else None
    return tuple(
        _target_type(target, scope, only) for target in select.targetList or ()
    )


def _target_type(
    target: ast.ResTarget, scope: dict[str, str], only: str | None
) -> FieldType | None:
    if not isinstance(target.val, ast.ColumnRef):
        return None
    names = _name_parts(target.val.fields)
    if len(names) == 2:
        dataset_name, field_name = scope.get(names[0]), names[1]
    elif len(names) == 1:
        dataset_name, field_name = only, names[0]
    else:
        return None
    if dataset_name is None:
        return None
    spec = dataset(dataset_name).by_name.get(field_name)
    return spec.type if spec is not None else None


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


def _literal_positions(select: ast.SelectStmt) -> set[int]:
    """Constants that stay constants.

    Two kinds. ``GROUP BY 1`` and ``ORDER BY 1`` select an output column, and a
    parameter there would be the number one. And a constant standing alone in
    the select list has nothing to take a type from — Postgres reads an
    unadorned parameter there as text — where the same constant compared
    against a column takes that column's type, which is what makes
    ``priority = $1`` work against an enum.
    """
    marked: set[int] = set()
    for entry in select.groupClause or ():
        if isinstance(entry, ast.A_Const):
            marked.add(id(entry))
    for entry in select.sortClause or ():
        if isinstance(entry, ast.SortBy) and isinstance(entry.node, ast.A_Const):
            marked.add(id(entry.node))
    for target in select.targetList or ():
        if isinstance(target, ast.ResTarget) and isinstance(target.val, ast.A_Const):
            marked.add(id(target.val))
    return marked


def _bind_literals(select: ast.SelectStmt) -> tuple[Any, ...]:
    ordinals = _literal_positions(select)
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
    column_types = _output_types(select, scope)
    _resolve_columns(select, scope)
    parameters = _bind_literals(select)
    return ResolvedQuery(
        sql=RawStream()(select),
        parameters=parameters,
        relations=tuple(sorted(set(scope.values()))),
        column_types=column_types,
    )

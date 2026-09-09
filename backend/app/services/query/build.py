"""Turn a structured description of a query into SQL.

The builder in the browser does not write SQL. It describes what somebody
clicked — a dataset, some columns, a filter, a grouping — and this writes the
statement, by building the parse tree and handing it to the same deparser that
writes every other statement this surface produces.

That is the whole reason it lives here rather than in the client. A statement a
person built by clicking must be one the validator accepts, and the two ways to
get that wrong are quoting and spelling: a name or a literal written into SQL by
hand has to be escaped exactly the way Postgres reads it, and a clause has to be
spelled the way the grammar expects. Building the tree settles both — there is
no string to escape, and a node that would not parse cannot be constructed.

The cutover migration writes its statements through the same functions, so the
SQL a stored definition was rewritten to and the SQL the builder produces are
the same SQL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from pglast import ast
from pglast.enums import A_Expr_Kind, BoolExprType, LimitOption, SortByDir
from pglast.stream import RawStream

from app.core.messages import QueryMessages
from app.schemas.query import FilterOp
from app.services.fields import dataset
from app.services.fields.registry import dataset_names
from app.services.query.resolve import QueryError, ResolvedQuery, resolve

#: What a column may be reduced to. Aggregates only — a window function is a
#: different question and the validator does not admit one.
AGGREGATES = frozenset({"count", "sum", "avg", "min", "max"})

#: What a date column may be rounded to. The vocabulary ``date_trunc`` takes,
#: narrowed to the buckets a tile is drawn at.
BUCKETS = frozenset({"day", "week", "month", "quarter", "year"})

#: How each operator is spelled in the tree.
_OPERATORS = {
    FilterOp.eq: "=",
    FilterOp.lt: "<",
    FilterOp.lte: "<=",
    FilterOp.gt: ">",
    FilterOp.gte: ">=",
    FilterOp.ilike: "~~*",
}


@dataclass(frozen=True)
class Column:
    """One thing the query returns."""

    field: str
    #: Reduce the column across the group, rather than returning it as it is.
    aggregate: Optional[str] = None
    #: Round a date down before grouping by it.
    bucket: Optional[str] = None
    #: What the output column is called. Defaults to the field's own name, or
    #: the aggregate's, so a chart's legend reads as something.
    alias: Optional[str] = None


@dataclass(frozen=True)
class Condition:
    """One comparison, in the same vocabulary the filter DSL uses."""

    field: str
    op: FilterOp = FilterOp.eq
    value: Any = None


@dataclass(frozen=True)
class Sort:
    field: str
    descending: bool = False


@dataclass(frozen=True)
class QuerySpec:
    """What somebody clicked, before it is a statement."""

    dataset: str
    columns: Sequence[Column] = field(default_factory=tuple)
    where: Sequence[Condition] = field(default_factory=tuple)
    #: Columns to group by, named the way the select list names them.
    group_by: Sequence[str] = field(default_factory=tuple)
    order_by: Optional[Sort] = None
    limit: Optional[int] = None


def _column_ref(name: str) -> ast.ColumnRef:
    return ast.ColumnRef(fields=(ast.String(sval=name),))


def _literal(value: Any) -> ast.Node:
    """A value as a constant. Written into the tree rather than the text, so
    what it contains is the deparser's problem and not a quoting rule of ours."""
    if value is None:
        return ast.A_Const(isnull=True)
    if isinstance(value, bool):
        return ast.A_Const(val=ast.Boolean(boolval=value))
    if isinstance(value, int):
        return ast.A_Const(val=ast.Integer(ival=value))
    if isinstance(value, float):
        return ast.A_Const(val=ast.Float(fval=repr(value)))
    return ast.A_Const(val=ast.String(sval=str(value)))


def _expression(column: Column) -> ast.Node:
    """The select-list expression for one column, innermost first: the field,
    rounded if it is bucketed, reduced if it is aggregated."""
    inner: ast.Node = _column_ref(column.field)
    if column.bucket:
        if column.bucket not in BUCKETS:
            raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, column.bucket)
        inner = ast.FuncCall(
            funcname=(ast.String(sval="date_trunc"),),
            args=(ast.A_Const(val=ast.String(sval=column.bucket)), inner),
        )
    if column.aggregate:
        if column.aggregate not in AGGREGATES:
            raise QueryError(QueryMessages.UNSUPPORTED_FUNCTION, column.aggregate)
        # count with nothing to count is count(*), which is the one aggregate
        # that takes no argument.
        if column.aggregate == "count" and column.field == "*":
            return ast.FuncCall(funcname=(ast.String(sval="count"),), agg_star=True)
        inner = ast.FuncCall(
            funcname=(ast.String(sval=column.aggregate),), args=(inner,)
        )
    return inner


def _alias(column: Column) -> str:
    if column.alias:
        return column.alias
    if column.aggregate and column.field == "*":
        return column.aggregate
    if column.aggregate:
        return f"{column.field}_{column.aggregate}"
    return column.field


def _predicate(condition: Condition) -> ast.Node:
    left = _column_ref(condition.field)
    if condition.op is FilterOp.is_null:
        # The DSL's is_null carries whether it means null or not-null.
        return ast.NullTest(arg=left, nulltesttype=0 if condition.value else 1)
    if condition.op is FilterOp.in_:
        values = (
            condition.value
            if isinstance(condition.value, (list, tuple))
            else [condition.value]
        )
        return ast.A_Expr(
            kind=A_Expr_Kind.AEXPR_IN,
            name=(ast.String(sval="="),),
            lexpr=left,
            rexpr=tuple(_literal(value) for value in values),
        )
    operator = _OPERATORS.get(condition.op)
    if operator is None:
        raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, str(condition.op))
    return ast.A_Expr(
        kind=A_Expr_Kind.AEXPR_OP,
        name=(ast.String(sval=operator),),
        lexpr=left,
        rexpr=_literal(condition.value),
    )


def _where(conditions: Sequence[Condition]) -> Optional[ast.Node]:
    """Every condition, AND-ed. A flat list, because that is what a builder
    produces and a nested one would spend a level nobody asked for."""
    if not conditions:
        return None
    predicates = tuple(_predicate(condition) for condition in conditions)
    if len(predicates) == 1:
        return predicates[0]
    return ast.BoolExpr(boolop=BoolExprType.AND_EXPR, args=predicates)


def build(spec: QuerySpec) -> str:
    """The statement *spec* describes.

    Written in the registry's own vocabulary — the dataset and field names a
    reader sees — so what is stored is what they built, and resolution to
    physical names happens when it runs, like any other statement.
    """
    if spec.dataset not in dataset_names():
        raise QueryError(QueryMessages.UNKNOWN_RELATION, spec.dataset)
    if not spec.columns:
        raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "no columns")
    known = dataset(spec.dataset).by_name
    for column in spec.columns:
        if column.field != "*" and column.field not in known:
            raise QueryError(
                QueryMessages.UNKNOWN_FIELD, f"{spec.dataset}.{column.field}"
            )

    # A bare column is already named after itself, so an alias there would read
    # as "priority AS priority". Anything computed needs one, because Postgres
    # would otherwise name it after the function that made it.
    targets = tuple(
        ast.ResTarget(
            name=None
            if column.alias is None and not column.aggregate and not column.bucket
            else _alias(column),
            val=_expression(column),
        )
        for column in spec.columns
    )
    aliases = [
        target.name or column.field for target, column in zip(targets, spec.columns)
    ]

    select = ast.SelectStmt(
        targetList=targets,
        fromClause=(ast.RangeVar(relname=spec.dataset, inh=True),),
        whereClause=_where(spec.where),
        op=0,
    )

    if spec.group_by:
        # By output position, because a grouped expression and its select-list
        # twin have to be the same expression and an ordinal says so outright.
        positions = []
        for name in spec.group_by:
            if name not in aliases:
                raise QueryError(QueryMessages.UNKNOWN_FIELD, name)
            positions.append(ast.A_Const(val=ast.Integer(ival=aliases.index(name) + 1)))
        select.groupClause = tuple(positions)

    if spec.order_by is not None:
        if spec.order_by.field not in aliases:
            raise QueryError(QueryMessages.UNKNOWN_FIELD, spec.order_by.field)
        select.sortClause = (
            ast.SortBy(
                node=ast.A_Const(
                    val=ast.Integer(ival=aliases.index(spec.order_by.field) + 1)
                ),
                sortby_dir=SortByDir.SORTBY_DESC
                if spec.order_by.descending
                else SortByDir.SORTBY_ASC,
            ),
        )

    if spec.limit is not None:
        select.limitCount = ast.A_Const(val=ast.Integer(ival=int(spec.limit)))
        select.limitOption = LimitOption.LIMIT_OPTION_COUNT

    return RawStream()(select)


def build_and_resolve(spec: QuerySpec) -> tuple[str, ResolvedQuery]:
    """The statement, and proof that the surface will run it.

    Resolved here rather than left to the caller: a builder that can produce a
    statement the validator refuses is a builder somebody can get stuck in.
    """
    sql = build(spec)
    return sql, resolve(sql)

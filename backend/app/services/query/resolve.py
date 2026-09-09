"""Parse a reader's SQL, admit only a read of declared names, and rewrite it.

Three things happen here, in one pass over the parsed statement:

**Admit only a read.** The statement must be a single ``SELECT``. Every node in
it must be one this surface accepts, and every function must be one it names —
both allow-lists, so a construct nobody considered is refused rather than
carried through.

**Resolve every name.** Relations resolve through the field registry to the
model behind them; columns resolve to the field's own column. A name the
registry did not produce cannot reach the database, because the statement that
reaches it is generated from this tree rather than forwarded.

**Refuse what is structurally expensive.** A join with no condition pairs every
row with every row; a statement may name only so many relations. Both are
answered by looking at the parsed statement, before anything is planned.

This layer is where a refusal gets a *reason*: a machine code and the word that
has to change. Execution settles the rest — the transaction, the role and the
cost ceiling are the executor's, and are described there.

Generating the statement rather than forwarding the reader's text is what makes
that true. The text is read once, into a tree; everything after that is ours.
Comments are dropped in the same step, so no part of the original travels.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Optional

import sqlglot
from sqlglot import exp
from sqlglot.dialects.postgres import Postgres
from sqlglot.errors import ParseError, TokenError

from app.core.messages import QueryMessages
from app.services.fields import dataset
from app.services.fields.registry import dataset_names

#: How many relations one statement may name. A dashboard tile asks about one
#: thing, sometimes joined to a second; the ceiling is what stops a statement
#: whose cost is polynomial in a single guild's data.
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

    #: The generated SQL. Physical names, bound parameters, no comments.
    sql: str
    #: Literal values lifted out of the statement, by placeholder name.
    parameters: dict[str, Any] = dataclass_field(default_factory=dict)
    #: The datasets this statement reads, for the caller that decides whether
    #: the reader may read them.
    relations: tuple[str, ...] = ()


# --- what the surface accepts ------------------------------------------------

#: Node types a statement may contain. An allow-list: a construct absent here
#: is refused by name, which is what keeps "we did not think about it" from
#: meaning "it runs".
_ALLOWED_NODES: frozenset[type] = frozenset(
    {
        # shape
        exp.Select,
        exp.From,
        exp.Table,
        exp.TableAlias,
        exp.Identifier,
        exp.Column,
        exp.Alias,
        exp.Star,
        exp.Where,
        exp.Group,
        exp.Having,
        exp.Order,
        exp.Ordered,
        exp.Limit,
        exp.Offset,
        exp.Join,
        exp.Distinct,
        exp.Paren,
        exp.Tuple,
        #: The unit a truncation or extraction names, which is a bare word.
        exp.Var,
        # values
        exp.Literal,
        exp.Boolean,
        exp.Null,
        exp.Placeholder,
        exp.Interval,
        exp.Cast,
        exp.DataType,
        # predicates
        exp.And,
        exp.Or,
        exp.Not,
        exp.EQ,
        exp.NEQ,
        exp.GT,
        exp.GTE,
        exp.LT,
        exp.LTE,
        exp.Is,
        exp.In,
        exp.Like,
        exp.ILike,
        exp.Between,
        # arithmetic
        exp.Add,
        exp.Sub,
        exp.Mul,
        exp.Div,
        exp.Mod,
        exp.Neg,
        # conditionals, which are shape rather than function
        exp.Case,
        exp.If,
    }
)

#: The function calls this surface supports, written the way a reader writes
#: them. One declaration, because the node a spelling parses to is the parser's
#: business and not always the one its name suggests — ``date_trunc`` arrives as
#: a timestamp-truncation node, not a date one. Parsing each spelling once at
#: import is what keeps the accepted set and the intended set the same set.
SUPPORTED_CALLS: tuple[str, ...] = (
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


def _supported_functions() -> tuple[frozenset[type], frozenset[str]]:
    """Which function nodes, and which bare names, the calls above imply.

    A spelling the parser has a node for is admitted by that node's type. One
    it does not is admitted by name, and only by the exact name written above.
    """
    nodes: set[type] = set()
    names: set[str] = set()
    for call in SUPPORTED_CALLS:
        parsed = sqlglot.parse_one(f"SELECT {call}", dialect="postgres")
        for node in parsed.walk():
            if isinstance(node, exp.Anonymous):
                names.add((node.name or "").lower())
            elif isinstance(node, exp.Func):
                nodes.add(type(node))
    return frozenset(nodes), frozenset(names)


_FUNCTION_NODES, _FUNCTION_NAMES = _supported_functions()


#: Where a literal is part of the grammar rather than a value: an ordinal in
#: ``GROUP BY 1`` selects a column, and a bound parameter there would not.
_LITERAL_IS_SYNTAX: tuple[type, ...] = (
    exp.Limit,
    exp.Offset,
    exp.Ordered,
    exp.Group,
    exp.Interval,
    exp.DataType,
)


class _Bound(Postgres.Generator):
    """Postgres, with placeholders written the way SQLAlchemy binds them."""

    def placeholder_sql(self, expression: exp.Placeholder) -> str:
        return f":{expression.name}"


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


def _parse(sql: str) -> exp.Expression:
    try:
        statements = sqlglot.parse(sql, dialect="postgres")
    except (ParseError, TokenError) as err:
        raise QueryError(QueryMessages.UNPARSEABLE, str(err).splitlines()[0]) from err
    present = [statement for statement in statements if statement is not None]
    if not present:
        raise QueryError(QueryMessages.UNPARSEABLE)
    if len(present) > 1:
        raise QueryError(QueryMessages.ONE_STATEMENT_ONLY)
    root = present[0]
    if not isinstance(root, exp.Select):
        raise QueryError(QueryMessages.READ_ONLY, type(root).__name__.upper())
    return root


def _relations(root: exp.Select) -> dict[str, str]:
    """The relations in scope, by the name a column may qualify with.

    Rewrites each to the table behind it as it goes, so the tree carries
    physical names by the time anything is generated from it.
    """
    scope: dict[str, str] = {}
    known = set(dataset_names())

    # Found by type rather than by argument name: the parser's key for the
    # FROM clause is its own business and has been renamed between releases,
    # and a lookup that quietly returns nothing would leave this scope empty.
    source = next(
        (arg for arg in root.args.values() if isinstance(arg, exp.From)), None
    )
    if source is None:
        raise QueryError(QueryMessages.MISSING_RELATION)

    joins = root.args.get("joins") or []
    handles: list[str] = []
    for table in [source.this] + [join.this for join in joins]:
        if not isinstance(table, exp.Table):
            raise QueryError(
                QueryMessages.UNSUPPORTED_SYNTAX, type(table).__name__.upper()
            )
        if table.db or table.catalog:
            raise QueryError(QueryMessages.QUALIFIED_RELATION, table.sql())
        name = table.name
        if name not in known:
            raise QueryError(QueryMessages.UNKNOWN_RELATION, name)
        handle = table.alias or name
        if handle in scope:
            raise QueryError(QueryMessages.DUPLICATE_ALIAS, handle)
        scope[handle] = name
        handles.append(handle)
        table.set("this", exp.to_identifier(_physical_table(name)))

    # Checked once the handles are known, because "this join is bound" means
    # its condition names this relation *and* one already in scope.
    for join, handle in zip(joins, handles[1:]):
        if not _join_is_bound(join, handle):
            raise QueryError(QueryMessages.JOIN_WITHOUT_CONDITION, handle)

    if len(scope) > MAX_RELATIONS:
        raise QueryError(QueryMessages.TOO_MANY_RELATIONS, str(len(scope)))
    return scope


def _join_is_bound(join: exp.Join, handle: str) -> bool:
    """Whether a join's condition actually pairs its rows with something.

    ``USING`` names the columns outright. An ``ON`` has to mention the relation
    being joined and at least one other, which is what separates a join from a
    condition that happens to sit in a join's place — ``ON true`` reads as a
    join and pairs every row with every row.
    """
    if join.args.get("using"):
        return True
    on = join.args.get("on")
    if on is None:
        return False
    mentioned = {column.table for column in on.find_all(exp.Column) if column.table}
    return handle in mentioned and len(mentioned) >= 2


def _table_name(node: exp.Expression) -> str:
    return node.name if isinstance(node, exp.Table) else type(node).__name__.upper()


def _check_node(node: exp.Expression) -> None:
    """Admit one node, or say what about it is not accepted.

    Structure is settled before functions, because the parser makes several
    plainly structural things a kind of function — ``AND`` and ``CASE`` among
    them. A real function call belongs in the function list below rather than
    the structural one.
    """
    if isinstance(node, exp.Anonymous):
        name = (node.name or "").lower()
        if name not in _FUNCTION_NAMES:
            raise QueryError(QueryMessages.UNSUPPORTED_FUNCTION, name)
        return
    if type(node) in _ALLOWED_NODES:
        return
    if isinstance(node, exp.Func):
        if type(node) in _FUNCTION_NODES:
            return
        raise QueryError(
            QueryMessages.UNSUPPORTED_FUNCTION, type(node).__name__.upper()
        )
    raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, type(node).__name__.upper())
    if isinstance(node, exp.Star) and not isinstance(node.parent, exp.Count):
        # A query names the columns it wants; ``*`` would mean whatever the
        # table happens to hold, which is not something a saved tile can rely
        # on. ``count(*)`` names no column and is the useful exception.
        raise QueryError(QueryMessages.STAR_NOT_ALLOWED)


#: Clauses that may name a column by the alias the select list gave it.
#: ``ORDER BY n`` means the output column ``n``, which no table has.
_ALIAS_VISIBLE: tuple[type, ...] = (exp.Order, exp.Group, exp.Having)


def _output_aliases(root: exp.Select) -> frozenset[str]:
    return frozenset(
        projection.alias
        for projection in root.expressions
        if isinstance(projection, exp.Alias) and projection.alias
    )


def _names_an_output(node: exp.Column, aliases: frozenset[str]) -> bool:
    if node.table or node.name not in aliases:
        return False
    parent: Optional[exp.Expression] = node.parent
    while parent is not None:
        if isinstance(parent, _ALIAS_VISIBLE):
            return True
        parent = parent.parent
    return False


def _resolve_column(
    node: exp.Column, scope: dict[str, str], aliases: frozenset[str]
) -> None:
    if _names_an_output(node, aliases):
        return
    qualifier = node.table
    if qualifier:
        dataset_name = scope.get(qualifier)
        if dataset_name is None:
            raise QueryError(QueryMessages.UNKNOWN_RELATION, qualifier)
    elif len(scope) == 1:
        dataset_name = next(iter(scope.values()))
    else:
        raise QueryError(QueryMessages.AMBIGUOUS_FIELD, node.name)
    node.set("this", exp.to_identifier(_physical_column(dataset_name, node.name)))


def _bind_literals(root: exp.Select) -> dict[str, Any]:
    parameters: dict[str, Any] = {}
    for literal in list(root.find_all(exp.Literal)):
        if _within_syntax(literal):
            continue
        name = f"p{len(parameters)}"
        parameters[name] = literal.this if literal.is_string else _number(literal.this)
        literal.replace(exp.Placeholder(this=name))
    return parameters


def _within_syntax(node: exp.Expression) -> bool:
    parent: Optional[exp.Expression] = node.parent
    while parent is not None:
        if isinstance(parent, _LITERAL_IS_SYNTAX):
            return True
        parent = parent.parent
    return False


def _number(raw: str) -> Any:
    try:
        return int(raw)
    except ValueError:
        return float(raw)


def resolve(sql: str) -> ResolvedQuery:
    """Read *sql*, and return the statement this surface will run instead.

    Raises :class:`QueryError` naming what has to change.
    """
    root = _parse(sql)
    for node in root.walk():
        _check_node(node)

    scope = _relations(root)
    aliases = _output_aliases(root)
    for node in root.find_all(exp.Column):
        _resolve_column(node, scope, aliases)

    parameters = _bind_literals(root)
    return ResolvedQuery(
        sql=_Bound(comments=False).generate(root.copy()),
        parameters=parameters,
        relations=tuple(sorted(set(scope.values()))),
    )

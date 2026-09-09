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
from pglast.enums import A_Expr_Kind, SetOperation
from pglast.parser import ParseError
from pglast.stream import RawStream
from pglast.visitors import Visitor

from app.core.messages import QueryMessages
from app.services.fields import dataset
from app.services.fields.registry import dataset_names
from app.services.fields.spec import ControlKind, FieldType

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
    #: Whether the statement asked about whoever is reading it. A caller that
    #: needs one answer for everybody has to know, because this is the one
    #: thing in the language that makes a statement answer differently per
    #: person.
    names_the_reader: bool = False

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
#:
#: Public, because a client helping somebody write a statement has to offer the
#: same set this refuses everything outside of.
ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
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

#: The one name a statement may use that is not a column: the reader.
#:
#: A saved statement holds no reader in it, so ``where created_by = me`` is one
#: widget answering differently for each person who opens the dashboard —
#: which is the only way a dashboard can be about you. The filter path has
#: taken the same word for as long as it has had an assignee filter; this is
#: that idea in the language rather than in one field's handler.
#:
#: It is a value and nothing more: the reader's own id, on the right of a
#: comparison. Which rows a statement reads is settled elsewhere — the guild by
#: the routing, the initiative by the dashboard the tile sits on — and naming
#: the reader narrows within that, one comparison like any other. It is not the
#: ``/me/`` routes' cross-guild sense of the word.
#:
#: Public, because a client offering what a statement may contain has to offer
#: this beside the datasets and the functions.
VIEWER = "me"

#: What ``me`` is written as, once. The request already says who is asking, so
#: this reads it there rather than being handed it — which keeps resolution
#: pure, keeps the reader's id out of anything stored, and leaves the answer to
#: the moment the statement runs rather than the moment it was written.
#:
#: Unset it reads as null, and a comparison against null selects nothing.
_VIEWER_EXPRESSION = "NULLIF(current_setting('app.current_user_id', true), '')::int"


def _viewer_node() -> ast.Node:
    """``me`` as a tree, parsed rather than assembled.

    Built fresh per use: each occurrence is its own node, and a tree is not
    something to share between two places in another tree.
    """
    target = parse_sql(f"SELECT {_VIEWER_EXPRESSION}")[0].stmt.targetList[0]
    return target.val


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
    for target in select.targetList or ():
        if isinstance(target, ast.ResTarget) and target.name == VIEWER:
            # An output column called ``me`` would make ``order by me`` mean
            # two things, and the word already means one.
            raise QueryError(QueryMessages.RESERVED_NAME, VIEWER)


def _column_refs(node: Any) -> list[ast.ColumnRef]:
    """Every column reference under *node*, in the order they are met."""
    found: list[ast.ColumnRef] = []

    class Collect(Visitor):
        def visit_ColumnRef(self, ancestors: Any, inner: ast.ColumnRef) -> None:
            found.append(inner)

    if node is not None:
        Collect()(node)
    return found


def joined(base: str, relation: Any, node: ast.Node, handle: str) -> ast.Node:
    """*node*, joined to everything *relation* passes through.

    Each hop is an ordinary inner join whose condition relates the two sides,
    which is what a join is asked to be here — so a statement that reaches
    through a relation is checked exactly like one that spelled the join out.
    The last hop is aliased to the relation's own name, so the columns read
    ``assignee.display_name``.

    Shared with the builder, which writes the same joins from the same
    declarations: one way of getting there, whether somebody clicked it or
    typed it.
    """
    left = base
    for index, hop in enumerate(relation.hops):
        last = index == len(relation.hops) - 1
        alias = handle if last else f"{handle}__{hop.dataset}"
        node = ast.JoinExpr(
            jointype=0,
            larg=node,
            rarg=ast.RangeVar(
                relname=hop.dataset, inh=True, alias=ast.Alias(aliasname=alias)
            ),
            quals=ast.A_Expr(
                kind=A_Expr_Kind.AEXPR_OP,
                name=(ast.String(sval="="),),
                lexpr=ast.ColumnRef(
                    fields=(ast.String(sval=left), ast.String(sval=hop.left))
                ),
                rexpr=ast.ColumnRef(
                    fields=(ast.String(sval=alias), ast.String(sval=hop.right))
                ),
            ),
        )
        left = alias
    return node


def _declared_handles(node: Any, found: dict[str, str]) -> None:
    """The relations a ``FROM`` names, by the handle a column would use, read
    before anything is rewritten."""
    if isinstance(node, ast.JoinExpr):
        _declared_handles(node.larg, found)
        _declared_handles(node.rarg, found)
        return
    if isinstance(node, ast.RangeVar):
        found[node.alias.aliasname if node.alias else node.relname] = node.relname


def _expand_relations(select: ast.SelectStmt) -> None:
    """Join in the datasets a statement reached through without saying so.

    A dataset declares what it can be read alongside, so ``assignee.display_name``
    over ``tasks`` is a person's name without anybody writing two joins to reach
    one. The expansion happens here, before names are resolved, so everything
    downstream sees a statement that spelled its joins out — including the
    checks on how many relations one statement may name and on each join being
    bound.
    """
    if not select.fromClause:
        return
    handles: dict[str, str] = {}
    _declared_handles(select.fromClause[0], handles)

    wanted: list[str] = []
    for node in _column_refs(select):
        parts = _name_parts(node.fields)
        if len(parts) == 2 and parts[0] not in handles and parts[0] not in wanted:
            wanted.append(parts[0])
    if not wanted:
        return

    node = select.fromClause[0]
    for name in wanted:
        sources = [
            (handle, dataset(known).by_relation[name])
            for handle, known in handles.items()
            if known in dataset_names() and name in dataset(known).by_relation
        ]
        if not sources:
            # Not a relation anybody declared. Left as it is, so the name is
            # refused where every other unknown relation is.
            continue
        if len(sources) > 1:
            raise QueryError(QueryMessages.AMBIGUOUS_FIELD, name)
        base, relation = sources[0]
        node = joined(base, relation, node, name)
    select.fromClause = (node,)


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
        if handle == VIEWER:
            raise QueryError(QueryMessages.RESERVED_NAME, VIEWER)
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
            if names[-1] not in ALLOWED_FUNCTIONS:
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


def _holder(scope: dict[str, str], field_name: str) -> str | None:
    """The dataset in scope that has this field, where exactly one does.

    An unqualified name is resolved the way the server resolves one: against
    whichever relation actually has it. ``None`` where none does or more than
    one does — the caller says which of those it is.

    Counted per relation in scope, not per dataset: the same table joined to
    itself is two relations, and a bare column of it names both.
    """
    holders = [name for name in scope.values() if field_name in dataset(name).by_name]
    return holders[0] if len(holders) == 1 else None


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
    return tuple(_target_type(target, scope) for target in select.targetList or ())


def _target_type(target: ast.ResTarget, scope: dict[str, str]) -> FieldType | None:
    if not isinstance(target.val, ast.ColumnRef):
        return None
    names = _name_parts(target.val.fields)
    if len(names) == 2:
        dataset_name, field_name = scope.get(names[0]), names[1]
    elif len(names) == 1:
        dataset_name, field_name = _holder(scope, names[0]), names[0]
    else:
        return None
    if dataset_name is None:
        return None
    spec = dataset(dataset_name).by_name.get(field_name)
    return spec.type if spec is not None else None


def _resolve_columns(select: ast.SelectStmt, scope: dict[str, str]) -> None:
    aliases = _output_aliases(select)
    alias_positions = _alias_positions(select)

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
            if names[0] == VIEWER:
                # Expanded once the literals are bound, so what it expands to
                # is not read as something the reader wrote.
                return
            if names[0] in aliases and id(node) in alias_positions:
                # An output alias: ``ORDER BY n`` names the count, and no table
                # has a column for it.
                return
            holder = _holder(scope, names[0])
            if holder is None:
                # Nothing in scope has it, or more than one does. Which of
                # those it is decides what the reader has to change.
                known = any(
                    names[0] in dataset(name).by_name for name in scope.values()
                )
                raise QueryError(
                    QueryMessages.AMBIGUOUS_FIELD
                    if known
                    else QueryMessages.UNKNOWN_FIELD,
                    names[0],
                )
            node.fields = (ast.String(sval=_physical_column(holder, names[0])),)

    Resolve()(select)


def _is_viewer(node: Any) -> bool:
    return isinstance(node, ast.ColumnRef) and _name_parts(node.fields) == [VIEWER]


def _holds_a_person(node: Any, scope: dict[str, str]) -> bool:
    """Whether *node* is a field that holds a person.

    Read by the name the reader wrote, so this is asked before the names are
    rewritten — the registry answers about ``assignee.id``, not about whatever
    column the members view keeps it in.
    """
    if not isinstance(node, ast.ColumnRef):
        return False
    names = _name_parts(node.fields)
    if len(names) == 2:
        dataset_name, field_name = scope.get(names[0]), names[1]
    elif len(names) == 1:
        dataset_name, field_name = _holder(scope, names[0]), names[0]
    else:
        return False
    if dataset_name is None:
        return False
    spec = dataset(dataset_name).by_name.get(field_name)
    return spec is not None and spec.kind is ControlKind.member


def _check_viewer(select: ast.SelectStmt, scope: dict[str, str]) -> None:
    """That ``me`` is somewhere it means something.

    The reader is a person, so the only thing to say about them is which person
    a field holds. Anywhere else the word would expand into a number beside
    something that is not one, and the statement would be a statement the
    database refuses — on a tile, long after it was written. This is the same
    rule the builder writes by, asked of a statement somebody typed.
    """
    placed: set[int] = set()

    class Compare(Visitor):
        def visit_A_Expr(self, ancestors: Any, node: ast.A_Expr) -> None:
            if node.kind == A_Expr_Kind.AEXPR_IN:
                against = node.lexpr
                sides = tuple(node.rexpr or ())
            elif node.kind == A_Expr_Kind.AEXPR_OP:
                against, sides = None, (node.lexpr, node.rexpr)
            else:
                return
            for index, side in enumerate(sides):
                if not _is_viewer(side):
                    continue
                other = against if against is not None else sides[1 - index]
                if not _holds_a_person(other, scope):
                    raise QueryError(QueryMessages.VIEWER_NEEDS_A_PERSON, VIEWER)
                placed.add(id(side))

    Compare()(select)

    for node in _column_refs(select):
        if _is_viewer(node) and id(node) not in placed:
            raise QueryError(QueryMessages.VIEWER_NEEDS_A_PERSON, VIEWER)


def _resolve_viewer(select: ast.SelectStmt) -> bool:
    """Write the reader in wherever the statement said ``me``.

    Answers whether it said so anywhere, for the caller that has to know.
    """
    named = False

    class Expand(Visitor):
        def visit_ColumnRef(self, ancestors: Any, node: ast.ColumnRef) -> Any:
            nonlocal named
            if _name_parts(node.fields) == [VIEWER]:
                named = True
                return _viewer_node()
            return None

    Expand()(select)
    return named


def _constants_in(node: Any) -> set[int]:
    """Every constant anywhere under *node*."""
    found: set[int] = set()

    class Collect(Visitor):
        def visit_A_Const(self, ancestors: Any, inner: ast.A_Const) -> None:
            found.add(id(inner))

    if node is not None:
        Collect()(node)
    return found


def _grouped_expressions(select: ast.SelectStmt) -> tuple[set[int], set[str]]:
    """Constants inside what a statement groups or orders by, and how those
    expressions are written.

    ``GROUP BY`` finds its output column by matching the expression, so the two
    copies of one have to be written the same way. A parameter is numbered by
    where it is met, and the two copies are met in different places — so a
    constant under either clause stays the constant it was, and so does its
    twin in the select list.
    """
    marked: set[int] = set()
    written: set[str] = set()
    stream = RawStream()
    for entry in select.groupClause or ():
        if isinstance(entry, ast.A_Const):
            continue
        marked |= _constants_in(entry)
        written.add(stream(entry))
    for entry in select.sortClause or ():
        node = entry.node if isinstance(entry, ast.SortBy) else entry
        if node is None or isinstance(node, ast.A_Const):
            continue
        marked |= _constants_in(node)
        written.add(stream(node))
    return marked, written


def _literal_positions(select: ast.SelectStmt) -> set[int]:
    """Constants that stay constants.

    Three kinds. ``GROUP BY 1`` and ``ORDER BY 1`` select an output column, and
    a parameter there would be the number one. A constant standing alone in the
    select list has nothing to take a type from — Postgres reads an unadorned
    parameter there as text — where the same constant compared against a column
    takes that column's type, which is what makes ``priority = $1`` work
    against an enum. And a constant inside a grouped or ordered expression is
    part of how that expression is written, which is what the output column is
    found by.
    """
    marked, grouped = _grouped_expressions(select)
    for entry in select.groupClause or ():
        if isinstance(entry, ast.A_Const):
            marked.add(id(entry))
    for entry in select.sortClause or ():
        if isinstance(entry, ast.SortBy) and isinstance(entry.node, ast.A_Const):
            marked.add(id(entry.node))
    stream = RawStream()
    for target in select.targetList or ():
        if not isinstance(target, ast.ResTarget):
            continue
        if isinstance(target.val, ast.A_Const):
            marked.add(id(target.val))
        elif target.val is not None and stream(target.val) in grouped:
            marked |= _constants_in(target.val)
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
    _expand_relations(select)
    scope = _relations(select)
    column_types = _output_types(select, scope)
    _check_viewer(select, scope)
    _resolve_columns(select, scope)
    parameters = _bind_literals(select)
    names_the_reader = _resolve_viewer(select)
    return ResolvedQuery(
        sql=RawStream()(select),
        parameters=parameters,
        relations=tuple(sorted(set(scope.values()))),
        column_types=column_types,
        names_the_reader=names_the_reader,
    )

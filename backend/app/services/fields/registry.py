"""The **field registry** — the datasets this deployment knows, and the bridge
from their declarations to the query engine.

Always the *field* registry, never the bare word: this codebase has several
registries (the initiative-RLS paths, the DAC resources, the auth providers) and
the qualifier is what says which one. It answers a single question — *what
fields does this thing have, and what may I do with them* — for every surface
that asks it.

One lookup for every consumer: the task list endpoint compiles filters through
:func:`allowed_fields` and orders through :func:`sort_fields`, the filter UI is
served :func:`describe`, and the query surface resolves names here rather than
against the physical schema.

Datasets are built on first use rather than at import. A declaration reads model
columns, and reading them at import time would tie this module's import order to
the mappers being configured — a fragility with nothing to gain, since the set
never changes within a process.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Any, Callable

from app.services.fields import tasks as tasks_dataset
from app.schemas.query import FilterOp
from app.services.fields.spec import (
    Dataset,
    FieldContext,
    FieldSpec,
    SortContext,
    offered_ops,
    offers_multiple,
)

#: Every dataset, by the name a consumer refers to it by. One entry per
#: declaration module; the module owns its fields, this owns the set.
_BUILDERS: dict[str, Callable[[], Dataset]] = {
    "tasks": tasks_dataset.build,
}


#: The datasets, as a type. Derived from the builders above rather than typed
#: out again, so a new dataset is nameable by a client — and refused by FastAPI
#: when it is not one — the moment it is declared, with no second list and no
#: hand-rolled "unknown dataset" branch to keep in step.
DatasetName = Enum("DatasetName", {name: name for name in _BUILDERS}, type=str)
DatasetName.__doc__ = "A dataset the field registry describes."


@lru_cache(maxsize=None)
def _built() -> dict[str, Dataset]:
    return {name: build() for name, build in _BUILDERS.items()}


def dataset(name: str) -> Dataset:
    """The named dataset, or ``KeyError`` — callers name a constant, not input."""
    return _built()[name]


def dataset_names() -> tuple[str, ...]:
    return tuple(_built())


def field(dataset_name: str, field_name: str) -> FieldSpec | None:
    """One field's declaration, or ``None`` if this dataset has no such field."""
    return dataset(dataset_name).by_name.get(field_name)


def allowed_fields(dataset_name: str, ctx: FieldContext) -> dict[str, Any]:
    """The ``allowed_fields`` mapping ``apply_filters`` consumes.

    A column field passes its column straight through; a computed one is bound
    to *ctx* here, because the engine calls a handler with ``(op, value)`` and
    knows nothing about whose request it is compiling for.

    Unknown fields are skipped by ``apply_filters`` rather than rejected, so a
    field this dataset does not declare simply narrows nothing — the same
    defense-in-depth the engine has always had.
    """
    resolved: dict[str, Any] = {}
    for spec in dataset(dataset_name).fields:
        if not spec.filterable:
            continue
        if spec.column is not None:
            resolved[spec.name] = spec.column
        else:
            resolved[spec.name] = _bind(spec, ctx)
    return resolved


def _bind(spec: FieldSpec, ctx: FieldContext) -> Callable[[Any, Any], Any]:
    """Bind a resolver to one request's context.

    A named function rather than a lambda so a traceback through a filter says
    which field it was compiling.
    """
    resolver = spec.resolve
    assert resolver is not None  # guaranteed by FieldSpec.__post_init__

    def resolve_field(op: Any, value: Any) -> Any:
        return resolver(op, value, ctx)

    resolve_field.__name__ = f"resolve_{spec.name}"
    return resolve_field


def allowed_ops(dataset_name: str) -> dict[str, frozenset[FilterOp]]:
    """The operators each field accepts, for ``apply_filters`` to enforce.

    Enforcement rather than description: a filter is applied in full or
    refused, so what a stored definition asks for and what it receives agree.
    """
    return {
        spec.name: spec.ops for spec in dataset(dataset_name).fields if spec.filterable
    }


def sort_fields(dataset_name: str, ctx: SortContext) -> dict[str, Any]:
    """The ``allowed_fields`` mapping ``apply_sorting`` consumes.

    Sorting lives in the same declaration as filtering because a field's
    orderability is a fact about the field, and because the query surface needs
    both from one place — ``ORDER BY`` is as much a part of SQL as ``WHERE``.

    Unlike filtering, these are plain expressions rather than callables: the
    sort engine takes a column to order by, so a field whose ordering depends on
    the request (a grouping in the reader's own timezone) is resolved here.
    """
    resolved: dict[str, Any] = {}
    for spec in dataset(dataset_name).fields:
        if not spec.sortable:
            continue
        resolved[spec.name] = spec.sort(ctx) if spec.sort is not None else spec.column
    return resolved


def sort_expression(dataset_name: str, field_name: str, ctx: SortContext) -> Any:
    """One field's ordering expression.

    For the caller that selects an ordering as a labelled column rather than
    only ordering by it — a cross-guild merge sorts in Python and needs the
    value carried out of SQL.
    """
    return sort_fields(dataset_name, ctx)[field_name]


def describe(dataset_name: str) -> list[dict[str, Any]]:
    """The dataset's fields as a client offers them, in the order it lists them.

    Deliberately not the resolvers: what a field compiles to is ours, and what
    it is called, holds, and is picked with is the client's. The operators here
    are what a *control* offers, which is the control's set narrowed to what the
    engine accepts — never the engine's full set, which includes shapes that are
    correct to compile and pointless to draw.
    """
    data = dataset(dataset_name)
    sortable = {spec.name for spec in data.fields if spec.sortable}
    return [
        {
            "name": spec.name,
            "type": spec.type.value,
            "kind": spec.kind.value,
            "ops": sorted(op.value for op in offered_ops(spec)),
            "multiple": offers_multiple(spec),
            "sortable": spec.name in sortable,
        }
        for spec in data.offered
    ]

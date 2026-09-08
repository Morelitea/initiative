"""The field registry: one declaration of what a field is, for every surface
that names one — filtering, sorting, the controls a client draws, and the
query surface's name resolution."""

from app.services.fields.registry import (
    allowed_fields,
    allowed_ops,
    dataset,
    dataset_names,
    describe,
    field,
    sort_expression,
    sort_fields,
)
from app.services.fields.spec import (
    ControlKind,
    Dataset,
    FieldContext,
    FieldSpec,
    FieldType,
    SortContext,
)

__all__ = [
    "ControlKind",
    "Dataset",
    "FieldContext",
    "FieldSpec",
    "FieldType",
    "SortContext",
    "allowed_fields",
    "allowed_ops",
    "dataset",
    "dataset_names",
    "describe",
    "field",
    "sort_expression",
    "sort_fields",
]

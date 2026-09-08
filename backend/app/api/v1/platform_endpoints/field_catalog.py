"""The field registry, as a client reads it.

One declaration serves the filter engine and the controls that build a filter,
so the operators a control offers cannot drift from the ones the server accepts.

Deliberately not guild-scoped: the answer describes the shape of a dataset, not
anybody's rows, and is identical for every guild on a deployment. Authentication
is still required — the field vocabulary is not something an anonymous caller
needs — but no guild context is taken, because taking one would imply the answer
depended on it.
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_active_user
from app.schemas.field_catalog import FieldCatalogResponse, FieldDescription
from app.services import fields as fields_registry
from app.services.fields.registry import DatasetName

router = APIRouter()


@router.get(
    "/fields/{dataset}",
    response_model=FieldCatalogResponse,
    dependencies=[Depends(get_current_active_user)],
)
def read_field_catalog(dataset: DatasetName) -> FieldCatalogResponse:
    """The fields *dataset* offers, in the order a client lists them.

    ``dataset`` is the registry's own enum, so an unknown name is refused by
    validation rather than by a branch here that would have to be kept in step
    with the registry.
    """
    return FieldCatalogResponse(
        dataset=dataset.value,
        fields=[
            FieldDescription(**entry)
            for entry in fields_registry.describe(dataset.value)
        ],
    )

"""The single resource-grant (sharing) schema for projects and documents.

Everything is a row in ``resource_grants``, so there is **one** shape:
``ResourceGrantSchema``. A resource's sharing state is just a list of them — the
identical shape both reports the grants (``grants`` on the read models) and
replaces them (the ``PUT /{id}/grants`` body). Lives in its own module so both
the ``project`` and ``document`` schemas can import it without a cycle
(``project`` already imports ``document``).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import ConfigDict, Field, model_validator

from app.core.tools import Tool
from app.schemas.base import SanitizedBaseModel

# Upper bound on how many resources one bulk grant request may touch. Each item is
# a load + authorize + rewrite + commit, so an unbounded list is a DoS / slow-query
# risk; a multi-select bulk-edit UI never needs more than this in one call.
MAX_BULK_GRANT_ITEMS = 200


class ResourceGrantSchema(SanitizedBaseModel):
    """One ``resource_grants`` row — exactly the columns that define a grant: a
    ``level`` for a user (``user_id``), an initiative role (``role_id``), or all
    initiative members (``all_initiative_members``). Exactly one grantee is set.

    The identical shape both reports a resource's grants (``grants`` is a list of
    these) and replaces them (the ``PUT /{id}/grants`` body) — no field is
    read-only or write-only. The server always preserves the resource's owner
    grant. Role display names are resolved client-side from the initiative's roles
    by ``role_id``."""

    # from_attributes so a read model can validate straight off the ORM
    # ResourceGrant row (e.g. ProjectRead.model_validate(project) reading
    # project.grants).
    model_config = ConfigDict(from_attributes=True)

    level: Literal["read", "write", "owner"]
    user_id: Optional[int] = None
    role_id: Optional[int] = None
    all_initiative_members: bool = False

    @model_validator(mode="after")
    def exactly_one_grantee(self) -> "ResourceGrantSchema":
        count = (
            (self.user_id is not None)
            + (self.role_id is not None)
            + self.all_initiative_members
        )
        if count != 1:
            raise ValueError(
                "Exactly one of user_id, role_id, or all_initiative_members must be set"
            )
        return self


class ResourceGrantBulkItem(SanitizedBaseModel):
    """One tool's full target sharing state in a bulk request — the same ``grants``
    body the per-resource ``PUT /{id}/grants`` takes, tagged with which tool it
    applies to (the app-wide ``Tool`` enum)."""

    resource_type: Tool
    resource_id: int
    grants: list[ResourceGrantSchema]


class ResourceGrantBulkRequest(SanitizedBaseModel):
    """Replace sharing on many resources (possibly of different types) in one call.
    Capped at ``MAX_BULK_GRANT_ITEMS`` items (422 otherwise)."""

    items: list[ResourceGrantBulkItem] = Field(
        min_length=1, max_length=MAX_BULK_GRANT_ITEMS
    )


class ResourceGrantBulkItemResult(SanitizedBaseModel):
    """Per-item outcome — bulk is best-effort: a resource the caller can't manage
    (``forbidden``) or that doesn't exist (``not_found``) is skipped without
    blocking the rest."""

    resource_type: Tool
    resource_id: int
    status: Literal["ok", "forbidden", "not_found"]
    detail: Optional[str] = None


class ResourceGrantBulkResponse(SanitizedBaseModel):
    results: list[ResourceGrantBulkItemResult]

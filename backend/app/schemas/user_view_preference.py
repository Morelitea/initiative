"""Request/response shapes for the per-user view-preferences API.

The ``value`` field is opaque JSON — the frontend defines the shape per
scope. Two caps live here (not on the DB column) so a misbehaving client
gets a 422 instead of writing an unbounded blob:

* ``scope_key`` length is bounded by ``MAX_SCOPE_KEY_LENGTH`` from the
  model module — kept centralized so the model and schema agree.
* ``value`` size is bounded by ``MAX_VALUE_JSON_BYTES`` measured at the
  serialized layer; we serialize once in the validator and compare.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field, field_validator

from app.models.user_view_preference import MAX_SCOPE_KEY_LENGTH, MAX_VALUE_JSON_BYTES
from app.schemas.base import SanitizedBaseModel


def _validate_value_size(value: Any) -> Any:
    try:
        serialized = json.dumps(value, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be JSON-serializable") from exc
    if len(serialized.encode("utf-8")) > MAX_VALUE_JSON_BYTES:
        raise ValueError(
            f"value exceeds {MAX_VALUE_JSON_BYTES} bytes when serialized as JSON"
        )
    return value


class UserViewPreferenceRead(SanitizedBaseModel):
    model_config = ConfigDict(from_attributes=True)

    scope_key: str
    value: Any
    updated_at: datetime


class UserViewPreferenceWrite(SanitizedBaseModel):
    """Body for ``PUT /user-view-preferences/{scope_key}``."""

    value: Any

    @field_validator("value")
    @classmethod
    def _check_size(cls, v: Any) -> Any:
        return _validate_value_size(v)


class UserViewPreferencesMap(SanitizedBaseModel):
    """Response for ``GET /user-view-preferences`` — keyed by scope."""

    items: dict[str, Any] = Field(default_factory=dict)


# Re-exported for use in path/query validators in the router.
SCOPE_KEY_MAX_LENGTH = MAX_SCOPE_KEY_LENGTH

"""Pydantic schemas for custom property definitions and values."""

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.property import PropertyAppliesTo, PropertyType

_SLUG_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_\-]*$"
_HEX_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"
_SELECT_TYPES = {PropertyType.select, PropertyType.multi_select}


class PropertyOption(BaseModel):
    """One option entry for select / multi_select property definitions."""

    value: str = Field(..., min_length=1, max_length=64, pattern=_SLUG_PATTERN)
    label: str = Field(..., min_length=1, max_length=100)
    color: Optional[str] = Field(default=None, pattern=_HEX_COLOR_PATTERN)


class PropertyDefinitionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: PropertyType
    applies_to: PropertyAppliesTo = PropertyAppliesTo.both
    position: float = 0.0
    color: Optional[str] = Field(default=None, pattern=_HEX_COLOR_PATTERN)
    options: Optional[List[PropertyOption]] = None

    @field_validator("name")
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Property name cannot be empty")
        return v

    @model_validator(mode="after")
    def _validate_options(self) -> "PropertyDefinitionBase":
        if self.type in _SELECT_TYPES:
            if not self.options:
                raise ValueError("PROPERTY_OPTIONS_REQUIRED")
            slugs = [opt.value for opt in self.options]
            if len(slugs) != len(set(slugs)):
                raise ValueError("PROPERTY_DUPLICATE_OPTION_VALUE")
        else:
            # Silently coerce away options on non-select types so create
            # calls from the client don't trip confusing errors.
            self.options = None
        return self


class PropertyDefinitionCreate(PropertyDefinitionBase):
    pass


class PropertyDefinitionUpdate(BaseModel):
    """Mutable fields on a property definition.

    ``type`` is deliberately excluded — type changes require a dedicated
    flow because existing values would become invalid. The endpoint
    raises 409 PROPERTY_TYPE_CHANGE_BLOCKED if any values exist; the
    service layer enforces the rule.
    """

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    applies_to: Optional[PropertyAppliesTo] = None
    position: Optional[float] = None
    color: Optional[str] = Field(default=None, pattern=_HEX_COLOR_PATTERN)
    options: Optional[List[PropertyOption]] = None

    @field_validator("name")
    def _strip_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Property name cannot be empty")
        return v

    @field_validator("options")
    def _unique_slugs(cls, v: Optional[List[PropertyOption]]) -> Optional[List[PropertyOption]]:
        if v is None:
            return v
        slugs = [opt.value for opt in v]
        if len(slugs) != len(set(slugs)):
            raise ValueError("PROPERTY_DUPLICATE_OPTION_VALUE")
        return v


class PropertyDefinitionRead(PropertyDefinitionBase):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    guild_id: int
    created_at: datetime
    updated_at: datetime


class PropertyDefinitionUpdateResponse(BaseModel):
    """Envelope for PATCH /property-definitions/{id}.

    Always returns ``orphaned_value_count`` so the SPA can surface a
    warning when option removal leaves dangling values. For non-option
    updates this is always 0.
    """

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    definition: PropertyDefinitionRead
    orphaned_value_count: int = 0


class PropertyValueInput(BaseModel):
    """A single (property_id, value) pair submitted by the client.

    The value is polymorphic because the Pydantic layer can't know the
    definition's type. Typed validation runs server-side in
    ``app.services.properties._validate_value_for_type``.
    """

    property_id: int
    value: Any = None


class PropertyValuesSetRequest(BaseModel):
    """Replace-all payload for PUT /{entity}/{id}/properties.

    An empty list clears every property value on the entity.
    """

    values: List[PropertyValueInput] = Field(default_factory=list)


class PropertySummary(BaseModel):
    """Lightweight property value for embedding in DocumentRead / TaskRead.

    ``value`` is rehydrated from the correct typed column by the service
    layer. For ``user_reference`` properties the service attaches a
    minimal ``{id, full_name}`` dict.
    """

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    property_id: int
    name: str
    type: PropertyType
    applies_to: PropertyAppliesTo
    options: Optional[List[PropertyOption]] = None
    value: Any = None

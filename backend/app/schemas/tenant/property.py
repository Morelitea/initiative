"""Pydantic schemas for custom property definitions and values."""

from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import (
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.core.identity_boundary import responding_to_install
from app.core.messages import PropertyMessages
from app.core.tools import PROPERTY_TARGETS
from app.schemas.base import SanitizedBaseModel
from app.schemas.platform.user import PluginPerson

from app.models.tenant.property import PropertyType

_SLUG_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_\-]*$"
_HEX_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"
_SELECT_TYPES = {PropertyType.select, PropertyType.multi_select}

# Derived, never re-declared: every Tool value plus every sub-tool (see
# PROPERTY_TARGETS in app.core.tools). A new Tool lands here — and in the
# OpenAPI spec / generated frontend types — automatically.
PropertyTarget = Enum(
    "PropertyTarget", {name: name for name in PROPERTY_TARGETS}, type=str
)
PropertyTarget.__doc__ = (
    "What can carry custom property values: every tool and sub-tool."
)


class PropertyOption(SanitizedBaseModel):
    """One option entry for select / multi_select property definitions."""

    value: str = Field(..., min_length=1, max_length=64, pattern=_SLUG_PATTERN)
    label: str = Field(..., min_length=1, max_length=100)
    color: Optional[str] = Field(default=None, pattern=_HEX_COLOR_PATTERN)


class PropertyDefinitionBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: PropertyType
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
                raise ValueError(PropertyMessages.OPTIONS_REQUIRED)
            slugs = [opt.value for opt in self.options]
            if len(slugs) != len(set(slugs)):
                raise ValueError(PropertyMessages.DUPLICATE_OPTION_VALUE)
        else:
            # Silently coerce away options on non-select types so create
            # calls from the client don't trip confusing errors.
            self.options = None
        return self


class PropertyDefinitionCreate(PropertyDefinitionBase):
    initiative_id: int


class PropertyDefinitionUpdate(SanitizedBaseModel):
    """Mutable fields on a property definition.

    ``type`` is deliberately excluded — type changes require a dedicated
    flow because existing values would become invalid. A ``type`` sent
    in the payload is ignored.
    """

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
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
    def _unique_slugs(
        cls, v: Optional[List[PropertyOption]]
    ) -> Optional[List[PropertyOption]]:
        if v is None:
            return v
        slugs = [opt.value for opt in v]
        if len(slugs) != len(set(slugs)):
            raise ValueError(PropertyMessages.DUPLICATE_OPTION_VALUE)
        return v


class PropertyDefinitionRead(PropertyDefinitionBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    initiative_id: int
    created_at: datetime
    updated_at: datetime


class PropertyDefinitionUpdateResponse(SanitizedBaseModel):
    """Envelope for PATCH /property-definitions/{id}.

    Always returns ``orphaned_value_count`` so the SPA can surface a
    warning when option removal leaves dangling values. For non-option
    updates this is always 0.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    definition: PropertyDefinitionRead
    orphaned_value_count: int = 0


class PropertyValueInput(SanitizedBaseModel):
    """A single (property_id, value) pair submitted by the client.

    The value is polymorphic because the Pydantic layer can't know the
    definition's type. Typed validation runs server-side in
    ``app.services.properties._validate_value_for_type``.
    """

    property_id: int
    value: Any = None


class PropertyValuesSetRequest(SanitizedBaseModel):
    """Replace-all payload for ``PUT /properties/{target}/{entity_id}``.

    An empty list clears every property value on the entity.
    """

    values: List[PropertyValueInput] = Field(default_factory=list)


class PropertiesOnCreate(SanitizedBaseModel):
    """What every tool and sub-tool's create takes beside its own fields: the
    custom property values to write with the row, in the same transaction."""

    properties: List[PropertyValueInput] = Field(default_factory=list)


class PropertiesOnUpdate(SanitizedBaseModel):
    """What a sub-tool's update takes beside its tags: the custom property
    values to replace, in the same transaction. Omitted, they stay as they
    are; a list (empty included) replaces them all."""

    properties: Optional[List[PropertyValueInput]] = None


class PropertySummary(SanitizedBaseModel):
    """Lightweight property value for embedding in entity reads.

    ``value`` is rehydrated from the correct typed column by the service
    layer. For ``user_reference`` properties the service attaches a
    minimal person dict (``id``, the handle, ``display_name``, ``avatar_url``).
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    property_id: int
    name: str
    type: PropertyType
    options: Optional[List[PropertyOption]] = None
    value: Any = Field(
        default=None,
        description=(
            "Shaped by the property's type. For user_reference, a person: id, "
            "username, discriminator, display_name and avatar_url, or an "
            "PluginPerson when the reader is an installed plug-in."
        ),
    )

    @field_serializer("value")
    def _value_out(self, value: Any) -> Any:
        """A person a ``user_reference`` value names, as the response's reader
        knows them: an installed plug-in gets an :class:`PluginPerson`."""
        if (
            self.type is not PropertyType.user_reference
            or not isinstance(value, dict)
            or not responding_to_install()
        ):
            return value
        return PluginPerson.model_validate(value).for_install()


def annotated_properties(entity: Any) -> List[PropertySummary]:
    """The summaries ``properties_service.annotate_properties`` put on this
    entity — read rather than recomputed, since a page's values are fetched for
    the whole page at once."""
    return list(getattr(entity, "properties", None) or [])

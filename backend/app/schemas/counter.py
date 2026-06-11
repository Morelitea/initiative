from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from pydantic import ConfigDict, Field, model_validator

from app.core.messages import CounterMessages
from app.models.counter import CounterPermissionLevel, CounterViewMode
from app.schemas.base import SanitizedBaseModel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.counter import Counter, CounterGroup


# ---------------------------------------------------------------------------
# Permission schemas
# ---------------------------------------------------------------------------


class CounterGroupPermissionCreate(SanitizedBaseModel):
    user_id: int
    level: CounterPermissionLevel = CounterPermissionLevel.write


class CounterGroupPermissionRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    user_id: int
    level: CounterPermissionLevel
    created_at: datetime


class CounterGroupRolePermissionCreate(SanitizedBaseModel):
    initiative_role_id: int
    level: CounterPermissionLevel = CounterPermissionLevel.read


class CounterGroupRolePermissionRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    initiative_role_id: int
    role_name: str = ""
    role_display_name: str = ""
    level: CounterPermissionLevel
    created_at: datetime


# ---------------------------------------------------------------------------
# Counter schemas
# ---------------------------------------------------------------------------


def _validate_counter_constraints(
    *,
    view_mode: CounterViewMode,
    min_value: Optional[Decimal],
    max_value: Optional[Decimal],
    step: Decimal,
) -> None:
    if view_mode != CounterViewMode.number and (min_value is None or max_value is None):
        raise ValueError(CounterMessages.VIEW_MODE_REQUIRES_BOUNDS)
    if min_value is not None and max_value is not None and min_value > max_value:
        raise ValueError(CounterMessages.MIN_GREATER_THAN_MAX)
    if step <= 0:
        raise ValueError(CounterMessages.STEP_MUST_BE_POSITIVE)


class CounterBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    color: Optional[str] = None
    count: Decimal = Decimal("0")
    min: Optional[Decimal] = None
    max: Optional[Decimal] = None
    step: Decimal = Decimal("1")
    initial_count: Decimal = Decimal("0")
    view_mode: CounterViewMode = CounterViewMode.number
    position: Decimal = Decimal("0")

    @model_validator(mode="after")
    def _check(self) -> "CounterBase":
        _validate_counter_constraints(
            view_mode=self.view_mode,
            min_value=self.min,
            max_value=self.max,
            step=self.step,
        )
        return self


class CounterCreate(CounterBase):
    pass


class CounterUpdate(SanitizedBaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    color: Optional[str] = None
    # ``min``/``max`` are nullable columns — an explicit null clears the bound.
    # The remaining fields back NOT NULL columns, so a null is meaningless; the
    # endpoint drops explicit nulls for them. ``gt=0`` rejects a provided step
    # of 0/negative with a clean 422. ``position`` allows negatives so a
    # fractional drop-to-front (prev - 1) still validates.
    min: Optional[Decimal] = None
    max: Optional[Decimal] = None
    step: Optional[Decimal] = Field(default=None, gt=0)
    initial_count: Optional[Decimal] = None
    view_mode: Optional[CounterViewMode] = None
    position: Optional[Decimal] = None


class CounterSetCountRequest(SanitizedBaseModel):
    count: Decimal


class CounterSortField(str, Enum):
    name = "name"
    count = "count"


class CounterSortDirection(str, Enum):
    asc = "asc"
    desc = "desc"


class CounterSortRequest(SanitizedBaseModel):
    field: CounterSortField
    direction: CounterSortDirection = CounterSortDirection.asc


class CounterRead(SanitizedBaseModel):
    """Serialized counter. Numeric fields are returned as plain decimal
    strings (e.g. "0", "12.5") rather than ``Decimal`` so JSON never emits
    PostgreSQL's exponent notation (``0E-10``) from ``Numeric(20, 10)``
    columns.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    counter_group_id: int
    guild_id: int
    name: str
    color: Optional[str] = None
    count: str
    min: Optional[str] = None
    max: Optional[str] = None
    step: str
    initial_count: str
    view_mode: CounterViewMode
    position: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Counter Group schemas
# ---------------------------------------------------------------------------


class CounterGroupBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class CounterGroupCreate(CounterGroupBase):
    initiative_id: int
    role_permissions: Optional[List[CounterGroupRolePermissionCreate]] = None
    user_permissions: Optional[List[CounterGroupPermissionCreate]] = None


class CounterGroupUpdate(SanitizedBaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None


class CounterGroupDuplicateRequest(SanitizedBaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)


class CounterGroupSummary(CounterGroupBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    initiative_id: int
    guild_id: int
    created_by_id: int
    counter_count: int = 0
    my_permission_level: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CounterGroupListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[CounterGroupSummary]
    total_count: int
    page: int
    page_size: int
    has_next: bool


class CounterGroupRead(CounterGroupSummary):
    counters: List[CounterRead] = Field(default_factory=list)
    permissions: List[CounterGroupPermissionRead] = Field(default_factory=list)
    role_permissions: List[CounterGroupRolePermissionRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Permission-update payloads (for PUT /permissions and /role-permissions)
# ---------------------------------------------------------------------------


class CounterGroupPermissionsUpdate(SanitizedBaseModel):
    permissions: List[CounterGroupPermissionCreate] = Field(default_factory=list)


class CounterGroupRolePermissionsUpdate(SanitizedBaseModel):
    role_permissions: List[CounterGroupRolePermissionCreate] = Field(
        default_factory=list
    )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _format_decimal(value: Decimal) -> str:
    """Return a plain decimal string with no exponent and no trailing zeros.

    PostgreSQL's ``Numeric(20, 10)`` round-trips zeros as ``Decimal('0E-10')``,
    which Python's default JSON encoder emits as ``"0E-10"`` — confusing to
    display and parse on the client. ``format(value, "f")`` gives fixed-point
    notation; we then trim trailing zeros after the decimal point but keep
    a single ``"0"`` when there's no integer part.
    """
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _format_optional_decimal(value: Optional[Decimal]) -> Optional[str]:
    return _format_decimal(value) if value is not None else None


def serialize_counter(counter: "Counter") -> CounterRead:
    return CounterRead(
        id=counter.id,
        counter_group_id=counter.counter_group_id,
        guild_id=counter.guild_id,
        name=counter.name,
        color=counter.color,
        count=_format_decimal(counter.count),
        min=_format_optional_decimal(counter.min),
        max=_format_optional_decimal(counter.max),
        step=_format_decimal(counter.step),
        initial_count=_format_decimal(counter.initial_count),
        view_mode=counter.view_mode,
        position=_format_decimal(counter.position),
        created_at=counter.created_at,
        updated_at=counter.updated_at,
    )


def _serialize_permissions(group: "CounterGroup") -> List[CounterGroupPermissionRead]:
    perms = getattr(group, "permissions", None) or []
    return [
        CounterGroupPermissionRead(
            user_id=p.user_id, level=p.level, created_at=p.created_at
        )
        for p in perms
    ]


def _serialize_role_permissions(
    group: "CounterGroup",
) -> List[CounterGroupRolePermissionRead]:
    role_perms = getattr(group, "role_permissions", None) or []
    result: List[CounterGroupRolePermissionRead] = []
    for rp in role_perms:
        role = getattr(rp, "role", None)
        result.append(
            CounterGroupRolePermissionRead(
                initiative_role_id=rp.initiative_role_id,
                role_name=getattr(role, "name", "") if role else "",
                role_display_name=getattr(role, "display_name", "") if role else "",
                level=rp.level,
                created_at=rp.created_at,
            )
        )
    return result


def _active_counters(group: "CounterGroup") -> list:
    counters = getattr(group, "counters", None) or []
    return [c for c in counters if getattr(c, "deleted_at", None) is None]


def serialize_counter_group_summary(
    group: "CounterGroup",
    *,
    my_permission_level: Optional[str] = None,
) -> CounterGroupSummary:
    return CounterGroupSummary(
        id=group.id,
        name=group.name,
        description=group.description,
        initiative_id=group.initiative_id,
        guild_id=group.guild_id,
        created_by_id=group.created_by_id,
        counter_count=len(_active_counters(group)),
        my_permission_level=my_permission_level,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


def serialize_counter_group(
    group: "CounterGroup",
    *,
    my_permission_level: Optional[str] = None,
) -> CounterGroupRead:
    summary = serialize_counter_group_summary(
        group, my_permission_level=my_permission_level
    )
    counters = sorted(_active_counters(group), key=lambda c: c.position)
    return CounterGroupRead(
        **summary.model_dump(),
        counters=[serialize_counter(c) for c in counters],
        permissions=_serialize_permissions(group),
        role_permissions=_serialize_role_permissions(group),
    )

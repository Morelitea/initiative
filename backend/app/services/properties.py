"""Service layer for custom property definitions and values.

Responsibilities:
* Validate raw input values against a PropertyDefinition's type and
  return the dict of typed columns to set on a value row.
* Replace-all attach of property values on documents and tasks.
* Serialize attached values to the ``PropertySummary`` API shape.

The caller owns session lifecycle (commit + reapply_rls_context) — these
functions only issue the in-transaction INSERT/DELETE statements so the
endpoint can control when RLS context is re-applied.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from fastapi import HTTPException, status
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import PropertyMessages
from app.models.document import Document
from app.models.guild import GuildMembership
from app.models.property import (
    DocumentPropertyValue,
    PropertyAppliesTo,
    PropertyDefinition,
    PropertyType,
    TaskPropertyValue,
)
from app.models.task import Task
from app.models.user import User
from app.schemas.property import PropertyOption, PropertySummary, PropertyValueInput

# Cap on the number of property predicates accepted by list endpoints.
# Bounds the per-request subquery count against task_property_values /
# document_property_values.
MAX_PROPERTY_FILTERS = 5

_HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)

_VALUE_COLUMNS = (
    "value_text",
    "value_number",
    "value_boolean",
    "value_date",
    "value_datetime",
    "value_user_id",
    "value_json",
)


def _empty_columns() -> Dict[str, Any]:
    """Return all typed value columns set to None (baseline for an update)."""
    return {col: None for col in _VALUE_COLUMNS}


def _bad_value(code: str = PropertyMessages.INVALID_VALUE_FOR_TYPE) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=code)


def _coerce_text(raw: Any) -> str:
    if not isinstance(raw, str):
        raise _bad_value()
    stripped = raw.strip()
    if not stripped:
        raise _bad_value()
    return stripped


def _coerce_number(raw: Any) -> Decimal:
    if isinstance(raw, bool):
        raise _bad_value()
    try:
        if isinstance(raw, Decimal):
            return raw
        if isinstance(raw, (int, float)):
            return Decimal(str(raw))
        if isinstance(raw, str):
            return Decimal(raw.strip())
    except (InvalidOperation, ValueError) as exc:
        raise _bad_value() from exc
    raise _bad_value()


def _coerce_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    raise _bad_value()


def _coerce_date(raw: Any) -> date:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError as exc:
            raise _bad_value() from exc
    raise _bad_value()


def _coerce_datetime(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise _bad_value() from exc
    raise _bad_value()


def _coerce_url(raw: Any) -> str:
    if not isinstance(raw, str):
        raise _bad_value()
    candidate = raw.strip()
    if not candidate:
        raise _bad_value()
    try:
        _HTTP_URL_ADAPTER.validate_python(candidate)
    except ValidationError as exc:
        raise _bad_value() from exc
    return candidate


def _option_slugs(defn: PropertyDefinition) -> Set[str]:
    options = defn.options or []
    slugs: Set[str] = set()
    for opt in options:
        slug = opt.get("value") if isinstance(opt, dict) else getattr(opt, "value", None)
        if slug:
            slugs.add(slug)
    return slugs


def _parsed_options(defn: PropertyDefinition) -> List[PropertyOption]:
    if not defn.options:
        return []
    parsed: List[PropertyOption] = []
    for raw in defn.options:
        if isinstance(raw, PropertyOption):
            parsed.append(raw)
            continue
        if isinstance(raw, dict):
            try:
                parsed.append(PropertyOption(**raw))
            except ValidationError:
                # Options in the DB that fail schema validation are ignored
                # at serialize time — they can't be produced through the API.
                continue
    return parsed


async def _ensure_user_in_guild(session: AsyncSession, user_id: int, guild_id: int) -> None:
    stmt = select(GuildMembership).where(
        GuildMembership.guild_id == guild_id,
        GuildMembership.user_id == user_id,
    )
    result = await session.exec(stmt)
    if result.one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=PropertyMessages.USER_NOT_IN_GUILD,
        )


def _is_empty_value(raw_value: Any) -> bool:
    """Return True when ``raw_value`` represents "attached but no value".

    Attached-but-empty property rows are allowed so a user can add a
    property definition to a document/task without being forced to enter
    a value — the row persists (all typed columns null) and the "is
    empty" filter can match it.
    """
    if raw_value is None:
        return True
    if isinstance(raw_value, str) and not raw_value.strip():
        return True
    if isinstance(raw_value, (list, tuple)) and len(raw_value) == 0:
        return True
    return False


async def _validate_value_for_type(
    session: AsyncSession,
    defn: PropertyDefinition,
    raw_value: Any,
    guild_id: int,
) -> Dict[str, Any]:
    """Return the typed-column dict for ``raw_value`` under ``defn``.

    When ``raw_value`` is "empty" (None, blank string, empty list) the
    returned dict has every typed column set to None — the row still
    persists as an attached-but-empty record.

    Raises ``HTTPException`` 400 on type mismatches or select/option
    issues, 400 ``USER_NOT_IN_GUILD`` for cross-guild ``user_reference``
    values.
    """
    cols = _empty_columns()

    if _is_empty_value(raw_value):
        return cols

    ptype = defn.type

    if ptype is PropertyType.text:
        cols["value_text"] = _coerce_text(raw_value)
    elif ptype is PropertyType.number:
        cols["value_number"] = _coerce_number(raw_value)
    elif ptype is PropertyType.checkbox:
        cols["value_boolean"] = _coerce_bool(raw_value)
    elif ptype is PropertyType.date:
        cols["value_date"] = _coerce_date(raw_value)
    elif ptype is PropertyType.datetime:
        cols["value_datetime"] = _coerce_datetime(raw_value)
    elif ptype is PropertyType.url:
        cols["value_text"] = _coerce_url(raw_value)
    elif ptype is PropertyType.select:
        slug = _coerce_text(raw_value)
        if slug not in _option_slugs(defn):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=PropertyMessages.OPTION_NOT_IN_DEFINITION,
            )
        cols["value_text"] = slug
    elif ptype is PropertyType.multi_select:
        if not isinstance(raw_value, (list, tuple)):
            raise _bad_value()
        valid = _option_slugs(defn)
        slugs: List[str] = []
        seen: Set[str] = set()
        for entry in raw_value:
            slug = _coerce_text(entry)
            if slug not in valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=PropertyMessages.OPTION_NOT_IN_DEFINITION,
                )
            if slug not in seen:
                seen.add(slug)
                slugs.append(slug)
        cols["value_json"] = slugs
    elif ptype is PropertyType.user_reference:
        if not isinstance(raw_value, int) or isinstance(raw_value, bool):
            raise _bad_value()
        await _ensure_user_in_guild(session, raw_value, guild_id)
        cols["value_user_id"] = raw_value
    else:  # pragma: no cover - defensive; PropertyType is closed
        raise _bad_value()

    return cols


def _expected_applies_to(entity_kind: str) -> Set[PropertyAppliesTo]:
    if entity_kind == "document":
        return {PropertyAppliesTo.document, PropertyAppliesTo.both}
    if entity_kind == "task":
        return {PropertyAppliesTo.task, PropertyAppliesTo.both}
    raise ValueError(f"Unknown entity kind: {entity_kind!r}")


async def _load_definitions(
    session: AsyncSession,
    definition_ids: Iterable[int],
) -> Dict[int, PropertyDefinition]:
    ids = list({did for did in definition_ids if did is not None})
    if not ids:
        return {}
    stmt = select(PropertyDefinition).where(PropertyDefinition.id.in_(ids))
    result = await session.exec(stmt)
    return {defn.id: defn for defn in result.all()}


async def _set_property_values(
    session: AsyncSession,
    *,
    entity_kind: str,
    entity_id: int,
    values: Sequence[PropertyValueInput],
    guild_id: int,
) -> None:
    value_model = (
        DocumentPropertyValue if entity_kind == "document" else TaskPropertyValue
    )
    id_column = value_model.document_id if entity_kind == "document" else value_model.task_id

    # Always wipe existing rows for the entity — replace-all semantics.
    await session.execute(delete(value_model).where(id_column == entity_id))

    if not values:
        return

    expected = _expected_applies_to(entity_kind)
    requested_ids = [v.property_id for v in values]
    if len(requested_ids) != len(set(requested_ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=PropertyMessages.INVALID_VALUE_FOR_TYPE,
        )

    definitions = await _load_definitions(session, requested_ids)

    for entry in values:
        defn = definitions.get(entry.property_id)
        if defn is None or defn.guild_id != guild_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=PropertyMessages.DEFINITION_NOT_FOUND,
            )
        if defn.applies_to not in expected:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=PropertyMessages.APPLIES_TO_MISMATCH,
            )
        cols = await _validate_value_for_type(session, defn, entry.value, guild_id)

        if entity_kind == "document":
            row = DocumentPropertyValue(
                document_id=entity_id,
                property_id=defn.id,
                **cols,
            )
        else:
            row = TaskPropertyValue(
                task_id=entity_id,
                property_id=defn.id,
                **cols,
            )
        session.add(row)


async def set_document_property_values(
    session: AsyncSession,
    document: Document,
    values: Sequence[PropertyValueInput],
    guild_id: int,
) -> None:
    """Replace all property values attached to ``document``.

    Caller is responsible for ``session.commit()`` + ``reapply_rls_context``.
    """
    await _set_property_values(
        session,
        entity_kind="document",
        entity_id=document.id,
        values=values,
        guild_id=guild_id,
    )


async def set_task_property_values(
    session: AsyncSession,
    task: Task,
    values: Sequence[PropertyValueInput],
    guild_id: int,
) -> None:
    """Replace all property values attached to ``task``.

    Caller is responsible for ``session.commit()`` + ``reapply_rls_context``.
    """
    await _set_property_values(
        session,
        entity_kind="task",
        entity_id=task.id,
        values=values,
        guild_id=guild_id,
    )


def _number_to_json(v: Optional[Decimal]) -> Optional[float]:
    if v is None:
        return None
    # Represent as float for JSON serialization; callers needing exact
    # arithmetic should hit the raw value directly.
    return float(v)


def _rehydrate_value(defn: PropertyDefinition, row: Any, user: Optional[User]) -> Any:
    ptype = defn.type
    if ptype in {PropertyType.text, PropertyType.url, PropertyType.select}:
        return row.value_text
    if ptype is PropertyType.number:
        return _number_to_json(row.value_number)
    if ptype is PropertyType.checkbox:
        return row.value_boolean
    if ptype is PropertyType.date:
        return row.value_date
    if ptype is PropertyType.datetime:
        return row.value_datetime
    if ptype is PropertyType.multi_select:
        return list(row.value_json) if row.value_json is not None else []
    if ptype is PropertyType.user_reference:
        if user is None:
            return {"id": row.value_user_id} if row.value_user_id else None
        return {"id": user.id, "full_name": user.full_name}
    return None  # pragma: no cover


def summaries_from_rows(rows: Iterable[Any]) -> List[PropertySummary]:
    """Build :class:`PropertySummary` list from loaded value rows.

    ``rows`` must be ``DocumentPropertyValue`` or ``TaskPropertyValue``
    instances with ``property_definition`` (and ``value_user`` when
    applicable) eager-loaded. Sync so it can be called from the existing
    non-async doc/task serializers.
    """
    summaries: List[PropertySummary] = []
    for row in rows:
        defn = getattr(row, "property_definition", None)
        if defn is None:
            continue
        value = _rehydrate_value(defn, row, getattr(row, "value_user", None))
        summaries.append(
            PropertySummary(
                property_id=defn.id,
                name=defn.name,
                type=defn.type,
                applies_to=defn.applies_to,
                options=_parsed_options(defn) or None,
                value=value,
            )
        )
    summaries.sort(key=lambda s: s.name.lower())
    return summaries


async def _serialize_values(
    session: AsyncSession,
    *,
    entity_kind: str,
    entity_id: int,
) -> List[PropertySummary]:
    value_model = (
        DocumentPropertyValue if entity_kind == "document" else TaskPropertyValue
    )
    id_column = value_model.document_id if entity_kind == "document" else value_model.task_id

    stmt = (
        select(value_model)
        .where(id_column == entity_id)
        .options(
            selectinload(value_model.property_definition),
            selectinload(value_model.value_user),
        )
    )
    result = await session.exec(stmt)
    rows = result.all()
    return summaries_from_rows(rows)


async def serialize_document_properties(
    session: AsyncSession,
    document: Document,
) -> List[PropertySummary]:
    return await _serialize_values(session, entity_kind="document", entity_id=document.id)


async def serialize_task_properties(
    session: AsyncSession,
    task: Task,
) -> List[PropertySummary]:
    return await _serialize_values(session, entity_kind="task", entity_id=task.id)


async def count_orphaned_values(
    session: AsyncSession,
    defn_id: int,
    valid_slugs: Set[str],
) -> int:
    """Count attached values whose option slug is no longer valid.

    Used on PATCH of a select/multi_select definition when the option list
    changes — the SPA surfaces the count as a warning. Orphaned values are
    preserved (not cleared) by design.
    """
    count = 0
    for value_model in (DocumentPropertyValue, TaskPropertyValue):
        # value_text (single select)
        stmt_text = select(value_model).where(
            value_model.property_id == defn_id,
            value_model.value_text.is_not(None),
        )
        result = await session.exec(stmt_text)
        for row in result.all():
            if row.value_text not in valid_slugs:
                count += 1

        # value_json (multi_select)
        stmt_json = select(value_model).where(
            value_model.property_id == defn_id,
            value_model.value_json.is_not(None),
        )
        result = await session.exec(stmt_json)
        for row in result.all():
            payload = row.value_json or []
            if any(slug not in valid_slugs for slug in payload):
                count += 1

    return count


async def any_values_exist_for_definition(
    session: AsyncSession,
    defn_id: int,
) -> bool:
    """Return True if any document or task currently has this property set."""
    for value_model in (DocumentPropertyValue, TaskPropertyValue):
        stmt = select(value_model).where(value_model.property_id == defn_id).limit(1)
        result = await session.exec(stmt)
        if result.first() is not None:
            return True
    return False


def typed_column_for_property(
    value_model: Any,
    property_type: PropertyType,
) -> Any:
    """Return the SA column on ``value_model`` used for the given type.

    Used by list filter builders to compile a typed-column predicate for
    property_values subqueries (see ``build_property_value_predicate``).
    """
    if property_type in {PropertyType.text, PropertyType.url, PropertyType.select}:
        return value_model.value_text
    if property_type is PropertyType.number:
        return value_model.value_number
    if property_type is PropertyType.checkbox:
        return value_model.value_boolean
    if property_type is PropertyType.date:
        return value_model.value_date
    if property_type is PropertyType.datetime:
        return value_model.value_datetime
    if property_type is PropertyType.user_reference:
        return value_model.value_user_id
    if property_type is PropertyType.multi_select:
        return value_model.value_json
    raise ValueError(f"Unsupported property type: {property_type!r}")


def _coerce_filter_scalar(property_type: PropertyType, raw: Any) -> Any:
    """Coerce a raw filter value to the Python type matching the column.

    Filter values arrive as JSON scalars (string / number / bool). Postgres
    refuses to compare a DATE column to a VARCHAR literal, so we convert
    before building the predicate. Returns the coerced value on success;
    returns ``None`` when coercion is impossible (the caller skips the
    filter rather than 500-ing on a bad value).
    """
    if raw is None:
        return None
    try:
        if property_type is PropertyType.number:
            if isinstance(raw, bool):
                return None
            if isinstance(raw, Decimal):
                return raw
            if isinstance(raw, (int, float)):
                return Decimal(str(raw))
            if isinstance(raw, str):
                return Decimal(raw.strip())
            return None
        if property_type is PropertyType.checkbox:
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str):
                lowered = raw.strip().lower()
                if lowered in {"true", "1", "yes"}:
                    return True
                if lowered in {"false", "0", "no"}:
                    return False
            return None
        if property_type is PropertyType.date:
            if isinstance(raw, datetime):
                return raw.date()
            if isinstance(raw, date):
                return raw
            if isinstance(raw, str):
                return date.fromisoformat(raw.strip())
            return None
        if property_type is PropertyType.datetime:
            if isinstance(raw, datetime):
                return raw
            if isinstance(raw, str):
                return datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
            return None
        if property_type is PropertyType.user_reference:
            if isinstance(raw, bool):
                return None
            if isinstance(raw, int):
                return raw
            if isinstance(raw, str):
                return int(raw.strip())
            return None
        # text, url, select — use raw string comparison.
        if isinstance(raw, str):
            return raw
        return str(raw)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _coerce_filter_value(property_type: PropertyType, op: Any, raw: Any) -> Any:
    """Coerce either a scalar or a list (for ``in_``) for a typed column."""
    from app.schemas.query import FilterOp  # noqa: WPS433 - local to avoid cycles

    if op == FilterOp.in_:
        if not isinstance(raw, (list, tuple)):
            return None
        coerced = [_coerce_filter_scalar(property_type, entry) for entry in raw]
        coerced = [c for c in coerced if c is not None]
        return coerced or None
    if op == FilterOp.ilike:
        # ilike only applies to text-like columns; keep the string as-is.
        return raw if isinstance(raw, str) else None
    return _coerce_filter_scalar(property_type, raw)


def build_property_value_predicate(
    column: Any,
    property_type: PropertyType,
    op: Any,
    value: Any,
) -> Any:
    """Build a single WHERE clause on a property-value typed column.

    ``op`` is a :class:`app.schemas.query.FilterOp`. For ``multi_select``
    the predicate uses the JSONB containment operator so that a value of
    ``["alpha"]`` matches rows whose ``value_json`` array contains that
    slug. All other types use the generic column comparisons after
    coercing ``value`` to the Python type that matches the typed column
    (see :func:`_coerce_filter_value`).

    Callers must handle :attr:`FilterOp.is_null` separately via
    :func:`property_value_presence_predicate` — "empty" needs to match
    entities that lack a row entirely, not just rows with a null value.
    """
    # Import locally to avoid circular dependency: query.py depends on
    # nothing app-specific but this service module is imported from
    # endpoints that also depend on query.py.
    from app.schemas.query import FilterOp  # noqa: WPS433 - intentional local import

    if op == FilterOp.is_null:
        # Presence vs. absence needs the parent-entity id column to
        # compose a NOT IN / IN subquery — delegate to
        # ``property_value_presence_predicate``.
        return None

    if property_type is PropertyType.multi_select:
        # Only ``contains-any`` semantics are meaningful for multi_select.
        # Coerce the incoming value into a JSONB array literal. Accept
        # either a single slug or a list of slugs.
        if isinstance(value, (list, tuple)):
            payload = [entry for entry in value if isinstance(entry, str)]
        elif isinstance(value, str):
            payload = [value]
        else:
            payload = []
        if not payload:
            return None
        return column.op("@>")(payload)

    coerced = _coerce_filter_value(property_type, op, value)
    if coerced is None:
        return None

    if op == FilterOp.eq:
        return column == coerced
    if op == FilterOp.lt:
        return column < coerced
    if op == FilterOp.lte:
        return column <= coerced
    if op == FilterOp.gt:
        return column > coerced
    if op == FilterOp.gte:
        return column >= coerced
    if op == FilterOp.in_:
        return column.in_(tuple(coerced))
    if op == FilterOp.ilike:
        return column.ilike(f"%{coerced}%")
    return None


def property_value_presence_predicate(
    value_model: Any,
    parent_id_column: Any,
    entity_id_column: Any,
    property_id: int,
    property_type: PropertyType,
    is_empty: bool,
) -> Any:
    """Build an IN / NOT IN subquery matching presence of a property value.

    - ``is_empty=True`` → match entities that either have no row in the
      value table OR have a row where the typed column is NULL
      (multi_select: empty / null JSON array).
    - ``is_empty=False`` → match entities that have a row with a
      non-empty value.

    ``parent_id_column`` is ``Task.id`` / ``Document.id``;
    ``entity_id_column`` is ``TaskPropertyValue.task_id`` /
    ``DocumentPropertyValue.document_id``.
    """
    typed = typed_column_for_property(value_model, property_type)
    non_empty = typed.is_not(None)
    if property_type is PropertyType.multi_select:
        # Treat a stored empty array as "empty" too, so the filter
        # behaves the same way as the UI does for multi-selects.
        non_empty = typed.is_not(None) & (func.jsonb_array_length(typed) > 0)

    subq = (
        select(entity_id_column)
        .where(value_model.property_id == property_id, non_empty)
    )
    if is_empty:
        return parent_id_column.not_in(subq)
    return parent_id_column.in_(subq)


class ParsedPropertyFilter:
    """A single decoded property filter condition.

    Kept as a plain dataclass-like object to avoid pulling Pydantic into
    the hot path — these are ephemeral parser outputs.
    """

    __slots__ = ("property_id", "op", "value")

    def __init__(self, property_id: int, op: Any, value: Any) -> None:
        self.property_id = property_id
        self.op = op
        self.value = value


def parse_property_filters(raw: Optional[str]) -> List[ParsedPropertyFilter]:
    """Parse the ``property_filters`` query param into validated conditions.

    Raises :class:`ValueError` on malformed input (caller converts to 400).
    Returns an empty list when ``raw`` is falsy. Caps the number of
    predicates at :data:`MAX_PROPERTY_FILTERS`.
    """
    import json

    from app.schemas.query import FilterOp  # noqa: WPS433 - local to avoid cycles

    if not raw:
        return []

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("property_filters is not valid JSON") from exc

    if not isinstance(payload, list):
        raise ValueError("property_filters must be a JSON array")

    if len(payload) > MAX_PROPERTY_FILTERS:
        raise ValueError(
            f"too many property filters (max {MAX_PROPERTY_FILTERS})"
        )

    parsed: List[ParsedPropertyFilter] = []
    for entry in payload:
        if not isinstance(entry, dict):
            raise ValueError("each property filter must be an object")
        pid_raw = entry.get("property_id")
        op_raw = entry.get("op", "eq")
        value = entry.get("value")
        try:
            pid = int(pid_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("property_id must be an integer") from exc
        try:
            op = FilterOp(op_raw)
        except ValueError as exc:
            raise ValueError(f"unknown filter op: {op_raw!r}") from exc
        parsed.append(ParsedPropertyFilter(property_id=pid, op=op, value=value))
    return parsed


async def load_definitions_by_ids(
    session: AsyncSession,
    definition_ids: Iterable[int],
    *,
    guild_id: int,
) -> Dict[int, PropertyDefinition]:
    """Load property definitions for a guild keyed by id.

    Used by list filters so the endpoint can resolve the correct typed
    column per condition without issuing one query per condition.
    """
    ids = list({did for did in definition_ids if did is not None})
    if not ids:
        return {}
    stmt = select(PropertyDefinition).where(
        PropertyDefinition.id.in_(ids),
        PropertyDefinition.guild_id == guild_id,
    )
    result = await session.exec(stmt)
    return {defn.id: defn for defn in result.all()}

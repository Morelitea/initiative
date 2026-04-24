"""
Unit tests for the properties service layer.

Focus areas:
- ``_validate_value_for_type`` — per-type coercion and rejection
- ``parse_property_filters`` — JSON-param parser
"""

from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.models.property import PropertyDefinition, PropertyType
from app.schemas.query import FilterOp
from app.services.properties import (
    MAX_PROPERTY_FILTERS,
    _validate_value_for_type,
    parse_property_filters,
)
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_user,
)


def _make_definition(
    type: PropertyType,
    *,
    options: list[dict] | None = None,
    initiative_id: int = 1,
) -> PropertyDefinition:
    """Build a non-persisted PropertyDefinition for pure-function tests."""
    defn = PropertyDefinition(
        initiative_id=initiative_id,
        name="Prop",
        type=type,
    )
    if options is not None:
        defn.options = options
    return defn


# ---------------------------------------------------------------------------
# _validate_value_for_type — text
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.service
async def test_validate_text_accepts_string(session: AsyncSession):
    defn = _make_definition(PropertyType.text)
    cols = await _validate_value_for_type(session, defn, "hello", initiative_id=1)
    assert cols["value_text"] == "hello"
    assert cols["value_number"] is None


@pytest.mark.unit
@pytest.mark.service
async def test_validate_text_rejects_non_string(session: AsyncSession):
    defn = _make_definition(PropertyType.text)
    with pytest.raises(HTTPException) as exc_info:
        await _validate_value_for_type(session, defn, 123, initiative_id=1)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "PROPERTY_INVALID_VALUE_FOR_TYPE"


# ---------------------------------------------------------------------------
# number
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.service
async def test_validate_number_accepts_int_float_and_string(
    session: AsyncSession,
):
    defn = _make_definition(PropertyType.number)

    cols_int = await _validate_value_for_type(session, defn, 10, initiative_id=1)
    assert cols_int["value_number"] == Decimal("10")

    cols_float = await _validate_value_for_type(session, defn, 2.5, initiative_id=1)
    assert cols_float["value_number"] == Decimal("2.5")

    cols_str = await _validate_value_for_type(session, defn, "42.0", initiative_id=1)
    assert cols_str["value_number"] == Decimal("42.0")


@pytest.mark.unit
@pytest.mark.service
async def test_validate_number_rejects_non_numeric(session: AsyncSession):
    defn = _make_definition(PropertyType.number)
    with pytest.raises(HTTPException) as exc_info:
        await _validate_value_for_type(session, defn, "abc", initiative_id=1)
    assert exc_info.value.detail == "PROPERTY_INVALID_VALUE_FOR_TYPE"


# ---------------------------------------------------------------------------
# checkbox
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.service
async def test_validate_checkbox_accepts_bool(session: AsyncSession):
    defn = _make_definition(PropertyType.checkbox)
    cols = await _validate_value_for_type(session, defn, True, initiative_id=1)
    assert cols["value_boolean"] is True


@pytest.mark.unit
@pytest.mark.service
async def test_validate_checkbox_rejects_non_bool(session: AsyncSession):
    """The current impl is strict: only bools pass (no string coercion)."""
    defn = _make_definition(PropertyType.checkbox)
    for bad in ("true", "false", 1, 0, "garbage"):
        with pytest.raises(HTTPException):
            await _validate_value_for_type(session, defn, bad, initiative_id=1)


# ---------------------------------------------------------------------------
# date
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.service
async def test_validate_date_accepts_iso_string(session: AsyncSession):
    defn = _make_definition(PropertyType.date)
    cols = await _validate_value_for_type(session, defn, "2026-04-22", initiative_id=1)
    assert cols["value_date"] == date(2026, 4, 22)


@pytest.mark.unit
@pytest.mark.service
async def test_validate_date_rejects_malformed(session: AsyncSession):
    defn = _make_definition(PropertyType.date)
    with pytest.raises(HTTPException):
        await _validate_value_for_type(session, defn, "notadate", initiative_id=1)


# ---------------------------------------------------------------------------
# datetime
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.service
async def test_validate_datetime_accepts_iso_with_tz(session: AsyncSession):
    defn = _make_definition(PropertyType.datetime)
    cols = await _validate_value_for_type(
        session, defn, "2026-04-22T10:00:00+00:00", initiative_id=1
    )
    assert isinstance(cols["value_datetime"], datetime)
    assert cols["value_datetime"].tzinfo is not None


@pytest.mark.unit
@pytest.mark.service
async def test_validate_datetime_rejects_malformed(session: AsyncSession):
    defn = _make_definition(PropertyType.datetime)
    with pytest.raises(HTTPException):
        await _validate_value_for_type(session, defn, "notadatetime", initiative_id=1)


# ---------------------------------------------------------------------------
# url
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.service
async def test_validate_url_accepts_http_https(session: AsyncSession):
    defn = _make_definition(PropertyType.url)

    for ok_url in ("https://example.com", "http://example.com/path?q=1"):
        cols = await _validate_value_for_type(session, defn, ok_url, initiative_id=1)
        assert cols["value_text"] == ok_url


@pytest.mark.unit
@pytest.mark.service
async def test_validate_url_rejects_invalid(session: AsyncSession):
    defn = _make_definition(PropertyType.url)
    for bad in ("ftp://example.com", "not a url"):
        with pytest.raises(HTTPException):
            await _validate_value_for_type(session, defn, bad, initiative_id=1)


@pytest.mark.unit
@pytest.mark.service
async def test_validate_empty_values_are_attached_but_empty(session: AsyncSession):
    """``None``, blank strings, and empty lists yield all-None columns.

    This lets a user attach a property definition to a doc/task without
    supplying a value (the "is empty" filter then matches the row).
    """
    text_defn = _make_definition(PropertyType.text)
    url_defn = _make_definition(PropertyType.url)
    multi_defn = _make_definition(
        PropertyType.multi_select,
        options=[{"value": "a", "label": "A"}],
    )

    for defn, empty in (
        (text_defn, None),
        (text_defn, ""),
        (text_defn, "   "),
        (url_defn, None),
        (url_defn, ""),
        (multi_defn, None),
        (multi_defn, []),
    ):
        cols = await _validate_value_for_type(session, defn, empty, initiative_id=1)
        assert cols["value_text"] is None
        assert cols["value_number"] is None
        assert cols["value_boolean"] is None
        assert cols["value_user_id"] is None
        assert cols["value_json"] is None


# ---------------------------------------------------------------------------
# select
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.service
async def test_validate_select_slug_in_options(session: AsyncSession):
    defn = _make_definition(
        PropertyType.select,
        options=[{"value": "live", "label": "Live"}],
    )
    cols = await _validate_value_for_type(session, defn, "live", initiative_id=1)
    assert cols["value_text"] == "live"


@pytest.mark.unit
@pytest.mark.service
async def test_validate_select_rejects_unknown_slug(session: AsyncSession):
    defn = _make_definition(
        PropertyType.select,
        options=[{"value": "live", "label": "Live"}],
    )
    with pytest.raises(HTTPException) as exc_info:
        await _validate_value_for_type(session, defn, "ghost", initiative_id=1)
    assert exc_info.value.detail == "PROPERTY_OPTION_NOT_IN_DEFINITION"


# ---------------------------------------------------------------------------
# multi_select
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.service
async def test_validate_multi_select_all_slugs_valid_and_deduped(
    session: AsyncSession,
):
    defn = _make_definition(
        PropertyType.multi_select,
        options=[
            {"value": "a", "label": "A"},
            {"value": "b", "label": "B"},
        ],
    )
    cols = await _validate_value_for_type(
        session, defn, ["a", "b", "a"], initiative_id=1
    )
    assert cols["value_json"] == ["a", "b"]


@pytest.mark.unit
@pytest.mark.service
async def test_validate_multi_select_rejects_unknown_slug(
    session: AsyncSession,
):
    defn = _make_definition(
        PropertyType.multi_select,
        options=[{"value": "a", "label": "A"}],
    )
    with pytest.raises(HTTPException) as exc_info:
        await _validate_value_for_type(session, defn, ["a", "nope"], initiative_id=1)
    assert exc_info.value.detail == "PROPERTY_OPTION_NOT_IN_DEFINITION"


# ---------------------------------------------------------------------------
# user_reference
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.service
async def test_validate_user_reference_accepts_initiative_member(
    session: AsyncSession,
):
    user = await create_user(session, email="member@example.com")
    guild = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild, role=GuildRole.member
    )
    initiative = await create_initiative(session, guild, user, name="Init")

    defn = _make_definition(PropertyType.user_reference, initiative_id=initiative.id)
    cols = await _validate_value_for_type(
        session, defn, user.id, initiative_id=initiative.id
    )
    assert cols["value_user_id"] == user.id


@pytest.mark.unit
@pytest.mark.service
async def test_validate_user_reference_rejects_non_member(
    session: AsyncSession,
):
    member = await create_user(session, email="member@example.com")
    outsider = await create_user(session, email="outsider@example.com")
    guild = await create_guild(session, creator=member)
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.admin
    )
    # Outsider IS in the guild, but NOT in the initiative.
    await create_guild_membership(
        session, user=outsider, guild=guild, role=GuildRole.member
    )
    initiative = await create_initiative(session, guild, member, name="Init")

    defn = _make_definition(PropertyType.user_reference, initiative_id=initiative.id)
    with pytest.raises(HTTPException) as exc_info:
        await _validate_value_for_type(
            session, defn, outsider.id, initiative_id=initiative.id
        )
    assert exc_info.value.detail == "PROPERTY_USER_NOT_IN_INITIATIVE"


@pytest.mark.unit
@pytest.mark.service
async def test_validate_user_reference_accepts_explicit_initiative_member(
    session: AsyncSession,
):
    """Adding a user as an InitiativeMember lets user_reference resolve."""
    pm = await create_user(session, email="pm@example.com")
    teammate = await create_user(session, email="teammate@example.com")
    guild = await create_guild(session, creator=pm)
    await create_guild_membership(session, user=pm, guild=guild, role=GuildRole.admin)
    await create_guild_membership(
        session, user=teammate, guild=guild, role=GuildRole.member
    )
    initiative = await create_initiative(session, guild, pm, name="Init")
    await create_initiative_member(session, initiative, teammate, role_name="member")

    defn = _make_definition(PropertyType.user_reference, initiative_id=initiative.id)
    cols = await _validate_value_for_type(
        session, defn, teammate.id, initiative_id=initiative.id
    )
    assert cols["value_user_id"] == teammate.id


@pytest.mark.unit
@pytest.mark.service
async def test_validate_user_reference_rejects_non_int(session: AsyncSession):
    defn = _make_definition(PropertyType.user_reference, initiative_id=1)
    with pytest.raises(HTTPException):
        await _validate_value_for_type(session, defn, "1", initiative_id=1)


# ---------------------------------------------------------------------------
# parse_property_filters
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_property_filters_empty_input_returns_empty_list():
    assert parse_property_filters(None) == []
    assert parse_property_filters("") == []


@pytest.mark.unit
def test_parse_property_filters_well_formed_input():
    raw = '[{"property_id": 5, "op": "eq", "value": "x"}]'
    parsed = parse_property_filters(raw)
    assert len(parsed) == 1
    assert parsed[0].property_id == 5
    assert parsed[0].op == FilterOp.eq
    assert parsed[0].value == "x"


@pytest.mark.unit
def test_parse_property_filters_invalid_json_raises():
    with pytest.raises(ValueError):
        parse_property_filters("not-json")


@pytest.mark.unit
def test_parse_property_filters_caps_at_max():
    raw = "[" + ",".join(
        f'{{"property_id": {i}, "op": "eq", "value": 1}}'
        for i in range(MAX_PROPERTY_FILTERS + 1)
    ) + "]"
    with pytest.raises(ValueError):
        parse_property_filters(raw)


@pytest.mark.unit
def test_parse_property_filters_missing_property_id_raises():
    with pytest.raises(ValueError):
        parse_property_filters('[{"op": "eq", "value": "x"}]')


@pytest.mark.unit
def test_parse_property_filters_unknown_op_raises():
    with pytest.raises(ValueError):
        parse_property_filters('[{"property_id": 1, "op": "weird", "value": "x"}]')


@pytest.mark.unit
def test_parse_property_filters_defaults_op_to_eq():
    """op defaults to ``eq`` when omitted."""
    parsed = parse_property_filters('[{"property_id": 1, "value": "x"}]')
    assert parsed[0].op == FilterOp.eq


@pytest.mark.unit
def test_parse_property_filters_is_null_defaults_value_to_true():
    """Omitting ``value`` on an is_null filter means "is empty" (True)."""
    parsed = parse_property_filters('[{"property_id": 1, "op": "is_null"}]')
    assert parsed[0].op == FilterOp.is_null
    assert parsed[0].value is True


@pytest.mark.unit
def test_parse_property_filters_is_null_preserves_explicit_booleans():
    parsed_true = parse_property_filters(
        '[{"property_id": 1, "op": "is_null", "value": true}]'
    )
    parsed_false = parse_property_filters(
        '[{"property_id": 1, "op": "is_null", "value": false}]'
    )
    assert parsed_true[0].value is True
    assert parsed_false[0].value is False


@pytest.mark.unit
def test_parse_property_filters_is_null_rejects_non_bool_value():
    """Non-bool values on is_null raise rather than silently coerce."""
    with pytest.raises(ValueError, match="must be a boolean"):
        parse_property_filters('[{"property_id": 1, "op": "is_null", "value": "yes"}]')
    with pytest.raises(ValueError, match="must be a boolean"):
        parse_property_filters('[{"property_id": 1, "op": "is_null", "value": 1}]')

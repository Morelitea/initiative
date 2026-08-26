"""Tests for SanitizedBaseModel."""

from __future__ import annotations

import importlib
import pkgutil
from enum import Enum
from typing import Optional

import pytest
from pydantic import BaseModel, ValidationError

import app.schemas as schemas_pkg
from app.schemas.base import (
    MAX_PLAIN_TEXT_LENGTH,
    RawTextStr,
    RichTextStr,
    SanitizedBaseModel,
)


class _Color(str, Enum):
    red = "red"
    blue = "blue"


class _Model(SanitizedBaseModel):
    name: str
    bio: Optional[str] = None
    rich: RichTextStr = ""
    rich_opt: Optional[RichTextStr] = None
    raw: RawTextStr = ""
    raw_opt: Optional[RawTextStr] = None
    count: int = 0
    enabled: bool = False
    color: _Color = _Color.red


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Markup goes, the text inside it stays.
        ("<script>alert(1)</script>hello", "hello"),
        ("<b>bold</b>", "bold"),
        ("before <img src=x onerror=alert(1)> after", "before  after"),
        # Benign characters survive verbatim rather than being entity-encoded
        # (an encoder here renders "&amp;" literally on screen).
        ("Death House Encounter & Planning", "Death House Encounter & Planning"),
        ('5 < 3 is false; she said "hi"', '5 < 3 is false; she said "hi"'),
        ("plain text without html", "plain text without html"),
        # Entities decode to their characters, still as text.
        ("5 &lt; 3 &amp; 2 &gt; 1", "5 < 3 & 2 > 1"),
    ],
)
def test_plain_text_keeps_the_text_and_drops_the_markup(
    raw: str, expected: str
) -> None:
    assert _Model(name=raw).name == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "absent"),
    [
        ("before &lt;img src=x onerror=alert(1)&gt; after", ["<img", "onerror"]),
        (
            "&amp;lt;script&amp;gt;alert(1)&amp;lt;/script&amp;gt;",
            ["<script", "alert(1)"],
        ),
        ('<a href="javascript:bad()">link</a>', ["javascript:"]),
    ],
)
def test_encoded_markup_is_not_turned_back_into_markup(
    raw: str, absent: list[str]
) -> None:
    """Decoding happens before stripping, and once — so nothing that arrives
    encoded (or double-encoded) comes back out live."""
    cleaned = _Model(name=raw).name
    for fragment in absent:
        assert fragment not in cleaned


@pytest.mark.unit
@pytest.mark.parametrize("field", ["rich", "raw", "rich_opt", "raw_opt"])
def test_opted_out_fields_keep_their_markup(field: str) -> None:
    """The opt-out marker is honoured on the field itself and when it is nested
    inside ``Optional[...]``, where field metadata alone does not show it."""
    raw = "<script>alert(1)</script><b>x</b> & < >"
    assert getattr(_Model(name="x", **{field: raw}), field) == raw


@pytest.mark.unit
def test_enum_field_not_modified() -> None:
    # Enums should never be coerced through nh3.clean.
    m = _Model(name="x", color=_Color.blue)
    assert m.color is _Color.blue

    # Same goes for string-form enum values.
    m2 = _Model(name="x", color="red")
    assert m2.color is _Color.red


@pytest.mark.unit
def test_non_str_fields_not_modified() -> None:
    m = _Model(name="x", count=42, enabled=True)
    assert m.count == 42
    assert m.enabled is True


@pytest.mark.unit
def test_optional_str_sanitized_when_present() -> None:
    m = _Model(name="x", bio="<script>x</script>safe")
    assert m.bio == "safe"


@pytest.mark.unit
def test_optional_str_none_passes_through() -> None:
    m = _Model(name="x", bio=None)
    assert m.bio is None


@pytest.mark.unit
def test_plain_text_over_max_length_rejected() -> None:
    with pytest.raises(ValidationError):
        _Model(name="x" * (MAX_PLAIN_TEXT_LENGTH + 1))


@pytest.mark.unit
def test_plain_text_at_max_length_allowed() -> None:
    m = _Model(name="x" * MAX_PLAIN_TEXT_LENGTH)
    assert len(m.name) == MAX_PLAIN_TEXT_LENGTH


@pytest.mark.unit
def test_raw_text_field_exempt_from_length_cap() -> None:
    big = "A" * (MAX_PLAIN_TEXT_LENGTH + 5000)
    m = _Model(name="ok", raw=big)
    assert m.raw == big


@pytest.mark.unit
def test_every_schema_extends_sanitized_base() -> None:
    """Lint: every Pydantic class in app.schemas must extend SanitizedBaseModel.

    Catches the case where a new schema is added that inherits directly from
    pydantic.BaseModel, silently bypassing HTML sanitization on its str fields.
    """
    offenders: list[str] = []
    for module_info in pkgutil.iter_modules(schemas_pkg.__path__):
        if module_info.name.endswith("_test"):
            continue
        module = importlib.import_module(f"app.schemas.{module_info.name}")
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if not isinstance(attr, type):
                continue
            if attr is BaseModel or attr is SanitizedBaseModel:
                continue
            if not issubclass(attr, BaseModel):
                continue
            # Skip classes re-exported from elsewhere.
            if not attr.__module__.startswith("app.schemas"):
                continue
            if not issubclass(attr, SanitizedBaseModel):
                offenders.append(f"{attr.__module__}.{attr.__name__}")
    assert not offenders, (
        "These Pydantic classes in app.schemas do not extend SanitizedBaseModel:\n"
        + "\n".join(f"  - {o}" for o in offenders)
        + "\n\nInherit from SanitizedBaseModel (app.schemas.base) instead of"
        " BaseModel so str fields are HTML-sanitized by default."
    )

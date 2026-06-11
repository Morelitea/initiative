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
def test_strips_script_tags() -> None:
    m = _Model(name="<script>alert(1)</script>hello")
    assert "<script>" not in m.name
    assert "alert(1)" not in m.name
    assert m.name == "hello"


@pytest.mark.unit
def test_strips_tags_from_plain_text() -> None:
    # Plain-text fields keep no markup at all: tags are removed, inner text kept.
    m = _Model(name="<b>bold</b>")
    assert m.name == "bold"


@pytest.mark.unit
def test_ampersand_not_html_encoded() -> None:
    # Regression: the HTML *encoder* (nh3.clean) used to store "Foo &amp; Bar",
    # which then rendered literally on screen. Benign chars must survive verbatim.
    m = _Model(name="Death House Encounter & Planning")
    assert m.name == "Death House Encounter & Planning"


@pytest.mark.unit
def test_angle_brackets_and_quotes_in_text_preserved() -> None:
    # Lone < / > / " that aren't part of a tag are real text, not markup.
    m = _Model(name='5 < 3 is false; she said "hi"')
    assert m.name == '5 < 3 is false; she said "hi"'


@pytest.mark.unit
def test_img_onerror_payload_fully_stripped() -> None:
    # The original CRIT-002 demonstrator. nh3's default allowlist would KEEP
    # <img src="x"> (dropping only onerror); an empty allowlist removes it wholly.
    m = _Model(name="before <img src=x onerror=alert(1)> after")
    assert "onerror" not in m.name
    assert "<img" not in m.name
    assert m.name == "before  after"


@pytest.mark.unit
def test_entity_encoded_img_payload_is_not_revived() -> None:
    # Regression: an *entity-encoded* payload must not be unescaped back into
    # live markup. A naive unescape-after-strip stored a raw "<img onerror=...>"
    # because nh3.clean saw the entities as inert text and skipped them.
    m = _Model(name="before &lt;img src=x onerror=alert(1)&gt; after")
    assert "<img" not in m.name
    assert "onerror" not in m.name


@pytest.mark.unit
def test_double_entity_encoded_payload_is_not_revived() -> None:
    # Even markup encoded twice (&amp;lt;) must be collapsed and stripped.
    m = _Model(name="&amp;lt;script&amp;gt;alert(1)&amp;lt;/script&amp;gt;")
    assert "<script" not in m.name
    assert "alert(1)" not in m.name


@pytest.mark.unit
def test_entity_encoded_benign_text_round_trips() -> None:
    # Decoding must still leave benign characters literal, not re-mangled.
    m = _Model(name="5 &lt; 3 &amp; 2 &gt; 1")
    assert m.name == "5 < 3 & 2 > 1"


@pytest.mark.unit
def test_rich_text_preserves_script() -> None:
    raw = "<script>alert(1)</script>hello"
    m = _Model(name="x", rich=raw)
    assert m.rich == raw


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
def test_plain_text_passes_through() -> None:
    m = _Model(name="plain text without html")
    assert m.name == "plain text without html"


@pytest.mark.unit
def test_optional_str_sanitized_when_present() -> None:
    m = _Model(name="x", bio="<script>x</script>safe")
    assert m.bio == "safe"


@pytest.mark.unit
def test_optional_str_none_passes_through() -> None:
    m = _Model(name="x", bio=None)
    assert m.bio is None


@pytest.mark.unit
def test_javascript_url_stripped() -> None:
    m = _Model(name='<a href="javascript:bad()">link</a>')
    assert "javascript:" not in m.name


@pytest.mark.unit
def test_raw_text_field_preserves_markup() -> None:
    raw = "<script>alert(1)</script><b>x</b> & < >"
    m = _Model(name="x", raw=raw)
    assert m.raw == raw


@pytest.mark.unit
def test_optional_raw_text_opts_out() -> None:
    # The opt-out marker must be detected even nested inside Optional[...].
    raw = "<img src=x onerror=alert(1)> & data"
    m = _Model(name="x", raw_opt=raw)
    assert m.raw_opt == raw


@pytest.mark.unit
def test_optional_rich_text_opts_out() -> None:
    # Regression: Optional[RichTextStr] used to be silently stripped because the
    # marker was nested in the Optional union and invisible to field metadata.
    raw = "<script>alert(1)</script>hello"
    m = _Model(name="x", rich_opt=raw)
    assert m.rich_opt == raw


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

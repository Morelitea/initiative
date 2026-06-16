"""Unit tests for user schema validation, focused on the avatar_base64 cap.

``avatar_base64`` is a ``RawTextStr`` so it skips the global 8 KiB plain-text
cap (it holds an inline image data URI, not free text). Left unbounded it is a
stored-amplification vector echoed to every guild member via presence — SEC-12
adds an explicit ``max_length`` while keeping the field raw (never HTML-mangled).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.user import (
    MAX_AVATAR_BASE64_LENGTH,
    UserSelfUpdate,
    UserUpdate,
)


def _data_uri(payload_len: int) -> str:
    return "data:image/png;base64," + ("A" * payload_len)


@pytest.mark.unit
def test_avatar_base64_within_cap_accepted_on_self_update() -> None:
    value = _data_uri(1000)
    model = UserSelfUpdate(avatar_base64=value)
    # RawTextStr — the value must be preserved verbatim (no HTML entity mangling).
    assert model.avatar_base64 == value


@pytest.mark.unit
def test_avatar_base64_at_cap_boundary_accepted() -> None:
    value = "x" * MAX_AVATAR_BASE64_LENGTH
    model = UserSelfUpdate(avatar_base64=value)
    assert model.avatar_base64 == value


@pytest.mark.unit
def test_avatar_base64_over_cap_rejected_on_self_update() -> None:
    value = "x" * (MAX_AVATAR_BASE64_LENGTH + 1)
    with pytest.raises(ValidationError):
        UserSelfUpdate(avatar_base64=value)


@pytest.mark.unit
def test_avatar_base64_over_cap_rejected_on_admin_update() -> None:
    value = "x" * (MAX_AVATAR_BASE64_LENGTH + 1)
    with pytest.raises(ValidationError):
        UserUpdate(avatar_base64=value)


@pytest.mark.unit
def test_avatar_base64_not_html_entity_mangled() -> None:
    # A literal ``&`` in the (degenerate) value must survive — the field must
    # stay RawTextStr, not be routed through the plain-text sanitizer.
    value = "data:image/svg+xml;base64,AA&BB"
    model = UserSelfUpdate(avatar_base64=value)
    assert model.avatar_base64 == value


@pytest.mark.unit
def test_avatar_base64_none_passes_through() -> None:
    assert UserSelfUpdate(avatar_base64=None).avatar_base64 is None

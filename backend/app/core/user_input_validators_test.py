import pytest
from fastapi import HTTPException

from app.core.messages import CommonMessages
from app.core.user_input_validators import (
    NEXT_PATH_MAX_LENGTH,
    is_safe_next_path,
    normalize_timezone,
    resolve_zone,
)


@pytest.mark.parametrize(
    "value", [None, "", "Not/AZone", "America", "../../etc/passwd", "a\x00b"]
)
def test_a_stored_zone_that_names_none_resolves_to_utc(value: str | None):
    assert resolve_zone(value).key == "UTC"


def test_a_stored_zone_resolves_to_itself():
    assert resolve_zone("Europe/Berlin").key == "Europe/Berlin"


def test_a_requested_zone_is_trimmed_and_blank_is_none():
    assert normalize_timezone("  Pacific/Auckland ") == "Pacific/Auckland"
    assert normalize_timezone("UTC") == "UTC"
    assert normalize_timezone(None) is None
    assert normalize_timezone("   ") is None


@pytest.mark.parametrize("value", ["Not/AZone", "America", "../../etc/passwd", "utc"])
def test_a_requested_zone_that_names_none_is_refused(value: str):
    with pytest.raises(HTTPException) as exc:
        normalize_timezone(value)
    assert exc.value.status_code == 400
    assert exc.value.detail == CommonMessages.UNKNOWN_TIMEZONE


@pytest.mark.parametrize(
    "value",
    [
        "/",
        "/c/5/projects/3",
        "/settings?tab=auth",
        "/c/5/documents/7#section",
    ],
)
def test_safe_next_paths_accepted(value: str):
    assert is_safe_next_path(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "relative/path",
        "//evil.example",
        "https://evil.example/x",
        "http://evil.example/x",
        "/a\\b",
        "\\\\evil.example",
        "/a\x00b",
        "/a\nb",
        "/" + "x" * NEXT_PATH_MAX_LENGTH,
    ],
)
def test_unsafe_next_paths_rejected(value: str):
    assert not is_safe_next_path(value)

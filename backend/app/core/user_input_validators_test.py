import pytest

from app.core.user_input_validators import NEXT_PATH_MAX_LENGTH, is_safe_next_path

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "value",
    [
        "/",
        "/g/5/projects/3",
        "/settings?tab=auth",
        "/g/5/documents/7#section",
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

"""What a user agent is shown as in the account's own session list."""

import pytest

from app.core.user_agents import ClientKind, describe, kind_of

CHROME_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
SAFARI_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)
EDGE_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0"
)
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"


@pytest.mark.parametrize(
    ("agent", "expected"),
    [
        (CHROME_MAC, "Chrome on macOS"),
        (SAFARI_IPHONE, "Safari on iPhone"),
        (FIREFOX_LINUX, "Firefox on Linux"),
    ],
)
def test_a_browser_reads_as_itself_and_its_platform(agent, expected):
    assert describe(agent) == expected


def test_a_derivative_is_not_read_as_the_engine_it_is_built_on():
    """Edge, Opera and the rest all carry ``Chrome`` in their agent, so the
    order the markers are read in is what keeps them apart."""
    assert describe(EDGE_WINDOWS) == "Edge on Windows"


@pytest.mark.parametrize(
    ("agent", "expected"),
    [
        (CHROME_MAC, ClientKind.desktop),
        (EDGE_WINDOWS, ClientKind.desktop),
        (FIREFOX_LINUX, ClientKind.desktop),
        (SAFARI_IPHONE, ClientKind.mobile),
        ("Mozilla/5.0 (Linux; Android 14; Pixel 8) Chrome/140.0", ClientKind.mobile),
        (None, ClientKind.unknown),
        ("curl/8.7.1", ClientKind.unknown),
    ],
)
def test_which_picture_to_draw(agent, expected):
    assert kind_of(agent) is expected


def test_an_android_agent_is_not_read_as_linux():
    """Android says ``Linux`` too, and answering with the wrong one would draw
    a computer beside somebody's phone."""
    assert describe("Mozilla/5.0 (Linux; Android 14; Pixel 8) Chrome/140.0") == (
        "Chrome on Android"
    )


def test_nothing_to_read_is_nothing_rather_than_a_guess():
    assert describe(None) is None
    assert describe("") is None
    assert describe("   ") is None


def test_an_unfamiliar_agent_keeps_itself():
    """More use in a list than "Unknown device", and cut so one long header
    cannot stretch the row it is drawn in."""
    assert describe("curl/8.7.1") == "curl/8.7.1"
    assert len(describe("x" * 500) or "") == 60

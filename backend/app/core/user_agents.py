"""A readable name for the client a session was opened from.

A browser session carries a user agent and nothing else that names it — only
the native app is handed a device label at sign-in. So the "where you're
signed in" list asks here, and gets back the two things it shows: a short
name a person recognises, and whether to draw a phone or a computer.

Deliberately coarse. The point is for somebody to recognise their own laptop
in a list of three, not to identify a build — so this knows the browsers and
platforms people actually read off a screen and says nothing about versions.
An agent it does not recognise keeps its raw string, which is still more use
than "Unknown device".
"""

from __future__ import annotations

from enum import Enum

__all__ = ["ClientKind", "describe", "kind_of"]


class ClientKind(str, Enum):
    """Which picture the list draws beside a session."""

    mobile = "mobile"
    desktop = "desktop"
    unknown = "unknown"


#: Browser markers, most specific first — the derivatives all carry the name of
#: the engine they are built on, so Edge has to be read before Chrome and
#: Chrome before Safari or every one of them comes out as the last entry.
_BROWSERS: tuple[tuple[str, str], ...] = (
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("Vivaldi", "Vivaldi"),
    ("SamsungBrowser", "Samsung Internet"),
    ("Firefox/", "Firefox"),
    ("FxiOS/", "Firefox"),
    ("CriOS/", "Chrome"),
    ("Chromium", "Chromium"),
    ("Chrome/", "Chrome"),
    ("Safari/", "Safari"),
)

#: Platform markers, most specific first: an iPad and an iPhone both say
#: "like Mac OS X", and Android says "Linux".
_PLATFORMS: tuple[tuple[str, str, ClientKind], ...] = (
    ("iPhone", "iPhone", ClientKind.mobile),
    ("iPad", "iPad", ClientKind.mobile),
    ("Android", "Android", ClientKind.mobile),
    ("CrOS", "ChromeOS", ClientKind.desktop),
    ("Windows", "Windows", ClientKind.desktop),
    ("Macintosh", "macOS", ClientKind.desktop),
    ("Mac OS X", "macOS", ClientKind.desktop),
    ("Linux", "Linux", ClientKind.desktop),
)

#: What a raw agent is cut to when nothing is recognised, so one pathological
#: header cannot stretch the row it is drawn in.
_RAW_LIMIT = 60


def _platform(user_agent: str) -> tuple[str | None, ClientKind]:
    for marker, name, kind in _PLATFORMS:
        if marker in user_agent:
            return name, kind
    return None, ClientKind.unknown


def _browser(user_agent: str) -> str | None:
    for marker, name in _BROWSERS:
        if marker in user_agent:
            return name
    return None


def describe(user_agent: str | None) -> str | None:
    """A short name for this client — ``"Chrome on macOS"`` — or ``None``.

    ``None`` where there is no agent to read, which is what the caller shows
    its "unknown device" wording for. An agent that is present but unfamiliar
    comes back as itself, trimmed.
    """
    if not user_agent or not user_agent.strip():
        return None
    agent = user_agent.strip()
    browser = _browser(agent)
    platform, _ = _platform(agent)
    if browser and platform:
        return f"{browser} on {platform}"
    if browser:
        return browser
    if platform:
        return platform
    return agent[:_RAW_LIMIT]


def kind_of(user_agent: str | None) -> ClientKind:
    """Whether this client is a phone or a computer, for the icon beside it."""
    if not user_agent:
        return ClientKind.unknown
    return _platform(user_agent)[1]

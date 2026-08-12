"""The bounded primitives every manifest value passes through.

A manifest arrives from outside this build — a shipped data file today, an
operator upload or a signed registry manifest later — so nothing it carries is
taken on trust. Validation here is *total*: every string has a length cap, every
list has a count cap, every identifier is checked against an explicit character
set, and a key this build does not know is dropped rather than stored. What
comes out has canonical shape, which is what makes a stored definition safe to
copy into a guild's schema and render months later.

The checks are deliberately dull and explicit — an allow-list of characters
rather than a pattern — so what is accepted can be read straight off the page.

One rule shapes the rest: **a listing declares capabilities, it does not supply
addresses.** Anything a service is asked for is a *path*, joined at call time to
a base URL that comes from the deployment's own registration. There is nowhere
in a manifest to put a host, which is why nothing here needs to decide whether a
host is trustworthy.
"""

from __future__ import annotations

import json
from typing import Any, NoReturn

__all__ = [
    "ListingDefinitionError",
    "IDENTIFIER_CHARS",
    "PATH_CHARS",
    "PUBLIC_ID_CHARS",
    "MAX_AUTHOR_NAME_LENGTH",
    "MAX_CONTACT_LENGTH",
    "MAX_HINT_LENGTH",
    "MAX_IDENTIFIER_LENGTH",
    "MAX_LABEL_LENGTH",
    "MAX_NAME_LENGTH",
    "MAX_PATH_LENGTH",
    "MAX_PUBLIC_ID_LENGTH",
    "MAX_URL_LENGTH",
    "check_identifier",
    "check_json_size",
    "check_path",
    "check_public_id",
    "check_single_line",
    "check_url",
    "clean_text",
    "fail",
    "require_list",
    "require_mapping",
    "utf8_bytes",
]


class ListingDefinitionError(ValueError):
    """A listing body this build cannot accept.

    The message names the reason in plain terms — these are read by an operator
    seeding a catalog or a publisher preparing a manifest, not surfaced to an
    end user.
    """


# --- caps -------------------------------------------------------------------
#
# Every one of these bounds a value a publisher chooses. They are generous
# enough that no honest manifest meets them and small enough that a stored
# definition stays a document rather than a payload.

MAX_IDENTIFIER_LENGTH = 64
MAX_PUBLIC_ID_LENGTH = 120
MAX_PATH_LENGTH = 200
#: A display name for what an install produces; the guild renames it after.
MAX_NAME_LENGTH = 255
MAX_LABEL_LENGTH = 120
MAX_AUTHOR_NAME_LENGTH = 120
MAX_URL_LENGTH = 300
MAX_CONTACT_LENGTH = 200
#: An `access_hint` string — the API and permission names a connection asks for.
MAX_HINT_LENGTH = 120

#: What an id inside a manifest may use: connection, widget, data source, embed.
#: Lowercase only, so two ids cannot differ by case alone.
IDENTIFIER_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_-")

#: What a `<publisher>.<slug>` id may use. Matches the catalog's own rule.
PUBLIC_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-_")

#: What a path may use. An explicit set, so a stored path is exactly what will
#: be appended to a registered base URL.
PATH_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/._-"
)

#: Schemes an author link may use. The server never requests these; they are
#: shown to a person deciding whether to install.
URL_SCHEMES = ("https://", "http://")


def fail(message: str) -> NoReturn:
    raise ListingDefinitionError(message)


# --- structure --------------------------------------------------------------


def require_mapping(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{what} must be an object")
    return value


def require_list(value: Any, what: str, limit: int) -> list[Any]:
    """A list, or an empty one when the key is absent. Never longer than
    ``limit`` — a manifest that exceeds it is refused rather than truncated, so
    a publisher learns their block was too big instead of quietly losing its
    tail."""
    if value is None:
        return []
    if not isinstance(value, list):
        fail(f"{what} must be a list")
    if len(value) > limit:
        fail(f"{what} holds more than {limit} entries")
    return value


# --- scalars ----------------------------------------------------------------


def clean_text(
    value: Any,
    *,
    what: str,
    limit: int,
    required: bool = True,
) -> str | None:
    """Plain text, trimmed and length-checked.

    Non-strings are dropped rather than coerced, so a nested object cannot
    smuggle itself into a rendered label. Over-length text is refused rather
    than cut: silently publishing half a sentence is worse than saying so.
    """
    if not isinstance(value, str):
        if required:
            fail(f"{what} is required")
        return None
    stripped = value.strip()
    if not stripped:
        if required:
            fail(f"{what} is required")
        return None
    if len(stripped) > limit:
        fail(f"{what} is longer than {limit} characters")
    return stripped


def check_single_line(value: str, *, what: str) -> str:
    """Text that will be shown on one line. Control characters, including line
    breaks and tabs, are refused."""
    for character in value:
        if ord(character) < 32 or ord(character) == 127:
            fail(f"{what} must be a single line of text")
    return value


def check_identifier(value: Any, *, what: str) -> str:
    """An id used as a key and composed into other ids."""
    if not isinstance(value, str) or not value:
        fail(f"{what} is required")
    if len(value) > MAX_IDENTIFIER_LENGTH:
        fail(f"{what} is longer than {MAX_IDENTIFIER_LENGTH} characters")
    for character in value:
        if character not in IDENTIFIER_CHARS:
            fail(f"{what} contains {character!r}, which is not allowed")
    return value


def check_public_id(value: Any, *, what: str) -> str:
    """A ``<publisher>.<slug>`` identifier."""
    if not isinstance(value, str) or not value:
        fail(f"{what} is required")
    if len(value) > MAX_PUBLIC_ID_LENGTH:
        fail(f"{what} is longer than {MAX_PUBLIC_ID_LENGTH} characters")
    for character in value:
        if character not in PUBLIC_ID_CHARS:
            fail(f"{what} contains {character!r}, which is not allowed")
    if "." not in value:
        fail(f"{what} must be '<publisher>.<slug>'")
    return value


def check_path(value: Any, *, what: str) -> str:
    """A path on the app's own service, never an address.

    The deployment joins this to the base URL its registration supplies, so a
    manifest states *which route*, and the operator states *where*. A value that
    could read as something other than a plain path — a scheme, a host, a parent
    segment — is refused by name.
    """
    if not isinstance(value, str) or not value:
        fail(f"{what} is required")
    if len(value) > MAX_PATH_LENGTH:
        fail(f"{what} is longer than {MAX_PATH_LENGTH} characters")
    if not value.startswith("/"):
        fail(f"{what} must be a path starting with '/'")
    for character in value:
        if character not in PATH_CHARS:
            fail(f"{what} contains {character!r}, which is not allowed")
    if "//" in value or ".." in value:
        fail(f"{what} must be a plain path with no '//' or '..'")
    return value


def check_url(value: Any, *, what: str) -> str:
    """A link shown beside a listing. Displayed, never requested by the server."""
    text = clean_text(value, what=what, limit=MAX_URL_LENGTH)
    if text is None:  # not reached: clean_text raises when the value is required
        fail(f"{what} is required")
    check_single_line(text, what=what)
    if " " in text:
        fail(f"{what} must not contain spaces")
    for scheme in URL_SCHEMES:
        if text.startswith(scheme) and len(text) > len(scheme):
            return text
    fail(f"{what} must start with 'https://' or 'http://'")


# --- opaque bodies ----------------------------------------------------------


def utf8_bytes(value: str, *, what: str) -> bytes:
    """The UTF-8 encoding of a string this build only ever measures.

    JSON permits escapes that do not encode, so this is where such a value is
    refused — before anything downstream tries to store or ship it.
    """
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ListingDefinitionError(f"{what} is not valid UTF-8") from exc


def check_json_size(value: Any, *, what: str, limit: int) -> None:
    """Bound a body this build stores without interpreting.

    Some manifest content is deliberately opaque — sample rows for a preview, a
    block belonging to another service. Shape and size are the whole contract
    for those, so this is the only check they get.
    """
    try:
        encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ListingDefinitionError(f"{what} must be plain JSON data") from exc
    size = len(encoded.encode("utf-8"))
    if size > limit:
        fail(f"{what} is larger than {limit} bytes")

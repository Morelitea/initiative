"""What a widget calls itself.

A widget's ``meta`` carries its name, its description, and the labels for its
own options in every language its author supports. A listing carries it as plain
data, and this module is where it is checked before it is stored; the browser
draws what was kept here. The limits it trims by are read from the vendored
plugin-kit contract.

Rebuilt from checked parts rather than inspected in place: unknown keys, unusable
locales, and over-long strings are dropped by construction, so what is stored is
exactly what can be rendered.
"""

from __future__ import annotations

from typing import Any

from app.services.marketplace import contract

__all__ = [
    "LOCALE_TAG_CHARS",
    "MAX_DESCRIPTION_LENGTH",
    "MAX_LOCALES",
    "MAX_LOCALE_TAG_LENGTH",
    "MAX_OPTIONS",
    "MAX_TEXT_LENGTH",
    "MAX_VALUES_PER_OPTION",
    "localized_text",
    "validate_widget_meta",
]

# --- limits ------------------------------------------------------------------
#
# Every one of these is read from the vendored contract. None of them refuses
# anything: an over-long string is
# truncated and a surplus entry is skipped, so they decide what is *kept* rather
# than what is allowed. What bounds the payload is the byte cap on the whole
# definition, not these.

MAX_TEXT_LENGTH = contract.cap("textLength")
MAX_DESCRIPTION_LENGTH = contract.cap("widgetDescriptionLength")
#: Languages one string may be supplied in. Generous — the cap only stops a
#: module from shipping a dictionary.
MAX_LOCALES = contract.cap("locales")
MAX_OPTIONS = contract.cap("widgetOptions")
MAX_VALUES_PER_OPTION = contract.cap("valuesPerOption")
#: `en`, `en-GB`, `pt-BR` — a language tag, not free text.
MAX_LOCALE_TAG_LENGTH = contract.cap("localeTagLength")

#: An explicit character check rather than a pattern: the set of things a
#: language tag may contain is short enough to state outright.
LOCALE_TAG_CHARS = contract.charset("localeTag")


def _is_locale_tag(value: str) -> bool:
    if not value or len(value) > MAX_LOCALE_TAG_LENGTH:
        return False
    for character in value:
        if character not in LOCALE_TAG_CHARS:
            return False
    return True


def localized_text(raw: Any, max_length: int) -> dict[str, str] | None:
    """A language-tag → text map, or ``None`` if nothing usable survives.

    Trimmed and truncated rather than refused: meta is presentation, and a
    widget with one over-long label should still name itself. Entries past the
    locale cap stop the scan, so the first forty are the ones kept.
    """
    if not isinstance(raw, dict):
        return None
    out: dict[str, str] = {}
    count = 0
    for tag, value in raw.items():
        count += 1
        if count > MAX_LOCALES:
            break
        if not isinstance(tag, str) or not _is_locale_tag(tag):
            continue
        if not isinstance(value, str):
            continue
        text = value.strip()[:max_length]
        if text:
            out[tag] = text
    return out or None


def _option_meta(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    label = localized_text(raw.get("label"), MAX_TEXT_LENGTH)
    if label is None:
        return None
    entry: dict[str, Any] = {"label": label}

    # Only a name-keyed object carries value labels; anything else is dropped
    # rather than read positionally.
    raw_values = raw.get("values")
    if isinstance(raw_values, dict):
        values: dict[str, dict[str, str]] = {}
        count = 0
        for value, raw_label in raw_values.items():
            count += 1
            if count > MAX_VALUES_PER_OPTION:
                break
            if not isinstance(value, str):
                continue
            value_label = localized_text(raw_label, MAX_TEXT_LENGTH)
            if value_label is not None:
                values[value] = value_label
        if values:
            entry["values"] = values
    return entry


def validate_widget_meta(raw: Any) -> dict[str, Any] | None:
    """Rebuild a widget's meta from validated parts.

    Returns ``None`` when there is no usable name — a widget without meta is not
    an error in the browser, which falls back to the type id, so this never
    raises. A *listing* holds its widgets to a higher bar (see
    ``service_plugins.py``): one that cannot name itself is refused at publish,
    because a marketplace widget with no name is a tile nobody can identify.
    """
    if not isinstance(raw, dict):
        return None

    name = localized_text(raw.get("name"), MAX_TEXT_LENGTH)
    if name is None:
        return None

    meta: dict[str, Any] = {"name": name}

    description = localized_text(raw.get("description"), MAX_DESCRIPTION_LENGTH)
    if description is not None:
        meta["description"] = description

    raw_options = raw.get("options")
    if isinstance(raw_options, dict):
        options: dict[str, Any] = {}
        count = 0
        for key, raw_option in raw_options.items():
            count += 1
            if count > MAX_OPTIONS:
                break
            if not isinstance(key, str):
                continue
            option = _option_meta(raw_option)
            if option is not None:
                options[key] = option
        if options:
            meta["options"] = options

    return meta

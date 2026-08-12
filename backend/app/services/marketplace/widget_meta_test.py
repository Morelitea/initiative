"""The widget-meta mirror, and proof it still matches the browser's copy.

Two implementations read the same structure: ``validateWidgetMeta`` in
``frontend/src/lib/widgets/widgetMeta.ts`` reads it out of the sandbox, and
``widget_meta.py`` reads it out of a listing. Neither can call the other, so the
only thing keeping them equal is a test that fails when they stop being.

``TestMirrorsTheFrontend`` is that test: it reads the TypeScript file and pins
every limit against the Python constant. A limit changed on one side, or a new
limit added to the frontend with no counterpart here, fails here — rather than
in production, where the symptom would be a widget the catalog accepted and the
browser then trimmed differently.
"""

from pathlib import Path

import pytest

from app.services.marketplace import widget_meta
from app.services.marketplace.widget_meta import (
    localized_text,
    validate_widget_meta,
)

pytestmark = pytest.mark.unit

# backend/app/services/marketplace/<this file> -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_FRONTEND = _REPO_ROOT / "frontend"
_MIRROR = _FRONTEND / "src" / "lib" / "widgets" / "widgetMeta.ts"

#: Every entry in the frontend's META_LIMITS, and the constant that mirrors it.
#: The mapping is asserted to be exhaustive in both directions, so a limit added
#: on either side has to be added here too.
_MIRRORED_LIMITS = {
    "maxTextLength": "MAX_TEXT_LENGTH",
    "maxDescriptionLength": "MAX_DESCRIPTION_LENGTH",
    "maxLocales": "MAX_LOCALES",
    "maxOptions": "MAX_OPTIONS",
    "maxValuesPerOption": "MAX_VALUES_PER_OPTION",
    "maxLocaleTagLength": "MAX_LOCALE_TAG_LENGTH",
}


def _read_mirror() -> str:
    if not _FRONTEND.is_dir():
        pytest.skip("frontend tree not present in this checkout")
    # Present but moved or renamed is a real failure: the mirror cannot be
    # checked, and silently passing is how the two copies would drift.
    assert _MIRROR.is_file(), f"widget meta mirror not found at {_MIRROR}"
    return _MIRROR.read_text(encoding="utf-8")


def _parse_limits(source: str) -> dict[str, int]:
    """The numbers out of ``META_LIMITS = { … } as const``.

    Deliberately a dull scan rather than a parser: the block is a flat list of
    ``name: number`` lines, and anything that stops being flat should fail the
    exhaustiveness check below rather than be silently reinterpreted.
    """
    _, _, rest = source.partition("META_LIMITS = {")
    body, _, _ = rest.partition("} as const")
    limits: dict[str, int] = {}
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(("/", "*")) or ":" not in stripped:
            continue
        name, _, value = stripped.partition(":")
        value = value.strip().rstrip(",").strip()
        if value.isdigit():
            limits[name.strip()] = int(value)
    return limits


def _parse_locale_chars(source: str) -> str:
    _, _, rest = source.partition("LOCALE_TAG_CHARS = ")
    value, _, _ = rest.partition("\n")
    return value.strip().rstrip(";").strip().strip('"')


class TestMirrorsTheFrontend:
    def test_every_limit_matches(self):
        limits = _parse_limits(_read_mirror())
        assert limits, "could not read META_LIMITS out of the mirror"
        for name, constant in _MIRRORED_LIMITS.items():
            assert name in limits, f"{name} is gone from the frontend's META_LIMITS"
            assert limits[name] == getattr(widget_meta, constant), (
                f"{name} and {constant} disagree"
            )

    def test_no_limit_exists_on_only_one_side(self):
        limits = _parse_limits(_read_mirror())
        assert set(limits) == set(_MIRRORED_LIMITS), (
            "the frontend's META_LIMITS and this mirror hold different limits"
        )

    def test_the_locale_alphabet_matches(self):
        chars = _parse_locale_chars(_read_mirror())
        assert chars, "could not read LOCALE_TAG_CHARS out of the mirror"
        assert frozenset(chars) == widget_meta.LOCALE_TAG_CHARS


class TestLocalizedText:
    def test_a_widget_may_ship_one_language(self):
        assert localized_text({"en": "Chart"}, 120) == {"en": "Chart"}

    def test_text_is_trimmed_and_truncated_rather_than_refused(self):
        # Meta is presentation: a widget with one over-long label should still
        # name itself, which is what the browser does with the same input.
        assert localized_text({"en": "  Chart  "}, 120) == {"en": "Chart"}
        assert localized_text({"en": "abcdef"}, 3) == {"en": "abc"}

    @pytest.mark.parametrize(
        "tag",
        [
            "en_US",  # underscore is not a language tag separator
            "en US",
            "toolongalanguagetag",
            "",
            "en/../..",
        ],
    )
    def test_a_key_that_is_not_a_language_tag_is_dropped(self, tag):
        assert localized_text({tag: "Chart", "en": "Chart"}, 120) == {"en": "Chart"}

    def test_a_non_string_value_is_dropped_rather_than_coerced(self):
        assert localized_text({"en": {"nested": "object"}, "de": "Diagramm"}, 120) == {
            "de": "Diagramm"
        }

    def test_nothing_usable_reads_as_nothing(self):
        assert localized_text({}, 120) is None
        assert localized_text({"en": "   "}, 120) is None
        assert localized_text("Chart", 120) is None
        assert localized_text(["Chart"], 120) is None

    def test_the_scan_stops_at_the_locale_cap(self):
        many = {f"l{index:03d}": "x" for index in range(widget_meta.MAX_LOCALES + 5)}
        # Not language tags, so nothing survives — but the point is that the
        # scan is bounded rather than proportional to what a module supplies.
        assert localized_text({**many, "en": "Chart"}, 120) is None


class TestValidateWidgetMeta:
    def test_a_widget_without_a_name_has_no_usable_meta(self):
        assert validate_widget_meta({"description": {"en": "no name"}}) is None
        assert validate_widget_meta(None) is None
        assert validate_widget_meta("Chart") is None

    def test_meta_is_rebuilt_from_checked_parts(self):
        meta = validate_widget_meta(
            {
                "name": {"en": "Chart", "de": "Diagramm"},
                "description": {"en": "Draws a series."},
                "options": {
                    "mark": {
                        "label": {"en": "Mark"},
                        "values": {"bar": {"en": "Bar"}, "line": {"en": "Line"}},
                    }
                },
                "render": "function () {}",
                "__proto__": {"en": "nope"},
            }
        )
        assert meta == {
            "name": {"en": "Chart", "de": "Diagramm"},
            "description": {"en": "Draws a series."},
            "options": {
                "mark": {
                    "label": {"en": "Mark"},
                    "values": {"bar": {"en": "Bar"}, "line": {"en": "Line"}},
                }
            },
        }

    def test_an_option_without_a_label_is_dropped(self):
        meta = validate_widget_meta(
            {"name": {"en": "Chart"}, "options": {"mark": {"values": {}}}}
        )
        assert meta == {"name": {"en": "Chart"}}

    def test_option_values_must_be_named(self):
        # A positional list cannot say which value it labels, so it is dropped
        # rather than read by index.
        meta = validate_widget_meta(
            {
                "name": {"en": "Chart"},
                "options": {"mark": {"label": {"en": "Mark"}, "values": ["Bar"]}},
            }
        )
        assert meta is not None
        assert meta["options"] == {"mark": {"label": {"en": "Mark"}}}

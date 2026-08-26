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

from app.services.marketplace import contract, widget_meta
from app.services.marketplace.widget_meta import (
    localized_text,
    validate_widget_meta,
)

pytestmark = pytest.mark.unit

# backend/app/services/marketplace/<this file> -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_FRONTEND = _REPO_ROOT / "frontend"

#: The two places the vendored contract lands. The backend validator reads one
#: and the browser's reads the other, and they are written by a single refresh.
_BACKEND_CONTRACT = (
    Path(__file__).resolve().parents[3]
    / "vendor"
    / "app-kit"
    / "manifest.contract.json"
)
_FRONTEND_CONTRACT = _FRONTEND / "src" / "contract" / "manifest.contract.json"


class TestTheBrowserTrimsByTheSameNumbers:
    """A widget's meta is validated here over catalog content and in the browser
    over what a module returns. Neither can call the other, so the numbers they
    trim by have to be one set — otherwise a widget is accepted by the catalog
    and then re-trimmed differently on screen.

    They used to be two hand-written sets held together by a test that parsed
    ``META_LIMITS`` out of the TypeScript. Now both sides read the vendored
    contract, so the only thing left to check is that the two copies of it are
    the same file.
    """

    def test_both_copies_are_the_same_contract(self):
        if not _FRONTEND.is_dir():
            pytest.skip("frontend tree not present in this checkout")
        # Present but moved is a real failure: the browser would fall back to
        # nothing, and silently passing is how the two would drift again.
        assert _FRONTEND_CONTRACT.is_file(), (
            f"no vendored contract at {_FRONTEND_CONTRACT}"
        )
        assert _BACKEND_CONTRACT.read_text(encoding="utf-8") == (
            _FRONTEND_CONTRACT.read_text(encoding="utf-8")
        ), "the two vendored copies differ — run backend/scripts/refresh_app_kit.py"

    def test_every_limit_this_module_uses_comes_from_the_contract(self):
        """Each name below is read by ``validate_widget_meta``; a limit that
        stopped coming from the contract would be one the browser cannot see."""
        for constant, cap in (
            ("MAX_TEXT_LENGTH", "textLength"),
            ("MAX_DESCRIPTION_LENGTH", "widgetDescriptionLength"),
            ("MAX_LOCALES", "locales"),
            ("MAX_OPTIONS", "widgetOptions"),
            ("MAX_VALUES_PER_OPTION", "valuesPerOption"),
            ("MAX_LOCALE_TAG_LENGTH", "localeTagLength"),
        ):
            assert getattr(widget_meta, constant) == contract.cap(cap), constant
        assert widget_meta.LOCALE_TAG_CHARS == contract.charset("localeTag")


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

"""Every refusal a person can be shown has words for it, in every locale.

``messages.py`` holds machine-readable codes; the wording lives in
``frontend/public/locales/<locale>/errors.json``. When a code has no entry
there, ``getErrorMessage`` falls through to displaying the code itself, so the
reader is handed ``WEBHOOK_SUBSCRIPTION_NOT_FOUND`` instead of a sentence. That
is invisible until somebody hits the path, which is why it is asserted here
rather than noticed in review.

The **machine surfaces** below are deliberately out of scope: service-to-service
channels — billing, the bundled-reference channel, an installed plug-in's
installation calls — where no person is on the other end and the code IS the
answer. The ``KindMessages`` refusals are worded once with the kind's name
filled in, so what a locale owes for a new tool or kind is its name, under
``kinds`` in the shared ``common`` namespace.
"""

import inspect
import json
from pathlib import Path

import pytest

from app.core import messages as messages_module
from app.core.tools import KINDS

pytestmark = pytest.mark.always


LOCALES = ("de", "en", "es", "fr")

#: Message classes belonging to service-to-service surfaces. Their routes are
#: not in the OpenAPI schema and resolve no user, so their codes are read by a
#: program and never rendered.
MACHINE_SURFACES = frozenset(
    {
        "PluginChannelMessages",
        "PluginDataMessages",
        "PluginServiceMessages",
        "BillingMessages",
        "BundledChannelMessages",
    }
)

#: The forms of a kind's name the ``KindMessages`` wording is filled in with:
#: as a sentence starts with it, as "this <kind>", and in the plural.
KIND_NAME_FORMS = frozenset({"name", "this", "plural"})


def _user_facing_codes() -> dict[str, str]:
    """Every code a person may be shown, mapped to what declares it."""
    codes: dict[str, str] = {}
    for name, obj in vars(messages_module).items():
        if not inspect.isclass(obj) or not name.endswith("Messages"):
            continue
        if name in MACHINE_SURFACES:
            continue
        for attr, value in vars(obj).items():
            if attr.startswith("_") or not isinstance(value, str):
                continue
            codes.setdefault(value, name)
    return codes


def _catalogue(locale: str, namespace: str = "errors") -> dict:
    locales = Path(__file__).resolve().parents[2].parent / "frontend/public/locales"
    return json.loads((locales / locale / f"{namespace}.json").read_text())


@pytest.mark.parametrize("locale", LOCALES)
def test_every_user_facing_code_has_wording(locale: str):
    catalogue = _catalogue(locale)
    missing = sorted(
        f"{code} (from {source})"
        for code, source in _user_facing_codes().items()
        if code not in catalogue
    )
    assert not missing, (
        f"{locale}/errors.json has no wording for {len(missing)} code(s):\n  "
        + "\n  ".join(missing)
    )


def test_no_two_codes_say_the_same_thing():
    """A second code with the same words is a code that need not exist.

    Two of them mean an endpoint got its own spelling of a refusal that already
    had one, and the reader cannot tell them apart. Fold the newer one into the
    code that already says it rather than adding a line here.

    English only: it is the source the others are written from, so it is where
    two codes meaning one thing shows up. A translation may fairly collapse a
    distinction English draws — ``delete`` and ``remove`` are one verb in
    several languages — and that is not a second code.
    """
    locale = "en"
    catalogue = _catalogue(locale)
    by_text: dict[str, list[str]] = {}
    for code, text in catalogue.items():
        if isinstance(text, str):
            by_text.setdefault(text.strip(), []).append(code)
    duplicated = {t: sorted(cs) for t, cs in by_text.items() if len(cs) > 1}
    assert not duplicated, (
        f"{locale}/errors.json says the same thing under several codes:\n  "
        + "\n  ".join(
            f"{text!r}: {codes}" for text, codes in sorted(duplicated.items())
        )
    )


def test_locales_agree_on_which_codes_exist():
    """A code is either worded everywhere or nowhere."""
    per_locale = {loc: set(_catalogue(loc)) for loc in LOCALES}
    reference = per_locale["en"]
    for locale, keys in per_locale.items():
        assert keys == reference, (
            f"{locale}/errors.json differs from en: "
            f"missing {sorted(reference - keys)}, extra {sorted(keys - reference)}"
        )


@pytest.mark.parametrize("locale", LOCALES)
def test_every_kind_is_named(locale: str):
    """Each kind's name, in every form a refusal about it is worded with."""
    names = _catalogue(locale, "common").get("kinds", {})
    unnamed = sorted(
        kind
        for kind in KINDS
        if not isinstance(names.get(kind), dict)
        or set(names[kind]) != KIND_NAME_FORMS
        or not all(isinstance(v, str) and v for v in names[kind].values())
    )
    assert not unnamed, f"{locale}/common.json has no full name for {unnamed}"
    assert set(names) == set(KINDS), (
        f"{locale}/common.json names kinds that are not: {sorted(set(names) - set(KINDS))}"
    )

"""Every refusal a person can be shown has words for it, in every locale.

``messages.py`` holds machine-readable codes; the wording lives in
``frontend/public/locales/<locale>/errors.json``. When a code has no entry
there, ``getErrorMessage`` falls through to displaying the code itself, so the
reader is handed ``WEBHOOK_SUBSCRIPTION_NOT_FOUND`` instead of a sentence. That
is invisible until somebody hits the path, which is why it is asserted here
rather than noticed in review.

Two kinds of code are deliberately out of scope. The **machine surfaces**
below are signed service-to-service channels — billing, the bundled-reference
channel, the app-service API, delegation exchange — where no person is on the
other end and the code IS the answer. And the per-tool codes are *derived* from
``Tool``, so the set grows on its own; what cannot be derived is the wording,
which is what this asks a locale for.
"""

import inspect
import json
from pathlib import Path

import pytest

from app.core import messages as messages_module
from app.core.messages import SharingMessages
from app.core.tools import Tool

pytestmark = pytest.mark.unit

LOCALES = ("de", "en", "es", "fr")

#: Message classes belonging to service-to-service surfaces. Their routes are
#: not in the OpenAPI schema and resolve no user, so their codes are read by a
#: program and never rendered.
MACHINE_SURFACES = frozenset(
    {
        "AppChannelMessages",
        "AppDataMessages",
        "AppServiceMessages",
        "BillingMessages",
        "BundledChannelMessages",
        "DelegationExchangeMessages",
    }
)

#: The per-tool code families, each a property on ``Tool``.
TOOL_CODE_PROPERTIES = (
    "not_found_code",
    "no_access_code",
    "owner_required_code",
    "write_required_code",
    "create_permission_code",
    "grant_cannot_manage_members_code",
    "role_permission_code",
    "feature_disabled_code",
)


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
    for tool in Tool:
        for prop in TOOL_CODE_PROPERTIES:
            codes.setdefault(getattr(tool, prop), f"Tool.{tool.value}.{prop}")
        codes.setdefault(SharingMessages.grantee_lacks_tool(tool), "SharingMessages")
    return codes


def _catalogue(locale: str) -> dict:
    locales = Path(__file__).resolve().parents[2].parent / "frontend/public/locales"
    return json.loads((locales / locale / "errors.json").read_text())


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

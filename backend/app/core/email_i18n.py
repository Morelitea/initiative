"""Simple JSON-based i18n loader for email templates.

Usage:
    from app.core.email_i18n import email_t

    email_t("verification.subject")                    # "Verify your Initiative account"
    email_t("verification.greeting", name="Jordan")    # "Hi Jordan,"
    email_t("overdue.body", count=3)                   # picks _one/_other based on count
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path


_LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"
_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


@lru_cache(maxsize=16)
def _load_locale(locale: str) -> dict:
    path = (_LOCALES_DIR / locale / "email.json").resolve()
    if not path.is_relative_to(_LOCALES_DIR.resolve()):
        return {}
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _resolve_key(data: dict, key: str) -> str | None:
    """Walk dot-separated key through nested dict."""
    parts = key.split(".")
    current: dict | str = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)  # type: ignore[assignment]
            if current is None:
                return None
        else:
            return None
    return current if isinstance(current, str) else None


def email_t(key: str, locale: str = "en", **kwargs: str | int) -> str:
    """Look up a translation key with ``{{var}}`` interpolation.

    Supports simple plural selection via ``count`` kwarg:
    if ``count`` is provided and a ``_one`` / ``_other`` suffixed key exists,
    the appropriate variant is returned.
    """
    data = _load_locale(locale)

    # Plural handling
    count = kwargs.get("count")
    if count is not None:
        suffix = "_one" if int(count) == 1 else "_other"
        plural_value = _resolve_key(data, f"{key}{suffix}")
        if plural_value is not None:
            return _VAR_RE.sub(lambda m: str(kwargs.get(m.group(1), m.group(0))), plural_value)

    value = _resolve_key(data, key)
    if value is None:
        return key  # fallback: return the key itself

    return _VAR_RE.sub(lambda m: str(kwargs.get(m.group(1), m.group(0))), value)

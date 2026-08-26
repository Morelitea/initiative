"""The app contract, as this build reads it.

The vocabulary an app manifest draws on — every enum, cap and character set —
and the shape it takes are declared once, in the ``initiative-app-kit``
repository, in ``manifest.contract.json``. That file is vendored here under
``backend/vendor/app-kit`` at a pinned kit version and read at import.

**Why the kit owns it.** An app author writes against the kit: its types, its
offline validator, its published JSON Schema. When the vocabulary lived here and
the kit's types were written by hand beside a schema fetched from this
repository, the two drifted — the kit could not declare a block this build
accepts. One document, generated into both representations, is what removes
that.

**Why this build still pins it.** ``normalize_service_app_definition`` is
admission control: it decides what a publisher may install. A deployment
therefore reads a copy it shipped with, never one fetched at run time, and a new
contract reaches it when it next releases. So the direction is asymmetric on
purpose — a kit release reaches app authors immediately and this build at its
next release — and a term the vendored contract declares that this build does
not act on is a failing test (:mod:`contract_coverage_test`), not a value
quietly dropped.

Refresh the vendored copy with ``python scripts/refresh_app_kit.py``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = [
    "KIT_REVISION",
    "discarded_terms",
    "KIT_VERSION",
    "SCHEMA_PATH",
    "cap",
    "charset",
    "enum",
    "fields",
    "int_enum",
    "ladder",
    "manifest_schema",
    "objects",
]

#: Where the vendored kit lives, relative to the backend package root.
_VENDOR = Path(__file__).resolve().parents[3] / "vendor" / "app-kit"

#: The JSON Schema the kit generates from the same contract. Not read by the
#: validator — it is what the conformance tests measure this build against.
SCHEMA_PATH = _VENDOR / "app-manifest.json"


def _read(name: str) -> str:
    return (_VENDOR / name).read_text(encoding="utf-8").strip()


#: Which kit release this build speaks, recorded so a reviewer can see it move.
KIT_VERSION = _read("KIT_VERSION")
KIT_REVISION = _read("KIT_REVISION")


@lru_cache(maxsize=1)
def _contract() -> dict[str, Any]:
    """The vendored contract, parsed once per process."""
    with (_VENDOR / "manifest.contract.json").open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def manifest_schema() -> dict[str, Any]:
    """The generated JSON Schema, for tests that measure the two against it."""
    with SCHEMA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def enum(name: str) -> frozenset[str]:
    """One closed vocabulary, as a set.

    A set rather than a sequence because every use here is a membership test.
    Where the order carries meaning — a ladder — use :func:`ladder`.
    """
    values = _contract()["enums"].get(name)
    if values is None:
        raise KeyError(f"the contract declares no enum {name!r}")
    return frozenset(values)


def int_enum(name: str) -> frozenset[int]:
    """A closed vocabulary of numbers rather than strings.

    Separate from :func:`enum` so each keeps a real element type; the protocol
    version is the one numeric vocabulary the contract carries.
    """
    values = _contract()["enums"].get(name)
    if values is None:
        raise KeyError(f"the contract declares no enum {name!r}")
    return frozenset(int(value) for value in values)


def ladder(name: str) -> tuple[str, ...]:
    """An ordered vocabulary: a value names the floor an audience must clear."""
    rungs = _contract()["ladders"].get(name)
    if rungs is None:
        raise KeyError(f"the contract declares no ladder {name!r}")
    return tuple(rungs)


def cap(name: str) -> int:
    """One upper bound, by the name the contract gives it."""
    value = _contract()["caps"].get(name)
    if value is None:
        raise KeyError(f"the contract declares no cap {name!r}")
    return int(value)


def charset(name: str) -> frozenset[str]:
    """The characters a class of id or path may use.

    A set, not a pattern: the checks in :mod:`manifest_values` are explicit
    membership tests, and the contract carries the characters themselves so the
    schema's pattern and this set cannot describe different things.
    """
    value = _contract()["charsets"].get(name)
    if value is None:
        raise KeyError(f"the contract declares no character set {name!r}")
    return frozenset(value)


def objects() -> dict[str, Any]:
    """Every object the contract defines, including the manifest itself."""
    contract = _contract()
    return {**contract["defs"], "manifest": contract["manifest"]}


def fields(owner: str) -> tuple[str, ...]:
    """Every field the contract declares on one object, in declaration order.

    The inventory the normalizer is held to. A field here that nothing reads is
    a restriction an author asked for and this build would silently discard.
    """
    node = objects().get(owner)
    if node is None:
        raise KeyError(f"the contract declares no object {owner!r}")
    return tuple(node.get("properties", {}))


#: Which contract object describes each list a manifest carries, and each
#: object nested inside one. Walking a served definition needs this because the
#: contract's `$ref`s are a schema concern the reader does not resolve.
_NESTED: dict[str, dict[str, str]] = {
    "manifest": {
        "connections": "connection",
        "endpoints": "endpoint",
        "widgets": "widget",
        "embeds": "embed",
        "dashboards": "bundledDashboard",
    },
    "connection": {"fields": "connectionField", "access_hint": "accessHint"},
    "endpoint": {"params": "endpointParam", "returns": "endpointReturn"},
    "bundledDashboard": {"widgets": "bundledDashboardWidget"},
}


def discarded_terms(definition: Any, *, owner: str = "manifest") -> list[str]:
    """Every key in a served definition that this build's contract does not name.

    A deployment reads the contract it shipped with, so an app written against a
    newer one can send terms this build has no meaning for. They are dropped
    rather than refused — that is what lets an app target a newer platform and
    still install on an older one — which leaves the author with nothing to see.
    This is what the registrar reports back so the skew is visible at
    verification instead of never.

    Paths are dotted and indexed (``endpoints.0.rate_limit``) so a report names
    the exact term rather than the object it was on.
    """
    if not isinstance(definition, dict):
        return []
    declared = set(fields(owner))
    nested = _NESTED.get(owner, {})
    found: list[str] = []
    for key, value in definition.items():
        if key not in declared:
            found.append(key)
            continue
        child = nested.get(key)
        if child is None:
            continue
        if isinstance(value, list):
            for index, item in enumerate(value):
                found += [
                    f"{key}.{index}.{term}"
                    for term in discarded_terms(item, owner=child)
                ]
        elif isinstance(value, dict):
            found += [f"{key}.{term}" for term in discarded_terms(value, owner=child)]
    return sorted(found)

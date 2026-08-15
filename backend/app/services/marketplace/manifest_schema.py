"""The app manifest as a JSON Schema, built from the validator's own vocabulary.

An app author works in another repository, in another language, against a
manifest this build accepts or refuses. Handing them a schema turns most of that
refusal into an editor squiggle and a compile error — which is what the SDK
generates its types from, and what an implementer in a stack we ship nothing for
checks against.

**Derived, never written twice.** Every enum, cap and character set here reads
from the constants :mod:`app.services.marketplace.service_apps` and
:mod:`app.services.marketplace.manifest_values` already declare. A cap raised
there is raised here on the next export, so the schema cannot quietly describe a
manifest the validator would reject. That is the whole reason this is generated
rather than kept as a checked-in document somebody remembers to update.

**The validator remains authoritative, and the schema says so.** Schema-valid is
necessary, not sufficient. Four classes of rule cannot be expressed in JSON
Schema and are enforced only by ``normalize_service_app_definition``:

* **Cross-references** — a widget binding a data source that exists, a
  ``requires`` term naming a declared connection, an event type prefixed with
  the app's own service id.
* **The features cross-check** — every declared feature backed by a block, and
  every block declared as a feature, in both directions.
* **Byte sizes** — the caps on ``module_source``, ``sample_data``, the
  ``automation`` body and the whole document are measured in UTF-8 bytes, which
  a character count cannot stand in for.
* **Conditional vocabulary** — an embed may name ``initiative_manager`` only if
  it also renders in an initiative, and ``connect_path`` belongs to an
  interactive connection alone.

Those are stated in the schema's own ``description`` too, so the limitation
travels with the file rather than living only here.

**Where the two are allowed to differ.** The rule is one-directional: this schema
must never reject a manifest the platform accepts *and acts on*. So it is
deliberately permissive in three places where the platform takes a value rather
than refusing it — an out-of-range ``cache_ttl_seconds`` is clamped into range, an
over-long localized string is truncated, and an unrecognized property is dropped.
Naming those as errors would tell an author their working manifest is broken, and
the last one would also break forward compatibility: an app targeting a newer
platform has to keep validating against an older copy of this file.

There is no exception. An earlier cut of this module made one for values the
platform discards outright — a localized entry that is not a string — on the
grounds that flagging something inert can only help. It cannot: the entry may be
inert, but refusing it rejects the whole document, and a manifest that installs
must never be reported as malformed. Catching a typo in an ignored value is a
linter's job, and an SDK is free to tighten this schema for authoring; nothing
downstream can loosen a published contract that refuses working input.
"""

from __future__ import annotations

from typing import Any

from app.services.marketplace.manifest_values import (
    IDENTIFIER_CHARS,
    MAX_HINT_LENGTH,
    MAX_IDENTIFIER_LENGTH,
    MAX_LABEL_LENGTH,
    MAX_NAME_LENGTH,
    MAX_PATH_LENGTH,
    MAX_PUBLIC_ID_LENGTH,
    PATH_CHARS,
    PUBLIC_ID_CHARS,
)
from app.services.marketplace.service_apps import (
    APP_PROTOCOL_VERSIONS,
    CONNECTION_SCOPES,
    EMBED_CAPABILITIES,
    EVENT_TYPE_CHARS,
    EVENT_TYPE_PREFIX,
    FEATURES,
    FIELD_TYPES,
    GUILD_WIDE_VISIBILITIES,
    MAX_ACCESS_HINT_SCOPES,
    MAX_CACHE_TTL_SECONDS,
    MAX_CONNECTIONS,
    MAX_DATA_SOURCES,
    MAX_EMBED_CAPABILITIES,
    MAX_EMBEDS,
    MAX_EVENT_TYPE_LENGTH,
    MAX_EVENTS,
    MAX_FIELDS_PER_CONNECTION,
    MAX_PARAMS_PER_SOURCE,
    MAX_REQUIRES_TERMS,
    MAX_SELECT_OPTIONS,
    MAX_WIDGET_SOURCES,
    MAX_WIDGETS,
    PARAM_TYPES,
    SURFACE_SCOPES,
    VISIBILITIES,
)
from app.services.marketplace.widget_meta import MAX_LOCALES, MAX_TEXT_LENGTH

__all__ = ["SCHEMA_ID", "build_manifest_schema"]

#: Where the schema says it lives. A stable, resolvable name an author can point
#: a ``$schema`` at and a generator can key a cache on — not a URL this build
#: serves, which would tie the contract to one deployment.
SCHEMA_ID = "https://initiative.morels.me/schemas/app-manifest-v1.json"

#: What schema-valid does not prove. Carried in the document so an implementer
#: reading only the file still learns it.
_AUTHORITY_NOTE = (
    "A manifest that satisfies this schema is well-formed, not necessarily "
    "acceptable. Cross-references (a widget's data sources, a requires term's "
    "connection, an event's service prefix), the features/blocks cross-check in "
    "both directions, UTF-8 byte-size caps, and the conditional rules for "
    "connect_path and initiative visibility are enforced by the platform on "
    "publish and are not expressible here."
)


def _char_class(chars: frozenset[str]) -> str:
    """A character class over exactly the set the validator allows.

    Built from the set rather than restated as a literal, so widening the
    vocabulary in one place widens it here. Characters are escaped and ordered so
    the output is stable across runs — the file is committed, and a diff should
    mean somebody changed a rule.
    """
    return "[" + "".join(_escape(character) for character in sorted(chars)) + "]"


def _pattern(chars: frozenset[str]) -> str:
    """One or more of ``chars``, anchored."""
    return f"^{_char_class(chars)}+$"


def _escape(character: str) -> str:
    """Escape for use inside a regex character class."""
    return f"\\{character}" if character in {"\\", "]", "^", "-"} else character


def _path_pattern() -> str:
    """A plain path: leading slash, allowed characters, no ``//`` and no ``..``.

    The two refusals are a lookahead rather than a second rule, so a path that
    reads as something other than a route on the app's own service fails here as
    it does in ``check_path``.
    """
    return f"^(?!.*(?://|\\.\\.))/{_char_class(PATH_CHARS)}*$"


def _enum(values: frozenset[str]) -> list[str]:
    """Sorted, so re-exporting an unchanged vocabulary produces no diff."""
    return sorted(values)


def _localized_text(max_length: int = MAX_TEXT_LENGTH) -> dict[str, Any]:
    """A human-readable string in one or more languages, keyed by language tag.

    Neither the length nor the value type is asserted, because the platform
    refuses neither: an over-long entry is truncated, and an entry that is not a
    string — or one past the locale cap, which is never inspected at all — is
    skipped while the rest of the object stands. Only ``minProperties`` survives,
    which matches the one thing that does fail: an object with nothing usable in
    it.

    Losing the value type costs a generator some precision. That is the right
    way round: a schema is a contract before it is a type source, and an SDK that
    wants a stricter shape for *authoring* can tighten it locally, which nothing
    downstream can do about a contract that rejects a working manifest.
    """
    return {
        "type": "object",
        "description": (
            "Localized text, keyed by language tag. At least one usable entry; "
            "the platform falls back to the reader's language, then to any "
            f"entry. Values should be strings: text longer than {max_length} "
            f"characters is truncated, and an entry that is not a string, is "
            f"not a language tag, or falls past the first {MAX_LOCALES} is "
            "ignored rather than refused."
        ),
        "minProperties": 1,
    }


def _field(*, types: frozenset[str], allow_managed: bool) -> dict[str, Any]:
    """One typed input, in a connection form or a data source's parameters."""
    properties: dict[str, Any] = {
        "key": {"type": "string", "$ref": "#/$defs/identifier"},
        "type": {"enum": _enum(types)},
        "required": {"type": "boolean", "default": False},
        "label": {"$ref": "#/$defs/localizedText"},
        "options": {
            "type": "array",
            "description": "Required when type is 'select'.",
            "maxItems": MAX_SELECT_OPTIONS,
            "minItems": 1,
            "items": {"type": "string", "maxLength": MAX_LABEL_LENGTH},
        },
    }
    if allow_managed:
        properties["managed"] = {
            "type": "boolean",
            "default": False,
            "description": (
                "The app writes this value back itself when it finishes a vendor "
                "flow; it is not typed into the settings form."
            ),
        }
    return {
        "type": "object",
        "required": ["key", "type", "label"],
        "properties": properties,
        # Expressible here, unlike the cross-reference rules: whether options are
        # required follows from this object alone.
        "if": {"properties": {"type": {"const": "select"}}, "required": ["type"]},
        "then": {"required": ["options"]},
    }


def _requires() -> dict[str, Any]:
    """Which connections satisfy an item — one level, one operator.

    ``oneOf`` over the two operators rather than a property count. The count
    reads better in an error, but it counts *every* key: an unknown property
    beside a valid operator would push the object to two, and the platform keeps
    the operator and discards the unknown one. ``oneOf`` asks the question that
    is actually being asked — is exactly one of these two present — and ignores
    anything else in the object.
    """
    terms = {
        "type": "array",
        "minItems": 1,
        "maxItems": MAX_REQUIRES_TERMS,
        "items": {"$ref": "#/$defs/identifier"},
    }
    return {
        "type": "object",
        "description": (
            "Connection ids that must hold a value before this is offered. "
            "Exactly one of 'all_of' or 'any_of'; each id must name a connection "
            "this manifest declares. Absent means always available."
        ),
        "properties": {"all_of": terms, "any_of": terms},
        "oneOf": [{"required": ["all_of"]}, {"required": ["any_of"]}],
    }


def _connection() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["id", "scope", "label", "fields"],
        "properties": {
            "id": {"$ref": "#/$defs/identifier"},
            "scope": {
                "enum": _enum(CONNECTION_SCOPES),
                "description": (
                    "'static' is one credential a guild admin supplies for the "
                    "whole guild; 'interactive' is each member's own account, "
                    "connected through the app's own vendor flow."
                ),
            },
            "label": {"$ref": "#/$defs/localizedText"},
            "fields": {
                "type": "array",
                "maxItems": MAX_FIELDS_PER_CONNECTION,
                "items": {"$ref": "#/$defs/connectionField"},
            },
            "connect_path": {
                "$ref": "#/$defs/path",
                "description": (
                    "Where the member is sent so the app can run the vendor's "
                    "flow. Interactive connections only."
                ),
            },
            "access_hint": {"$ref": "#/$defs/accessHint"},
        },
    }


def _access_hint() -> dict[str, Any]:
    return {
        "type": "object",
        "description": (
            "What the credential will be used for. Display-only: it is shown "
            "beside the form so an admin can mint a minimal credential, and no "
            "other system's permissions are enforced from it."
        ),
        "properties": {
            "api": {"type": "string", "maxLength": MAX_HINT_LENGTH},
            "scopes": {
                "type": "array",
                "maxItems": MAX_ACCESS_HINT_SCOPES,
                "items": {"type": "string", "maxLength": MAX_HINT_LENGTH},
            },
        },
    }


def _data_source() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["id", "path"],
        "properties": {
            "id": {"$ref": "#/$defs/identifier"},
            "path": {"$ref": "#/$defs/path"},
            "visibility": {
                "enum": _enum(GUILD_WIDE_VISIBILITIES),
                "description": (
                    "A source is fetched for a guild rather than an initiative, "
                    "so the initiative rung is not on offer."
                ),
            },
            "cache_ttl_seconds": {
                "type": "integer",
                "default": 0,
                "description": (
                    "How long a response may be reused. Clamped into "
                    f"0..{MAX_CACHE_TTL_SECONDS} rather than refused, so a value "
                    "outside that range is accepted and takes effect at the "
                    "bound — which is why no range is asserted here."
                ),
            },
            "params_schema": {
                "type": "array",
                "maxItems": MAX_PARAMS_PER_SOURCE,
                "items": {"$ref": "#/$defs/sourceParam"},
            },
            "requires": {"$ref": "#/$defs/requires"},
        },
    }


def _widget() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["id", "meta", "module_source"],
        "properties": {
            "id": {"$ref": "#/$defs/identifier"},
            "meta": {
                "type": "object",
                "description": (
                    "The widget's own name and description, as the picker shows "
                    "them. Must name the widget in at least one language."
                ),
            },
            "module_source": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "The widget's browser-side module. Stored as an opaque "
                    "string and executed only inside the sandbox; the platform "
                    "never parses it. Capped in UTF-8 bytes, which this schema "
                    "cannot express."
                ),
            },
            "sources": {
                "type": "array",
                "maxItems": MAX_WIDGET_SOURCES,
                "items": {"$ref": "#/$defs/identifier"},
                "description": "Data source ids this manifest also declares.",
            },
            "sample_data": {
                "type": "object",
                "description": (
                    "Rows keyed by declared source id, so a preview renders with "
                    "no network call. Keys naming an undeclared source are "
                    "dropped."
                ),
            },
            "requires": {"$ref": "#/$defs/requires"},
        },
    }


def _embed() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["id", "path", "name"],
        "properties": {
            "id": {"$ref": "#/$defs/identifier"},
            "path": {"$ref": "#/$defs/path"},
            "name": {"$ref": "#/$defs/localizedText"},
            "scopes": {
                "type": "array",
                "maxItems": len(SURFACE_SCOPES),
                "items": {"enum": _enum(SURFACE_SCOPES)},
                "default": ["guild"],
                "description": (
                    "Where the surface renders. Declaring both gives it a "
                    "guild-wide entry and an entry inside each initiative."
                ),
            },
            "visibility": {
                "enum": _enum(VISIBILITIES),
                "description": (
                    "The floor an audience clears. 'initiative_manager' is only "
                    "namable by a surface that also renders in an initiative — "
                    "a rule the platform enforces, not this schema."
                ),
            },
            "capabilities": {
                "type": "array",
                "maxItems": MAX_EMBED_CAPABILITIES,
                "items": {"enum": _enum(EMBED_CAPABILITIES)},
                "description": (
                    "Browser features the frame is granted. A surface that names "
                    "nothing is framed with all of them denied."
                ),
            },
            "requires": {"$ref": "#/$defs/requires"},
        },
    }


def build_manifest_schema() -> dict[str, Any]:
    """The service-app manifest schema, as a JSON Schema 2020-12 document."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "title": "Initiative app manifest (the 'definition' body)",
        "description": (
            "What a service app declares it can do. This is the 'definition' "
            "field of the document served at /.well-known/initiative-app.json, "
            "NOT that whole document: a registrar also requires "
            "protocol_version, public_id and kind alongside it, and refuses a "
            "definition served bare. Generated from the platform's own "
            f"validator vocabulary. {_AUTHORITY_NOTE}"
        ),
        "type": "object",
        "required": ["app_kind", "service", "features"],
        "properties": {
            "app_kind": {
                "const": "service",
                "description": "The only kind that names a container to call.",
            },
            "service": {
                "type": "object",
                "required": ["public_id"],
                "properties": {
                    "public_id": {
                        "type": "string",
                        "maxLength": MAX_PUBLIC_ID_LENGTH,
                        # The dot is required, not merely allowed: a public id
                        # without one is not '<publisher>.<slug>'.
                        "pattern": (
                            f"^{_char_class(PUBLIC_ID_CHARS)}*"
                            f"\\.{_char_class(PUBLIC_ID_CHARS)}*$"
                        ),
                        "description": (
                            "'<publisher>.<slug>'. The name the deployment's "
                            "registration is matched by, and the namespace this "
                            "app's events are emitted under."
                        ),
                    },
                    "protocol": {
                        "enum": sorted(APP_PROTOCOL_VERSIONS),
                        "default": 1,
                    },
                },
            },
            "features": {
                "type": "array",
                "maxItems": len(FEATURES),
                "items": {"enum": _enum(FEATURES)},
                "description": (
                    "What this app contributes. Cross-checked against the blocks "
                    "present in both directions: a feature with no block, or a "
                    "block with no feature, is refused."
                ),
            },
            "default_name": {"type": "string", "maxLength": MAX_NAME_LENGTH},
            "connections": {
                "type": "array",
                "maxItems": MAX_CONNECTIONS,
                "items": {"$ref": "#/$defs/connection"},
            },
            "data_sources": {
                "type": "array",
                "maxItems": MAX_DATA_SOURCES,
                "items": {"$ref": "#/$defs/dataSource"},
            },
            "widgets": {
                "type": "array",
                "maxItems": MAX_WIDGETS,
                "items": {"$ref": "#/$defs/widget"},
            },
            "embeds": {
                "type": "array",
                "maxItems": MAX_EMBEDS,
                "items": {"$ref": "#/$defs/embed"},
            },
            "events": {
                "type": "array",
                "maxItems": MAX_EVENTS,
                "items": {
                    "type": "string",
                    "maxLength": MAX_EVENT_TYPE_LENGTH,
                    "pattern": _pattern(EVENT_TYPE_CHARS),
                    "description": (
                        "Namespaced under the app's own service id — "
                        f"'{EVENT_TYPE_PREFIX}<public_id>.<name>'. The prefix is "
                        "checked against the emitting registration at ingress."
                    ),
                },
            },
            "automation": {
                "type": "object",
                "description": (
                    "The automation service's own block. Opaque to the platform: "
                    "checked for shape and size, stored verbatim, and described "
                    "by no vocabulary here."
                ),
            },
        },
        "$defs": {
            "identifier": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_IDENTIFIER_LENGTH,
                "pattern": _pattern(IDENTIFIER_CHARS),
            },
            "path": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_PATH_LENGTH,
                "pattern": _path_pattern(),
                "description": (
                    "A route on the app's own service, never an address. The "
                    "deployment joins it to the base URL its registration "
                    "supplies."
                ),
            },
            "localizedText": _localized_text(),
            "requires": _requires(),
            "accessHint": _access_hint(),
            "connectionField": _field(types=FIELD_TYPES, allow_managed=True),
            "sourceParam": _field(types=PARAM_TYPES, allow_managed=False),
            "connection": _connection(),
            "dataSource": _data_source(),
            "widget": _widget(),
            "embed": _embed(),
        },
    }

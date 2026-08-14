"""The schema describes the manifest the validator actually accepts.

Two kinds of case, and the second is the one that earns its keep:

* **Derivation** — every vocabulary and cap in the schema reads from the
  constant it came from, so widening a rule in one place cannot leave the schema
  describing the old one.
* **Agreement** — a corpus of manifests run through both. Anything the validator
  accepts must satisfy the schema, or an author would be told their working
  manifest is wrong; anything the schema rejects for a reason it *can* express
  must be refused by the validator too, or the schema would be inventing a rule.

The asymmetry is deliberate and stated in the module: schema-valid is necessary,
not sufficient. The cases at the bottom pin the specific rules that only the
validator enforces, so that boundary is written down rather than discovered.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.services.marketplace.manifest_schema import (
    SCHEMA_ID,
    build_manifest_schema,
)
from app.services.marketplace.manifest_values import (
    MAX_IDENTIFIER_LENGTH,
    MAX_PATH_LENGTH,
    MAX_PUBLIC_ID_LENGTH,
)
from app.services.marketplace.definitions import normalize_listing_definition
from app.services.marketplace.widget_meta import MAX_TEXT_LENGTH
from app.services.marketplace.service_apps import (
    APP_PROTOCOL_VERSIONS,
    CONNECTION_SCOPES,
    EMBED_CAPABILITIES,
    FEATURES,
    FIELD_TYPES,
    GUILD_WIDE_VISIBILITIES,
    MAX_CONNECTIONS,
    MAX_DATA_SOURCES,
    MAX_EMBEDS,
    MAX_WIDGETS,
    PARAM_TYPES,
    SURFACE_SCOPES,
    VISIBILITIES,
)


def platform_accepts(manifest) -> None:
    """Run a manifest through the whole app path, not the service normalizer.

    `app_kind` is read by the dispatcher rather than by
    `normalize_service_app_definition`, so a case that varies it has to enter
    where a published manifest actually enters.
    """
    normalize_listing_definition("app", manifest)


SCHEMA_FILE = Path(__file__).resolve().parents[3] / "schemas" / "app-manifest.json"


# Unannotated on purpose: `jsonschema` builds its validator classes at runtime,
# so the name is not a type the checker can resolve.
@pytest.fixture(scope="module")
def validator():
    schema = build_manifest_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _manifest(**overrides):
    """A minimal manifest the platform accepts, for a case to vary one thing of."""
    body = {
        "app_kind": "service",
        "service": {"public_id": "acme.tracker", "protocol": 1},
        "features": [],
    }
    body.update(overrides)
    return body


# --- the schema is a schema -------------------------------------------------


@pytest.mark.unit
def test_the_schema_is_a_valid_2020_12_document():
    Draft202012Validator.check_schema(build_manifest_schema())


@pytest.mark.unit
def test_every_ref_resolves():
    """A `$ref` naming a definition that isn't there fails at use rather than at
    load, so it would survive a test that only validated the happy path."""
    schema = build_manifest_schema()
    defs = set(schema["$defs"])

    def walk(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                assert ref.startswith("#/$defs/"), ref
                assert ref.removeprefix("#/$defs/") in defs, ref
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)


@pytest.mark.unit
def test_the_committed_file_matches_the_generator():
    """CI regenerates and diffs; this says the same thing where it is cheap to
    read, so a vocabulary change with no re-export fails beside the change."""
    assert SCHEMA_FILE.exists(), f"{SCHEMA_FILE} is missing"
    on_disk = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    assert on_disk == build_manifest_schema()


# --- derived, not restated --------------------------------------------------


@pytest.mark.unit
def test_vocabularies_come_from_the_validator():
    schema = build_manifest_schema()
    props = schema["properties"]
    defs = schema["$defs"]

    assert set(props["features"]["items"]["enum"]) == FEATURES
    assert set(props["service"]["properties"]["protocol"]["enum"]) == (
        APP_PROTOCOL_VERSIONS
    )
    assert set(defs["connection"]["properties"]["scope"]["enum"]) == CONNECTION_SCOPES
    assert set(defs["connectionField"]["properties"]["type"]["enum"]) == FIELD_TYPES
    assert set(defs["sourceParam"]["properties"]["type"]["enum"]) == PARAM_TYPES
    assert set(defs["dataSource"]["properties"]["visibility"]["enum"]) == (
        GUILD_WIDE_VISIBILITIES
    )
    assert set(defs["embed"]["properties"]["visibility"]["enum"]) == VISIBILITIES
    assert set(defs["embed"]["properties"]["scopes"]["items"]["enum"]) == SURFACE_SCOPES
    assert set(defs["embed"]["properties"]["capabilities"]["items"]["enum"]) == (
        EMBED_CAPABILITIES
    )


@pytest.mark.unit
def test_caps_come_from_the_validator():
    props = build_manifest_schema()["properties"]
    assert props["connections"]["maxItems"] == MAX_CONNECTIONS
    assert props["data_sources"]["maxItems"] == MAX_DATA_SOURCES
    assert props["widgets"]["maxItems"] == MAX_WIDGETS
    assert props["embeds"]["maxItems"] == MAX_EMBEDS


@pytest.mark.unit
def test_a_secret_is_not_a_query_parameter():
    """`secret` is a connection field type and deliberately not a param type;
    the schema must not blur the two by sharing one field definition."""
    defs = build_manifest_schema()["$defs"]
    assert "secret" in defs["connectionField"]["properties"]["type"]["enum"]
    assert "secret" not in defs["sourceParam"]["properties"]["type"]["enum"]
    # And only a connection field is written back by the app.
    assert "managed" in defs["connectionField"]["properties"]
    assert "managed" not in defs["sourceParam"]["properties"]


@pytest.mark.unit
def test_lengths_come_from_the_validator():
    defs = build_manifest_schema()["$defs"]
    assert defs["identifier"]["maxLength"] == MAX_IDENTIFIER_LENGTH
    assert defs["path"]["maxLength"] == MAX_PATH_LENGTH
    assert (
        build_manifest_schema()["properties"]["service"]["properties"]["public_id"][
            "maxLength"
        ]
        == MAX_PUBLIC_ID_LENGTH
    )


@pytest.mark.unit
def test_the_schema_names_itself_stably():
    """The SDK keys generated types on this; a drifting `$id` invalidates them."""
    assert build_manifest_schema()["$id"] == SCHEMA_ID


# --- the two agree ----------------------------------------------------------

ACCEPTED = [
    pytest.param(_manifest(), id="minimal"),
    pytest.param(
        _manifest(
            features=["data"],
            connections=[
                {
                    "id": "api",
                    "scope": "static",
                    "label": {"en": "API key"},
                    "fields": [
                        {"key": "token", "type": "secret", "label": {"en": "Token"}}
                    ],
                    "access_hint": {"api": "GitHub", "scopes": ["repo:read"]},
                }
            ],
            data_sources=[
                {
                    "id": "issues",
                    "path": "/data/issues",
                    "visibility": "member",
                    "cache_ttl_seconds": 300,
                    "params_schema": [
                        {
                            "key": "state",
                            "type": "select",
                            "label": {"en": "State"},
                            "options": ["open", "closed"],
                        }
                    ],
                    "requires": {"all_of": ["api"]},
                }
            ],
        ),
        id="static-connection-and-source",
    ),
    pytest.param(
        _manifest(
            features=["embeds"],
            connections=[
                {
                    "id": "account",
                    "scope": "interactive",
                    "label": {"en": "Your account"},
                    "fields": [],
                    "connect_path": "/connect/start",
                }
            ],
            embeds=[
                {
                    "id": "board",
                    "path": "/embed/board",
                    "name": {"en": "Board"},
                    "scopes": ["guild", "initiative"],
                    "visibility": "initiative_manager",
                    "capabilities": ["clipboard-write", "fullscreen"],
                    "requires": {"any_of": ["account"]},
                }
            ],
        ),
        id="interactive-connection-and-embed",
    ),
    pytest.param(
        _manifest(
            features=["events", "automations"],
            events=["app.acme.tracker.issue-opened"],
            automation={"nodes": [{"anything": "the service understands"}]},
        ),
        id="events-and-opaque-automation",
    ),
    # The three the platform takes rather than refuses. Each was a real
    # over-strict rule in the first cut of this schema, caught in review: a
    # schema that rejects any of these tells an author their working manifest
    # is broken.
    pytest.param(
        _manifest(
            features=["data"],
            data_sources=[{"id": "s", "path": "/d", "cache_ttl_seconds": 10_000_000}],
        ),
        id="cache-ttl-clamped-not-refused",
    ),
    pytest.param(
        _manifest(
            features=["data"],
            data_sources=[{"id": "s", "path": "/d", "invented_by_a_newer_app": 1}],
            some_future_block={"whatever": True},
        ),
        id="unknown-keys-dropped-not-refused",
    ),
    pytest.param(
        _manifest(
            features=["embeds"],
            embeds=[
                {"id": "e", "path": "/e", "name": {"en": "N" * (MAX_TEXT_LENGTH + 50)}}
            ],
        ),
        id="over-long-label-truncated-not-refused",
    ),
    pytest.param(
        _manifest(
            features=["data"],
            connections=[
                {
                    "id": "api",
                    "scope": "static",
                    "label": {"en": "API"},
                    "fields": [{"key": "t", "type": "secret", "label": {"en": "T"}}],
                }
            ],
            data_sources=[
                {
                    "id": "s",
                    "path": "/d",
                    # One operator plus a key from a newer manifest revision.
                    # The platform reads the operator and drops the rest, so a
                    # rule that counted properties would refuse this.
                    "requires": {"all_of": ["api"], "from_a_newer_revision": True},
                }
            ],
        ),
        id="requires-alongside-an-unknown-key",
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize("manifest", ACCEPTED)
def test_what_the_platform_accepts_satisfies_the_schema(manifest, validator):
    """The direction that matters most: an author whose manifest installs must
    never be told by the schema that it is malformed."""
    platform_accepts(manifest)
    assert list(validator.iter_errors(manifest)) == []


REFUSED_BY_BOTH = [
    pytest.param(
        {"service": {"public_id": "acme.x"}, "features": []}, id="no-app-kind"
    ),
    pytest.param(_manifest(app_kind="tool_instance"), id="wrong-app-kind"),
    pytest.param(
        _manifest(service={"public_id": "no-dot"}), id="public-id-without-dot"
    ),
    pytest.param(_manifest(service={"public_id": "Acme.Tracker"}), id="uppercase-id"),
    pytest.param(_manifest(features=["telepathy"]), id="unknown-feature"),
    pytest.param(
        _manifest(service={"public_id": "acme.x", "protocol": 99}),
        id="unspoken-protocol",
    ),
    pytest.param(
        _manifest(
            features=["data"],
            data_sources=[{"id": "s", "path": "https://elsewhere.test/data"}],
        ),
        id="path-that-is-an-address",
    ),
    pytest.param(
        _manifest(features=["data"], data_sources=[{"id": "s", "path": "/a/../b"}]),
        id="path-climbing-out",
    ),
    pytest.param(
        _manifest(features=["data"], data_sources=[{"id": "UPPER", "path": "/x"}]),
        id="identifier-out-of-charset",
    ),
    pytest.param(
        _manifest(
            features=["embeds"],
            embeds=[
                {
                    "id": "e",
                    "path": "/e",
                    "name": {"en": "E"},
                    "capabilities": ["payment"],
                }
            ],
        ),
        id="capability-not-on-offer",
    ),
    # The two shapes `oneOf` has to keep refusing now that the object no longer
    # counts its properties.
    pytest.param(
        _manifest(
            features=["data"],
            data_sources=[
                {
                    "id": "s",
                    "path": "/d",
                    "requires": {"all_of": ["a"], "any_of": ["b"]},
                }
            ],
        ),
        id="requires-naming-both-operators",
    ),
    pytest.param(
        _manifest(
            features=["data"],
            data_sources=[{"id": "s", "path": "/d", "requires": {}}],
        ),
        id="requires-naming-no-operator",
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize("manifest", REFUSED_BY_BOTH)
def test_what_the_schema_refuses_the_platform_refuses_too(manifest, validator):
    """The other direction, for the rules a schema *can* express: the schema
    must not invent a constraint the platform would have allowed."""
    assert list(validator.iter_errors(manifest)) != [], "schema accepted it"
    with pytest.raises(ValueError):
        platform_accepts(manifest)


@pytest.mark.unit
def test_the_schema_flags_a_localized_value_the_platform_discards(validator):
    """The one place it is stricter on purpose: a non-string entry is dropped
    outright, so it has no effect, and saying so can only help."""
    manifest = _manifest(
        features=["embeds"],
        embeds=[{"id": "e", "path": "/e", "name": {"en": "N", "fr": 7}}],
    )
    platform_accepts(manifest)  # the bad entry is skipped, the good one stands
    assert list(validator.iter_errors(manifest)) != []


# --- where the schema stops -------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "manifest,why",
    [
        (
            _manifest(features=["data"]),
            "a declared feature with no block behind it",
        ),
        (
            _manifest(
                features=["widgets", "data"],
                data_sources=[{"id": "known", "path": "/d"}],
                widgets=[
                    {
                        "id": "w",
                        "meta": {"name": {"en": "W"}},
                        "module_source": "export default () => ({})",
                        "sources": ["absent"],
                    }
                ],
            ),
            "a widget binding a data source that does not exist",
        ),
        (
            _manifest(features=["events"], events=["app.someone-else.thing"]),
            "an event namespaced under another app",
        ),
    ],
)
def test_the_platform_enforces_what_the_schema_cannot(manifest, why, validator):
    """Schema-valid is necessary, not sufficient — written down as cases so the
    boundary is a fact about this build rather than a caveat in a docstring."""
    assert list(validator.iter_errors(manifest)) == [], f"schema caught it: {why}"
    with pytest.raises(ValueError):
        platform_accepts(manifest)

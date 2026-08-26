"""Every field the contract declares is one this build reads.

The vocabulary now arrives from the app-kit rather than being declared here, and
a kit release can reach an author before it reaches a deployment. That makes one
failure possible that could not happen while this build owned both sides: the
contract declares a field, the normalizer does not read it, and the field is
dropped on publish.

It matters because several of them are not descriptions — they are restrictions
an author is asking this build to enforce. ``visibility``, ``requires``,
``actors`` and ``connection.scope`` all narrow who or what reaches something,
and a narrowing that is dropped does not fail loudly at the moment it is lost.

So the inventory is checked in both directions:

* every field the contract declares survives a publish, and
* every key a published definition carries is one the contract declares —
  otherwise this build stores a term no author can discover.

The manifest below is deliberately maximal: it exists to populate every field
once, not to be a realistic app. A field added to the contract and to nothing
else fails here.
"""

import pytest

from app.services.marketplace import contract
from app.services.marketplace.definitions import normalize_listing_definition

#: The endpoint a widget binds and a sample is keyed by, written once.
READ_ENDPOINT = "app.acme.tracker.read"


def maximal_manifest() -> dict:
    """One manifest carrying every field the contract declares.

    Two fields cannot appear beside their neighbours and are covered elsewhere in
    the document: a ``requires`` names exactly one operator, so ``all_of`` and
    ``any_of`` are used in different places; and an emitting endpoint carries
    none of the caller-side fields, so those sit on the read endpoint.
    """
    return {
        "app_kind": "service",
        "service": {"public_id": "acme.tracker", "protocol": 1},
        "features": ["endpoints", "widgets", "embeds", "dashboards"],
        "default_name": "Acme Tracker",
        "connections": [
            {
                "id": "vendor",
                "scope": "interactive",
                "label": {"en": "Vendor"},
                "fields": [
                    {
                        "key": "choice",
                        "type": "select",
                        "label": {"en": "Choice"},
                        "required": True,
                        "options": ["a", "b"],
                        "managed": True,
                    }
                ],
                "connect_path": "/connect",
                "access_hint": {"api": "Acme API", "scopes": ["read"]},
            },
            {
                "id": "other",
                "scope": "static",
                "label": {"en": "Other"},
                "fields": [
                    {"key": "token", "type": "secret", "label": {"en": "Token"}}
                ],
            },
        ],
        "endpoints": [
            {
                "id": READ_ENDPOINT,
                "direction": "read",
                "label": {"en": "Read"},
                "description": {"en": "Reads something"},
                "returns": [
                    {
                        "key": "count",
                        "type": "int",
                        "label": {"en": "Count"},
                        "list": True,
                    }
                ],
                "group": "reports",
                "needs_subject": "tasks",
                "params": [
                    {
                        "key": "choice",
                        "type": "select",
                        "label": {"en": "Choice"},
                        "required": False,
                        "options": ["a", "b"],
                        "picker": "project",
                    }
                ],
                "actors": ["member", "installation"],
                "requires": {"all_of": ["vendor"]},
                "cache_ttl_seconds": 60,
                "visibility": "guild_admin",
            },
            {
                "id": "app.acme.tracker.emitted",
                "direction": "emit",
                "label": {"en": "Emitted"},
            },
        ],
        "widgets": [
            {
                "id": "tile",
                "meta": {"name": {"en": "Tile"}},
                "module_source": "export default () => null;",
                "endpoints": [READ_ENDPOINT],
                # Keyed by the endpoints the widget declared; anything else is
                # dropped, so this is the only key that survives.
                "sample_data": {READ_ENDPOINT: {"count": 1}},
                "requires": {"any_of": ["vendor"]},
            }
        ],
        "embeds": [
            {
                "id": "panel",
                "path": "/panel",
                "name": {"en": "Panel"},
                "scopes": ["guild", "initiative"],
                "visibility": "initiative_manager",
                "capabilities": ["camera"],
                "requires": {"all_of": ["other"]},
            }
        ],
        "dashboards": [
            {
                "uid": "0123456789ABCD",
                "public_id": "acme.board",
                "name": "Board",
                "description": "A ready-made arrangement",
                "layout": {"columns": 6},
                "widgets": [
                    {
                        "id": "w1",
                        "type": "tile",
                        "title": "Tile",
                        "grid": {"x": 0, "y": 0, "w": 3, "h": 2},
                        "binding": {
                            "endpoint_id": READ_ENDPOINT,
                            "params": {"choice": "a"},
                        },
                    }
                ],
            }
        ],
    }


@pytest.fixture(scope="module")
def published() -> dict:
    """The maximal manifest as this build would store it."""
    return normalize_listing_definition("app", maximal_manifest())


def _nodes(published: dict) -> list[tuple[str, dict]]:
    """Each contract object beside the published node that should carry it."""
    connection, other = published["connections"]
    read = published["endpoints"][0]
    widget = published["widgets"][0]
    dashboard = published["dashboards"][0]
    return [
        ("manifest", published),
        ("connection", connection),
        ("connectionField", connection["fields"][0]),
        ("accessHint", connection["access_hint"]),
        ("endpoint", read),
        ("endpointParam", read["params"][0]),
        ("endpointReturn", read["returns"][0]),
        ("widget", widget),
        ("embed", published["embeds"][0]),
        ("bundledDashboard", dashboard),
        ("bundledDashboardWidget", dashboard["widgets"][0]),
        # `requires` names one operator at a time, so the two are covered from
        # the two places that use them.
        ("requires", {**read["requires"], **widget["requires"]}),
        ("other", other),
    ]


@pytest.mark.unit
def test_every_declared_field_survives_a_publish(published):
    """A field the contract declares that nothing here reads is a restriction an
    author asked for and this build would discard without saying so."""
    for owner, node in _nodes(published):
        if owner == "other":
            continue
        missing = [field for field in contract.fields(owner) if field not in node]
        assert not missing, f"{owner} lost {missing}"


@pytest.mark.unit
def test_nothing_is_stored_that_the_contract_does_not_declare(published):
    """The other direction: a key this build writes but the contract does not
    name is one no author can discover, and no schema describes."""
    for owner, node in _nodes(published):
        if owner in {"requires", "other"}:
            continue
        declared = set(contract.fields(owner))
        assert not set(node) - declared, f"{owner} carries undeclared keys"


@pytest.mark.unit
def test_the_maximal_manifest_really_is_maximal(published):
    """The two tests above pass trivially if the fixture stopped covering
    something, so the fixture itself is checked: every object the contract
    defines with fields is one this manifest reaches."""
    reached = {owner for owner, _ in _nodes(published)} - {"other"}
    with_fields = {name for name in contract.objects() if contract.fields(name)}
    assert with_fields - reached == set()


@pytest.mark.unit
def test_an_emitting_endpoint_keeps_what_describes_it(published):
    """An emission is the one endpoint chosen without ever being called, so the
    fields that describe it must survive even though the caller-side ones are
    refused on it."""
    emitted = published["endpoints"][1]
    assert emitted["label"] == {"en": "Emitted"}
    assert emitted["direction"] == "emit"
    for caller_side in (
        "params",
        "requires",
        "cache_ttl_seconds",
        "visibility",
        "actors",
    ):
        assert caller_side not in emitted


# --- values a stored column depends on --------------------------------------


@pytest.mark.unit
def test_the_uid_shape_matches_the_contract():
    """The uid's length and alphabet are the contract's, and they are also a
    column width.

    Deliberately checked rather than read: `models.platform.marketplace` sizes a
    Postgres column with `UID_LENGTH`, so adopting a new value automatically
    would change a stored column without a migration. A cap that reaches the
    database has to break the build and be moved by hand.
    """
    from app.models.platform.marketplace import UID_ALPHABET, UID_LENGTH

    assert UID_LENGTH == contract.cap("uidLength")
    assert frozenset(UID_ALPHABET) == contract.charset("uid")

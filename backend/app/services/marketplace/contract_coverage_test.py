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
                        "list": True,
                    }
                ],
                "actors": ["member", "installation"],
                "requires": {"all_of": ["vendor"]},
                "cache_ttl_seconds": 60,
                "visibility": "guild_admin",
            },
            {
                "id": "app.acme.tracker.written",
                "direction": "write",
                "label": {"en": "Written"},
                "returns": [{"key": "number", "type": "int"}],
                # The same kind and key the emission about it declares, so a
                # consumer resolves both to one address.
                "identity": {"kind": "issue", "key": ["number"]},
            },
            {
                "id": "app.acme.tracker.emitted",
                "direction": "emit",
                "label": {"en": "Emitted"},
                "returns": [{"key": "number", "type": "int"}],
                "identity": {"kind": "issue", "key": ["number"]},
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
    read, written, _emitted = published["endpoints"]
    widget = published["widgets"][0]
    dashboard = published["dashboards"][0]
    return [
        ("manifest", published),
        ("connection", connection),
        ("connectionField", connection["fields"][0]),
        ("accessHint", connection["access_hint"]),
        # A read carries the caller-side fields and a write carries the
        # identity; no single direction carries every field, so the two are
        # measured together.
        ("endpoint", {**read, **written}),
        ("endpointParam", read["params"][0]),
        ("endpointReturn", read["returns"][0]),
        ("widget", widget),
        ("embed", published["embeds"][0]),
        ("bundledDashboard", dashboard),
        ("bundledDashboardWidget", dashboard["widgets"][0]),
        # `requires` names one operator at a time, so the two are covered from
        # the two places that use them.
        ("requires", {**read["requires"], **widget["requires"]}),
        ("endpointIdentity", written["identity"]),
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
    emitted = published["endpoints"][2]
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


# --- what the registrar reports -------------------------------------------


@pytest.mark.unit
def test_a_term_the_contract_does_not_name_is_reported():
    """The whole point of the report: a newer app's extra terms are named."""
    served = maximal_manifest()
    served["rate_limit"] = 5
    served["endpoints"][0]["retries"] = 3
    assert contract.discarded_terms(served) == ["endpoints.0.retries", "rate_limit"]


@pytest.mark.unit
def test_a_term_nested_in_an_inline_object_is_reported():
    """Not every object a manifest carries is a named definition — `service`,
    `layout`, `grid` and `binding` are written inline — and a term added inside
    one is exactly as invisible as a term added at the top.

    This is walked from the contract's own structure rather than from a list of
    where things nest, because that list is the kind of second copy the contract
    exists to remove: it was one, it missed all four of these, and nothing said
    so.
    """
    served = maximal_manifest()
    served["service"]["region"] = "eu"
    served["dashboards"][0]["layout"]["gutter"] = 4
    served["dashboards"][0]["widgets"][0]["grid"]["z"] = 9
    served["dashboards"][0]["widgets"][0]["binding"]["timeout"] = 30

    assert contract.discarded_terms(served) == [
        "dashboards.0.layout.gutter",
        "dashboards.0.widgets.0.binding.timeout",
        "dashboards.0.widgets.0.grid.z",
        "service.region",
    ]


@pytest.mark.unit
def test_an_object_the_contract_leaves_open_reports_nothing():
    """A widget's `meta` and `sample_data` are opaque to the contract, and a
    binding's `params` are named by the author. Keys inside them are nobody's
    to declare, so reporting them would be noise on every honest manifest."""
    served = maximal_manifest()
    served["widgets"][0]["meta"]["whatever"] = 1
    served["widgets"][0]["sample_data"][READ_ENDPOINT] = {"anything": 2}
    served["dashboards"][0]["widgets"][0]["binding"]["params"]["choice"] = "b"

    assert contract.discarded_terms(served) == []


@pytest.mark.unit
def test_a_manifest_this_build_fully_understands_reports_nothing():
    """The ordinary case. A report on an app written against this contract
    would be a false alarm on every verification."""
    assert contract.discarded_terms(maximal_manifest()) == []


# --- what only the app can know --------------------------------------------


@pytest.mark.unit
def test_an_identity_must_name_single_returns_of_its_own_endpoint():
    """Nothing downstream refuses a bad address — it resolves to nothing, and a
    fire somebody was waiting on is dropped without a word. So it is refused
    here, at the one moment somebody can still fix it."""
    from app.services.marketplace.manifest_values import ListingDefinitionError

    def publish(**endpoint):
        body = maximal_manifest()
        body["endpoints"][1].update(endpoint)
        return normalize_listing_definition("app", body)

    with pytest.raises(ListingDefinitionError):
        publish(identity={"kind": "issue", "key": ["nothing_returned"]})

    with pytest.raises(ListingDefinitionError):
        publish(
            returns=[{"key": "numbers", "type": "int", "list": True}],
            identity={"kind": "issue", "key": ["numbers"]},
        )


@pytest.mark.unit
def test_a_read_endpoint_has_no_identity():
    """It touched nothing, so there is nothing for it to address."""
    from app.services.marketplace.manifest_values import ListingDefinitionError

    body = maximal_manifest()
    body["endpoints"][0]["identity"] = {"kind": "issue", "key": ["count"]}
    with pytest.raises(ListingDefinitionError):
        normalize_listing_definition("app", body)

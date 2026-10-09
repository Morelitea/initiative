"""Every field the contract declares is one this build reads.

The vocabulary now arrives from the plugin-kit rather than being declared here, and
a kit release can reach an author before it reaches a deployment. That makes one
failure possible that could not happen while this build owned both sides: the
contract declares a field, the normalizer does not read it, and the field is
dropped on publish.

It matters because several of them are not descriptions — they are restrictions
an author is asking this build to enforce. ``admin_only``, ``requires``,
``actors`` and ``connection.scope`` all narrow who or what reaches something,
and a narrowing that is dropped does not fail loudly at the moment it is lost.

So the inventory is checked in both directions:

* every field the contract declares survives a publish, and
* every key a published definition carries is one the contract declares —
  otherwise this build stores a term no author can discover.

The manifests below are deliberately maximal: they exist to populate every
field once, not to be realistic plug-ins. A plug-in is a container or declarative and
never both, so there are two, and each object is measured across both. A field
added to the contract and to nothing else fails here.
"""

import pytest

from app.services.marketplace import contract
from app.services.marketplace.definitions import normalize_listing_definition

pytestmark = pytest.mark.always

#: The endpoint a widget draws, written once.
READ_ENDPOINT = "plugin.acme.tracker.read"
#: The declarative plug-in's listing, which names it.
DECLARATIVE_ID = "acme.issues"


def maximal_manifest() -> dict:
    """One manifest carrying every field the contract declares.

    Two fields cannot appear beside their neighbours and are covered elsewhere in
    the document: a ``requires`` names exactly one operator, so ``all_of`` and
    ``any_of`` are used in different places; and an emitting endpoint carries
    none of the caller-side fields, so those sit on the read endpoint.
    """
    return {
        "plugin_kind": "service",
        "service": {
            "public_id": "acme.tracker",
            "protocol": 1,
            "scopes": ["projects:write", "comments:read", "plugins:acme.github"],
        },
        "features": ["endpoints", "widgets", "pages", "dashboards"],
        "default_name": "Acme Tracker",
        "minimum_age": {"default": 16, "US": 13},
        "min_plugin_api": "4.2",
        "vendor": {
            "label": {"en": "Acme client"},
            "fields": [
                {
                    "key": "client_id",
                    "type": "string",
                    "required": True,
                    "label": {"en": "Client id"},
                },
                {"key": "private_key", "type": "secret", "label": {"en": "Key"}},
            ],
            "setup": {
                "kind": "github_app_manifest",
                "app": {
                    "name": "Acme Tracker",
                    "url": "https://acme.test",
                    "public": True,
                    "default_permissions": {"issues": "write"},
                    "default_events": ["issues"],
                },
                "values": {"client_id": "client_id", "private_key": "pem"},
            },
        },
        "connections": [
            {
                "id": "vendor",
                "scope": "static",
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
                "flow": {
                    "type": "oauth2",
                    "authorize_url": "https://acme.test/oauth/authorize",
                    "token_url": "https://acme.test/oauth/token",
                    "client_id": "{vendor.client_id}",
                    "client_secret": "{vendor.private_key}",
                    "scopes": ["read"],
                    "pkce": True,
                    "authorize_params": {"prompt": "consent"},
                    "install_url": "https://acme.test/install",
                    "after_connect": True,
                    "revoke": "rfc7009",
                    "revoke_url": "https://acme.test/oauth/revoke",
                },
                "token": {
                    "type": "jwt_bearer",
                    "exchange_url": "https://acme.test/installs/{choice}/token",
                    "iss": "{vendor.client_id}",
                    "key": "{vendor.private_key}",
                    "alg": "RS256",
                    "lifetime": 300,
                },
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
        "webhooks": {
            "verify": {
                "scheme": "hmac_sha256",
                "header": "X-Acme-Signature",
                "prefix": "sha256=",
                "encoding": "hex",
                "secret": "{vendor.private_key}",
            },
            "dedup": "X-Acme-Delivery",
            "route": {"path": "install.id", "connection": "vendor", "field": "choice"},
        },
        "schedules": [{"id": "sync", "every": "15m"}],
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
                    },
                    {
                        "key": "labels",
                        "type": "string",
                        "label": {"en": "Labels"},
                        "list": True,
                    },
                    # A figure counted against its ceiling, so a summary can
                    # draw the two as one measure.
                    {"key": "used", "type": "int", "of": "allowed"},
                    {"key": "allowed", "type": "int"},
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
                        # Values only the plug-in can enumerate, and the sibling
                        # answer it has to be told to enumerate them.
                        "options_from": {
                            "endpoint": READ_ENDPOINT,
                            "key": "count",
                            "label_key": "labels",
                            "needs": {"scope": "scope"},
                        },
                    },
                    {
                        "key": "scope",
                        "type": "string",
                        "label": {"en": "Scope"},
                    },
                ],
                "actors": ["member", "installation"],
                "requires": {"all_of": ["vendor"]},
                "cache_ttl_seconds": 60,
                "admin_only": True,
                "public": True,
            },
            {
                "id": "plugin.acme.tracker.written",
                "direction": "write",
                "label": {"en": "Written"},
                "returns": [{"key": "number", "type": "int"}],
                # The same kind and key the emission about it declares, so a
                # consumer resolves both to one address.
                "identity": {"kind": "issue", "key": ["number"]},
            },
            {
                "id": "plugin.acme.tracker.emitted",
                "direction": "emit",
                "label": {"en": "Emitted"},
                "returns": [{"key": "number", "type": "int"}],
                "identity": {"kind": "issue", "key": ["number"]},
            },
        ],
        "community_summary": READ_ENDPOINT,
        "widgets": [
            {
                "id": "tile",
                "meta": {"name": {"en": "Tile"}},
                "endpoint": READ_ENDPOINT,
                # Reads a single return, a list return and its own words, so
                # every field it names is checked against the endpoint.
                "template": (
                    '<div><metric :value="values.used" :label="strings.title" />'
                    '<ul><li for="r in rows">{{ r.labels }}</li></ul></div>'
                ),
                "strings": {"title": {"en": "Used"}},
                # The endpoint's answer, written in its returns.
                "sample_data": {"count": [1], "labels": ["one"], "used": 1},
                "requires": {"any_of": ["vendor"]},
            }
        ],
        "pages": [
            {
                "id": "panel",
                "path": "/panel",
                "name": {"en": "Panel"},
                "scopes": ["community", "initiative"],
                "admin_only": True,
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


def maximal_declarative_manifest() -> dict:
    """One declarative manifest carrying every declarative term.

    A request sends a body or a GraphQL query, a cursor goes in a parameter or
    a variable, and a route reads a body path or a header, so those are spread
    over several requests.
    """
    api = '"https://api.tracker.example/issues"'
    paged = {
        "kind": "page_number",
        "page_param": "page",
        "per_page_param": "per_page",
        "per_page": 50,
        "items": "response.body",
        "max_pages": 5,
        "on_limit": "truncate",
    }
    return {
        "plugin_kind": "service",
        "features": ["endpoints"],
        "hosts": ["api.tracker.example", "*.tracker.example"],
        "auth": {"header": "X-Tracker-Token", "prefix": ""},
        "vendor": {
            "fields": [
                {"key": "client_id", "type": "string", "label": {"en": "Client"}},
                {"key": "secret", "type": "secret", "label": {"en": "Secret"}},
            ]
        },
        "connections": [
            {
                "id": "workspace",
                "scope": "static",
                "label": {"en": "Workspace"},
                "fields": [
                    {
                        "key": "owner",
                        "type": "string",
                        "label": {"en": "Owner"},
                        "managed": True,
                    }
                ],
                "flow": {
                    "type": "oauth2",
                    "authorize_url": "https://tracker.example/authorize",
                    "token_url": "https://tracker.example/token",
                    "client_id": "{vendor.client_id}",
                    "after_connect": {
                        "request": {
                            "method": "GET",
                            "url": '"https://api.tracker.example/user"',
                            "paging": {
                                "kind": "link_header",
                                "items": "response.body",
                                "max_pages": 3,
                                "on_limit": "truncate",
                            },
                        },
                        "map": '{"values": {"owner": response.body[0].login}}',
                        "refuse_when": "$not($exists(result.values.owner))",
                        "code": "not-installed",
                    },
                },
                "health": {
                    "request": {
                        "method": "GET",
                        "url": '"https://api.tracker.example/" & connection.owner',
                    },
                    "every": "15m",
                    "states": [
                        {
                            "status": "4xx",
                            "when": 'response.body.reason = "gone"',
                            "state": "removed",
                        }
                    ],
                },
            },
            {
                "id": "profile",
                "scope": "interactive",
                "label": {"en": "Your profile"},
                "fields": [],
                "flow": {
                    "type": "oauth2",
                    "authorize_url": "https://tracker.example/authorize",
                    "token_url": "https://tracker.example/token",
                    "client_id": "{vendor.client_id}",
                    "after_connect": {
                        "steps": [
                            {
                                "name": "me",
                                "request": {
                                    "method": "GET",
                                    "url": '"https://api.tracker.example/user"',
                                },
                            },
                            {
                                "name": "home",
                                "request": {
                                    "method": "GET",
                                    "url": '"https://api.tracker.example/users/"'
                                    " & steps.me.body.login",
                                },
                            },
                        ],
                        "map": '{"account_label": steps.home.body.name}',
                    },
                },
            },
        ],
        "webhooks": {
            "verify": {
                "scheme": "hmac_sha256",
                "header": "X-Signature",
                "encoding": "hex",
                "secret": "{vendor.secret}",
            },
            "dedup": "X-Delivery",
            "route": {"header": "X-Owner", "connection": "workspace", "field": "owner"},
            "events": [
                {
                    "when": 'headers."x-event" = "opened"',
                    "emit": "plugin.acme.issues.opened",
                    "map": '{"number": payload.number}',
                }
            ],
            "status": [
                {
                    "when": 'headers."x-event" = "suspend"',
                    "connection": "workspace",
                    "state": "suspended",
                }
            ],
        },
        "endpoints": [
            {
                "id": "plugin.acme.issues.list",
                "direction": "read",
                "returns": [{"key": "titles", "type": "string", "list": True}],
                "unavailable": ["archived"],
                "request": {
                    "method": "GET",
                    "url": api,
                    "query": {"state": '"open"'},
                    "headers": {"Accept": '"application/json"'},
                    "connection": "workspace",
                    "paging": paged,
                },
                "map": '{"titles": response.body.title[]}',
                "errors": [
                    {"status": 410, "when": "response.status = 410", "code": "archived"}
                ],
            },
            {
                "id": "plugin.acme.issues.search",
                "direction": "read",
                "returns": [{"key": "ids", "type": "string", "list": True}],
                "request": {
                    "method": "POST",
                    "url": api,
                    "graphql": {
                        "query": "query($after: String) { ids(after: $after) }",
                        "variables": "{}",
                    },
                    "connection": "workspace",
                    "paging": {
                        "kind": "cursor",
                        "next": "response.body.cursor",
                        "more": "response.body.more",
                        "variable": "after",
                        "items": "response.body.ids",
                        "max_pages": 2,
                        "on_limit": "refuse",
                    },
                },
                "map": '{"ids": response.body[]}',
            },
            {
                "id": "plugin.acme.issues.label",
                "direction": "write",
                "returns": [{"key": "number", "type": "int"}],
                "identity": {"kind": "issue", "key": ["number"]},
                "steps": [
                    {
                        "name": "current",
                        "request": {
                            "method": "GET",
                            "url": api,
                            "connection": "workspace",
                            "paging": {
                                "kind": "cursor",
                                "next": "response.body.next",
                                "more": "$exists(response.body.next)",
                                "param": "cursor",
                                "max_pages": 2,
                                "on_limit": "truncate",
                            },
                        },
                    },
                    {
                        "name": "set",
                        "request": {
                            "method": "PUT",
                            "url": api,
                            "body": '{"labels": steps.current.body.name}',
                            "connection": "workspace",
                        },
                    },
                ],
                "map": '{"number": steps.set.body.number}',
            },
            {
                "id": "plugin.acme.issues.opened",
                "direction": "emit",
                "returns": [{"key": "number", "type": "int"}],
            },
        ],
    }


@pytest.fixture(scope="module")
def published() -> dict:
    """The maximal manifest as this build would store it."""
    return normalize_listing_definition("plugin", maximal_manifest())


@pytest.fixture(scope="module")
def declarative() -> dict:
    """The maximal declarative manifest as this build would store it."""
    return normalize_listing_definition(
        "plugin", maximal_declarative_manifest(), public_id=DECLARATIVE_ID
    )


@pytest.fixture(scope="module")
def nodes(published, declarative) -> list[tuple[str, dict]]:
    return _nodes(published, declarative)


def _nodes(published: dict, declarative: dict) -> list[tuple[str, dict]]:
    """Each contract object beside the published node that should carry it,
    measured across both manifests where neither alone carries every field."""
    connection, other = published["connections"]
    read, written, _emitted = published["endpoints"]
    widget = published["widgets"][0]
    dashboard = published["dashboards"][0]
    workspace, profile = declarative["connections"]
    after = workspace["flow"]["after_connect"]
    listed, searched, labelled, _opened = declarative["endpoints"]
    current, setting = labelled["steps"]
    hooks = declarative["webhooks"]
    return [
        ("manifest", {**published, **declarative}),
        ("connection", {**connection, **workspace}),
        ("connectionField", connection["fields"][0]),
        ("connectionFlow", connection["flow"]),
        ("connectionToken", connection["token"]),
        ("vendor", published["vendor"]),
        ("vendorField", published["vendor"]["fields"][0]),
        ("githubAppManifestSetup", published["vendor"]["setup"]),
        ("githubAppManifest", published["vendor"]["setup"]["app"]),
        ("webhooks", {**published["webhooks"], **hooks}),
        ("webhookVerify", published["webhooks"]["verify"]),
        ("webhookRoute", {**published["webhooks"]["route"], **hooks["route"]}),
        ("schedule", published["schedules"][0]),
        ("accessHint", connection["access_hint"]),
        # A read carries the caller-side fields and a write carries the
        # identity; no single direction carries every field, so the two are
        # measured together.
        ("endpoint", {**read, **written, **listed, **labelled}),
        ("endpointParam", read["params"][0]),
        # `list` and `of` never share a return: a list has no one figure to
        # count against anything.
        ("endpointReturn", {**read["returns"][0], **read["returns"][2]}),
        ("widget", widget),
        ("page", published["pages"][0]),
        ("bundledDashboard", dashboard),
        ("bundledDashboardWidget", dashboard["widgets"][0]),
        # `requires` names one operator at a time, so the two are covered from
        # the two places that use them.
        ("requires", {**read["requires"], **widget["requires"]}),
        ("endpointIdentity", written["identity"]),
        ("vendorAuth", declarative["auth"]),
        (
            "vendorRequest",
            {**listed["request"], **searched["request"], **setting["request"]},
        ),
        ("graphqlRequest", searched["request"]["graphql"]),
        ("requestStep", current),
        ("pageNumberPaging", listed["request"]["paging"]),
        ("linkHeaderPaging", after["request"]["paging"]),
        (
            "cursorPaging",
            {**searched["request"]["paging"], **current["request"]["paging"]},
        ),
        ("errorRule", listed["errors"][0]),
        # A call is one request or its steps, so the two after_connects are
        # measured together.
        ("afterConnect", {**after, **profile["flow"]["after_connect"]}),
        ("connectionHealth", workspace["health"]),
        ("healthState", workspace["health"]["states"][0]),
        ("webhookEvent", hooks["events"][0]),
        ("webhookStatus", hooks["status"][0]),
        ("other", other),
    ]


def test_every_declared_field_survives_a_publish(nodes):
    """A field the contract declares that nothing here reads is a restriction an
    author asked for and this build would discard without saying so."""
    for owner, node in nodes:
        if owner == "other":
            continue
        missing = [field for field in contract.fields(owner) if field not in node]
        assert not missing, f"{owner} lost {missing}"


def test_nothing_is_stored_that_the_contract_does_not_declare(nodes):
    """The other direction: a key this build writes but the contract does not
    name is one no author can discover, and no schema describes."""
    for owner, node in nodes:
        if owner in {"requires", "other"}:
            continue
        declared = set(contract.fields(owner))
        assert not set(node) - declared, f"{owner} carries undeclared keys"


def test_every_service_field_survives_a_publish(published):
    """``service`` is written inline rather than as a named object, so the
    inventory above does not reach it; its fields are measured here."""
    declared = contract.manifest_schema()["properties"]["service"]["properties"]
    assert set(declared) == set(published["service"])
    assert published["service"]["scopes"] == [
        "comments:read",
        "plugins:acme.github",
        "projects:write",
    ]


def test_the_maximal_manifests_really_are_maximal(nodes):
    """The two tests above pass trivially if the fixtures stopped covering
    something, so the fixtures themselves are checked: every object the
    contract defines with fields is one these manifests reach."""
    reached = {owner for owner, _ in nodes} - {"other"}
    with_fields = {name for name in contract.objects() if contract.fields(name)}
    assert with_fields - reached == set()


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
        "actors",
        "admin_only",
        "public",
    ):
        assert caller_side not in emitted


# --- values a stored column depends on --------------------------------------


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


def test_a_term_the_contract_does_not_name_is_reported():
    """The whole point of the report: a newer plug-in's extra terms are named."""
    served = maximal_manifest()
    served["rate_limit"] = 5
    served["endpoints"][0]["retries"] = 3
    assert contract.discarded_terms(served) == ["endpoints.0.retries", "rate_limit"]


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


def test_an_object_the_contract_leaves_open_reports_nothing():
    """A widget's `meta` and `sample_data` are opaque to the contract, and its
    `strings` keys and a binding's `params` are named by the author. Keys inside
    them are nobody's to declare, so reporting them would be noise on every
    honest manifest."""
    served = maximal_manifest()
    served["widgets"][0]["meta"]["whatever"] = 1
    served["widgets"][0]["sample_data"]["anything"] = 2
    served["widgets"][0]["strings"]["subtitle"] = {"en": "Of"}
    served["dashboards"][0]["widgets"][0]["binding"]["params"]["choice"] = "b"

    assert contract.discarded_terms(served) == []


def test_a_manifest_this_build_fully_understands_reports_nothing():
    """The ordinary case. A report on a plug-in written against this contract
    would be a false alarm on every verification."""
    assert contract.discarded_terms(maximal_manifest()) == []


# --- what only the plug-in can know --------------------------------------------


def test_an_identity_must_name_single_returns_of_its_own_endpoint():
    """Nothing downstream refuses a bad address — it resolves to nothing, and a
    fire somebody was waiting on is dropped without a word. So it is refused
    here, at the one moment somebody can still fix it."""
    from app.services.marketplace.manifest_values import ListingDefinitionError

    def publish(**endpoint):
        body = maximal_manifest()
        body["endpoints"][1].update(endpoint)
        return normalize_listing_definition("plugin", body)

    with pytest.raises(ListingDefinitionError):
        publish(identity={"kind": "issue", "key": ["nothing_returned"]})

    with pytest.raises(ListingDefinitionError):
        publish(
            returns=[{"key": "numbers", "type": "int", "list": True}],
            identity={"kind": "issue", "key": ["numbers"]},
        )


def test_a_read_endpoint_has_no_identity():
    """It touched nothing, so there is nothing for it to address."""
    from app.services.marketplace.manifest_values import ListingDefinitionError

    body = maximal_manifest()
    body["endpoints"][0]["identity"] = {"kind": "issue", "key": ["count"]}
    with pytest.raises(ListingDefinitionError):
        normalize_listing_definition("plugin", body)


# --- a vendor's own setup flow ---------------------------------------------


@pytest.mark.parametrize(
    "values",
    [
        {"client_id": "pem"},
        {"client_id": "client_id", "private_key": "client_id"},
        {"nothing": "id"},
        {"client_id": "token"},
        {},
    ],
    ids=["secret-to-plain", "twice", "undeclared", "unknown", "empty"],
)
def test_a_setup_writes_each_answer_once_and_secrets_only_to_a_secret(values):
    """What GitHub answers with is written to the fields the setup names, so a
    secret one meeting a plain field would be shown on the settings form."""
    from app.services.marketplace.manifest_values import ListingDefinitionError

    body = maximal_manifest()
    body["vendor"]["setup"]["values"] = values
    with pytest.raises(ListingDefinitionError):
        normalize_listing_definition("plugin", body)


# --- container or declarative ----------------------------------------------


def _member_request_not_required(body: dict) -> None:
    """A request on a member's connection the endpoint does not require."""
    body["connections"].append(
        {
            "id": "account",
            "scope": "interactive",
            "label": {"en": "Your account"},
            "fields": [],
            "flow": {
                "type": "oauth2",
                "authorize_url": "https://tracker.example/authorize",
                "token_url": "https://tracker.example/token",
                "client_id": "{vendor.client_id}",
            },
        }
    )
    body["endpoints"][0]["request"]["connection"] = "account"


def _with(build, change):
    body = build()
    change(body)
    return body


@pytest.mark.parametrize(
    "body",
    [
        _with(maximal_manifest, lambda b: b.update(hosts=["api.acme.test"])),
        _with(
            maximal_manifest,
            lambda b: b["endpoints"][0].update(map='{"count": [1]}'),
        ),
        _with(
            maximal_manifest,
            lambda b: b["connections"][0]["flow"].update(
                after_connect=maximal_declarative_manifest()["connections"][0]["flow"][
                    "after_connect"
                ]
            ),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b.update(schedules=[{"id": "sync", "every": "15m"}]),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["connections"][0]["flow"].update(after_connect=True),
        ),
        _with(maximal_declarative_manifest, lambda b: b.pop("hosts")),
        _with(maximal_declarative_manifest, lambda b: b["endpoints"][0].pop("request")),
        _with(
            maximal_declarative_manifest,
            lambda b: b["endpoints"][0].update(map="steps.later.body"),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["connections"][1]["flow"]["after_connect"].update(
                request={"method": "GET", "url": '"https://api.tracker.example/"'}
            ),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["connections"][1]["flow"]["after_connect"].update(
                map="steps.later.body"
            ),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["endpoints"][0].update(map='{"titles": ['),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["endpoints"][0]["request"].update(url='"https://x" &'),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["endpoints"][0]["request"]["headers"].update(
                {"x-tracker-token": '"mine"'}
            ),
        ),
        _with(
            maximal_declarative_manifest, lambda b: b["endpoints"][0].update(retries=3)
        ),
        _with(maximal_declarative_manifest, _member_request_not_required),
    ],
    ids=[
        "container-hosts",
        "container-map",
        "container-after-connect-request",
        "declarative-schedules",
        "declarative-after-connect-hook",
        "declarative-no-hosts",
        "declarative-no-request",
        "declarative-reads-a-later-step",
        "after-connect-request-and-steps",
        "after-connect-reads-a-later-step",
        "declarative-map-does-not-parse",
        "declarative-url-does-not-parse",
        "declarative-sets-the-credential",
        "unknown-endpoint-term",
        "member-connection-not-in-requires",
    ],
)
def test_one_plugin_is_one_kind_and_says_only_what_its_kind_says(body):
    """A plug-in is a container or declarative, never both, and a declarative
    plug-in's expressions parse and read only the steps before them. An endpoint
    is closed: a misspelt term is refused, not dropped."""
    from app.services.marketplace.manifest_values import ListingDefinitionError

    with pytest.raises(ListingDefinitionError):
        normalize_listing_definition("plugin", body, public_id=DECLARATIVE_ID)


def test_a_declarative_manifest_is_named_by_its_listing():
    """Its endpoints are namespaced under the listing's public id, since there
    is no service block to name it."""
    from app.services.marketplace.manifest_values import ListingDefinitionError

    with pytest.raises(ListingDefinitionError):
        normalize_listing_definition("plugin", maximal_declarative_manifest())
    with pytest.raises(ListingDefinitionError):
        normalize_listing_definition(
            "plugin", maximal_declarative_manifest(), public_id="acme.other"
        )
    assert contract.discarded_terms(maximal_declarative_manifest()) == []

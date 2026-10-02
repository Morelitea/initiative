"""A declarative endpoint, run as the SDK's ``runEndpoint`` runs it.

The app is the SDK's own test app (``test/support/app.ts``, 1.4.0), and each
case asserts what its ``test/testing.test.ts`` asserts: the requests rendered,
in order, and what the run answered. The vendor is ``FakeVendor``'s API,
answering from recorded answers; the one difference from the SDK's rendered
requests is the credential, which only Initiative adds.
"""

from datetime import datetime, timezone

import pytest

from app.core.messages import AppDataMessages
from app.services.marketplace.app_data import AppDataError
from app.services.marketplace.declarative import run_endpoint
from app.services.marketplace.definitions import normalize_listing_definition
from app.testing.fake_vendor import FakeVendor

NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
API = "https://api.tracker.example"
CREDENTIALS = {"workspace": "tok-workspace", "account": "tok-account"}
WORKSPACE = {"workspace": {"owner": "acme"}}


def _api(path: str) -> str:
    return f'"{API}{path}"'


def issues_app(**changes) -> dict:
    """The SDK's ``issuesApp``, as Initiative stores it."""
    endpoints: dict[str, dict] = {
        "open-issues": {
            "direction": "read",
            "params": [
                {
                    "key": "state",
                    "type": "select",
                    "options": ["Open", "Closed"],
                    "label": {"en": "State"},
                }
            ],
            "returns": [
                {"key": "titles", "type": "string", "list": True},
                {"key": "total", "type": "int"},
            ],
            "request": {
                "method": "GET",
                "url": f'{_api("/repos/")} & connection.owner & "/issues"',
                "query": {
                    "state": "$lowercase(params.state)",
                    "labels": "params.labels",
                },
                "headers": {"Accept": '"application/json"'},
                "connection": "workspace",
                "paging": {
                    "kind": "page_number",
                    "page_param": "page",
                    "per_page_param": "per_page",
                    "per_page": 2,
                    "max_pages": 2,
                    "on_limit": "refuse",
                },
            },
            "map": '{"titles": response.body.title[], "total": $count(response.body)}',
        },
        "label": {
            "direction": "write",
            "returns": [{"key": "labels", "type": "string", "list": True}],
            "unavailable": ["locked"],
            "steps": [
                {
                    "name": "current",
                    "request": {
                        "method": "GET",
                        "url": f'{_api("/issues/")} & params.number & "/labels"',
                        "connection": "workspace",
                    },
                },
                {
                    "name": "set",
                    "request": {
                        "method": "PUT",
                        "url": f'{_api("/issues/")} & params.number & "/labels"',
                        "body": '{"labels": $append(steps.current.body.name, params.label)}',
                        "connection": "workspace",
                    },
                },
            ],
            "map": '{"labels": steps.set.body.name[]}',
            "errors": [
                {
                    "status": 422,
                    "when": 'response.body.message = "locked"',
                    "code": "locked",
                }
            ],
        },
        "search": {
            "direction": "read",
            # The SDK's test app leaves this out; Initiative requires a member
            # connection a request uses to be named in requires.
            "requires": {"all_of": ["account"]},
            "returns": [{"key": "ids", "type": "string", "list": True}],
            "request": {
                "method": "POST",
                "url": _api("/graphql"),
                "graphql": {
                    "query": "query($after: String) { issues(after: $after) { nodes { id } } }",
                    "variables": '{"after": null}',
                },
                "connection": "account",
                "paging": {
                    "kind": "cursor",
                    "next": "response.body.data.issues.pageInfo.endCursor",
                    "more": "response.body.data.issues.pageInfo.hasNextPage",
                    "variable": "after",
                    "items": "response.body.data.issues.nodes",
                    "max_pages": 3,
                    "on_limit": "truncate",
                },
            },
            "map": '{"ids": response.body.id[]}',
        },
    }
    for name, change in changes.items():
        endpoints[name] = {**endpoints.get(name, {}), **change}
    return normalize_listing_definition(
        "app",
        {
            "app_kind": "service",
            "features": ["endpoints"],
            "hosts": ["api.tracker.example", "*.tracker.example"],
            "connections": [
                {
                    "id": "workspace",
                    "scope": "static",
                    "label": {"en": "Workspace"},
                    "fields": [
                        {"key": "owner", "type": "string", "label": {"en": "Owner"}}
                    ],
                },
                {
                    "id": "account",
                    "scope": "interactive",
                    "label": {"en": "Your account"},
                    "fields": [],
                    "flow": {
                        "type": "oauth2",
                        "authorize_url": "https://tracker.example/authorize",
                        "token_url": "https://tracker.example/token",
                        "client_id": "abc",
                    },
                },
            ],
            "endpoints": [
                {"id": f"app.acme.issues.{name}", **endpoint}
                for name, endpoint in endpoints.items()
            ],
        },
        public_id="acme.issues",
    )


@pytest.fixture
def vendor(monkeypatch) -> FakeVendor:
    vendor = FakeVendor(api_host="api.tracker.example")
    vendor.install(monkeypatch)
    return vendor


async def _run(
    name: str, *, params=None, definition=None, connections=WORKSPACE
) -> dict:
    definition = definition or issues_app()
    endpoint = next(
        entry for entry in definition["endpoints"] if entry["id"].endswith(f".{name}")
    )
    return await run_endpoint(
        definition,
        endpoint,
        params=params or {},
        connections=connections,
        credentials=CREDENTIALS,
        now=NOW,
    )


async def test_each_page_is_rendered_and_the_map_reads_every_pages_items(vendor):
    vendor.api_answers = [
        {"body": [{"title": "A"}, {"title": "B"}]},
        {"body": [{"title": "C"}]},
    ]
    result = await _run("open-issues", params={"state": "Open"})

    assert [request["url"] for request in vendor.api_requests] == [
        f"{API}/repos/acme/issues?state=open&page={page}&per_page=2" for page in (1, 2)
    ]
    first = vendor.api_requests[0]
    assert first["method"] == "GET"
    assert first["headers"]["accept"] == "application/json"
    assert first["headers"]["authorization"] == "Bearer tok-workspace"
    assert result == {"titles": ["A", "B", "C"], "total": 3}


async def test_a_range_past_max_pages_is_refused_when_on_limit_says_so(vendor):
    full = {"body": [{"title": "A"}, {"title": "B"}]}
    vendor.api_answers = [full, full]
    assert await _run("open-issues") == {"unavailable": "range-too-large"}


async def test_a_truncating_range_answers_the_pages_it_read(vendor):
    full = {"body": [{"title": "A"}, {"title": "B"}]}
    vendor.api_answers = [full, full]
    definition = issues_app(
        **{
            "open-issues": {
                "request": {
                    **issues_app()["endpoints"][0]["request"],
                    "paging": {
                        "kind": "page_number",
                        "page_param": "page",
                        "per_page": 2,
                        "max_pages": 2,
                        "on_limit": "truncate",
                    },
                }
            }
        }
    )
    result = await _run("open-issues", definition=definition)
    assert result == {"titles": ["A", "B", "A", "B"], "total": 4}
    assert vendor.api_requests[1]["url"] == f"{API}/repos/acme/issues?page=2"


async def test_steps_run_in_order_each_reading_the_ones_before_it(vendor):
    vendor.api_answers = [
        {"body": [{"name": "ui"}]},
        {"body": [{"name": "ui"}, {"name": "bug"}]},
    ]
    result = await _run("label", params={"number": 7, "label": "bug"})

    second = vendor.api_requests[1]
    assert (second["method"], second["url"]) == ("PUT", f"{API}/issues/7/labels")
    assert second["body"] == {"labels": ["ui", "bug"]}
    assert second["headers"]["content-type"] == "application/json"
    assert result == {"labels": ["ui", "bug"]}


@pytest.mark.parametrize(
    "answer,answered",
    [
        ({"status": 422, "body": {"message": "locked"}}, "locked"),
        ({"status": 422, "body": {"message": "bad"}}, "invalid"),
        ({"status": 404}, "not-found"),
        ({"status": 403}, "not-authorized"),
        ({"status": 429}, None),
        ({"status": 502}, None),
    ],
)
async def test_an_answer_means_what_its_rule_or_the_default_says(
    vendor, answer, answered
):
    vendor.api_answers = [answer]
    if answered is None:
        with pytest.raises(AppDataError) as refused:
            await _run("label", params={"number": 7})
        assert refused.value.code == AppDataMessages.SERVICE_UNAVAILABLE
        assert refused.value.status_code == 502
    else:
        assert await _run("label", params={"number": 7}) == {"unavailable": answered}
    assert [request["method"] for request in vendor.api_requests] == ["GET"]


async def test_connections_holds_each_connection_requires_names(vendor):
    """A request on the member's connection reads the community's by id; a
    connection ``requires`` does not name is not there."""
    definition = issues_app(
        comment={
            "direction": "write",
            "requires": {"all_of": ["workspace", "account"]},
            "returns": [{"key": "id", "type": "int"}],
            "request": {
                "method": "POST",
                "url": f'{_api("/repos/")} & connections.workspace.owner & "/comments"',
                "body": '{"seen": connections, "login": connection.login}',
                "connection": "account",
            },
            "map": '{"id": response.body.id}',
        }
    )
    vendor.api_answers = [{"body": {"id": 9}}]
    result = await _run(
        "comment",
        definition=definition,
        connections={
            **WORKSPACE,
            "account": {"login": "alice"},
            "other": {"owner": "elsewhere"},
        },
    )

    sent = vendor.api_requests[0]
    assert sent["url"] == f"{API}/repos/acme/comments"
    assert sent["headers"]["authorization"] == "Bearer tok-account"
    assert sent["body"] == {
        "seen": {"workspace": {"owner": "acme"}, "account": {"login": "alice"}},
        "login": "alice",
    }
    assert result == {"id": 9}


async def test_a_graphql_cursor_is_sent_in_its_variable_from_the_second_page(vendor):
    def page(ids, more):
        return {
            "body": {
                "data": {
                    "issues": {
                        "nodes": [{"id": id_} for id_ in ids],
                        "pageInfo": {"endCursor": ids[-1], "hasNextPage": more},
                    }
                }
            }
        }

    vendor.api_answers = [page(["a"], True), page(["b"], False)]
    result = await _run("search")

    assert [request["body"]["variables"] for request in vendor.api_requests] == [
        {"after": None},
        {"after": "a"},
    ]
    assert vendor.api_requests[0]["headers"]["authorization"] == "Bearer tok-account"
    assert result == {"ids": ["a", "b"]}


async def test_a_link_header_is_followed_on_the_apps_hosts_only(vendor):
    listing = {
        "request": {
            "method": "GET",
            "url": _api("/issues"),
            "connection": "workspace",
            "paging": {"kind": "link_header", "max_pages": 3, "on_limit": "truncate"},
        },
        "map": '{"titles": response.body.title[], "total": $count(response.body)}',
    }
    definition = issues_app(**{"open-issues": listing})
    vendor.api_answers = [
        {
            "headers": {"Link": f'<{API}/issues?page=2>; rel="next"'},
            "body": [{"title": "A"}],
        },
        {
            "headers": {"Link": '<https://elsewhere.example/more>; rel="next"'},
            "body": [{"title": "B"}],
        },
    ]
    result = await _run("open-issues", definition=definition)

    assert result == {"unavailable": "mapping-failed"}
    assert [request["url"] for request in vendor.api_requests] == [
        f"{API}/issues",
        f"{API}/issues?page=2",
    ]


@pytest.mark.parametrize(
    "url",
    [
        '"https://elsewhere.example/issues"',
        '"http://api.tracker.example/issues"',
        '"https://api.tracker.example:8443/issues"',
        '"https://deep.api.tracker.example/issues"',
        "42",
    ],
)
async def test_a_request_off_the_apps_hosts_is_never_sent(vendor, url):
    definition = issues_app(
        **{
            "open-issues": {
                "request": {"method": "GET", "url": url, "connection": "workspace"},
            }
        }
    )
    assert await _run("open-issues", definition=definition) == {
        "unavailable": "mapping-failed"
    }
    assert vendor.api_requests == []


async def test_a_cursor_in_a_parameter_and_the_apps_own_auth(vendor):
    definition = issues_app(
        **{
            "open-issues": {
                "request": {
                    "method": "GET",
                    "url": _api("/issues"),
                    "connection": "workspace",
                    "paging": {
                        "kind": "cursor",
                        "next": "response.body.next",
                        "more": "$exists(response.body.next)",
                        "param": "cursor",
                        "items": "response.body.items",
                        "max_pages": 3,
                        "on_limit": "truncate",
                    },
                },
            }
        }
    )
    definition["auth"] = {"header": "X-Tracker-Token", "prefix": ""}
    vendor.api_answers = [
        {"body": {"items": [{"title": "A"}], "next": "c 2"}},
        {"body": {"items": [{"title": "B"}]}},
    ]
    result = await _run("open-issues", definition=definition)

    assert [request["url"] for request in vendor.api_requests] == [
        f"{API}/issues",
        f"{API}/issues?cursor=c+2",
    ]
    assert vendor.api_requests[0]["headers"]["x-tracker-token"] == "tok-workspace"
    assert "authorization" not in vendor.api_requests[0]["headers"]
    assert result == {"titles": ["A", "B"], "total": 2}


@pytest.mark.parametrize(
    "mapping,answered",
    [
        ('{"titles": [1]}', "mapping-failed"),
        ('{"stranger": 1}', "mapping-failed"),
        ('{"unavailable": "locked"}', "mapping-failed"),
        ('{"unavailable": "not-found"}', "not-found"),
        ('$pad("", 1048577, "x")', "mapping-failed"),
    ],
    ids=["wrong-type", "undeclared", "undeclared-code", "platform-code", "too-large"],
)
async def test_a_map_answers_its_returns_or_a_code_of_its_own(
    vendor, mapping, answered
):
    """A map that does not fit the declared returns, names a code the endpoint
    does not have, or passes an expression bound answers mapping-failed."""
    vendor.api_answers = [{"body": []}]
    definition = issues_app(**{"open-issues": {"map": mapping}})
    assert await _run("open-issues", definition=definition) == {"unavailable": answered}

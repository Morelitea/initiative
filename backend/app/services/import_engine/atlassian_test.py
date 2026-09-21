"""Reading somebody else's site: what we ask it, and what we do when it
answers badly.

Egress is stubbed at ``request_public_target`` — the same seam the AI and
webhook paths are tested through. What matters here is the *shape* of the
conversation (which paths, which auth, which method) and that every way a
foreign server can misbehave becomes a code rather than prose.
"""

import base64

import httpx
import pytest

from app.core.messages import ImportEngineMessages
from app.services.import_engine import atlassian
from app.services.import_engine.contract import ImportEngineError

pytestmark = pytest.mark.unit


CREDENTIAL = atlassian.AtlassianCredential(
    site_url="https://acme.atlassian.net",
    email="someone@example.com",
    api_token="shhh",
)


def _response(status_code: int, payload=None, *, text: str | None = None):
    if text is not None:
        return httpx.Response(status_code, text=text)
    return httpx.Response(status_code, json=payload if payload is not None else {})


def _stub(monkeypatch, handler):
    """Answer every outbound call with ``handler(method, url, json)``."""
    calls: list[dict] = []

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        calls.append({"method": method, "url": url, "headers": headers, "json": json})
        return handler(method, url, json)

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    return calls


# --- the address -----------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://acme.atlassian.net", "https://acme.atlassian.net"),
        ("acme.atlassian.net", "https://acme.atlassian.net"),
        ("https://acme.atlassian.net/", "https://acme.atlassian.net"),
        # What a person actually pastes: a board, deep inside one product.
        (
            "https://acme.atlassian.net/jira/software/projects/ACME/boards/3",
            "https://acme.atlassian.net",
        ),
        ("  https://acme.atlassian.net  ", "https://acme.atlassian.net"),
        # A port is part of the address.
        ("https://acme.example.com:8443/wiki", "https://acme.example.com:8443"),
    ],
)
def test_a_site_is_read_down_to_its_host(raw, expected):
    assert atlassian.normalize_site_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "http://acme.atlassian.net", "https://"])
def test_a_site_we_cannot_call_is_refused(raw):
    """No scheme-less nonsense, and no http: the token would go in the clear,
    which is not a thing to support for a credential somebody typed."""
    with pytest.raises(ImportEngineError) as exc:
        atlassian.normalize_site_url(raw)
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE


# --- one call --------------------------------------------------------------


async def test_the_token_travels_as_basic_auth(monkeypatch):
    calls = _stub(monkeypatch, lambda m, u, j: _response(200, {"ok": True}))
    await atlassian.get_json(CREDENTIAL, "/rest/api/3/myself")

    expected = base64.b64encode(b"someone@example.com:shhh").decode()
    assert calls[0]["headers"]["Authorization"] == f"Basic {expected}"
    assert calls[0]["url"] == "https://acme.atlassian.net/rest/api/3/myself"


@pytest.mark.parametrize(
    "status_code,code",
    [
        (401, ImportEngineMessages.IMPORT_SOURCE_AUTH),
        (403, ImportEngineMessages.IMPORT_SOURCE_AUTH),
        (429, ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED),
        (500, ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE),
        (404, ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE),
    ],
)
async def test_every_refusal_becomes_a_code(monkeypatch, status_code, code):
    _stub(monkeypatch, lambda m, u, j: _response(status_code))
    with pytest.raises(ImportEngineError) as exc:
        await atlassian.get_json(CREDENTIAL, "/rest/api/3/myself")
    assert exc.value.code == code


async def test_a_body_that_is_not_json_is_not_an_answer(monkeypatch):
    """A proxy's error page comes back 200 with HTML in it. That is the
    network talking, not Atlassian."""
    _stub(monkeypatch, lambda m, u, j: _response(200, text="<html>nope</html>"))
    with pytest.raises(ImportEngineError) as exc:
        await atlassian.get_json(CREDENTIAL, "/rest/api/3/myself")
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE


async def test_a_private_address_is_refused_not_fetched(monkeypatch):
    from app.services.webhook_target_url import WebhookTargetUrlPrivateError

    async def fake_request(*a, **kw):
        raise WebhookTargetUrlPrivateError("private")

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    with pytest.raises(ImportEngineError) as exc:
        await atlassian.get_json(CREDENTIAL, "/rest/api/3/myself")
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_PRIVATE_HOST


async def test_a_site_that_will_not_answer_is_unreachable(monkeypatch):
    async def fake_request(*a, **kw):
        raise httpx.ConnectTimeout("too slow")

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    with pytest.raises(ImportEngineError) as exc:
        await atlassian.get_json(CREDENTIAL, "/rest/api/3/myself")
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE


# --- looking around --------------------------------------------------------


def _site(*, projects=None, spaces=None, jira_status=200, confluence_status=200):
    """A site that answers the four calls a probe makes."""

    def handler(method, url, json):
        if "/rest/api/3/project/search" in url:
            if jira_status != 200:
                return _response(jira_status)
            return _response(200, {"values": projects or []})
        if "/rest/api/3/search/approximate-count" in url:
            return _response(200, {"count": 42})
        if "/wiki/api/v2/spaces" in url:
            if confluence_status != 200:
                return _response(confluence_status)
            return _response(200, {"results": spaces or []})
        if "/wiki/rest/api/search" in url:
            return _response(200, {"totalSize": 7})
        return _response(404)

    return handler


async def test_a_probe_lists_both_products_with_their_counts(monkeypatch):
    calls = _stub(
        monkeypatch,
        _site(
            projects=[{"id": "1", "key": "ACME", "name": "Acme Board"}],
            spaces=[{"id": "9", "key": "DOCS", "name": "Docs"}],
        ),
    )
    jira, confluence = await atlassian.probe_site(CREDENTIAL)

    assert jira.available and confluence.available
    assert [(p.key, p.issue_count) for p in jira.projects] == [("ACME", 42)]
    assert [(s.key, s.page_count) for s in confluence.spaces] == [("DOCS", 7)]
    # The count is asked for as a POST, which is how the surviving Jira search
    # API takes a JQL.
    counts = [c for c in calls if "approximate-count" in c["url"]]
    assert counts and counts[0]["method"] == "POST"
    assert counts[0]["json"] == {"jql": 'project = "ACME"'}


async def test_a_site_with_only_one_product_still_connects(monkeypatch):
    """Plenty of sites run Jira and no Confluence. That is not a failure, and
    it must not stop somebody importing the product they do have."""
    _stub(
        monkeypatch,
        _site(
            projects=[{"id": "1", "key": "ACME", "name": "Acme"}],
            confluence_status=404,
        ),
    )
    jira, confluence = await atlassian.probe_site(CREDENTIAL)

    assert jira.available
    assert not confluence.available
    assert confluence.reason == ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE
    assert confluence.spaces == []


async def test_a_rejected_token_fails_the_whole_probe(monkeypatch):
    """Unlike a missing product, a token the site will not take is the
    person's problem to fix — the wizard has to say so rather than show an
    empty list."""
    _stub(monkeypatch, _site(jira_status=401))
    with pytest.raises(ImportEngineError) as exc:
        await atlassian.probe_site(CREDENTIAL)
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_AUTH


async def test_a_site_with_neither_product_is_the_wrong_address(monkeypatch):
    _stub(monkeypatch, _site(jira_status=404, confluence_status=404))
    with pytest.raises(ImportEngineError) as exc:
        await atlassian.probe_site(CREDENTIAL)
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE


async def test_one_unreadable_project_does_not_fail_the_probe(monkeypatch):
    """A count is a convenience. A project that will not answer reports no
    number rather than taking the whole site down with it."""

    def handler(method, url, json):
        if "/rest/api/3/project/search" in url:
            return _response(
                200,
                {
                    "values": [
                        {"id": "1", "key": "OK", "name": "Fine"},
                        {"id": "2", "key": "BAD", "name": "Locked"},
                    ]
                },
            )
        if "/rest/api/3/search/approximate-count" in url:
            if json and "BAD" in json.get("jql", ""):
                return _response(500)
            return _response(200, {"count": 3})
        if "/wiki/api/v2/spaces" in url:
            return _response(200, {"results": []})
        return _response(404)

    _stub(monkeypatch, handler)
    jira, _ = await atlassian.probe_site(CREDENTIAL)
    assert [(p.key, p.issue_count) for p in jira.projects] == [("OK", 3), ("BAD", None)]


async def test_a_huge_site_is_cut_rather_than_refused(monkeypatch):
    """One connect must not become a thousand outbound calls. The listing is
    capped, and only the first page of it is counted."""
    many = [{"id": str(i), "key": f"P{i}", "name": f"Project {i}"} for i in range(400)]
    calls = _stub(monkeypatch, _site(projects=many))
    jira, _ = await atlassian.probe_site(CREDENTIAL)

    assert len(jira.projects) == atlassian.MAX_PROBE_ENTRIES
    counted = [p for p in jira.projects if p.issue_count is not None]
    assert len(counted) == atlassian.MAX_COUNTED_ENTRIES
    assert len([c for c in calls if "approximate-count" in c["url"]]) == (
        atlassian.MAX_COUNTED_ENTRIES
    )

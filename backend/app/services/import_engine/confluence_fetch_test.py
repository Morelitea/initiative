"""Reading Confluence spaces into a bundle: the calls, the paging, and what a
site that is slow, partial or absent does to it."""

from __future__ import annotations

import io
import json
import zipfile

import httpx
import pytest

from app.core.messages import ImportEngineMessages
from app.services.import_engine import atlassian, confluence_fetch
from app.services.import_engine.contract import ImportEngineError

pytestmark = pytest.mark.unit

CREDENTIAL = atlassian.AtlassianCredential(
    site_url="https://acme.atlassian.net",
    email="someone@example.com",
    api_token="shhh",
)


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(atlassian, "_sleep", fake_sleep)


def _page(page_id, title, parent=None, parent_type="page", position=0, body=None):
    return {
        "id": str(page_id),
        "title": title,
        "parentId": str(parent) if parent else None,
        "parentType": parent_type if parent else None,
        "position": position,
        "authorId": "acc-1",
        "createdAt": "2024-03-04T09:00:00.000Z",
        "version": {"createdAt": "2024-05-01T10:00:00.000Z"},
        "body": {"storage": {"value": body or f"<p>{title} body</p>"}},
    }


def _site(
    monkeypatch,
    *,
    pages=None,
    batches=None,
    folders=None,
    labels=None,
    users=None,
    locked=(),
    throttled=False,
):
    """A Confluence site. ``batches`` pages the listing: a list of page lists,
    each followed by a ``next`` link but the last."""
    calls: list[dict] = []
    folders = folders or {}
    labels = labels or {}
    names: dict[str, str] = users if users is not None else {"acc-1": "Robin Ade"}
    batches = batches if batches is not None else [pages or []]

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        calls.append({"method": method, "url": url, "json": json})
        if throttled:
            return httpx.Response(429, json={})
        if "/wiki/api/v2/spaces?keys=" in url:
            key = url.split("keys=")[1].split("&")[0]
            if key in locked:
                return httpx.Response(200, json={"results": []})
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": f"9{key}",
                            "key": key,
                            "name": f"{key} space",
                            "homepageId": "1",
                        }
                    ]
                },
            )
        if "/pages?" in url and "/spaces/" in url:
            index = int(url.split("cursor=")[1]) if "cursor=" in url else 0
            body = {"results": batches[index]}
            if index + 1 < len(batches):
                body["_links"] = {
                    "next": url.split("/wiki")[1].split("&cursor=")[0]
                    + f"&cursor={index + 1}"
                }
            return httpx.Response(200, json=body)
        if "/labels" in url:
            page_id = url.split("/pages/")[1].split("/")[0]
            return httpx.Response(
                200, json={"results": [{"name": n} for n in labels.get(page_id, [])]}
            )
        if "/wiki/api/v2/folders/" in url:
            folder_id = url.rsplit("/", 1)[1]
            if folder_id in folders:
                return httpx.Response(200, json=folders[folder_id])
            return httpx.Response(404, json={})
        if url.endswith("/wiki/api/v2/users-bulk"):
            wanted = (json or {}).get("accountIds") or []
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"accountId": a, "displayName": names[a]}
                        for a in wanted
                        if a in names
                    ]
                },
            )
        return httpx.Response(404, json={})

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    return calls


async def _bundle(**kw):
    return await confluence_fetch.fetch_spaces_bundle(
        CREDENTIAL,
        space_keys=kw.pop("space_keys", ["DOCS"]),
        guild_id=1,
        guild_name="acme.atlassian.net",
        target_initiative_id=42,
        app_version="0.0.0-test",
        **kw,
    )


def _open(bundle: bytes) -> tuple[dict, dict[str, dict]]:
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        envelopes = {
            e["path"]: json.loads(archive.read(e["path"])) for e in manifest["entries"]
        }
    return manifest, envelopes


async def test_a_space_becomes_a_wiki_in_the_chosen_initiative(monkeypatch):
    _site(
        monkeypatch,
        pages=[
            _page(1, "Home"),
            _page(
                2,
                "Guide",
                parent=1,
                body='<p>Ask <ac:link><ri:user ri:account-id="acc-2"/></ac:link></p>',
            ),
        ],
        labels={"2": ["howto"]},
        users={"acc-1": "Robin Ade", "acc-2": "Sam Bee"},
    )
    bundle, report = await _bundle()
    manifest, envelopes = _open(bundle)
    (initiative,) = manifest["initiatives"]
    assert initiative["target_initiative_id"] == 42
    assert initiative["tools"] == {"wiki": "included"}
    (entry,) = manifest["entries"]
    assert entry["tool"] == "wiki" and entry["type"] == "initiative-wiki"
    wiki = envelopes[entry["path"]]
    assert wiki["name"] == "DOCS space" and wiki["home_page"] == "home"
    guide = wiki["pages"][1]
    assert guide["parent"] == "home" and guide["tags"] == ["howto"]
    assert guide["author_handle"] == "Robin Ade"
    assert guide["mention_handles"] == ["Sam Bee"]
    assert [p["handle"] for p in manifest["people"]] == ["Robin Ade", "Sam Bee"]
    assert (report.spaces, report.pages, report.labels) == (1, 2, 1)


async def test_the_bundle_is_one_the_backup_importer_reads(monkeypatch):
    from app.services.import_engine import backup

    _site(monkeypatch, pages=[_page(1, "Home")])
    bundle, _report = await _bundle()
    plan = backup.plan_backup(
        bundle, existing_initiative_names=set(), member_ids_by_handle={}
    )
    assert plan.initiatives[0].target_initiative_id == 42


async def test_every_page_of_the_listing_is_read(monkeypatch):
    calls = _site(
        monkeypatch,
        batches=[[_page(1, "One")], [_page(2, "Two")], [_page(3, "Three")]],
    )
    _bundle_bytes, report = await _bundle()
    assert report.pages == 3
    listing = [c["url"] for c in calls if "/pages?" in c["url"]]
    assert len(listing) == 3
    # Current pages, with their bodies, in the one format the walker reads.
    assert "body-format=storage" in listing[0] and "status=current" in listing[0]


async def test_a_page_in_a_folder_is_filed_under_it(monkeypatch):
    _site(
        monkeypatch,
        pages=[
            _page(1, "Home"),
            _page(2, "Login", parent=60, parent_type="folder"),
        ],
        folders={
            "60": {
                "id": "60",
                "title": "Designs",
                "parentId": "50",
                "parentType": "folder",
            },
            "50": {
                "id": "50",
                "title": "Product",
                "parentId": "1",
                "parentType": "page",
            },
        },
    )
    bundle, report = await _bundle()
    _manifest, envelopes = _open(bundle)
    (wiki,) = envelopes.values()
    parents = {p["title"]: p["parent"] for p in wiki["pages"]}
    assert parents == {
        "Home": None,
        "Product": "home",
        "Designs": "product",
        "Login": "designs",
    }
    assert report.containers == 2


async def test_a_space_the_token_cannot_read_is_named_not_fatal(monkeypatch):
    _site(monkeypatch, pages=[_page(1, "Home")], locked=("SECRET",))
    bundle, report = await _bundle(space_keys=["SECRET", "DOCS"])
    manifest, _envelopes = _open(bundle)
    assert report.unreadable_spaces == ["SECRET"]
    assert report.spaces == 1 and len(manifest["entries"]) == 1


async def test_nothing_readable_fails_the_fetch(monkeypatch):
    _site(monkeypatch, locked=("SECRET",))
    with pytest.raises(ImportEngineError) as caught:
        await _bundle(space_keys=["SECRET"])
    assert caught.value.code == ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE


async def test_nothing_ticked_is_refused_before_a_call(monkeypatch):
    calls = _site(monkeypatch)
    with pytest.raises(ImportEngineError) as caught:
        await _bundle(space_keys=[])
    assert caught.value.code == ImportEngineMessages.IMPORT_SOURCE_NOTHING_SELECTED
    assert calls == []


async def test_being_throttled_stops_the_fetch(monkeypatch):
    _site(monkeypatch, throttled=True)
    with pytest.raises(ImportEngineError) as caught:
        await _bundle()
    assert caught.value.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED


async def test_progress_hears_each_space_and_can_stop_the_walk(monkeypatch):
    _site(monkeypatch, pages=[_page(1, "Home")])
    heard: list[int] = []

    class Stop(Exception):
        pass

    async def progress(report):
        heard.append(report.spaces)
        raise Stop

    with pytest.raises(Stop):
        await _bundle(space_keys=["DOCS", "MORE"], progress=progress)
    assert heard == [1]


def test_a_next_link_that_is_not_the_listing_is_not_followed():
    assert confluence_fetch._next_path({"_links": {"next": "/api/v2/x?cursor=2"}}) == (
        "/wiki/api/v2/x?cursor=2"
    )
    assert (
        confluence_fetch._next_path({"_links": {"next": "https://evil.example/"}})
        is None
    )
    assert confluence_fetch._next_path({"_links": {"next": "/wiki/rest/api/x"}}) is None
    assert confluence_fetch._next_path({}) is None

"""Reading Confluence spaces into a bundle the ordinary backup importer applies.

The Confluence half of the Atlassian fetch, and the same shape as the Jira
one: the calls and the paging live here, the mapping is pure and lives in
``confluence_mapping``, and the applying is ``backup.apply_backup``. It writes
no content row and opens no routed session — its one artifact is the zip.

Each space becomes one wiki envelope in a manifest naming the one initiative
the person picked, carried as ``target_initiative_id``.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import quote

from app.core.config import settings
from app.core.messages import ImportEngineMessages
from app.services.import_engine import confluence_mapping
from app.services.import_engine.atlassian import AtlassianCredential, get_json
from app.services.import_engine.contract import ImportEngineError

logger = logging.getLogger(__name__)

#: Pages per request. The API's own ceiling; each page carries its body, so a
#: request is held in memory whole.
PAGE_LIMIT = 250

#: A hard stop on paging, whatever the site says: ``_links.next`` is the
#: site's to hand back, and a loop that trusts it without a bound is a loop
#: somebody else controls.
MAX_PAGE_REQUESTS = 200

#: How deep a chain of folders is followed before it is treated as the top.
MAX_FOLDER_DEPTH = 20

#: Account ids per ``users-bulk`` request.
USERS_PER_REQUEST = 100

#: Held back from the envelope's byte bound for the wiki row and the
#: manifest's own framing.
_ENVELOPE_RESERVE_BYTES = 256 * 1024

_ACCOUNT_ID = re.compile(r'ri:account-id="([^"]{1,128})"')


@dataclass
class ConfluenceFetchReport:
    """What the fetch found, for the plan the wizard shows. Counts only."""

    spaces: int = 0
    pages: int = 0
    #: Folders, and pages with children and no words of their own, that were
    #: given a list of what sits beneath them.
    containers: int = 0
    #: What the converter left out, by kind — a macro's name, ``image`` for a
    #: picture that did not come over.
    dropped: Counter[str] = field(default_factory=Counter)
    #: Spaces ticked that the token could not read.
    unreadable_spaces: list[str] = field(default_factory=list)
    #: Pages left out because the space's wiki would have been too large to
    #: import in one piece, or the import's row budget was spent.
    pages_over_limit: int = 0
    #: Files the pages show or link to. They do not come over yet.
    attachments: int = 0
    #: Tags the pages' labels will become.
    labels: int = 0

    @property
    def dropped_nodes(self) -> int:
        return sum(self.dropped.values())


def _next_path(payload: dict) -> Optional[str]:
    """The next page of a v2 listing, as a path on the site.

    The API hands back a path under ``/wiki``; anything that does not look
    like one of its own listings ends the walk rather than being followed.
    """
    links = payload.get("_links")
    link = links.get("next") if isinstance(links, dict) else None
    if not isinstance(link, str) or not link:
        return None
    path = link if link.startswith("/wiki/") else f"/wiki{link}"
    return path if path.startswith("/wiki/api/v2/") else None


async def fetch_space(credential: AtlassianCredential, key: str) -> dict:
    """The space row: its id, name, description and home page."""
    payload = await get_json(
        credential,
        f"/wiki/api/v2/spaces?keys={quote(key, safe='')}&description-format=plain",
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    space = results[0] if isinstance(results, list) and results else None
    if not isinstance(space, dict) or not space.get("id"):
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE)
    return space


async def fetch_pages(
    credential: AtlassianCredential, space_id: str, *, max_pages: int
) -> list[dict[str, Any]]:
    """Every current page in the space, with its storage-format body.

    Current only: a draft is somebody's unfinished work, and an archived page
    is one the space itself set aside.
    """
    pages: list[dict[str, Any]] = []
    path: Optional[str] = (
        f"/wiki/api/v2/spaces/{quote(space_id, safe='')}/pages"
        f"?body-format=storage&status=current&limit={PAGE_LIMIT}"
    )
    for _ in range(MAX_PAGE_REQUESTS):
        if path is None or len(pages) >= max_pages:
            break
        payload = await get_json(credential, path)
        if not isinstance(payload, dict):
            break
        results = payload.get("results")
        if isinstance(results, list):
            pages.extend(page for page in results if isinstance(page, dict))
        path = _next_path(payload)
    return pages[:max_pages]


async def fetch_labels(
    credential: AtlassianCredential, page_id: str
) -> tuple[str, ...]:
    """A page's labels. One that will not answer has none — not worth
    failing the space over. Being throttled is, as everywhere else."""
    try:
        payload = await get_json(
            credential, f"/wiki/api/v2/pages/{page_id}/labels?limit=250"
        )
    except ImportEngineError as exc:
        if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
            raise
        return ()
    return confluence_mapping.page_labels(payload)


async def fetch_folders(
    credential: AtlassianCredential, pages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The folders the pages sit in, and the folders those sit in.

    A folder is not a page, so the page listing leaves it out; it is read on
    its own, up the chain, for as far as folders go.
    """
    wanted = {
        str(page.get("parentId"))
        for page in pages
        if page.get("parentType") == "folder" and page.get("parentId")
    }
    folders: dict[str, Any] = {}
    for _ in range(MAX_FOLDER_DEPTH):
        wanted -= folders.keys()
        if not wanted:
            break
        found: set[str] = set()
        for folder_id in sorted(wanted):
            if not folder_id.isdigit():
                continue
            try:
                folder = await get_json(credential, f"/wiki/api/v2/folders/{folder_id}")
            except ImportEngineError as exc:
                if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
                    raise
                continue
            if not isinstance(folder, dict):
                continue
            folders[folder_id] = folder
            if folder.get("parentType") == "folder" and folder.get("parentId"):
                found.add(str(folder["parentId"]))
        wanted = found
    return list(folders.values())


async def fetch_user_names(
    credential: AtlassianCredential, account_ids: set[str]
) -> dict[str, str]:
    """Who each account is, by the name the site shows for them.

    A name, never an address: who that is *here* is the people step's to
    answer. An account the site will not name keeps none, and its mentions
    keep the words they were written with.
    """
    names: dict[str, str] = {}
    ids = sorted(account_ids)
    for start in range(0, len(ids), USERS_PER_REQUEST):
        batch = ids[start : start + USERS_PER_REQUEST]
        try:
            payload = await get_json(
                credential,
                "/wiki/api/v2/users-bulk",
                method="POST",
                json={"accountIds": batch},
            )
        except ImportEngineError as exc:
            if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
                raise
            logger.info("confluence users unreadable code=%s", exc.code)
            continue
        results = payload.get("results") if isinstance(payload, dict) else None
        for user in results if isinstance(results, list) else []:
            if not isinstance(user, dict):
                continue
            account = str(user.get("accountId") or "")
            name = str(user.get("displayName") or user.get("publicName") or "").strip()
            if account and name:
                names[account] = name
    return names


def _account_ids(pages: list[confluence_mapping.SourcePage]) -> set[str]:
    ids = {page.author_id for page in pages if page.author_id}
    for page in pages:
        if page.body:
            ids.update(_ACCOUNT_ID.findall(page.body))
    return ids


@dataclass
class ConfluenceFetched:
    """Everything a Confluence fetch read, ready to be written into a bundle."""

    envelopes: list[tuple[str, dict[str, Any]]]
    people: Counter[str]
    report: ConfluenceFetchReport


async def fetch_spaces_bundle(
    credential: AtlassianCredential,
    *,
    guild_id: int,
    guild_name: str,
    target_initiative_id: int,
    **kwargs: Any,
) -> tuple[bytes, ConfluenceFetchReport]:
    """:func:`fetch_spaces`, written into a bundle of its own."""
    from app.services.import_engine.atlassian_bundle import merge_people, write_bundle

    fetched = await fetch_spaces(credential, **kwargs)
    bundle = write_bundle(
        wikis=fetched.envelopes,
        people=merge_people([], fetched.people),
        guild_id=guild_id,
        guild_name=guild_name,
        target_initiative_id=target_initiative_id,
        app_version=kwargs["app_version"],
        site_url=credential.site_url,
    )
    return bundle, fetched.report


async def fetch_spaces(
    credential: AtlassianCredential,
    *,
    space_keys: list[str],
    app_version: str,
    progress: Optional[Callable[[ConfluenceFetchReport], Awaitable[None]]] = None,
    max_rows: Optional[int] = None,
) -> ConfluenceFetched:
    """Read the chosen spaces and return what was read plus what it found.

    A space the token cannot read is counted, not fatal; every one unreadable
    fails the fetch, because then the selection is what is wrong. ``progress``
    hears the running report after each space, and raising from it stops the
    walk there — how a cancelled job ends.
    """
    if not space_keys:
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_NOTHING_SELECTED)

    report = ConfluenceFetchReport()
    remaining = settings.IMPORT_MAX_ROWS if max_rows is None else max_rows
    envelopes: list[tuple[str, dict[str, Any]]] = []
    people: Counter[str] = Counter()
    labels: set[str] = set()
    max_bytes = max(0, settings.IMPORT_MAX_ENVELOPE_BYTES - _ENVELOPE_RESERVE_BYTES)

    for key in space_keys:
        if remaining <= 1:
            logger.info("confluence fetch row budget spent, stopping at space=%s", key)
            break
        try:
            space = await fetch_space(credential, key)
            raw_pages = await fetch_pages(
                credential, str(space["id"]), max_pages=remaining - 1
            )
            pages: list[confluence_mapping.SourcePage] = []
            for raw in raw_pages:
                page_id = str(raw.get("id") or "")
                page = confluence_mapping.read_page(
                    raw,
                    await fetch_labels(credential, page_id)
                    if page_id.isdigit()
                    else (),
                )
                if page is not None:
                    pages.append(page)
            for raw in await fetch_folders(credential, raw_pages):
                folder = confluence_mapping.read_folder(raw)
                if folder is not None:
                    pages.append(folder)
            users = await fetch_user_names(credential, _account_ids(pages))
        except ImportEngineError as exc:
            if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
                raise
            logger.info("confluence space unreadable key=%s code=%s", key, exc.code)
            report.unreadable_spaces.append(key)
        else:
            mapped = confluence_mapping.build_wiki_envelope(
                space=space,
                pages=pages,
                users=users,
                site_url=credential.site_url,
                app_version=app_version,
                max_bytes=max_bytes,
            )
            envelopes.append((key, mapped.envelope))
            people.update(mapped.people)
            report.spaces += 1
            report.pages += mapped.pages
            report.containers += mapped.containers
            report.dropped.update(mapped.dropped)
            report.pages_over_limit += mapped.over_limit
            report.attachments += sum(len(a) for a in mapped.attachments.values())
            for entry in mapped.envelope["pages"]:
                labels.update(tag.casefold() for tag in entry["tags"])
            report.labels = len(labels)
            remaining -= mapped.pages + 1
        if progress is not None:
            await progress(report)

    if not envelopes:
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE)

    return ConfluenceFetched(envelopes=envelopes, people=people, report=report)

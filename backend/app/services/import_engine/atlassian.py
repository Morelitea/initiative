"""Talking to an Atlassian site: the one place this app makes that call.

Everything here runs in the **fetch** half of an import, which never opens a
routed content session. It reads a credential on the system engine, speaks to
somebody else's server, and hands back counts and names. The routed,
RLS-enforced session appears only when rows are written, which is a different
module and a later step.

**Egress is bounded the way the app's other outbound calls are.** Every
request goes through :func:`app.services.safe_http.request_public_target`:
https only, the host resolved once to a public address, the connection pinned
to it, and no redirect followed automatically. A site that resolves to a
private address is refused rather than fetched — a LAN-hosted Data Center is
a later, credential-free route (the HTML-export zip), not this one.

**Failures are codes, never prose.** Somebody else's server can say anything,
and an import job records what went wrong for a reader who is not the person
who typed the token. Every failure here becomes one of the
``IMPORT_SOURCE_*`` constants, and the body that caused it is dropped.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.core.messages import ImportEngineMessages
from app.schemas.tenant.atlassian import (
    AtlassianConfluenceProbe,
    AtlassianConfluenceSpace,
    AtlassianJiraProbe,
    AtlassianJiraProject,
)
from app.services.import_engine.contract import ImportEngineError
from app.services.safe_http import request_public_target
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
)

logger = logging.getLogger(__name__)

#: How long one call to the site may take. A probe makes several, so this is
#: deliberately short: the person is sitting in front of a wizard, and a site
#: that cannot answer a listing in ten seconds is not one we can read a
#: thousand issues from either.
REQUEST_TIMEOUT_SECONDS = 10.0

#: How many listing calls run at once. Counts are one call per project or
#: space, so a site with fifty of each would be a hundred round trips in
#: series. Eight keeps the probe quick without becoming the reason a site
#: starts rate-limiting us.
PROBE_CONCURRENCY = 8

#: How many projects/spaces the probe will list. A site with more than this is
#: not refused — the listing is simply cut, and the wizard says so. It exists
#: so one connect cannot turn into a thousand outbound calls.
MAX_PROBE_ENTRIES = 200

#: How many of those get a count. Counting is the expensive half (one call
#: each), and a checklist is readable long before its two-hundredth row; the
#: rest report ``None``, which the wizard renders as "not counted".
MAX_COUNTED_ENTRIES = 100


@dataclass(frozen=True)
class AtlassianCredential:
    """What one site needs to be read, held for the length of a call.

    Deliberately not the stored row: this is the decrypted form, and it exists
    in memory only. See ``import_engine.credentials`` for the row and its
    lifecycle.
    """

    site_url: str
    email: str
    api_token: str

    @property
    def auth_header(self) -> str:
        """Atlassian's API tokens authenticate as HTTP Basic, the account's
        address standing in for a username."""
        raw = f"{self.email}:{self.api_token}".encode()
        return "Basic " + base64.b64encode(raw).decode()


def normalize_site_url(raw: str) -> str:
    """The site as a URL we will actually call, or a refusal.

    People paste what their browser is showing, which is usually a board deep
    inside one of the products. Only the scheme and the host mean anything
    here — the products live at fixed paths under them — so everything after
    the host is dropped rather than interpreted.

    https only. An http site would carry the token in the clear, and there is
    no version of that worth supporting for a credential somebody typed in.
    """
    candidate = (raw or "").strip()
    if not candidate:
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE)
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parts = urlsplit(candidate)
    if parts.scheme != "https" or not parts.hostname:
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE)
    # netloc rather than hostname: a non-default port is part of the address.
    return f"https://{parts.netloc}"


async def get_json(
    credential: AtlassianCredential,
    path: str,
    *,
    method: str = "GET",
    json: object | None = None,
) -> object:
    """One call to the site, with every way it can go wrong turned into a code.

    ``path`` is absolute from the site root (``/rest/api/3/project/search``).
    The response body is returned parsed; a body that is not JSON is treated
    as the site being unreachable, because a proxy's error page is not an
    answer from Atlassian.
    """
    url = f"{credential.site_url}{path}"
    try:
        response = await request_public_target(
            method,
            url,
            headers={
                "Authorization": credential.auth_header,
                "Accept": "application/json",
            },
            json=json,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except WebhookTargetUrlPrivateError:
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_PRIVATE_HOST)
    except WebhookTargetUrlError:
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE)
    except (httpx.TimeoutException, httpx.TransportError):
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE)

    if response.status_code in (401, 403):
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_AUTH)
    if response.status_code == 429:
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED)
    if response.status_code >= 400:
        # Logged by status only: the body is somebody else's server talking,
        # and it can hold anything.
        logger.info(
            "atlassian call failed status=%s path=%s", response.status_code, path
        )
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE)
    try:
        return response.json()
    except ValueError:
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE)


async def _gather_bounded(coros: list) -> list:
    """Run the calls a few at a time, keeping their order."""
    semaphore = asyncio.Semaphore(PROBE_CONCURRENCY)

    async def run(coro):
        async with semaphore:
            return await coro

    return await asyncio.gather(*(run(c) for c in coros), return_exceptions=True)


async def _jira_issue_count(
    credential: AtlassianCredential, project_key: str
) -> int | None:
    """Roughly how many issues one project holds.

    Approximate on purpose: Jira answers this without walking the index, and
    the number is for a person deciding what to bring over rather than for
    anything that has to balance. A project that will not answer reports
    ``None`` rather than failing the whole probe — one unreadable project is
    not a reason to refuse a site.
    """
    try:
        payload = await get_json(
            credential,
            "/rest/api/3/search/approximate-count",
            method="POST",
            json={"jql": f'project = "{project_key}"'},
        )
    except ImportEngineError:
        return None
    if isinstance(payload, dict):
        count = payload.get("count")
        if isinstance(count, int):
            return count
    return None


async def _confluence_page_count(
    credential: AtlassianCredential, space_key: str
) -> int | None:
    """How many pages one space holds.

    Through v1 CQL with ``limit=0``: v2 has no count of its own, and asking
    for none of the results is how that API reports a total.
    """
    try:
        payload = await get_json(
            credential,
            f"/wiki/rest/api/search?cql=space=%22{space_key}%22+and+type=page&limit=0",
        )
    except ImportEngineError:
        return None
    if isinstance(payload, dict):
        total = payload.get("totalSize")
        if isinstance(total, int):
            return total
    return None


async def probe_jira(credential: AtlassianCredential) -> AtlassianJiraProbe:
    """Which Jira projects this token can see, and roughly how big they are.

    An auth failure is raised, because a token the site rejects is the
    person's problem to fix and the wizard has to say so. Anything else — no
    Jira on this site, a product the token cannot reach — comes back as
    ``available=False`` with the reason, so a Confluence-only import is not
    blocked by a Jira that was never there.
    """
    try:
        payload = await get_json(
            credential, "/rest/api/3/project/search?maxResults=200"
        )
    except ImportEngineError as exc:
        if exc.code == ImportEngineMessages.IMPORT_SOURCE_AUTH:
            raise
        return AtlassianJiraProbe(available=False, reason=exc.code)

    values = payload.get("values") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        return AtlassianJiraProbe(
            available=False, reason=ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE
        )

    projects = [
        AtlassianJiraProject(
            id=str(item.get("id", "")),
            key=str(item.get("key", "")),
            name=str(item.get("name", "")),
        )
        for item in values[:MAX_PROBE_ENTRIES]
        if isinstance(item, dict) and item.get("key")
    ]
    counted = projects[:MAX_COUNTED_ENTRIES]
    counts = await _gather_bounded(
        [_jira_issue_count(credential, project.key) for project in counted]
    )
    for project, count in zip(counted, counts):
        project.issue_count = count if isinstance(count, int) else None
    return AtlassianJiraProbe(available=True, projects=projects)


async def probe_confluence(credential: AtlassianCredential) -> AtlassianConfluenceProbe:
    """Which Confluence spaces this token can see, and how big they are.

    Same rule as Jira: an auth failure is raised; a missing product is
    reported rather than thrown.
    """
    try:
        payload = await get_json(credential, "/wiki/api/v2/spaces?limit=200")
    except ImportEngineError as exc:
        if exc.code == ImportEngineMessages.IMPORT_SOURCE_AUTH:
            raise
        return AtlassianConfluenceProbe(available=False, reason=exc.code)

    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return AtlassianConfluenceProbe(
            available=False, reason=ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE
        )

    spaces = [
        AtlassianConfluenceSpace(
            id=str(item.get("id", "")),
            key=str(item.get("key", "")),
            name=str(item.get("name", "")),
        )
        for item in results[:MAX_PROBE_ENTRIES]
        if isinstance(item, dict) and item.get("key")
    ]
    counted = spaces[:MAX_COUNTED_ENTRIES]
    counts = await _gather_bounded(
        [_confluence_page_count(credential, space.key) for space in counted]
    )
    for space, count in zip(counted, counts):
        space.page_count = count if isinstance(count, int) else None
    return AtlassianConfluenceProbe(available=True, spaces=spaces)


async def probe_site(
    credential: AtlassianCredential,
) -> tuple[AtlassianJiraProbe, AtlassianConfluenceProbe]:
    """Both products, asked in turn.

    In turn rather than at once: the first call is also what proves the token,
    and a bad one should cost the site two rejected requests rather than a
    burst of them.
    """
    jira = await probe_jira(credential)
    confluence = await probe_confluence(credential)
    if not jira.available and not confluence.available:
        # Neither product answered and the token was not rejected, so the
        # address is the thing that is wrong.
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE)
    return jira, confluence

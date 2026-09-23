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
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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
class RetryPolicy:
    """How long one call will wait out a site that says "slow down".

    Atlassian answers a burst with ``429`` and, usually, a ``Retry-After``
    saying when to come back. Honouring it is the difference between a short
    pause and a long block, so a throttled call waits and tries again — up to
    ``attempts`` tries in all, and never for longer than ``max_wait_seconds``
    at a time. A site that asks for a longer wait than that is not asking for
    a retry; the call gives up with ``IMPORT_SOURCE_RATE_LIMITED`` instead of
    sleeping on it.
    """

    attempts: int
    max_wait_seconds: float


#: The worker's fetch. Nobody is watching the clock, and a fetch that fails on
#: its first 429 would fail on every site big enough to be worth importing.
BACKGROUND = RetryPolicy(attempts=4, max_wait_seconds=60.0)

#: The connect probe. A person is sitting in the wizard waiting for a listing,
#: so the waits are kept short enough that the request still answers.
INTERACTIVE = RetryPolicy(attempts=2, max_wait_seconds=5.0)

#: The first wait when the site gives no ``Retry-After``; each retry doubles it.
BACKOFF_BASE_SECONDS = 1.0

#: Added on top of every wait, as a fraction of it, so the probe's concurrent
#: calls do not all come back at the same instant and get throttled again.
#: Only ever added: a call never returns earlier than the site asked.
JITTER_FRACTION = 0.25


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """The wait a ``Retry-After`` header asks for, or ``None`` without one.

    The header is either a number of seconds or an HTTP date. Anything that
    parses as neither is treated as absent — the backoff takes over — rather
    than trusted.
    """
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()
    try:
        seconds = float(raw)
    except ValueError:
        try:
            when = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - datetime.now(timezone.utc)).total_seconds()
    if seconds != seconds:  # NaN
        return None
    return max(0.0, seconds)


def _retry_delay(attempt: int, retry_after: float | None) -> float:
    """How long to wait before retry number ``attempt`` (counting from 0),
    before jitter."""
    if retry_after is not None:
        return retry_after
    return BACKOFF_BASE_SECONDS * (2**attempt)


async def _sleep(seconds: float) -> None:
    """Looked up at call time, so a test can wait without waiting."""
    await asyncio.sleep(seconds)


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
    retry: RetryPolicy = BACKGROUND,
) -> object:
    """One call to the site, with every way it can go wrong turned into a code.

    ``path`` is absolute from the site root (``/rest/api/3/project/search``).
    The response body is returned parsed; a body that is not JSON is treated
    as the site being unreachable, because a proxy's error page is not an
    answer from Atlassian.

    A ``429`` is waited out under ``retry`` (see :class:`RetryPolicy`) before
    it becomes ``IMPORT_SOURCE_RATE_LIMITED``. Nothing else is retried: every
    other failure is an answer, and asking again would get the same one.
    """
    for attempt in range(retry.attempts):
        response = await _request(credential, path, method=method, json=json)
        if response.status_code != 429:
            return _parse(response, path)
        if attempt + 1 >= retry.attempts:
            break
        delay = _retry_delay(attempt, _retry_after_seconds(response))
        if delay > retry.max_wait_seconds:
            # Told to come back later than this call is willing to wait: that
            # is a block, not a pause, and sleeping on it helps nobody.
            break
        delay += random.uniform(0, delay * JITTER_FRACTION)
        logger.info(
            "atlassian throttled path=%s attempt=%s waiting=%.1fs",
            path,
            attempt + 1,
            delay,
        )
        await _sleep(delay)
    raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED)


async def _request(
    credential: AtlassianCredential,
    path: str,
    *,
    method: str,
    json: object | None,
) -> httpx.Response:
    """Send one request, with the transport's failures turned into codes."""
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
    return response


def _parse(response: httpx.Response, path: str) -> object:
    """A non-throttled answer as JSON, or the code for what went wrong."""
    if response.status_code in (401, 403):
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_AUTH)
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
            retry=INTERACTIVE,
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
            retry=INTERACTIVE,
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
            credential,
            "/rest/api/3/project/search?maxResults=200",
            retry=INTERACTIVE,
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
        payload = await get_json(
            credential, "/wiki/api/v2/spaces?limit=200", retry=INTERACTIVE
        )
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

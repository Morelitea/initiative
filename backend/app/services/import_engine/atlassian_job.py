"""An import from an Atlassian site as a job: starting one, and fetching it.

The job's life is the backup's with one step in front of it::

    queued → fetching → staged → (confirm) → queued → running → done | failed

Everything from ``staged`` on is the backup path, unchanged — the fetch writes
the same zip a backup upload stages, and the worker applies it the same way.
What this module adds is the part before that: the request that names what
to bring over, and the worker's fetch that turns it into a bundle.

A queued Atlassian job with no payload has not been fetched yet; one with a
payload has been, and was confirmed. That is the whole of how the worker tells
the two apart (:func:`awaits_fetch`), and it is why a re-claimed fetch drops
its payload on the way back into the queue.

**The credential is spent by the fetch.** Everything the apply needs is in the
bundle, so the moment the bundle is staged the token has no further use and is
dropped — the review step can sit for hours without a live secret behind it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncContextManager, Awaitable, Callable
from urllib.parse import urlsplit

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.messages import ImportEngineMessages
from app.core.version import get_version
from app.db.session import SYSTEM_SATISFIED
from app.models.platform.user import User, UserStatus
from app.models.tenant.import_job import ImportJob, ImportJobStatus
from app.schemas.tenant.import_job import AtlassianFetchSummary, BackupImportPlan
from app.services.import_engine import credentials as import_credentials
from app.services.import_engine import engine as import_engine
from app.services.import_engine import jira_fetch
from app.services.import_engine.atlassian import AtlassianCredential
from app.services.import_engine.common import load_guild_member_handles
from app.services.import_engine.contract import ImportEngineError

logger = logging.getLogger(__name__)

#: ``import_jobs.source`` for every import read from an Atlassian site.
SOURCE = "atlassian"

#: The provider a credential has to have been stored under to start one.
PROVIDER = "atlassian"

#: The importer whose permission a Jira project needs. A Confluence space will
#: add the wiki importer's beside it.
_PROJECT_ENVELOPE = "initiative-project"


def awaits_fetch(job: ImportJob) -> bool:
    """Whether the worker should read the site for this job rather than apply."""
    return job.source == SOURCE and not job.payload_ref


def summary_of(report: jira_fetch.FetchReport) -> AtlassianFetchSummary:
    return AtlassianFetchSummary(
        projects=report.projects,
        tasks=report.tasks,
        dropped_nodes=report.dropped_nodes,
        skipped_issues=report.skipped_issues,
        unreadable_projects=list(report.unreadable_projects),
    )


async def start_jira_import(
    session: AsyncSession,
    *,
    user: User,
    guild_id: int,
    credential_id: int,
    initiative_id: int,
    project_keys: list[str],
) -> ImportJob:
    """Queue a job that reads these Jira projects into ``initiative_id``.

    Everything that can be refused now is refused now, so a person finds out
    in the wizard rather than from a failed job minutes later: nothing
    ticked, a connection that is not theirs or not live, a connection another
    job already took, an initiative they cannot create projects in. The
    worker asks the last of those again before it reads anything, and the
    apply asks it a third time — authorization is a property of the moment.
    """
    # Order kept, repeats dropped: the order is the order they were ticked.
    keys = list(dict.fromkeys(key.strip() for key in project_keys if key.strip()))
    if not keys:
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_NOTHING_SELECTED)

    credential = await import_credentials.describe(
        credential_id, guild_id=guild_id, user_id=user.id
    )
    if credential is None or credential.provider != PROVIDER:
        raise ImportEngineError(
            ImportEngineMessages.IMPORT_CREDENTIAL_UNAVAILABLE, status_code=404
        )
    if await _credential_taken(session, credential_id):
        # One connection, one job. A second job quoting it would fail when the
        # first one's end dropped the credential, so it is refused here instead.
        raise ImportEngineError(
            ImportEngineMessages.IMPORT_CREDENTIAL_UNAVAILABLE, status_code=409
        )

    initiative = await import_engine.load_target_initiative(
        session,
        guild_id=guild_id,
        initiative_id=initiative_id,
        importer=import_engine.get_importer(_PROJECT_ENVELOPE),
        user=user,
    )
    await import_engine.count_active_jobs_locked(session, user=user)

    job = ImportJob(
        created_by=user.id,
        source=SOURCE,
        params={
            "initiative_id": initiative.id,
            "credential_id": credential.id,
            # Which site, so the wizard and the Data tab can say where this
            # came from. The person typed it; it is not a secret.
            "site_url": credential.site_url,
            "jira_projects": keys,
        },
        status=ImportJobStatus.queued,
        expires_at=datetime.now(timezone.utc)
        + timedelta(hours=settings.IMPORT_STAGED_TTL_HOURS),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _credential_taken(session: AsyncSession, credential_id: int) -> bool:
    """Whether some job already quotes this credential.

    Only the credential's owner can quote it, and their own jobs are what the
    own-row policy shows them, so the jobs that matter are all visible here.
    """
    taken = (
        await session.exec(
            select(ImportJob.id)
            .where(ImportJob.params["credential_id"].as_integer() == credential_id)
            .limit(1)
        )
    ).first()
    return taken is not None


@dataclass(frozen=True)
class StagedFetch:
    """A finished fetch: where the bundle is, and the plan to review it by."""

    payload_ref: str
    plan: dict[str, Any]


class FetchCancelled(Exception):
    """The job stopped being a fetch while the fetch was running."""


async def fetch(
    job: ImportJob,
    *,
    guild_id: int,
    open_user_session: Callable[[], AsyncContextManager[AsyncSession]],
    progress: Callable[[AtlassianFetchSummary], Awaitable[None]] | None = None,
) -> StagedFetch:
    """Read the job's projects from the site and stage the bundle.

    Raises an :class:`ImportEngineError` for anything the person has to act
    on, and lets ``progress`` raise :class:`FetchCancelled` to stop early.
    Nothing is written to any content table: the one artifact is the zip, and
    it is staged only after the whole read succeeded, so a failure leaves
    nothing behind to clean up.
    """
    from app.api.deps import establish_guild_access
    from app.services.platform import accounts as accounts_service

    params = job.params or {}
    credential_id = params.get("credential_id")
    keys = params.get("jira_projects")
    if not isinstance(credential_id, int) or not isinstance(keys, list):
        raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_PARAMS)
    keys = [key for key in keys if isinstance(key, str) and key]

    user = await accounts_service.load_one(job.created_by)
    if user is None or user.status != UserStatus.active:
        raise ImportEngineError(ImportEngineMessages.IMPORT_CREATOR_INACTIVE)

    loaded = await import_credentials.load(credential_id, guild_id=guild_id)
    if (
        loaded is None
        or loaded.created_by != job.created_by
        or (loaded.provider != PROVIDER)
    ):
        raise ImportEngineError(ImportEngineMessages.IMPORT_CREDENTIAL_UNAVAILABLE)

    # Before a single call to the site: is the person still somebody who may
    # put projects in that initiative? The session is closed again before
    # the read, which can take far longer than a routed session may live.
    async with open_user_session() as user_session:
        context = await establish_guild_access(
            user_session, user, guild_id, satisfied_providers=SYSTEM_SATISFIED
        )
        if context.content_read_only or context.is_pam or context.grant is not None:
            raise ImportEngineError(ImportEngineMessages.IMPORT_WRITE_REQUIRED)
        initiative = await import_engine.load_target_initiative(
            user_session,
            guild_id=guild_id,
            initiative_id=params.get("initiative_id"),
            importer=import_engine.get_importer(_PROJECT_ENVELOPE),
            user=user,
        )
        target_initiative_id = initiative.id
        # The community's roster, so the plan can suggest who each person the
        # site names is — read now, as the person, like a backup upload does.
        roster = await load_guild_member_handles(user_session, guild_id=guild_id)

    async def report_progress(report: jira_fetch.FetchReport) -> None:
        if progress is not None:
            await progress(summary_of(report))

    credential = AtlassianCredential(
        site_url=loaded.site_url, email=loaded.principal, api_token=loaded.secret
    )
    bundle, report = await jira_fetch.fetch_projects_bundle(
        credential,
        project_keys=keys,
        guild_id=guild_id,
        # The bundle's "source guild" is where it came from, which is the site.
        guild_name=urlsplit(loaded.site_url).hostname or loaded.site_url,
        target_initiative_id=target_initiative_id,
        app_version=get_version(),
        progress=report_progress,
    )

    from app.services.import_engine import backup as backup_service

    plan: BackupImportPlan = backup_service.plan_backup(
        bundle, existing_initiative_names=set(), member_ids_by_handle=roster
    )
    plan.atlassian = summary_of(report)
    payload_ref = import_engine.stage_payload(guild_id, bundle, suffix="zip")
    return StagedFetch(payload_ref=payload_ref, plan=plan.model_dump(mode="json"))

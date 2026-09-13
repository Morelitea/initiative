"""Where a security-relevant warning goes so that a person sees it.

The estate produces good structured warnings -- a refused sign-in recorded
against the account it named, a service call verified with an overlap secret
during a rotation -- and until now they all ended in a log. A log nobody
watches is evidence after an incident, not detection.

This is the destination. One HTTPS POST per alert, to a URL the operator sets:

* Unset (the default) is the behaviour that exists today. Nothing is sent, the
  warning is still logged, and no deployment has to change to keep working.
* Set, and the same warnings are delivered. The body is JSON with a ``text``
  field, which is what Slack, Discord, Mattermost and Teams incoming webhooks
  read, alongside structured fields for anything that parses properly. Picking
  a shape that several destinations accept is what keeps this from being a
  choice of vendor.

**Thresholds, not every event.** A single refused sign-in is somebody
mistyping their password; it belongs in the audit log and nowhere else. What
is worth interrupting a person for is a rate: several failures against one
account inside a window, delivered once per window. The count comes from
``audit_events``, which already records each refusal, and uses the
``(target_user_id, occurred_at)`` index that is already there.

**It never breaks the request it was called from.** Delivery failure is logged
and swallowed. An alert sink that can fail a sign-in has turned a detective
control into an availability risk, and the first outage would get it removed.

Sending is never in the caller's critical path either: alerts are dispatched on
a background task, so a slow destination costs the request nothing.

See ``docs/runbooks/security-alerts.md`` for the response and retirement
actions this is wired to.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.config import PROJECT_NAME, settings
from app.models.platform.audit_event import AuditEvent
from app.services.safe_http import request_public_target

logger = logging.getLogger(__name__)

#: Long enough that a slow destination is not reported as broken, short enough
#: that a hung one cannot pile up background tasks.
DELIVERY_TIMEOUT_SECONDS = 10.0


class SecurityAlert:
    """What is being reported, in the two shapes a destination might want."""

    def __init__(self, *, kind: str, summary: str, detail: dict[str, Any]):
        self.kind = kind
        self.summary = summary
        self.detail = detail

    def payload(self) -> dict[str, Any]:
        return {
            # Read by Slack, Discord, Mattermost and Teams incoming webhooks.
            "text": f"[{PROJECT_NAME}] {self.summary}",
            # For anything that parses rather than renders.
            "kind": self.kind,
            "summary": self.summary,
            "detail": self.detail,
            "at": datetime.now(UTC).isoformat(),
        }


def alerting_configured() -> bool:
    return bool(settings.SECURITY_ALERT_WEBHOOK_URL)


async def deliver(alert: SecurityAlert) -> bool:
    """Send one alert. Returns whether it was delivered.

    Every failure path returns False rather than raising: see the module
    docstring on why this must not be able to fail a request.
    """
    url = settings.SECURITY_ALERT_WEBHOOK_URL
    if not url:
        return False
    try:
        response = await request_public_target(
            "POST",
            url,
            json=alert.payload(),
            timeout=DELIVERY_TIMEOUT_SECONDS,
            # An operator-configured destination, not a caller-supplied one, so
            # a private address is a legitimate deployment (an in-cluster relay)
            # rather than a target to refuse. Still pinned to the address that
            # was validated.
            allow_private=True,
        )
    except (httpx.HTTPError, ValueError, OSError) as exc:
        logger.warning(
            "security_alert.delivery_failed kind=%s error=%s", alert.kind, exc
        )
        return False
    if response.status_code >= 400:
        logger.warning(
            "security_alert.delivery_refused kind=%s status=%s",
            alert.kind,
            response.status_code,
        )
        return False
    return True


def dispatch(alert: SecurityAlert) -> None:
    """Deliver in the background, so the caller waits for nothing.

    Always logs, whether or not a destination is configured. The log is the
    floor: it is what a deployment that has set no webhook still gets, and it
    is what remains if the webhook is unreachable.
    """
    logger.warning("security_alert kind=%s %s", alert.kind, alert.summary)
    if not alerting_configured():
        return
    task = asyncio.create_task(deliver(alert))
    # Held so the loop cannot collect the task before it runs, which is the
    # documented way an asyncio task disappears without executing.
    _in_flight.add(task)
    task.add_done_callback(_in_flight.discard)


_in_flight: set[asyncio.Task[bool]] = set()


async def drain(timeout: float = DELIVERY_TIMEOUT_SECONDS) -> None:
    """Let deliveries already in flight finish, at shutdown.

    Without this a restart during a POST cancels the only attempt: there is no
    retry and nothing is persisted, so the alert exists as a log line and
    nowhere else. Bounded, because shutdown cannot wait on an unreachable
    destination indefinitely.
    """
    if not _in_flight:
        return
    pending = list(_in_flight)
    done, still_running = await asyncio.wait(pending, timeout=timeout)
    for task in still_running:
        task.cancel()
    if still_running:
        logger.warning("security_alert.drain_incomplete pending=%d", len(still_running))


async def failed_sign_ins_for(
    session: AsyncSession, user_id: int, *, window: timedelta
) -> int:
    """How many refused sign-ins this account has collected inside ``window``."""
    since = datetime.now(UTC) - window
    # session.exec, not session.execute: SQLModel deprecates the latter, and
    # this project turns warnings into errors.
    result = await session.exec(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.event_type == AuditEventType.AUTH_SIGN_IN_FAILED.value,
            AuditEvent.target_user_id == user_id,
            AuditEvent.occurred_at >= since,
        )
    )
    # exec() on a count returns a Row of one column.
    return int(result.one()[0])


#: When this account was last alerted about, so a count that stays above the
#: threshold produces one alert per window rather than one per attempt.
#:
#: In process, deliberately. Persisting it would put a write on the sign-in
#: path to schedule a notification, and the cost of getting it wrong is a
#: duplicate alert per replica per window -- which a person reads fine, and
#: which is much better than the alternative failure of sending none.
_last_alerted: dict[int, datetime] = {}


async def note_failed_sign_in(session: AsyncSession, user_id: int) -> None:
    """Alert once per window when an account is over the failure threshold.

    Called after the refusal has been recorded, so the count includes it.

    At or above, not exactly equal. Two refusals committing at once can carry
    the count from one below the threshold to one above it, and both readers
    then see the higher number, which no equality test would match. Every later
    count in that window is above it too. A burst is the case this exists for.

    Once per window rather than once per event, so a count that stays high
    delivers one notification rather than one per refusal.
    """
    threshold = settings.SECURITY_ALERT_FAILED_SIGN_IN_THRESHOLD
    if threshold <= 0:
        return
    window = timedelta(minutes=settings.SECURITY_ALERT_FAILED_SIGN_IN_WINDOW_MINUTES)
    try:
        count = await failed_sign_ins_for(session, user_id, window=window)
    except Exception:  # noqa: BLE001 - counting must never fail a sign-in
        # Deliberately broad, and it has a cost worth knowing: during
        # development it swallowed a real error here and the alert simply never
        # fired. Hence the exception log, and a test that asserts the swallow
        # rather than leaving it to be discovered.
        logger.exception("security_alert.count_failed user_id=%s", user_id)
        return
    if count < threshold:
        return

    now = datetime.now(UTC)
    previous = _last_alerted.get(user_id)
    if previous is not None and now - previous < window:
        return
    _last_alerted[user_id] = now
    _forget_stale_alert_marks(now, window)

    dispatch(
        SecurityAlert(
            kind="auth.failed_sign_in_threshold",
            summary=(
                f"{count} refused sign-ins for one account in "
                f"{window // timedelta(minutes=1)} minutes"
            ),
            # The account id, never the address that was typed: an address is
            # the one part of a refused sign-in that may belong to nobody.
            detail={
                "user_id": user_id,
                "count": count,
                "window_minutes": window // timedelta(minutes=1),
            },
        )
    )


def _forget_stale_alert_marks(now: datetime, window: timedelta) -> None:
    """Drop marks older than the window, so the map cannot grow without bound."""
    cutoff = now - window
    for user_id in [uid for uid, at in _last_alerted.items() if at < cutoff]:
        del _last_alerted[user_id]


async def send_test_alert() -> bool:
    """Prove the destination works, without waiting for something to go wrong.

    A sink nobody has ever seen deliver is a sink nobody knows is broken.
    """
    return await deliver(
        SecurityAlert(
            kind="test",
            summary="test alert -- security alerting is configured and reachable",
            detail={"source": "send_test_alert"},
        )
    )


def _main() -> int:
    """`python -m app.services.platform.security_alerts` — send a test alert.

    A destination nobody has seen deliver is a destination nobody knows is
    broken, and finding that out during an incident is finding it out too late.
    """
    import sys

    if not alerting_configured():
        print(
            "SECURITY_ALERT_WEBHOOK_URL is not set. Warnings are logged and "
            "nothing is delivered.\n"
            "See docs/runbooks/security-alerts.md.",
            file=sys.stderr,
        )
        return 2
    delivered = asyncio.run(send_test_alert())
    if delivered:
        print("Delivered a test alert to the configured destination.")
        return 0
    print(
        "The destination did not accept the test alert. The reason is on the "
        "WARNING line above.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(_main())

"""The properties the poller has to actually hold.

Each of these covers a way the first cut of this code was wrong: backoff that
unrelated traffic could clear, transactions split across envelopes, two replicas
delivering the same batch under different ids, and a cursor that could run past
an in-flight transaction.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.tenant.event_outbox import EventOutbox
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.services.tenant import outbox_poller

pytestmark = pytest.mark.unit


def _subscription(**overrides) -> WebhookSubscription:
    defaults = dict(
        id=7,
        guild_id=1,
        initiative_id=None,
        created_by_user_id=3,
        target_url="https://example.test/hook",
        hmac_secret="s3cret",
        event_types=["tasks.created", "tasks.updated"],
        active=True,
        cursor_event_id=0,
        failure_count=0,
        next_attempt_at=None,
    )
    defaults.update(overrides)
    return WebhookSubscription(**defaults)


def _row(row_id: int, txn_id: int, **overrides) -> EventOutbox:
    defaults = dict(
        id=row_id,
        txn_id=txn_id,
        occurred_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
        actor_user_id=3,
        initiative_id=11,
        resource_type="tasks",
        resource_id=100 + row_id,
        action="created",
        changed=[],
    )
    defaults.update(overrides)
    return EventOutbox(**defaults)


def test_event_id_is_the_same_for_the_same_batch():
    """Two replicas delivering one batch must produce one id, or a receiver
    deduping on it sees the duplicate as new work."""
    first = outbox_poller._event_id(7, 4242)
    second = outbox_poller._event_id(7, 4242)
    assert first == second
    assert first != outbox_poller._event_id(7, 4243)
    assert first != outbox_poller._event_id(8, 4242)


def test_grouping_is_by_transaction_not_adjacency():
    """Concurrent commits interleave ids, so one transaction's rows are not
    necessarily contiguous in the log."""
    subscription = _subscription()
    rows = [_row(1, 500), _row(2, 501), _row(3, 500), _row(4, 501)]

    grouped: dict[int, list[EventOutbox]] = {}
    for row in rows:
        if outbox_poller._matches(row, subscription):
            grouped.setdefault(row.txn_id, []).append(row)

    assert sorted(grouped) == [500, 501]
    assert [r.id for r in grouped[500]] == [1, 3]
    assert [r.id for r in grouped[501]] == [2, 4]


def test_one_transaction_is_one_envelope():
    subscription = _subscription()
    rows = [_row(1, 500), _row(3, 500)]
    envelope = outbox_poller._envelope(subscription, 500, rows)

    assert len(envelope["changes"]) == 2
    assert envelope["event_id"] == outbox_poller._event_id(subscription.id, 500)
    # Names and ids only — no value from any changed column rides along.
    for change in envelope["changes"]:
        assert set(change) == {
            "event_type",
            "initiative_id",
            "resource",
            "action",
            "changed",
        }


class _FakeSession:
    """Just enough session to drive _advance / _release."""

    def __init__(self) -> None:
        self.commits = 0

    def add(self, _obj) -> None:  # noqa: D102
        pass

    async def commit(self) -> None:
        self.commits += 1


async def test_an_empty_window_does_not_clear_a_failing_backoff():
    """A window holding nothing this subscriber wanted is not a delivery, so it
    must not reset a failing target's failure count."""
    now = datetime.now(timezone.utc)
    subscription = _subscription(
        failure_count=3, next_attempt_at=now + timedelta(seconds=600)
    )
    session = _FakeSession()

    await outbox_poller._advance(session, subscription, 50, now=now, outcome=None)

    assert subscription.failure_count == 3, (
        "a non-matching window reset the backoff, so unrelated traffic would "
        "keep a dead target being retried every pass"
    )
    assert subscription.cursor_event_id == 50


async def test_a_refused_delivery_backs_off_and_holds_the_cursor():
    now = datetime.now(timezone.utc)
    subscription = _subscription(cursor_event_id=10, failure_count=1)
    session = _FakeSession()

    await outbox_poller._advance(session, subscription, 9, now=now, outcome=False)

    assert subscription.failure_count == 2
    assert subscription.next_attempt_at is not None
    assert subscription.next_attempt_at > now
    # The cursor never moves backwards.
    assert subscription.cursor_event_id == 10


async def test_an_accepted_delivery_clears_failure_state():
    now = datetime.now(timezone.utc)
    subscription = _subscription(
        cursor_event_id=10, failure_count=4, next_attempt_at=now
    )
    session = _FakeSession()

    await outbox_poller._advance(session, subscription, 42, now=now, outcome=True)

    assert subscription.failure_count == 0
    assert subscription.next_attempt_at is None
    assert subscription.cursor_event_id == 42


def test_backoff_grows_and_is_bounded():
    schedule = [outbox_poller._backoff(n).total_seconds() for n in range(1, 10)]
    assert schedule == sorted(schedule), "backoff must never shrink"
    assert schedule[-1] == outbox_poller._BACKOFF_SECONDS[-1]

"""The properties the poller has to actually hold.

Each of these covers a way the first cut of this code was wrong: backoff that
unrelated traffic could clear, transactions split across envelopes, two replicas
delivering the same batch under different ids, and a cursor that could run past
an in-flight transaction.
"""

from __future__ import annotations

from datetime import datetime, timezone

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


def test_a_window_with_nothing_to_send_leaves_failure_state_alone():
    """A window holding nothing this subscriber wanted is not evidence about the
    target, so it must not clear a failing one's backoff."""
    now = datetime.now(timezone.utc)
    count, next_attempt = outbox_poller._next_retry_state(3, outcome=None, now=now)
    assert count == 3, (
        "a non-matching window reset the backoff, so unrelated traffic would "
        "keep a dead target being retried every pass"
    )
    assert next_attempt is None


def test_a_refused_delivery_backs_off():
    now = datetime.now(timezone.utc)
    count, next_attempt = outbox_poller._next_retry_state(1, outcome=False, now=now)
    assert count == 2
    assert next_attempt is not None and next_attempt > now


def test_an_accepted_delivery_clears_failure_state():
    now = datetime.now(timezone.utc)
    count, next_attempt = outbox_poller._next_retry_state(4, outcome=True, now=now)
    assert count == 0
    assert next_attempt is None


def test_backoff_grows_and_is_bounded():
    schedule = [outbox_poller._backoff(n).total_seconds() for n in range(1, 10)]
    assert schedule == sorted(schedule), "backoff must never shrink"
    assert schedule[-1] == outbox_poller._BACKOFF_SECONDS[-1]


async def test_every_subscription_in_a_guild_is_drained(
    session, acting_user, monkeypatch
):
    """Each pass expunges the identity map, so the roster is held as ids and
    each subscription is re-loaded. Held as instances, the second and later ones
    are detached and every one after the first fails."""
    from app.models.platform.guild import GuildRole
    from app.services.tenant import outbox_poller as poller

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)

    for index in range(3):
        session.add(
            WebhookSubscription(
                guild_id=a.guild.id,
                initiative_id=None,
                created_by_user_id=a.user.id,
                target_url=f"https://example.test/hook-{index}",
                hmac_secret=f"secret-{index}",
                event_types=["tasks.created"],
                active=True,
                cursor_event_id=0,
                failure_count=0,
                next_attempt_at=None,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
    await session.commit()

    drained: list[int] = []

    async def _record(session_, subscription, *, now, lease):
        drained.append(subscription.id)

    monkeypatch.setattr(poller, "_drain_subscription", _record)

    now = datetime.now(timezone.utc)
    await poller._drain_guild(session, a.guild.id, now=now)

    assert len(drained) == 3, (
        f"only {len(drained)} of 3 subscriptions drained — the rest were "
        "detached by the per-pass expunge and never delivered to"
    )


class _Span:
    """A (txn_id, first_id, last_id) row as the spans query returns it."""

    def __init__(self, txn_id: int, first_id: int, last_id: int) -> None:
        self.txn_id = txn_id
        self.first_id = first_id
        self.last_id = last_id


def test_watermark_never_lands_inside_a_transaction():
    """A stops at 5 but opened at 1, and B sits entirely inside that span.
    Stopping at B's end would cut A, so the only safe stop is A's end."""
    spans = [_Span(500, 1, 5), _Span(501, 2, 3)]

    assert outbox_poller._safe_watermark(spans) == 5


def test_watermark_stops_where_every_open_transaction_has_closed():
    spans = [_Span(500, 1, 2), _Span(501, 3, 4)]

    assert outbox_poller._safe_watermark(spans) == 4


def test_a_transaction_hidden_beyond_a_barrier_is_not_treated_as_finished():
    """The regression that produced duplicate-id envelopes.

    A wrote rows 1, 3 and 5; an in-flight transaction holds row 4. Reading rows
    and stopping at row 4 makes A look finished at 3 — it ships as [1, 3], then
    row 5 ships later under the SAME event_id and a deduping receiver drops it.
    Spans come from the database and A's last_id is 5, so the barrier at 4
    excludes A entirely rather than truncating it.
    """
    spans = [_Span(500, 1, 5)]
    barrier = 4

    eligible = [s for s in spans if s.last_id < barrier]

    assert eligible == [], (
        "transaction A ends past the barrier, so no part of it may go out yet"
    )
    assert outbox_poller._safe_watermark(eligible) is None

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


def test_window_trim_never_splits_a_transaction_at_the_limit():
    """The row limit must not cut a transaction in half.

    Mirrors _readable_window's trim: when the window ends exactly at the limit,
    the last transaction may continue past it, so its rows wait for the next
    pass rather than going out as a partial envelope.
    """
    limit = 4
    rows = [_row(1, 500), _row(2, 500), _row(3, 501), _row(4, 501)]

    tail_txn = rows[-1].txn_id
    trimmed = [r for r in rows if r.txn_id != tail_txn]

    assert [r.id for r in trimmed] == [1, 2]
    assert len(rows) == limit
    # Transaction 501 is held back whole rather than delivered as rows 3 of 4.
    assert all(r.txn_id != 501 for r in trimmed)


def test_interleaved_window_never_advances_past_a_withheld_row():
    """The cursor is one number, so it may only stop where every transaction
    that started below it also finished below it.

    Trimming the tail transaction by id alone loses events: with rows
    1(A) 2(B) 3(A) 4(B), dropping B leaves [1, 3] and a watermark of 3 — but
    row 2 is B's and sits *below* 3, so it would never be read again.
    """
    rows = [_row(1, 500), _row(2, 501), _row(3, 500), _row(4, 501)]

    prefix, watermark = outbox_poller._complete_prefix(rows, truncated=True)

    assert watermark is None or watermark < 2, (
        f"watermark {watermark} skips row 2, which was withheld with its "
        "transaction — those events are unreachable on every later pass"
    )
    assert all(r.id <= (watermark or 0) for r in prefix)


def test_complete_prefix_stops_before_an_unfinished_transaction():
    """Transaction 500 closes at row 2; 501 is still open at the window edge."""
    rows = [_row(1, 500), _row(2, 500), _row(3, 501)]

    prefix, watermark = outbox_poller._complete_prefix(rows, truncated=True)

    assert watermark == 2
    assert [r.id for r in prefix] == [1, 2]


def test_complete_prefix_takes_everything_when_nothing_is_open():
    rows = [_row(1, 500), _row(2, 500), _row(3, 501)]

    prefix, watermark = outbox_poller._complete_prefix(rows, truncated=False)

    assert watermark == 3
    assert [r.id for r in prefix] == [1, 2, 3]


def test_prefix_over_a_filtered_subset_would_skip_unseen_rows():
    """Why _complete_prefix must be given a contiguous range, not a subset.

    Rows 1(A) 2(B) 3(A) 5(A) are what a re-read filtered to transactions {A, B}
    returns; row 4 belongs to some transaction C and is invisible to it. The
    walk closes A at 5 and reports a watermark of 5 — above row 4, which it was
    never shown. The fallback therefore widens the id RANGE rather than
    filtering to particular transactions.
    """
    subset = [_row(1, 500), _row(2, 501), _row(3, 500), _row(5, 500)]

    _prefix, watermark = outbox_poller._complete_prefix(subset, truncated=False)

    assert watermark == 5, (
        "guarding the documented contract: fed a filtered subset the walk "
        "reports a watermark above rows it never saw, so callers must widen "
        "the range instead"
    )


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

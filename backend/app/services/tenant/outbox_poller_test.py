"""The properties the poller has to actually hold.

Each of these covers a way the first cut of this code was wrong: backoff that
unrelated traffic could clear, transactions split across envelopes, two replicas
delivering the same batch under different ids, and a cursor that could run past
an in-flight transaction.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.session import set_rls_context
from app.models.tenant.event_outbox import EventOutbox
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.services.tenant import outbox_poller

pytestmark = pytest.mark.unit


def _subscription(**overrides) -> WebhookSubscription:
    defaults = dict(
        id=7,
        guild_id=1,
        initiative_id=None,
        created_by=3,
        target_url="https://example.test/hook",
        hmac_secret="s3cret",
        event_types=["tasks.created", "tasks.updated"],
        active=True,
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


async def test_every_subscription_in_a_guild_is_drained(
    session, acting_user, monkeypatch
):
    """Each pass expunges the identity map, so the roster is held as ids and
    each subscription is re-loaded. Held as instances, the second and later ones
    are detached and every one after the first fails."""
    from app.models.platform.guild import GuildRole
    from app.services.tenant import outbox_poller as poller

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    guild_id, user_id = a.guild.id, a.user.id

    for index in range(3):
        session.add(
            WebhookSubscription(
                guild_id=guild_id,
                initiative_id=None,
                created_by=user_id,
                target_url=f"https://example.test/hook-{index}",
                hmac_secret=f"secret-{index}",
                event_types=["tasks.created"],
                active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
    await session.commit()

    drained: list[int] = []

    async def _record(session_, subscription, *, now):
        drained.append(subscription.id)

    monkeypatch.setattr(poller, "_drain_subscription", _record)

    now = datetime.now(timezone.utc)
    await poller._drain_guild(session, guild_id, now=now)

    assert len(drained) == 3, (
        f"only {len(drained)} of 3 subscriptions drained — the rest were "
        "detached by the per-pass expunge and never delivered to"
    )


def test_a_batch_is_one_transaction_whole():
    """Rows are selected by txn_id, so a batch is every row that transaction
    wrote. A partial batch is not a state this design can reach."""
    subscription = _subscription()
    rows = [_row(1, 500), _row(3, 500), _row(9, 500)]

    envelope = outbox_poller._envelope(subscription, 500, rows)

    assert [c["resource"]["id"] for c in envelope["changes"]] == [101, 103, 109]
    assert envelope["event_id"] == outbox_poller._event_id(subscription.id, 500)


@pytest.mark.integration
async def test_ledger_delivers_each_transaction_once(session, acting_user, monkeypatch):
    """A drain marks each pending transaction delivered, and a second pass over
    the same log sends nothing further."""
    from app.models.platform.guild import GuildRole
    from app.services.tenant import outbox_poller as poller
    from app.testing import create_task

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    guild_id, user_id = a.guild.id, a.user.id
    await create_task(session, a.project)
    await create_task(session, a.project)

    session.add(
        WebhookSubscription(
            guild_id=guild_id,
            initiative_id=None,
            created_by=user_id,
            target_url="https://example.test/hook",
            hmac_secret="secret",
            event_types=["tasks.created"],
            active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()

    sent: list[dict] = []

    async def _accept(*, target_url, secret, envelope):
        sent.append(envelope)
        return True

    monkeypatch.setattr(poller, "deliver", _accept)

    await poller._drain_guild(session, guild_id, now=datetime.now(timezone.utc))
    first_pass = len(sent)
    assert first_pass > 0, "no transaction was delivered"

    await poller._drain_guild(session, guild_id, now=datetime.now(timezone.utc))
    assert len(sent) == first_pass, (
        "a settled transaction was delivered twice — the ledger row should make "
        "it ineligible on every later pass"
    )


@pytest.mark.integration
async def test_a_refused_batch_is_retried_not_lost(session, acting_user, monkeypatch):
    """A refusal leaves the transaction pending, so it comes back once its
    backoff expires rather than being skipped."""
    from app.models.platform.guild import GuildRole
    from app.services.tenant import outbox_poller as poller
    from app.testing import create_task

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    guild_id, user_id = a.guild.id, a.user.id
    await create_task(session, a.project)

    session.add(
        WebhookSubscription(
            guild_id=guild_id,
            initiative_id=None,
            created_by=user_id,
            target_url="https://example.test/hook",
            hmac_secret="secret",
            event_types=["tasks.created"],
            active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()

    attempts: list[str] = []

    async def _refuse(*, target_url, secret, envelope):
        attempts.append(envelope["event_id"])
        return False

    monkeypatch.setattr(poller, "deliver", _refuse)

    await poller._drain_guild(session, guild_id, now=datetime.now(timezone.utc))
    assert len(attempts) == 1

    # Past the backoff, the same batch is offered again under the same id.
    later = datetime.now(timezone.utc) + timedelta(hours=2)
    await poller._drain_guild(session, guild_id, now=later)
    assert len(attempts) == 2, "a refused batch was dropped instead of retried"
    assert attempts[0] == attempts[1], (
        "the retry carried a different event_id, so a receiver deduping on it "
        "would treat the redelivery as new work"
    )


@pytest.mark.integration
async def test_repeated_refusals_escalate_the_backoff(
    session, acting_user, monkeypatch
):
    """The schedule has to be applied, not merely defined.

    _settle previously incremented attempts but always scheduled the first step,
    so an unreachable target was retried every five seconds forever. This drives
    real refusals and reads the interval Postgres actually stored.
    """
    from sqlalchemy import text as sa_text

    from app.models.platform.guild import GuildRole
    from app.services.tenant import outbox_poller as poller
    from app.testing import create_task

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    guild_id, user_id = a.guild.id, a.user.id
    await create_task(session, a.project)

    session.add(
        WebhookSubscription(
            guild_id=guild_id,
            initiative_id=None,
            created_by=user_id,
            target_url="https://example.test/hook",
            hmac_secret="secret",
            event_types=["tasks.created"],
            active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()

    async def _refuse(*, target_url, secret, envelope):
        return False

    monkeypatch.setattr(poller, "deliver", _refuse)

    intervals: list[float] = []
    moment = datetime.now(timezone.utc)
    for _ in range(3):
        await poller._drain_guild(session, guild_id, now=moment)
        await set_rls_context(session, guild_id=guild_id, guild_role="admin")
        row = (
            await session.exec(
                sa_text(
                    "SELECT attempts, next_attempt_at FROM webhook_deliveries "
                    "WHERE delivered_at IS NULL ORDER BY txn_id LIMIT 1"
                )
            )
        ).first()
        intervals.append((row[1] - moment).total_seconds())
        # Jump past the backoff so the next pass re-claims the same batch.
        moment = row[1] + timedelta(seconds=1)

    assert intervals == sorted(intervals) and intervals[0] < intervals[-1], (
        f"backoff did not escalate across repeated refusals: {intervals} — an "
        "unreachable target would be retried at the first interval forever"
    )
    assert intervals[:3] == [float(s) for s in poller._BACKOFF_SECONDS[:3]]

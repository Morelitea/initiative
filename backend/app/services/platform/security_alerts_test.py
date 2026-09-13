"""Whether a warning reaches a person, and whether it can hurt anything.

Two properties matter and they pull against each other: alerts have to be
delivered, and delivering them must never be able to fail the request that
raised one. Most of these are about the second.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.services import audit as audit_service
from app.services.platform import security_alerts

WEBHOOK = "https://alerts.example.test/hook"


class _Recorder:
    """Stands in for the destination. Records what it was sent."""

    def __init__(self, status: int = 200, raises: Exception | None = None):
        self.status = status
        self.raises = raises
        self.calls: list[dict] = []

    async def __call__(self, method, url, *, json, timeout, allow_private=False, **_):
        self.calls.append(
            {"method": method, "url": url, "json": json, "allow_private": allow_private}
        )
        if self.raises:
            raise self.raises
        return httpx.Response(self.status, request=httpx.Request(method, url))


@pytest.fixture(autouse=True)
def _forget_alert_marks():
    """Each case starts with nothing already alerted about."""
    security_alerts._last_alerted.clear()
    yield
    security_alerts._last_alerted.clear()


@pytest.fixture
def destination(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(security_alerts, "request_public_target", recorder)
    monkeypatch.setattr(settings, "SECURITY_ALERT_WEBHOOK_URL", WEBHOOK)
    return recorder


async def _settle():
    """Let the background dispatch run."""
    for _ in range(10):
        await asyncio.sleep(0)
        if not security_alerts._in_flight:
            return
    await asyncio.gather(*list(security_alerts._in_flight), return_exceptions=True)


async def _record_refusal(session: AsyncSession, user_id: int, *, at=None) -> None:
    """A refused sign-in, written the way the sign-in path writes it.

    Through the real recorder rather than a hand-built row: the table has
    columns the recorder fills in, and a test that constructs rows itself
    drifts from the shape the code under test actually reads.
    """
    event = await audit_service.record(
        session,
        event_type=AuditEventType.AUTH_SIGN_IN_FAILED,
        actor_user_id=None,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={"method": "password", "reason": "bad_password"},
    )
    if at is not None:
        event.occurred_at = at
        session.add(event)
    await session.commit()


@pytest.mark.unit
async def test_an_alert_is_delivered(destination):
    assert await security_alerts.send_test_alert() is True
    assert destination.calls[0]["url"] == WEBHOOK
    assert destination.calls[0]["method"] == "POST"


@pytest.mark.unit
async def test_the_payload_carries_text_and_structure(destination):
    # `text` is what Slack, Discord, Mattermost and Teams render; the rest is
    # for anything that parses. Losing either makes this a choice of vendor.
    await security_alerts.send_test_alert()
    body = destination.calls[0]["json"]
    assert isinstance(body["text"], str) and body["text"]
    assert body["kind"] == "test"
    assert "summary" in body and "detail" in body and "at" in body


@pytest.mark.unit
async def test_nothing_is_sent_when_no_destination_is_configured(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(security_alerts, "request_public_target", recorder)
    monkeypatch.setattr(settings, "SECURITY_ALERT_WEBHOOK_URL", None)

    assert await security_alerts.send_test_alert() is False
    assert recorder.calls == []


@pytest.mark.unit
async def test_a_refused_destination_is_reported_not_raised(monkeypatch):
    recorder = _Recorder(status=500)
    monkeypatch.setattr(security_alerts, "request_public_target", recorder)
    monkeypatch.setattr(settings, "SECURITY_ALERT_WEBHOOK_URL", WEBHOOK)

    assert await security_alerts.send_test_alert() is False


@pytest.mark.unit
async def test_an_unreachable_destination_is_reported_not_raised(monkeypatch):
    recorder = _Recorder(raises=httpx.ConnectError("no route"))
    monkeypatch.setattr(security_alerts, "request_public_target", recorder)
    monkeypatch.setattr(settings, "SECURITY_ALERT_WEBHOOK_URL", WEBHOOK)

    # The property the whole design rests on: a broken sink is not an outage.
    assert await security_alerts.send_test_alert() is False


@pytest.mark.unit
async def test_dispatch_logs_even_with_no_destination(monkeypatch, caplog):
    monkeypatch.setattr(settings, "SECURITY_ALERT_WEBHOOK_URL", None)
    alert = security_alerts.SecurityAlert(
        kind="k", summary="something happened", detail={}
    )

    with caplog.at_level(
        logging.WARNING, logger="app.services.platform.security_alerts"
    ):
        security_alerts.dispatch(alert)

    assert "something happened" in "\n".join(r.getMessage() for r in caplog.records)


def test_a_rule_carries_its_own_numbers_rather_than_settings():
    """One switch for an operator, not one per rule.

    Review asked for this shape: setting the destination turns alerting on, and
    a rule applies its own threshold. Every rule that needs a number of its own
    would otherwise add two more environment variables a self-hoster has to read
    past, and the second rule is the one that makes it a pattern rather than a
    pair.

    Asserted rather than described, because the pressure to add "just one more
    knob" arrives with the next rule and this is what refuses it.
    """
    for gone in (
        "SECURITY_ALERT_FAILED_SIGN_IN_THRESHOLD",
        "SECURITY_ALERT_FAILED_SIGN_IN_WINDOW_MINUTES",
    ):
        assert not hasattr(settings, gone), (
            f"{gone} is a per-rule knob. A rule's numbers belong beside the rule "
            "in security_alerts.py; SECURITY_ALERT_WEBHOOK_URL is the only "
            "setting an operator should need."
        )

    # And the rule does carry them, so removing the settings did not remove the
    # behaviour along with them.
    assert security_alerts.FAILED_SIGN_IN_THRESHOLD > 0
    assert security_alerts.FAILED_SIGN_IN_WINDOW > timedelta(0)


@pytest.mark.database
async def test_the_threshold_alerts_once_per_window(
    session: AsyncSession, destination, monkeypatch
):
    # One delivery per window, not one per refusal.
    monkeypatch.setattr(security_alerts, "FAILED_SIGN_IN_THRESHOLD", 3)
    monkeypatch.setattr(security_alerts, "FAILED_SIGN_IN_WINDOW", timedelta(minutes=15))
    user_id = 987_654

    for _ in range(5):
        await _record_refusal(session, user_id)
        await security_alerts.note_failed_sign_in(session, user_id)
        await _settle()

    assert len(destination.calls) == 1
    assert destination.calls[0]["json"]["kind"] == "auth.failed_sign_in_threshold"


@pytest.mark.database
async def test_the_alert_names_the_account_and_not_the_address(
    session: AsyncSession, destination, monkeypatch
):
    # An address typed at a sign-in form is the one part of a refusal that may
    # belong to nobody, so it does not leave the building.
    monkeypatch.setattr(security_alerts, "FAILED_SIGN_IN_THRESHOLD", 1)
    user_id = 987_655
    await _record_refusal(session, user_id)

    await security_alerts.note_failed_sign_in(session, user_id)
    await _settle()

    body = destination.calls[0]["json"]
    assert body["detail"]["user_id"] == user_id
    assert "@" not in body["text"]


@pytest.mark.database
async def test_failures_outside_the_window_do_not_count(
    session: AsyncSession, destination, monkeypatch
):
    monkeypatch.setattr(security_alerts, "FAILED_SIGN_IN_THRESHOLD", 2)
    monkeypatch.setattr(security_alerts, "FAILED_SIGN_IN_WINDOW", timedelta(minutes=15))
    user_id = 987_656
    old = datetime.now(UTC) - timedelta(hours=2)
    await _record_refusal(session, user_id, at=old)
    await _record_refusal(session, user_id)

    await security_alerts.note_failed_sign_in(session, user_id)
    await _settle()

    assert destination.calls == []


@pytest.mark.database
async def test_unsetting_the_destination_is_what_turns_alerting_off(
    session: AsyncSession, destination, monkeypatch
):
    """The one switch, from the other side.

    This replaces a case that set the threshold to 0 to disable the rule while
    leaving the destination working. That was a per-rule off switch, and review
    asked for the rule's numbers to stop being operator configuration -- so the
    capability went with the setting. Said plainly rather than quietly dropped:
    an operator can no longer silence this rule and keep others, and with the
    URL as the only switch, silencing everything is what unsetting it does.

    Worth revisiting only when a second rule exists and somebody actually wants
    one of them quiet. Until then it is a knob nobody asked for.
    """
    monkeypatch.setattr(settings, "SECURITY_ALERT_WEBHOOK_URL", None)
    for _ in range(security_alerts.FAILED_SIGN_IN_THRESHOLD + 1):
        await _record_refusal(session, 987_657)
    await security_alerts.note_failed_sign_in(session, 987_657)
    await _settle()

    assert destination.calls == []


@pytest.mark.database
async def test_a_counting_failure_is_swallowed_but_logged(
    session: AsyncSession, destination, monkeypatch, caplog
):
    # Counting runs on the sign-in path. If it can raise, a detective control
    # has become a way to fail authentication -- so it is swallowed.
    #
    # And the swallow has a cost: while this was being written it hid a real
    # error here and the alert simply never fired. That is why the log line is
    # asserted and not just the absence of an exception.
    async def boom(*_args, **_kwargs):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(security_alerts, "failed_sign_ins_for", boom)

    with caplog.at_level(logging.ERROR, logger="app.services.platform.security_alerts"):
        await security_alerts.note_failed_sign_in(session, 987_658)

    assert destination.calls == []
    assert "count_failed" in "\n".join(r.getMessage() for r in caplog.records)


@pytest.mark.database
async def test_a_burst_that_skips_the_exact_threshold_still_alerts(
    session: AsyncSession, destination, monkeypatch
):
    """The count can pass the threshold without ever equalling it.

    Two refusals committing at once carry it from one below to one above, and
    both readers see the higher number. An equality test delivered nothing --
    and every later count in the window is above the threshold too, so nothing
    would arrive for the rest of it.
    """
    monkeypatch.setattr(security_alerts, "FAILED_SIGN_IN_THRESHOLD", 3)
    user_id = 987_660

    # Four refusals recorded before anything counts: the first count this
    # sees is 4, and the threshold of 3 was never observed exactly.
    for _ in range(4):
        await _record_refusal(session, user_id)

    await security_alerts.note_failed_sign_in(session, user_id)
    await _settle()

    assert len(destination.calls) == 1
    assert destination.calls[0]["json"]["detail"]["count"] == 4


@pytest.mark.database
async def test_a_second_window_alerts_again(
    session: AsyncSession, destination, monkeypatch
):
    # Once per window, not once ever: an account still under attempt an hour
    # later has to be reported again.
    monkeypatch.setattr(security_alerts, "FAILED_SIGN_IN_THRESHOLD", 1)
    monkeypatch.setattr(security_alerts, "FAILED_SIGN_IN_WINDOW", timedelta(minutes=15))
    user_id = 987_661
    await _record_refusal(session, user_id)

    await security_alerts.note_failed_sign_in(session, user_id)
    await _settle()
    assert len(destination.calls) == 1

    # The window has passed.
    security_alerts._last_alerted[user_id] = datetime.now(UTC) - timedelta(hours=1)
    await security_alerts.note_failed_sign_in(session, user_id)
    await _settle()

    assert len(destination.calls) == 2


@pytest.mark.database
async def test_one_account_alerting_does_not_silence_another(
    session: AsyncSession, destination, monkeypatch
):
    monkeypatch.setattr(security_alerts, "FAILED_SIGN_IN_THRESHOLD", 1)
    first, second = 987_662, 987_663
    await _record_refusal(session, first)
    await _record_refusal(session, second)

    await security_alerts.note_failed_sign_in(session, first)
    await security_alerts.note_failed_sign_in(session, second)
    await _settle()

    assert {c["json"]["detail"]["user_id"] for c in destination.calls} == {
        first,
        second,
    }


@pytest.mark.unit
async def test_a_mark_older_than_the_window_is_forgotten():
    # The map is keyed by account and would otherwise grow for the life of the
    # process.
    now = datetime.now(UTC)
    security_alerts._last_alerted.update({1: now - timedelta(hours=2), 2: now})

    security_alerts._forget_stale_alert_marks(now, timedelta(minutes=15))

    assert set(security_alerts._last_alerted) == {2}


@pytest.mark.unit
async def test_draining_waits_for_a_delivery_in_flight(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    delivered: list[bool] = []

    async def slow(*_args, **_kwargs):
        started.set()
        await release.wait()
        delivered.append(True)
        return httpx.Response(200, request=httpx.Request("POST", WEBHOOK))

    monkeypatch.setattr(security_alerts, "request_public_target", slow)
    monkeypatch.setattr(settings, "SECURITY_ALERT_WEBHOOK_URL", WEBHOOK)

    security_alerts.dispatch(
        security_alerts.SecurityAlert(kind="k", summary="s", detail={})
    )
    await started.wait()
    release.set()

    await security_alerts.drain(timeout=5)

    assert delivered == [True]


@pytest.mark.unit
async def test_draining_gives_up_rather_than_hanging_shutdown(monkeypatch):
    # A destination that never answers must not hold the process open.
    async def never(*_args, **_kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(security_alerts, "request_public_target", never)
    monkeypatch.setattr(settings, "SECURITY_ALERT_WEBHOOK_URL", WEBHOOK)

    security_alerts.dispatch(
        security_alerts.SecurityAlert(kind="k", summary="s", detail={})
    )
    await asyncio.sleep(0)

    await asyncio.wait_for(security_alerts.drain(timeout=0.05), timeout=5)

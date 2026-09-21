"""The terms an account agrees to, and the record that it did.

Two things these hold down. A self-hosted deployment must never ask anybody to
accept anything — it has no terms of its own and no portal to serve them — and
a hosted one must never fail a registration because the portal is having a bad
day: the acceptance is the fact, the version is the garnish.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.models.platform.legal_acceptance import LegalAcceptance
from app.services.platform import legal as legal_service
from app.testing import create_user

PORTAL = "https://billing.example.com"

INDEX_BODY = {
    "documents": [
        {
            "slug": "terms",
            "title": "Terms of Service",
            "version": "2.1",
            "effective_date": "2026-09-01",
            "sha256": "a" * 64,
        },
        {
            "slug": "privacy",
            "title": "Privacy Policy",
            "version": "1.4",
            "effective_date": "2026-09-01",
            "sha256": "b" * 64,
        },
    ]
}


@pytest.fixture(autouse=True)
def _clear_cache():
    legal_service.reset_index_cache()
    yield
    legal_service.reset_index_cache()


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setattr(settings, "BILLING_URL", PORTAL)


def _serve(monkeypatch, body=INDEX_BODY, *, fail: bool = False):
    """Stand in for the portal's index endpoint, counting the calls."""
    calls: list[str] = []

    class _Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return body

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def get(self, url, **kwargs):
            calls.append(url)
            if fail:
                raise RuntimeError("portal is down")
            return _Response()

    monkeypatch.setattr(legal_service.httpx, "AsyncClient", _Client)
    return calls


@pytest.mark.unit
def test_a_self_hosted_deployment_has_no_terms(monkeypatch):
    """No portal, no legal entity behind the service, nothing to accept."""
    monkeypatch.setattr(settings, "BILLING_URL", None)
    assert legal_service.legal_documents_enabled() is False


@pytest.mark.unit
def test_a_portal_makes_it_hosted(hosted):
    assert legal_service.legal_documents_enabled() is True


@pytest.mark.unit
async def test_index_is_read_once_and_then_cached(hosted, monkeypatch):
    calls = _serve(monkeypatch)

    first = await legal_service.get_index()
    second = await legal_service.get_index()

    assert [d.slug for d in first] == ["terms", "privacy"]
    assert second == first
    assert len(calls) == 1


@pytest.mark.unit
async def test_a_portal_that_goes_down_keeps_answering_from_the_last_read(
    hosted, monkeypatch
):
    _serve(monkeypatch)
    await legal_service.get_index()

    _serve(monkeypatch, fail=True)
    still = await legal_service.get_index(force=True)

    assert [d.version for d in still] == ["2.1", "1.4"]


@pytest.mark.unit
async def test_a_portal_that_was_never_reached_raises(hosted, monkeypatch):
    _serve(monkeypatch, fail=True)
    with pytest.raises(legal_service.LegalPortalUnavailable):
        await legal_service.get_index()


@pytest.mark.integration
async def test_nothing_is_recorded_on_a_self_hosted_deployment(session, monkeypatch):
    monkeypatch.setattr(settings, "BILLING_URL", None)
    user = await create_user(session)

    await legal_service.record_acceptance(session, user_id=user.id)
    await session.commit()

    assert await _rows(session, user.id) == []
    assert await legal_service.acceptance_outstanding(session, user=user) is False


@pytest.mark.integration
async def test_acceptance_records_the_revision_that_was_current(
    session, hosted, monkeypatch
):
    _serve(monkeypatch)
    user = await create_user(session)

    await legal_service.record_acceptance(session, user_id=user.id)
    await session.commit()

    rows = await _rows(session, user.id)
    assert [(r.document, r.version, r.document_sha256) for r in rows] == [
        ("terms", "2.1", "a" * 64),
        ("privacy", "1.4", "b" * 64),
    ]
    assert await legal_service.acceptance_outstanding(session, user=user) is False


@pytest.mark.integration
async def test_an_unreachable_portal_still_records_the_acceptance(
    session, hosted, monkeypatch
):
    """What is being written down is that somebody agreed, and when. Which
    revision they agreed to is recoverable from the portal's own history of
    the document; refusing the registration over it would not be."""
    _serve(monkeypatch, fail=True)
    user = await create_user(session)

    await legal_service.record_acceptance(session, user_id=user.id)
    await session.commit()

    rows = await _rows(session, user.id)
    assert [r.document for r in rows] == ["terms", "privacy"]
    assert [r.version for r in rows] == [None, None]
    assert await legal_service.acceptance_outstanding(session, user=user) is False


@pytest.mark.integration
async def test_a_half_finished_record_still_owes_the_rest(session, hosted, monkeypatch):
    _serve(monkeypatch)
    user = await create_user(session)
    session.add(LegalAcceptance(user_id=user.id, document="terms", version="2.1"))
    await session.commit()

    assert await legal_service.acceptance_outstanding(session, user=user) is True


@pytest.mark.integration
async def test_a_document_nobody_asked_for_does_not_settle_the_debt(
    session, hosted, monkeypatch
):
    _serve(monkeypatch)
    user = await create_user(session)
    session.add(LegalAcceptance(user_id=user.id, document="sla", version="1.0"))
    session.add(LegalAcceptance(user_id=user.id, document="terms", version="2.1"))
    session.add(LegalAcceptance(user_id=user.id, document="sla", version="1.1"))
    await session.commit()

    assert await legal_service.acceptance_outstanding(session, user=user) is True


@pytest.mark.integration
async def test_a_newer_revision_does_not_interrupt_somebody_already_here(
    session, hosted, monkeypatch
):
    """The question is whether they ever agreed, not whether they agreed to
    today's wording. Publishing a correction must not put every account in the
    deployment back in front of a consent screen."""
    _serve(monkeypatch)
    user = await create_user(session)
    await legal_service.record_acceptance(session, user_id=user.id)
    await session.commit()

    moved = {
        "documents": [
            {**d, "version": "9.9", "sha256": "c" * 64} for d in INDEX_BODY["documents"]
        ]
    }
    legal_service.reset_index_cache()
    _serve(monkeypatch, moved)

    assert await legal_service.acceptance_outstanding(session, user=user) is False


async def _rows(session, user_id: int) -> list[LegalAcceptance]:
    from sqlmodel import select

    return list(
        (
            await session.exec(
                select(LegalAcceptance)
                .where(LegalAcceptance.user_id == user_id)
                .order_by(LegalAcceptance.id)
            )
        ).all()
    )

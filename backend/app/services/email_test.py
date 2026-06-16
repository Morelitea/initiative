"""Tests for transactional email rendering (SEC-5: HTML escaping)."""

import pytest

from app.core.email_i18n import email_t
from app.services import email as email_service
from app.testing import create_user

EVIL_NAME = '<a href="https://phish.example">Reset your password</a>'


@pytest.mark.integration
async def test_mention_email_escapes_malicious_display_name(session, monkeypatch):
    """A mention email whose actor display name contains markup must show the
    literal text in the HTML part (no live phishing link inside the trusted,
    brand-styled body) while the plain-text alternative keeps the raw text."""
    user = await create_user(session, full_name="Victim")

    captured: dict = {}

    async def fake_send_email(
        _session, *, recipients, subject, html_body, text_body=None, settings_obj=None
    ):
        captured.update(
            recipients=recipients,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
        )

    monkeypatch.setattr(email_service, "send_email", fake_send_email)

    # Mirrors notify_document_mention: the actor name is interpolated via
    # email_t, which now escapes values for the email (HTML) namespace.
    body_text = email_t(
        "mention.document.body", "en", actor=EVIL_NAME, document="Plans"
    )
    await email_service.send_mention_email(
        session,
        user,
        subject=email_t(
            "mention.document.subject", "en", document="Plans", escape=False
        ),
        headline=email_t("mention.document.title", "en"),
        body_text=body_text,
        link="https://app.example/documents/1",
    )

    # HTML part: markup neutralized to literal text; template <strong> intact.
    assert EVIL_NAME not in captured["html_body"]
    assert "&lt;a href=&quot;https://phish.example&quot;&gt;" in captured["html_body"]
    assert "<strong>" in captured["html_body"]
    # Plain-text part: the user's raw text, tags from the template stripped.
    assert EVIL_NAME in captured["text_body"]
    # Subject is a header, not HTML — never entity-encoded.
    assert captured["subject"] == "You were mentioned in Plans"


@pytest.mark.unit
def test_strip_html_unescapes_entities():
    # The plain-text alternative is derived from the escaped HTML fragment, so
    # tags are stripped first and entities decoded back to literal text.
    assert (
        email_service._strip_html("<strong>Tom &amp; Jerry</strong> said &lt;hi&gt;")
        == "Tom & Jerry said <hi>"
    )

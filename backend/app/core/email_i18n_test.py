"""Unit tests for the JSON-based translation loader."""

import pytest

from app.core.email_i18n import email_t, translate


@pytest.mark.unit
def test_translate_resolves_email_namespace_by_default():
    assert translate("verification.subject", "en") == "Verify your Initiative account"


@pytest.mark.unit
def test_email_namespace_holds_rich_email_copy():
    # The email namespace carries subject + title + body for a notification.
    assert translate("event.invitation.subject", "en", event="Raid Night") == (
        "You're invited: Raid Night"
    )
    assert (
        translate(
            "event.invitation.body",
            "en",
            organizer="Ada",
            event="Raid Night",
            when="tonight",
        )
        == "Ada invited you to Raid Night (tonight)."
    )


@pytest.mark.unit
def test_notifications_namespace_holds_terse_push_copy():
    # The notifications namespace carries only title + body, worded for push.
    assert (
        translate("event.invitation.title", "en", namespace="notifications")
        == "New event invitation"
    )
    assert (
        translate(
            "event.invitation.body",
            "en",
            namespace="notifications",
            event="Raid",
            when="8pm",
        )
        == "Raid (8pm)"
    )


@pytest.mark.unit
def test_translate_localizes_per_locale():
    assert (
        translate("comment.reply.title", "es", namespace="notifications")
        == "Respuesta a tu comentario"
    )
    assert (
        translate(
            "mention.task.body",
            "fr",
            namespace="notifications",
            actor="Léa",
            task="Donjon",
            context="Quête",
        )
        == "Léa a mentionné Donjon dans Quête"
    )


@pytest.mark.unit
def test_access_grant_level_word_is_localized():
    body = translate(
        "accessGrant.approved.body",
        "fr",
        namespace="notifications",
        guild="Guilde",
        level=translate("accessGrant.levelReadWrite", "fr", namespace="notifications"),
    )
    assert body == "Votre accès en lecture-écriture à Guilde a été approuvé"


@pytest.mark.unit
def test_translate_falls_back_to_english_for_untranslated_locale():
    # ``zz`` has no locale files at all, so it must fall back to English
    # rather than surfacing the raw key.
    assert (
        translate("event.reminder.title", "zz", namespace="notifications")
        == "Upcoming event"
    )


@pytest.mark.unit
def test_translate_returns_key_when_missing_everywhere():
    assert translate("event.nope.missing", "en", namespace="notifications") == (
        "event.nope.missing"
    )


@pytest.mark.unit
def test_email_t_is_backward_compatible():
    assert email_t("verification.subject", "fr") == "Vérifiez votre compte Initiative"


@pytest.mark.unit
def test_plural_selection_uses_count():
    one = translate("overdue.body", "en", count=1)
    other = translate("overdue.body", "en", count=3)
    assert one == "You have 1 overdue task:"
    assert other == "You have 3 overdue tasks:"

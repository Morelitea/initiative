"""The slug rule and the first free suffixed slug."""

from app.services.tenant.names import slugify, unique_slug


def test_slugify_keeps_the_alphabet_and_falls_back_when_nothing_survives():
    assert slugify("  Release Notes: v2.0!  ", fallback="page") == "release-notes-v2-0"
    assert slugify("Café — menu", fallback="page") == "caf-menu"
    assert slugify("???", fallback="page") == "page"
    assert slugify("abc def", fallback="page", max_length=4) == "abc"


def test_unique_slug_suffixes_from_two_within_the_length():
    assert unique_slug("notes", set()) == "notes"
    assert unique_slug("notes", {"notes", "notes-2"}) == "notes-3"
    assert unique_slug("abcdef", {"abcdef"}, max_length=6) == "abcd-2"

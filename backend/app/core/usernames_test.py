"""What a name part may be, and what a seed turns into."""

import pytest

from app.core import usernames
from app.core.usernames import UsernameError

pytestmark = pytest.mark.unit


class TestValidate:
    @pytest.mark.parametrize(
        "name", ["foobar", "abc", "a_b-c", "jordan2", "x" * 32, "FooBar"]
    )
    def test_accepts(self, name):
        assert usernames.validate(name) == name.lower()

    @pytest.mark.parametrize(
        ("name", "code"),
        [
            ("ab", "USERNAME_TOO_SHORT"),
            ("x" * 33, "USERNAME_TOO_LONG"),
            ("foo bar", "USERNAME_INVALID_CHARACTERS"),
            ("foo.bar", "USERNAME_INVALID_CHARACTERS"),
            ("foo@bar", "USERNAME_INVALID_CHARACTERS"),
            # ``#`` separates the two halves of a handle, so it cannot be in one.
            ("foo#bar", "USERNAME_INVALID_CHARACTERS"),
            ("foo--bar", "USERNAME_INVALID_CHARACTERS"),
            ("foo-", "USERNAME_INVALID_CHARACTERS"),
            ("1jordan", "USERNAME_MUST_START_WITH_LETTER"),
            ("-jordan", "USERNAME_MUST_START_WITH_LETTER"),
            # Digits alone would read as a discriminator rather than a name.
            ("1234", "USERNAME_MUST_START_WITH_LETTER"),
            ("admin", "USERNAME_RESERVED"),
            ("support", "USERNAME_RESERVED"),
        ],
    )
    def test_refuses(self, name, code):
        with pytest.raises(UsernameError) as exc:
            usernames.validate(name)
        assert exc.value.code == code


class TestSlugify:
    @pytest.mark.parametrize(
        ("seed", "expected"),
        [
            ("Jordan", "jordan"),
            ("Jordan Drako", "jordan-drako"),
            ("  Jordan  ", "jordan"),
            ("Renée", "renee"),
            ("O'Brien", "obrien"),
        ],
    )
    def test_reduces_a_typed_name(self, seed, expected):
        assert usernames.slugify(seed) == expected

    @pytest.mark.parametrize("seed", [None, "", "   ", "!!!", "ab", "12"])
    def test_gives_up_on_nothing_usable(self, seed):
        assert usernames.slugify(seed) is None

    @pytest.mark.parametrize(
        "seed", ["jordan@example.com", "Jordan <jordan@example.com>"]
    )
    def test_an_address_is_never_a_handle(self, seed):
        """An SSO account with no name claim stored its address as its display
        name, so the seed has to refuse one."""
        assert usernames.slugify(seed) is None

    @pytest.mark.parametrize(
        ("full_name", "expected"),
        [
            # First initial, then last name.
            ("Lee Janzen", "ljanzen"),
            ("Jordan Janzen", "jjanzen"),
            ("Ada Lovelace King", "aking"),
            ("J. Janzen", "jjanzen"),
            ("Élodie Martin", "emartin"),
            # One word has no last name to join, so it stands on its own.
            ("Jordan", "jordan"),
            # An address is never the source of a handle.
            ("jordan@example.com", None),
            (None, None),
            ("   ", None),
            # Too little survives to be a handle.
            ("A B", None),
        ],
    )
    def test_builds_from_a_display_name(self, full_name, expected):
        assert usernames.from_full_name(full_name) == expected


class TestGenerated:
    def test_a_generated_name_is_valid(self):
        for _ in range(50):
            usernames.validate(usernames.random_name())

    def test_a_number_is_in_range(self):
        for _ in range(200):
            assert 0 <= usernames.random_discriminator() <= 9999


class TestHandleText:
    def test_the_number_is_always_four_digits(self):
        assert usernames.format_handle("foobar", 12) == "foobar#0012"
        assert usernames.format_handle("foobar", 1234) == "foobar#1234"
        assert usernames.format_handle("foobar", 0) == "foobar#0000"

    @pytest.mark.parametrize(
        ("term", "expected"),
        [
            ("foobar", ("foobar", None)),
            ("foobar#1234", ("foobar", "1234")),
            ("foobar#12", ("foobar", "12")),
            ("foobar#", ("foobar", None)),
            # A number is digits. Anything else after the ``#`` is not a
            # discriminator, so the whole term stays a name search.
            ("foobar#ab", ("foobar#ab", None)),
        ],
    )
    def test_a_typed_term_splits(self, term, expected):
        assert usernames.parse_handle(term) == expected

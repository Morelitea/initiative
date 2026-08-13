"""What Initiative hands an app service, and what it deliberately does not.

Four properties carry the weight, and each is here because losing it quietly
would be hard to notice from the outside:

* **One guild.** ``guild_id`` is a claim on a token minted for one call. A token
  that named two guilds, or named none, would be a standing key.
* **About a minute.** Long enough for a round trip, short enough that a captured
  token is spent before it is useful.
* **No person.** No ``sub``, no email, no name — anywhere in the payload. Where a
  member's own vendor credential is involved the token carries the *opaque*
  handle instead, which is exactly the substitution that keeps an app from
  accumulating identities.
* **One audience.** ``initiative-app:<public_id>``, so a token minted for one app
  is not accepted by another even if it somehow crosses.

The JWKS is checked by actually verifying a minted token against it, rather than
by comparing fields — that is what an app will do, and it is the only assertion
that fails if the encoding is subtly wrong.
"""

import base64
import json
from datetime import timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import settings
from app.core.security import AppPlatformSigningNotConfiguredError
from app.services.marketplace import context_jwt

pytestmark = pytest.mark.unit

_keypair = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _keypair.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()

PUBLIC_ID = "acme.shop"
KEY_ID = "app-platform-1"


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", _PRIVATE_PEM)
    monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_KEY_ID", KEY_ID)
    # The document is memoized per key; a test that swaps the key must not read
    # the previous one's answer.
    monkeypatch.setattr(context_jwt, "_jwks_cache", None, raising=False)


def _mint(**overrides) -> str:
    token, _ = context_jwt.mint_context_token(
        **{
            "public_id": PUBLIC_ID,
            "guild_id": 7,
            "app_install_id": 3,
            "scope": "data",
            **overrides,
        }
    )
    return token


def _claims(token: str) -> dict:
    return jwt.decode(
        token,
        _keypair.public_key(),
        algorithms=["RS256"],
        audience=f"initiative-app:{PUBLIC_ID}",
    )


class TestClaims:
    def test_the_token_is_pinned_to_one_guild_and_one_install(self):
        claims = _claims(_mint(guild_id=42, app_install_id=9))
        assert claims["guild_id"] == 42
        assert claims["app_install_id"] == 9
        assert claims["scope"] == "data"

    def test_the_audience_names_exactly_one_app(self):
        token = _mint()
        assert _claims(token)["aud"] == f"initiative-app:{PUBLIC_ID}"

        # Another app's service must not accept it, which is what verifying
        # against its own audience proves.
        with pytest.raises(jwt.InvalidAudienceError):
            jwt.decode(
                token,
                _keypair.public_key(),
                algorithms=["RS256"],
                audience="initiative-app:other.app",
            )

    def test_it_expires_in_about_a_minute(self):
        claims = _claims(_mint())
        assert claims["exp"] - claims["iat"] == 60

    def test_a_shorter_lifetime_is_honored(self):
        claims = _claims(_mint(lifetime=timedelta(seconds=15)))
        assert claims["exp"] - claims["iat"] == 15

    def test_it_carries_no_user_identity_at_all(self):
        """Not "no ``sub``" — nothing anywhere in the payload that is a person.

        Asserted over the whole serialized claim set rather than a field list,
        so a later claim carrying an identity fails here rather than shipping.
        """
        token = _mint(connection_refs={"github": "cr_7f3abc"})
        claims = _claims(token)

        assert "sub" not in claims
        assert set(claims) <= {
            "jti",
            "iss",
            "aud",
            "iat",
            "exp",
            "guild_id",
            "app_install_id",
            "scope",
            "source_id",
            "action_id",
            "connection_refs",
        }
        body = json.dumps(claims)
        for identity in ("user_id", "email", "full_name", "username", "sub"):
            assert identity not in body

    def test_connection_refs_travel_only_when_a_member_credential_is_involved(self):
        assert "connection_refs" not in _claims(_mint())
        assert _claims(_mint(connection_refs={"github": "cr_1"}))[
            "connection_refs"
        ] == {"github": "cr_1"}

    def test_the_source_is_named_when_one_is_being_fetched(self):
        claims = _claims(_mint(source_id="orders_summary"))
        assert claims["source_id"] == "orders_summary"
        assert "action_id" not in claims

    def test_every_token_has_its_own_jti(self):
        assert _claims(_mint())["jti"] != _claims(_mint())["jti"]

    def test_the_key_id_is_stamped_so_a_rotation_can_be_followed(self):
        assert jwt.get_unverified_header(_mint())["kid"] == KEY_ID

    @pytest.mark.parametrize("scope", ["data", "action", "lifecycle"])
    def test_the_scope_vocabulary_is_what_it_declares(self, scope):
        assert _claims(_mint(scope=scope))["scope"] == scope

    def test_an_unknown_scope_is_refused(self):
        with pytest.raises(context_jwt.ContextTokenError):
            _mint(scope="admin")

    def test_more_handles_than_a_call_can_need_are_refused(self):
        with pytest.raises(context_jwt.ContextTokenError):
            _mint(connection_refs={f"c{i}": f"ref{i}" for i in range(11)})


class TestJwks:
    def test_a_minted_token_verifies_against_the_published_key(self):
        """The assertion an app actually makes."""
        document = context_jwt.context_jwks()
        entry = document["keys"][0]

        def _int(value: str) -> int:
            padded = value + "=" * (-len(value) % 4)
            return int.from_bytes(base64.urlsafe_b64decode(padded), "big")

        rebuilt = rsa.RSAPublicNumbers(_int(entry["e"]), _int(entry["n"])).public_key()
        claims = jwt.decode(
            _mint(),
            rebuilt,
            algorithms=["RS256"],
            audience=f"initiative-app:{PUBLIC_ID}",
        )
        assert claims["guild_id"] == 7

    def test_it_publishes_the_kid_the_header_carries(self):
        entry = context_jwt.context_jwks()["keys"][0]
        assert entry["kid"] == KEY_ID
        assert entry["kty"] == "RSA"
        assert entry["alg"] == "RS256"
        assert entry["use"] == "sig"

    def test_it_publishes_no_private_material(self):
        body = json.dumps(context_jwt.context_jwks())
        for private in ("d", "p", "q", "dp", "dq", "qi"):
            assert f'"{private}"' not in body

    def test_it_refuses_rather_than_publishing_an_empty_key_set(self, monkeypatch):
        """An empty ``keys`` array is a claim ("this platform has no keys") that
        an app would cache. Absent configuration raises instead."""
        monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", None)
        monkeypatch.setattr(context_jwt, "_jwks_cache", None, raising=False)
        with pytest.raises(AppPlatformSigningNotConfiguredError):
            context_jwt.context_jwks()

    def test_a_key_that_is_not_rsa_is_reported_rather_than_published(self, monkeypatch):
        from cryptography.hazmat.primitives.asymmetric import ed25519

        pem = (
            ed25519.Ed25519PrivateKey.generate()
            .private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            .decode()
        )
        monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", pem)
        monkeypatch.setattr(context_jwt, "_jwks_cache", None, raising=False)
        with pytest.raises(context_jwt.ContextTokenError):
            context_jwt.context_jwks()

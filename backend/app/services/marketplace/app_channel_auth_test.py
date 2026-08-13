"""The signing scheme itself, checked without a database.

The endpoint tests hold the behaviour an app sees; these hold the two pure
pieces underneath it — what goes into the MAC, and what the header reader will
accept before anything is looked up. Keeping them separate matters because the
signing material is a published contract: an app-kit in another language has to
reproduce it byte for byte, so a change here should read as a change to that
contract rather than as an incidental test edit.
"""

import hashlib
import time

import pytest

from app.core.messages import AppChannelMessages
from app.services.marketplace.app_channel_auth import (
    APP_HEADER,
    NONCE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_WINDOW_SECONDS,
    TIMESTAMP_HEADER,
    AppChannelAuthError,
    read_envelope,
    sign_request,
    signing_material,
)

pytestmark = pytest.mark.unit

SECRET = "shared"
ARGS = {
    "method": "post",
    "path": "/api/v1/app-service/events",
    "timestamp": "1755000000",
    "nonce": "abc123",
    "body": b'{"guild_id":1}',
}


def _headers(**overrides) -> dict[str, str]:
    stamp = str(overrides.pop("timestamp", int(time.time())))
    headers = {
        APP_HEADER: "tests.shop",
        TIMESTAMP_HEADER: stamp,
        NONCE_HEADER: "abc123",
        SIGNATURE_HEADER: "sha256=" + "0" * 64,
    }
    headers.update(overrides)
    return headers


class TestSigningMaterial:
    def test_the_material_is_the_documented_field_order(self):
        """Method, path, timestamp, nonce, body digest — newline separated, with
        the method upper-cased so a client's spelling does not decide."""
        material = signing_material(**ARGS).decode()

        assert material.split("\n") == [
            "POST",
            "/api/v1/app-service/events",
            "1755000000",
            "abc123",
            hashlib.sha256(ARGS["body"]).hexdigest(),
        ]

    def test_the_body_enters_as_a_digest_not_verbatim(self):
        """A large body costs the same to sign as a small one, and the material
        stays a fixed length."""
        small = signing_material(**{**ARGS, "body": b"x"})
        large = signing_material(**{**ARGS, "body": b"x" * 100_000})

        assert len(small) == len(large)
        assert small != large

    @pytest.mark.parametrize(
        "changed",
        [
            {"method": "get"},
            {"path": "/api/v1/app-service/installs"},
            {"timestamp": "1755000001"},
            {"nonce": "different"},
            {"body": b'{"guild_id":2}'},
        ],
    )
    def test_every_field_changes_the_signature(self, changed):
        assert sign_request(SECRET, **ARGS) != sign_request(
            SECRET, **{**ARGS, **changed}
        )

    def test_the_secret_changes_the_signature(self):
        assert sign_request(SECRET, **ARGS) != sign_request("other", **ARGS)

    def test_the_signature_is_prefixed_hex(self):
        signature = sign_request(SECRET, **ARGS)

        assert signature.startswith("sha256=")
        assert len(signature) == len("sha256=") + 64
        int(signature.removeprefix("sha256="), 16)


class TestEnvelopeShape:
    def test_a_complete_envelope_is_read(self):
        envelope = read_envelope(_headers())

        assert envelope.public_id == "tests.shop"
        assert envelope.nonce == "abc123"

    def test_the_app_id_is_normalized(self):
        """One canonical spelling, because it is what a registration lookup and
        a JWT audience are built from."""
        envelope = read_envelope(_headers(**{APP_HEADER: "  Tests.Shop  "}))

        assert envelope.public_id == "tests.shop"

    @pytest.mark.parametrize(
        "header", [APP_HEADER, TIMESTAMP_HEADER, NONCE_HEADER, SIGNATURE_HEADER]
    )
    def test_a_missing_header_is_refused(self, header):
        headers = _headers()
        del headers[header]

        with pytest.raises(AppChannelAuthError) as exc:
            read_envelope(headers)
        assert exc.value.code == AppChannelMessages.MISSING_SIGNATURE

    def test_a_signature_without_the_algorithm_prefix_is_refused(self):
        with pytest.raises(AppChannelAuthError) as exc:
            read_envelope(_headers(**{SIGNATURE_HEADER: "0" * 64}))
        assert exc.value.code == AppChannelMessages.MISSING_SIGNATURE

    def test_an_oversized_nonce_is_refused_before_any_lookup(self):
        with pytest.raises(AppChannelAuthError) as exc:
            read_envelope(_headers(**{NONCE_HEADER: "n" * 200}))
        assert exc.value.code == AppChannelMessages.MISSING_SIGNATURE

    @pytest.mark.parametrize(
        "offset", [-(SIGNATURE_WINDOW_SECONDS + 1), SIGNATURE_WINDOW_SECONDS + 1]
    )
    def test_a_timestamp_outside_the_window_is_refused(self, offset):
        with pytest.raises(AppChannelAuthError) as exc:
            read_envelope(_headers(timestamp=int(time.time()) + offset))
        assert exc.value.code == AppChannelMessages.STALE_TIMESTAMP

    def test_a_timestamp_inside_the_window_is_read(self):
        inside = int(time.time()) - (SIGNATURE_WINDOW_SECONDS - 5)

        assert read_envelope(_headers(timestamp=inside)).timestamp == inside

    def test_a_non_numeric_timestamp_is_refused(self):
        with pytest.raises(AppChannelAuthError) as exc:
            read_envelope(_headers(**{TIMESTAMP_HEADER: "recently"}))
        assert exc.value.code == AppChannelMessages.STALE_TIMESTAMP

    def test_the_refusal_carries_its_own_status(self):
        """The endpoint layer maps a refusal by reading it, rather than keeping
        a second table of codes to statuses."""
        error = AppChannelAuthError(AppChannelMessages.APP_DISABLED, status_code=403)

        assert error.code == AppChannelMessages.APP_DISABLED
        assert error.status_code == 403

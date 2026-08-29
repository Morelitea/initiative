"""What the registry client will and will not accept.

There is no network here. Each test builds an index in memory, signs it with a
key generated in the test, and serves it through a stand-in for the egress
helper — which also records every URL that was asked for, so "did the client
stop before it read the content" is an assertion rather than an assumption.

The tests are grouped by what they defend:

* the signature, and the order it is checked in;
* the key set, and which publisher a key may speak for;
* freshness and the serial, which are what a signature alone cannot say;
* the digest pin on every file the index names;
* what actually lands in the catalog afterwards, including that no image URL
  belonging to somebody else survives the trip.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlmodel import select

from app.core.config import settings
from app.core.messages import MarketplaceRegistryMessages as Codes
from app.models.platform.marketplace import MarketplaceListing
from app.models.platform.marketplace_registry import (
    MarketplaceMedia,
    MarketplaceRegistryState,
)
from app.services.marketplace import registry


REGISTRY_ROOT = "https://registry.example.test/catalog/"
INDEX_URL = REGISTRY_ROOT + "index.json"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _jwks(*entries: tuple[str, Ed25519PrivateKey, list[str]]) -> str:
    """A JWKS document for the given ``(kid, key, prefixes)`` triples."""
    keys = []
    for kid, private, prefixes in entries:
        raw = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        keys.append(
            {
                "kty": "OKP",
                "crv": "Ed25519",
                "kid": kid,
                "x": _b64(raw),
                "publisher_prefixes": list(prefixes),
            }
        )
    return json.dumps({"keys": keys})


def _png(seed: str) -> bytes:
    """Bytes that begin like a PNG. Nothing decodes them; the client checks the
    leading bytes against the type the index declares, and the tail keeps each
    fixture image's digest distinct."""
    return b"\x89PNG\r\n\x1a\n" + seed.encode()


class FakeRegistry:
    """A static host, in a dict."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.requested: list[str] = []
        self.unreachable: set[str] = set()
        self.entries: list[dict[str, Any]] = []

    # --- publishing side ---------------------------------------------------

    def _put(self, name: str, data: bytes) -> dict[str, Any]:
        self.files[REGISTRY_ROOT + name] = data
        return {
            "url": name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }

    def add(
        self,
        public_id: str,
        uid: str,
        *,
        kind: str = "app",
        version: str = "1.0.0",
        definition: Optional[dict[str, Any]] = None,
        avatar_url: str = "https://images.example.invalid/pixel.gif",
        images: Optional[list[str]] = None,
        name: str = "A thing",
    ) -> dict[str, Any]:
        """Publish one listing: its manifest file, its icon, and the index entry
        naming both by digest.

        The manifest deliberately carries a remote ``avatar_url`` and remote
        ``images`` — that is what a third-party manifest looks like before the
        client mirrors its artwork.
        """
        manifest = {
            "uid": uid,
            "public_id": public_id,
            "kind": kind,
            "name": name,
            # Attribution is required on every ingestion path, a registry's
            # included — a manifest without it is refused by the validator
            # before anything here gets a say.
            "publisher": "Acme",
            "description": "A thing from a registry.",
            "avatar_url": avatar_url,
            "images": (
                images
                if images is not None
                else ["https://images.example.invalid/shot.png"]
            ),
            "version": version,
            "definition": definition
            or {"app_kind": "tool_instance", "tool": "calendar"},
        }
        manifest_spec = self._put(
            f"{public_id}-{version}.json", json.dumps(manifest).encode()
        )
        avatar_spec = self._put(f"{public_id}-icon.png", _png(public_id))
        avatar_spec["content_type"] = "image/png"
        screenshot_spec = self._put(f"{public_id}-shot.png", _png(public_id + "-shot"))
        screenshot_spec["content_type"] = "image/png"
        entry = {
            "uid": uid,
            "public_id": public_id,
            "manifest": manifest_spec,
            "avatar": avatar_spec,
            "images": [screenshot_spec],
        }
        self.entries.append(entry)
        return entry

    def publish(
        self,
        private: Ed25519PrivateKey,
        *,
        serial: int = 1,
        generated_at: Optional[datetime] = None,
        kid: str = "publisher-1",
        entries: Optional[list[dict[str, Any]]] = None,
        schema_version: int = 1,
    ) -> bytes:
        """Write index.json and its detached signature. Returns the index bytes."""
        stamp = generated_at or datetime.now(timezone.utc)
        index = {
            "schema_version": schema_version,
            "serial": serial,
            "generated_at": stamp.isoformat().replace("+00:00", "Z"),
            "listings": self.entries if entries is None else entries,
        }
        raw = json.dumps(index).encode()
        self.files[INDEX_URL] = raw
        self.sign(private, kid=kid)
        return raw

    def sign(self, private: Ed25519PrivateKey, *, kid: str = "publisher-1") -> None:
        """(Re-)sign whatever index.json currently is."""
        signature = private.sign(self.files[INDEX_URL])
        self.files[INDEX_URL + registry.SIGNATURE_SUFFIX] = json.dumps(
            {"signatures": [{"alg": "Ed25519", "kid": kid, "sig": _b64(signature)}]}
        ).encode()

    def tamper(self) -> None:
        """Flip one byte of the served index, leaving the signature alone."""
        raw = bytearray(self.files[INDEX_URL])
        raw[-2] ^= 0x20
        self.files[INDEX_URL] = bytes(raw)

    def corrupt(self, name: str) -> None:
        """Serve different bytes for one artifact than the index recorded."""
        self.files[REGISTRY_ROOT + name] += b"  "

    # --- serving side ------------------------------------------------------

    async def fetch(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[dict[str, str]] = None,
        timeout: Any = None,
        **_kwargs: Any,
    ) -> httpx.Response:
        self.requested.append(url)
        if url in self.unreachable:
            raise httpx.ConnectError(f"cannot reach {url}")
        body = self.files.get(url)
        if body is None:
            return httpx.Response(404, content=b"not found")
        return httpx.Response(200, content=body)


@pytest.fixture
def publisher_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture
def configured(monkeypatch, publisher_key) -> None:
    """Point this deployment at the fixture registry, trusting one key that may
    publish for ``acme`` only."""
    monkeypatch.setattr(settings, "MARKETPLACE_REGISTRY_ENABLED", True)
    monkeypatch.setattr(settings, "MARKETPLACE_REGISTRY_URL", INDEX_URL)
    monkeypatch.setattr(
        settings,
        "MARKETPLACE_REGISTRY_PUBLIC_KEYS",
        _jwks(("publisher-1", publisher_key, ["acme"])),
    )


@pytest.fixture
def host(monkeypatch, configured) -> FakeRegistry:
    fake = FakeRegistry()
    monkeypatch.setattr(registry, "request_public_target", fake.fetch)
    return fake


async def _listing(session, public_id: str) -> Optional[MarketplaceListing]:
    return (
        await session.exec(
            select(MarketplaceListing).where(MarketplaceListing.public_id == public_id)
        )
    ).first()


async def _state(session) -> Optional[MarketplaceRegistryState]:
    return (await session.exec(select(MarketplaceRegistryState))).first()


class TestAbsentWhenUnconfigured:
    """No URL, no keys, or the switch off: the feature is not there at all."""

    async def test_unconfigured_by_default(self, monkeypatch):
        monkeypatch.setattr(settings, "MARKETPLACE_REGISTRY_URL", None)
        monkeypatch.setattr(settings, "MARKETPLACE_REGISTRY_PUBLIC_KEYS", None)
        assert registry.registry_configured() is False

    async def test_a_url_without_keys_is_not_half_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "MARKETPLACE_REGISTRY_URL", INDEX_URL)
        monkeypatch.setattr(settings, "MARKETPLACE_REGISTRY_PUBLIC_KEYS", None)
        assert registry.registry_configured() is False

    async def test_keys_without_a_url_are_not_half_configured(
        self, monkeypatch, publisher_key
    ):
        monkeypatch.setattr(settings, "MARKETPLACE_REGISTRY_URL", None)
        monkeypatch.setattr(
            settings,
            "MARKETPLACE_REGISTRY_PUBLIC_KEYS",
            _jwks(("publisher-1", publisher_key, ["acme"])),
        )
        assert registry.registry_configured() is False

    async def test_the_switch_turns_it_off_without_losing_the_settings(
        self, monkeypatch, configured
    ):
        assert registry.registry_configured() is True
        monkeypatch.setattr(settings, "MARKETPLACE_REGISTRY_ENABLED", False)
        assert registry.registry_configured() is False

    async def test_refreshing_unconfigured_touches_nothing(
        self, session, monkeypatch, host
    ):
        monkeypatch.setattr(settings, "MARKETPLACE_REGISTRY_URL", None)

        result = await registry.refresh_registry(session)

        assert result.ran is False
        assert result.code == Codes.NOT_CONFIGURED
        assert host.requested == []
        assert await _state(session) is None


class TestSignature:
    async def test_a_valid_index_ingests(self, session, host, publisher_key):
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(publisher_key)

        result = await registry.refresh_registry(session)

        assert result.ok, result.code
        assert result.upserted == 1
        assert result.skipped == []
        listing = await _listing(session, "acme.widgets")
        assert listing is not None
        assert listing.source == "registry"
        assert listing.available is True

    async def test_a_tampered_byte_is_refused_before_any_listing_is_read(
        self, session, host, publisher_key
    ):
        """The signature covers the bytes as received, and it is checked before
        they are parsed — so a modified index stops the refresh without any of
        its content having been looked at, and without the files it names ever
        being requested."""
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(publisher_key)
        host.tamper()

        result = await registry.refresh_registry(session)

        assert result.code == Codes.SIGNATURE_INVALID
        assert await _listing(session, "acme.widgets") is None
        manifest_urls = [url for url in host.requested if url.endswith("-1.0.0.json")]
        assert manifest_urls == []

    async def test_an_unknown_key_id_is_refused(self, session, host):
        stranger = Ed25519PrivateKey.generate()
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(stranger, kid="somebody-elses-key")

        result = await registry.refresh_registry(session)

        assert result.code == Codes.KEY_UNKNOWN
        assert await _listing(session, "acme.widgets") is None

    async def test_a_known_key_id_signed_by_the_wrong_key_is_refused(
        self, session, host
    ):
        """Claiming a trusted key id proves nothing; only the signature does."""
        impostor = Ed25519PrivateKey.generate()
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(impostor, kid="publisher-1")

        result = await registry.refresh_registry(session)

        assert result.code == Codes.SIGNATURE_INVALID
        assert await _listing(session, "acme.widgets") is None

    async def test_a_second_key_can_be_added_before_it_is_used(
        self, session, monkeypatch, host, publisher_key
    ):
        """Rotation: both keys are trusted, the publisher signs with the new
        one, and nothing else has to change."""
        successor = Ed25519PrivateKey.generate()
        monkeypatch.setattr(
            settings,
            "MARKETPLACE_REGISTRY_PUBLIC_KEYS",
            _jwks(
                ("publisher-1", publisher_key, ["acme"]),
                ("publisher-2", successor, ["acme"]),
            ),
        )
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(successor, kid="publisher-2")

        result = await registry.refresh_registry(session)

        assert result.ok, result.code
        assert result.key_id == "publisher-2"

    async def test_an_unreadable_key_set_is_named_as_such(
        self, session, monkeypatch, host
    ):
        monkeypatch.setattr(
            settings, "MARKETPLACE_REGISTRY_PUBLIC_KEYS", "{not json at all"
        )

        result = await registry.refresh_registry(session)

        assert result.code == Codes.KEYS_INVALID
        assert host.requested == []

    async def test_a_key_may_not_claim_the_reserved_prefix(self, publisher_key):
        with pytest.raises(registry.RegistryError) as exc:
            registry.load_trusted_keys(_jwks(("k", publisher_key, ["core"])))
        assert exc.value.code == Codes.KEYS_INVALID


class TestFreshnessAndSerial:
    async def test_a_stale_index_is_refused(self, session, host, publisher_key):
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(
            publisher_key,
            generated_at=datetime.now(timezone.utc) - timedelta(days=30),
        )

        result = await registry.refresh_registry(session)

        assert result.code == Codes.INDEX_STALE
        assert await _listing(session, "acme.widgets") is None

    async def test_an_index_dated_in_the_future_is_refused(
        self, session, host, publisher_key
    ):
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(
            publisher_key, generated_at=datetime.now(timezone.utc) + timedelta(hours=2)
        )

        result = await registry.refresh_registry(session)

        assert result.code == Codes.INDEX_STALE

    async def test_a_rolled_back_serial_is_refused(self, session, host, publisher_key):
        """A perfectly signed older index is still an older index. Serving one
        again must not roll the catalog back to it."""
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(publisher_key, serial=5)
        assert (await registry.refresh_registry(session)).ok

        host.publish(publisher_key, serial=4)
        result = await registry.refresh_registry(session)

        assert result.code == Codes.SERIAL_REGRESSION
        state = await _state(session)
        assert state is not None
        assert state.last_serial == 5
        assert state.last_error == Codes.SERIAL_REGRESSION

    async def test_the_same_serial_with_different_content_is_refused(
        self, session, host, publisher_key
    ):
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(publisher_key, serial=7)
        assert (await registry.refresh_registry(session)).ok

        host.add("acme.gadgets", "BBBBBBBBBBBBBB")
        host.publish(publisher_key, serial=7)
        result = await registry.refresh_registry(session)

        assert result.code == Codes.SERIAL_REGRESSION
        assert await _listing(session, "acme.gadgets") is None

    async def test_an_unchanged_index_is_a_no_op(self, session, host, publisher_key):
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(publisher_key, serial=3)
        assert (await registry.refresh_registry(session)).ok

        result = await registry.refresh_registry(session)

        assert result.ok, result.code
        assert result.unchanged is True
        assert result.upserted == 0

    async def test_the_serial_survives_a_restart(self, session, host, publisher_key):
        """The rollback guard lives in the database, so it is still there when
        the process that learned it is gone."""
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(publisher_key, serial=9)
        assert (await registry.refresh_registry(session)).ok

        state = await _state(session)
        assert state is not None
        assert state.last_serial == 9
        served = hashlib.sha256(host.files[INDEX_URL]).hexdigest()
        assert state.last_index_sha256 == served
        assert state.key_id == "publisher-1"
        assert state.last_error is None


class TestNamespaces:
    async def test_core_is_never_published_by_a_registry(
        self, session, monkeypatch, host, publisher_key
    ):
        """``core.*`` names listings shipped in this repository. A registry
        holds it even with a key authorized for everything."""
        monkeypatch.setattr(
            settings,
            "MARKETPLACE_REGISTRY_PUBLIC_KEYS",
            _jwks(("publisher-1", publisher_key, ["*"])),
        )
        host.add("core.project-health", "CCCCCCCCCCCCCC")
        host.publish(publisher_key)

        result = await registry.refresh_registry(session)

        assert result.ok, result.code
        assert [item.code for item in result.skipped] == [Codes.RESERVED_NAMESPACE]
        assert await _listing(session, "core.project-health") is None

    async def test_a_key_cannot_publish_outside_its_prefixes(
        self, session, host, publisher_key
    ):
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.add("othervendor.thing", "DDDDDDDDDDDDDD")
        host.publish(publisher_key)

        result = await registry.refresh_registry(session)

        assert result.upserted == 1
        assert [item.public_id for item in result.skipped] == ["othervendor.thing"]
        assert result.skipped[0].code == Codes.PUBLISHER_NOT_AUTHORIZED
        assert await _listing(session, "othervendor.thing") is None
        # The authorized listing in the same index still lands.
        assert await _listing(session, "acme.widgets") is not None

    async def test_a_wildcard_key_publishes_for_anyone_but_core(
        self, session, monkeypatch, host, publisher_key
    ):
        monkeypatch.setattr(
            settings,
            "MARKETPLACE_REGISTRY_PUBLIC_KEYS",
            _jwks(("publisher-1", publisher_key, ["*"])),
        )
        host.add("othervendor.thing", "DDDDDDDDDDDDDD")
        host.publish(publisher_key)

        result = await registry.refresh_registry(session)

        assert result.ok, result.code
        assert await _listing(session, "othervendor.thing") is not None


class TestArtifacts:
    async def test_a_manifest_that_does_not_match_its_digest_is_refused(
        self, session, host, publisher_key
    ):
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(publisher_key)
        host.corrupt("acme.widgets-1.0.0.json")

        result = await registry.refresh_registry(session)

        assert [item.code for item in result.skipped] == [Codes.ARTIFACT_INVALID]
        assert await _listing(session, "acme.widgets") is None

    async def test_an_image_that_does_not_match_its_digest_is_refused(
        self, session, host, publisher_key
    ):
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(publisher_key)
        host.corrupt("acme.widgets-icon.png")

        result = await registry.refresh_registry(session)

        assert [item.code for item in result.skipped] == [Codes.ARTIFACT_INVALID]
        assert await _listing(session, "acme.widgets") is None

    async def test_a_manifest_naming_a_different_listing_is_refused(
        self, session, host, publisher_key
    ):
        """The signed index says which listing this is; a manifest that
        disagrees is not the file the index meant."""
        entry = host.add("acme.widgets", "AAAAAAAAAAAAAA")
        entry["public_id"] = "acme.something-else"
        host.publish(publisher_key)

        result = await registry.refresh_registry(session)

        assert [item.code for item in result.skipped] == [Codes.ARTIFACT_INVALID]

    async def test_an_artifact_on_another_host_is_refused(
        self, session, host, publisher_key
    ):
        entry = host.add("acme.widgets", "AAAAAAAAAAAAAA")
        entry["manifest"]["url"] = "https://elsewhere.example.test/manifest.json"
        host.publish(publisher_key)

        result = await registry.refresh_registry(session)

        assert [item.code for item in result.skipped] == [Codes.ARTIFACT_INVALID]
        assert "https://elsewhere.example.test/manifest.json" not in host.requested

    async def test_an_unfetchable_artifact_is_reported_not_fatal(
        self, session, host, publisher_key
    ):
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.add("acme.gadgets", "BBBBBBBBBBBBBB")
        host.publish(publisher_key)
        host.unreachable.add(REGISTRY_ROOT + "acme.gadgets-1.0.0.json")

        result = await registry.refresh_registry(session)

        assert result.upserted == 1
        assert [item.code for item in result.skipped] == [Codes.ARTIFACT_UNREACHABLE]
        # Recorded, so the next refresh re-ingests this serial rather than
        # treating it as already applied.
        state = await _state(session)
        assert state is not None
        assert state.last_error == Codes.ARTIFACT_UNREACHABLE
        assert state.last_success_at is None

    async def test_bytes_that_are_not_the_declared_image_type_are_refused(
        self, session, host, publisher_key
    ):
        entry = host.add("acme.widgets", "AAAAAAAAAAAAAA")
        entry["avatar"]["content_type"] = "image/jpeg"
        host.publish(publisher_key)

        result = await registry.refresh_registry(session)

        assert [item.code for item in result.skipped] == [Codes.ARTIFACT_INVALID]


class TestMirroredArtwork:
    async def test_no_remote_image_url_survives_into_the_catalog(
        self, session, host, publisher_key
    ):
        """The manifest's own artwork fields are discarded and replaced with
        the mirrored copies, so browsing the catalog never makes a request to
        the publisher's host."""
        host.add(
            "acme.widgets",
            "AAAAAAAAAAAAAA",
            avatar_url="https://images.example.invalid/tracker.gif",
            images=["https://images.example.invalid/also-tracked.png"],
        )
        host.publish(publisher_key)

        assert (await registry.refresh_registry(session)).ok

        listing = await _listing(session, "acme.widgets")
        assert listing is not None
        assert listing.avatar_url.startswith(registry.MEDIA_URL_PREFIX)
        assert listing.images
        assert all(url.startswith(registry.MEDIA_URL_PREFIX) for url in listing.images)
        stored = json.dumps([listing.avatar_url, *listing.images])
        assert "example.invalid" not in stored
        assert "http" not in stored

    async def test_the_mirrored_bytes_are_stored_under_their_digest(
        self, session, host, publisher_key
    ):
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(publisher_key)

        assert (await registry.refresh_registry(session)).ok

        listing = await _listing(session, "acme.widgets")
        assert listing is not None
        digest = listing.avatar_url.rsplit("/", 1)[-1]
        media = (
            await session.exec(
                select(MarketplaceMedia).where(MarketplaceMedia.sha256 == digest)
            )
        ).first()
        assert media is not None
        assert media.content_type == "image/png"
        assert hashlib.sha256(media.data).hexdigest() == digest

    async def test_an_image_two_listings_share_is_kept_once(
        self, session, host, publisher_key
    ):
        first = host.add("acme.widgets", "AAAAAAAAAAAAAA")
        second = host.add("acme.gadgets", "BBBBBBBBBBBBBB")
        second["avatar"] = dict(first["avatar"])
        second["images"] = []
        host.publish(publisher_key)

        assert (await registry.refresh_registry(session)).ok

        digest = first["avatar"]["sha256"]
        rows = (
            await session.exec(
                select(MarketplaceMedia).where(MarketplaceMedia.sha256 == digest)
            )
        ).all()
        assert len(rows) == 1


class TestWithdrawal:
    async def test_a_listing_absent_from_a_newer_index_is_withdrawn(
        self, session, host, publisher_key
    ):
        """Withdrawn, never deleted: a guild that installed it keeps its app
        and its provenance, it simply stops being offered."""
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        gadgets = host.add("acme.gadgets", "BBBBBBBBBBBBBB")
        host.publish(publisher_key, serial=1)
        assert (await registry.refresh_registry(session)).ok

        host.entries = [entry for entry in host.entries if entry is not gadgets]
        host.publish(publisher_key, serial=2)
        result = await registry.refresh_registry(session)

        assert result.withdrawn == 1
        gone = await _listing(session, "acme.gadgets")
        assert gone is not None
        assert gone.available is False
        assert (await _listing(session, "acme.widgets")).available is True

    async def test_one_publishers_key_cannot_retire_anothers_listing(
        self, session, monkeypatch, host, publisher_key
    ):
        """Absence from an index says nothing about a publisher who does not
        sign it.

        Two trusted keys, each authorized for its own namespace. The second
        publishes an index that simply does not mention the first publisher's
        listing — which must not read as a retirement, or any authorized key
        could take down the whole catalog by omission.
        """
        other_key = Ed25519PrivateKey.generate()
        monkeypatch.setattr(
            settings,
            "MARKETPLACE_REGISTRY_PUBLIC_KEYS",
            _jwks(
                ("publisher-1", publisher_key, ["acme"]),
                ("publisher-2", other_key, ["globex"]),
            ),
        )

        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(publisher_key, serial=1)
        assert (await registry.refresh_registry(session)).ok
        assert (await _listing(session, "acme.widgets")).available is True

        host.entries = []
        host.add("globex.things", "CCCCCCCCCCCCCC")
        host.publish(other_key, serial=2, kid="publisher-2")
        result = await registry.refresh_registry(session)

        assert result.ok
        assert result.withdrawn == 0
        assert (await _listing(session, "acme.widgets")).available is True

    async def test_an_unauthorized_entry_cannot_shield_a_listing_from_withdrawal(
        self, session, host, publisher_key
    ):
        """Retention is withdrawal read backwards, so it needs the same
        authority.

        The key may publish for ``acme``. Its index drops ``acme.widgets`` — a
        real retirement — but carries an entry in a namespace it may not
        publish under, reusing the dropped listing's uid. If an unauthorized
        entry could put a uid in the retained set, that forged line would keep
        the listing alive.
        """
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(publisher_key, serial=1)
        assert (await registry.refresh_registry(session)).ok
        assert (await _listing(session, "acme.widgets")).available is True

        host.entries = []
        # Not publishable by this key, and wearing the dropped listing's uid.
        host.add("globex.decoy", "AAAAAAAAAAAAAA")
        host.publish(publisher_key, serial=2)
        result = await registry.refresh_registry(session)

        assert result.withdrawn == 1
        assert (await _listing(session, "acme.widgets")).available is False

    async def test_a_listing_the_index_still_carries_is_not_withdrawn_when_skipped(
        self, session, host, publisher_key
    ):
        """A file this deployment could not fetch is a local problem. The
        publisher still lists the app, so it keeps being offered."""
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(publisher_key, serial=1)
        assert (await registry.refresh_registry(session)).ok

        host.publish(publisher_key, serial=2)
        host.unreachable.add(REGISTRY_ROOT + "acme.widgets-1.0.0.json")
        result = await registry.refresh_registry(session)

        assert result.withdrawn == 0
        assert (await _listing(session, "acme.widgets")).available is True

    async def test_a_refused_index_withdraws_nothing(
        self, session, host, publisher_key
    ):
        """Nothing about a refusal reaches the catalog — not an upsert, and not
        a withdrawal."""
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(publisher_key, serial=1)
        assert (await registry.refresh_registry(session)).ok

        host.entries = []
        host.publish(publisher_key, serial=2)
        host.tamper()
        result = await registry.refresh_registry(session)

        assert result.code == Codes.SIGNATURE_INVALID
        assert (await _listing(session, "acme.widgets")).available is True


class TestConcurrency:
    async def test_a_second_refresh_in_the_same_process_is_turned_away(
        self, session, host, publisher_key
    ):
        """One refresh at a time: the operator's button and the background
        worker would otherwise fetch and apply the same index twice."""
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(publisher_key)

        await registry._refresh_lock.acquire()
        try:
            result = await registry.refresh_registry(session)
        finally:
            registry._refresh_lock.release()

        assert result.ran is False
        assert result.code == Codes.REFRESH_IN_PROGRESS
        assert host.requested == []

    async def test_the_lock_is_released_after_a_refusal(
        self, session, host, publisher_key
    ):
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(publisher_key)
        host.tamper()

        refused = await registry.refresh_registry(session)
        assert refused.code == Codes.SIGNATURE_INVALID
        assert registry._refresh_lock.locked() is False

        # Republish rather than re-sign: ``tamper`` corrupted the index bytes
        # themselves, so signing them again would only prove that malformed JSON
        # verifies. Serial 1 again, which also shows the refused index advanced
        # no bookkeeping that would block the retry.
        host.publish(publisher_key)
        assert (await registry.refresh_registry(session)).ok

    async def test_two_refreshes_started_together_apply_the_index_once(
        self, session, host, publisher_key
    ):
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(publisher_key)

        first, second = await asyncio.gather(
            registry.refresh_registry(session),
            registry.refresh_registry(session),
        )

        both = (first, second)
        applied = [r for r in both if r.ran and r.code is None]
        turned_away = [r for r in both if r.code == Codes.REFRESH_IN_PROGRESS]
        assert len(applied) == 1
        assert len(turned_away) == 1
        assert await _listing(session, "acme.widgets") is not None


class TestMalformedIndex:
    async def test_an_index_that_is_not_json_is_refused(
        self, session, host, publisher_key
    ):
        host.files[INDEX_URL] = b"<!doctype html><h1>404</h1>"
        host.sign(publisher_key)

        result = await registry.refresh_registry(session)

        assert result.code == Codes.INDEX_MALFORMED

    async def test_an_unsupported_schema_version_is_refused(
        self, session, host, publisher_key
    ):
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(publisher_key, schema_version=99)

        result = await registry.refresh_registry(session)

        assert result.code == Codes.INDEX_MALFORMED
        assert await _listing(session, "acme.widgets") is None

    async def test_a_missing_index_is_reported_as_unreachable(
        self, session, host, publisher_key
    ):
        host.add("acme.widgets", "AAAAAAAAAAAAAA")
        host.publish(publisher_key)
        del host.files[INDEX_URL]

        result = await registry.refresh_registry(session)

        assert result.code == Codes.UNREACHABLE

    async def test_a_listing_the_validator_refuses_is_skipped(
        self, session, host, publisher_key
    ):
        host.add(
            "acme.widgets",
            "AAAAAAAAAAAAAA",
            definition={"app_kind": "embed", "embed_target": "somewhere-else"},
        )
        host.publish(publisher_key)

        result = await registry.refresh_registry(session)

        assert [item.code for item in result.skipped] == [Codes.LISTING_REJECTED]
        assert await _listing(session, "acme.widgets") is None
        # Refused before its artwork was fetched — there is nothing to mirror
        # for a listing that cannot be stored.
        assert REGISTRY_ROOT + "acme.widgets-icon.png" not in host.requested

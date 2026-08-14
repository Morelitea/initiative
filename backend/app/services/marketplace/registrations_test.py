"""Tests for the app service registration service.

The handshake is driven by an injected ``httpx.MockTransport`` and the base URL
is a loopback literal, so nothing here touches the network.
"""

import json

import httpx
import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.core.config import settings
from app.core.encryption import SALT_APP_SERVICE_SECRET, decrypt_field
from app.core.messages import AppServiceMessages
from app.models.platform.app_service_registration import (
    AppServiceRegistration,
    AppServiceStatus,
)
from app.services.marketplace import registrations as service
from app.services.marketplace.handshake_test import BASE_URL, SECRET, make_transport

pytestmark = [pytest.mark.integration, pytest.mark.database]

#: A public address for the same app, standing in for what a reverse proxy
#: publishes while ``BASE_URL`` stays the address the deployment itself calls.
EMBED_ORIGIN = "https://widgets.example.com"


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    """The app platform requires its own keypair; these tests are about the
    registry rather than the fail-closed path, so give it one."""
    monkeypatch.setattr(
        settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", "-----BEGIN PRIVATE KEY-----"
    )


# --- grants vocabulary -------------------------------------------------------


def test_grants_vocabulary_accepts_only_known_powers():
    assert service.normalize_grants(["delegation"]) == ["delegation"]
    assert service.normalize_grants(["delegation", "delegation"]) == ["delegation"]
    assert service.normalize_grants(None) == []


@pytest.mark.parametrize("value", ["admin", "write", "DELEGATION!", "", "*"])
def test_grants_outside_the_vocabulary_are_refused(value):
    with pytest.raises(HTTPException) as excinfo:
        service.normalize_grants([value])
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == AppServiceMessages.UNKNOWN_GRANT


def _rsa_jwk(kid: str) -> dict:
    """A usable public JWK, generated rather than pasted so the test asserts on
    the parser rather than on one frozen key."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jwt.algorithms import RSAAlgorithm

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = kid
    return jwk


def test_delegation_jwks_accepts_a_usable_key_set():
    key_set = {"keys": [_rsa_jwk("auto.core-delegation-1")]}
    assert service.normalize_delegation_jwks(key_set) == key_set


def test_delegation_jwks_treats_empty_as_cleared():
    assert service.normalize_delegation_jwks(None) is None
    assert service.normalize_delegation_jwks({}) is None


def test_delegation_jwks_requires_a_kid_on_every_key():
    keyless = _rsa_jwk("dropped")
    del keyless["kid"]
    with pytest.raises(HTTPException) as excinfo:
        service.normalize_delegation_jwks({"keys": [keyless]})
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == AppServiceMessages.INVALID_DELEGATION_JWKS


def test_delegation_jwks_refuses_two_keys_sharing_a_kid():
    with pytest.raises(HTTPException) as excinfo:
        service.normalize_delegation_jwks(
            {"keys": [_rsa_jwk("same"), _rsa_jwk("same")]}
        )
    assert excinfo.value.detail == AppServiceMessages.INVALID_DELEGATION_JWKS


@pytest.mark.parametrize(
    "value",
    [
        {"keys": []},
        {"keys": "not-a-list"},
        {"keys": [{"kid": "k", "kty": "banana"}]},
        {"keys": ["not-an-object"]},
        {"no_keys_member": True},
    ],
)
def test_delegation_jwks_refuses_a_set_it_could_not_verify_with(value):
    with pytest.raises(HTTPException) as excinfo:
        service.normalize_delegation_jwks(value)
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == AppServiceMessages.INVALID_DELEGATION_JWKS


def test_base_url_and_origin_shapes_are_enforced():
    assert service.normalize_base_url("http://127.0.0.1:9100/") == (
        "http://127.0.0.1:9100"
    )
    assert service.normalize_origin("https://app.example.com/") == (
        "https://app.example.com"
    )
    for bad in ("ftp://x", "http://", "http://h?a=b", "not-a-url"):
        with pytest.raises(HTTPException):
            service.normalize_base_url(bad)
    for bad in ("https://app.example.com/path", "*", "https://"):
        with pytest.raises(HTTPException):
            service.normalize_origin(bad)


def test_origins_default_to_the_browser_base_origin():
    """The list holds browser origins, so it is derived from the address a
    browser uses — the wire surface only when the app answers on one address."""
    assert service.normalize_origins(None, browser_base=BASE_URL) == [BASE_URL]
    assert service.normalize_origins(None, browser_base=f"{EMBED_ORIGIN}/apps/x") == [
        EMBED_ORIGIN
    ]


def test_embed_origin_accepts_a_base_and_reports_its_own_code():
    """Held to the same shape as base_url, since it stands in for it — a
    deployment publishing an app under a path prefix says so here too."""
    assert service.normalize_embed_origin(f"{EMBED_ORIGIN}/auto/") == (
        f"{EMBED_ORIGIN}/auto"
    )
    for bad in ("ftp://x", "http://", "https://h#frag", "not-a-url"):
        with pytest.raises(HTTPException) as excinfo:
            service.normalize_embed_origin(bad)
        assert excinfo.value.detail == AppServiceMessages.INVALID_EMBED_ORIGIN


# --- signing key -------------------------------------------------------------


async def test_registration_fails_closed_without_a_signing_key(session, monkeypatch):
    """The app-platform keypair is required and has no fallback to any other
    configured key, so the registry refuses rather than borrowing one."""
    monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", None)

    with pytest.raises(HTTPException) as excinfo:
        await service.create_registration(
            session, base_url=BASE_URL, secret=SECRET, transport=make_transport()
        )

    assert excinfo.value.status_code == 503
    assert excinfo.value.detail == AppServiceMessages.SIGNING_NOT_CONFIGURED


# --- create / verify ---------------------------------------------------------


async def test_create_verifies_and_records_the_manifest(session):
    row = await service.create_registration(
        session, base_url=BASE_URL, secret=SECRET, transport=make_transport()
    )

    assert row.public_id == "acme.widgets"
    assert row.listing_uid == "K7M2QX8N4TVB9C"
    assert row.status == AppServiceStatus.OK
    assert row.last_verified_at is not None
    assert row.manifest_hash
    # The secret is stored encrypted and round-trips.
    assert row.secret_encrypted != SECRET
    assert decrypt_field(row.secret_encrypted, SALT_APP_SERVICE_SECRET) == SECRET


async def test_create_without_public_id_refuses_an_unreachable_service(session):
    """Nothing names the row, so there is no registration to store."""
    transport = make_transport(raise_on_manifest=httpx.ConnectError("refused"))

    with pytest.raises(HTTPException) as excinfo:
        await service.create_registration(
            session, base_url=BASE_URL, secret=SECRET, transport=transport
        )

    assert excinfo.value.status_code == 502
    assert excinfo.value.detail == AppServiceMessages.UNREACHABLE


async def test_create_with_public_id_stores_an_unreachable_service(session):
    """A declared app whose container has not booted still gets a row, carrying
    the reason it is unverified."""
    transport = make_transport(raise_on_manifest=httpx.ConnectError("refused"))

    row = await service.create_registration(
        session,
        base_url=BASE_URL,
        secret=SECRET,
        public_id="acme.pending",
        transport=transport,
    )

    assert row.status == AppServiceStatus.UNREACHABLE
    assert row.last_verified_at is None
    assert row.manifest_hash is None


async def test_create_refuses_a_manifest_naming_another_app(session):
    with pytest.raises(HTTPException) as excinfo:
        await service.create_registration(
            session,
            base_url=BASE_URL,
            secret=SECRET,
            public_id="acme.something-else",
            transport=make_transport(),
        )

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == AppServiceMessages.PUBLIC_ID_MISMATCH


async def test_duplicate_public_id_is_refused(session):
    await service.create_registration(
        session, base_url=BASE_URL, secret=SECRET, transport=make_transport()
    )

    with pytest.raises(HTTPException) as excinfo:
        await service.create_registration(
            session, base_url=BASE_URL, secret=SECRET, transport=make_transport()
        )

    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == AppServiceMessages.DUPLICATE_PUBLIC_ID


async def test_verify_records_a_failure_on_the_row(session):
    """The outcome is persisted before the refusal is raised, so the list an
    operator reloads agrees with the response they just got."""
    row = await service.create_registration(
        session, base_url=BASE_URL, secret=SECRET, transport=make_transport()
    )

    with pytest.raises(HTTPException) as excinfo:
        await service.verify_registration(
            session,
            row.id,
            transport=make_transport(sign_with="a-different-secret"),
        )
    assert excinfo.value.detail == AppServiceMessages.SIGNATURE_MISMATCH

    session.expunge_all()
    stored = await session.get(AppServiceRegistration, row.id)
    assert stored.status == AppServiceStatus.SIGNATURE_MISMATCH


async def test_rotating_the_secret_clears_the_recorded_verification(session):
    row = await service.create_registration(
        session, base_url=BASE_URL, secret=SECRET, transport=make_transport()
    )
    assert row.status == AppServiceStatus.OK

    updated = await service.update_registration(session, row.id, secret="rotated")

    assert updated.status == AppServiceStatus.UNVERIFIED
    assert updated.manifest_hash is None
    assert updated.last_verified_at is None


async def test_delegation_keys_are_provisioned_and_cleared_without_re_verifying(
    session,
):
    key_set = {"keys": [_rsa_jwk("acme.shopify-delegation-1")]}
    row = await service.create_registration(
        session,
        base_url=BASE_URL,
        secret=SECRET,
        grants=["delegation"],
        delegation_jwks=key_set,
        transport=make_transport(),
    )
    assert row.delegation_jwks == key_set
    assert row.status == AppServiceStatus.OK

    rotated = {"keys": [_rsa_jwk("acme.shopify-delegation-2")]}
    updated = await service.update_registration(
        session, row.id, delegation_jwks=rotated
    )
    assert updated.delegation_jwks == rotated
    # A key set describes who signs, not what was fetched from the app, so the
    # recorded handshake still stands.
    assert updated.status == AppServiceStatus.OK

    cleared = await service.update_registration(session, row.id, delegation_jwks={})
    assert cleared.delegation_jwks is None


async def test_create_keeps_the_handshake_on_the_wire_surface(session):
    """A registration can carry two addresses, and the handshake uses exactly
    one of them: the app is checked where this deployment calls it."""
    seen: list[str] = []
    app = make_transport()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.url.scheme}://{request.url.netloc.decode()}")
        return app.handle_request(request)

    row = await service.create_registration(
        session,
        base_url=BASE_URL,
        secret=SECRET,
        embed_origin=EMBED_ORIGIN,
        transport=httpx.MockTransport(handler),
    )

    assert set(seen) == {BASE_URL}
    assert row.status == AppServiceStatus.OK
    assert row.embed_origin == EMBED_ORIGIN
    # Browser origins, so they come from the browser address.
    assert row.allowed_origins == [EMBED_ORIGIN]


async def test_moving_the_browser_address_keeps_the_verification(session):
    """The manifest hash describes what the handshake fetched, and the handshake
    never goes to the browser address — so moving it settles nothing."""
    row = await service.create_registration(
        session, base_url=BASE_URL, secret=SECRET, transport=make_transport()
    )
    assert row.allowed_origins == [BASE_URL]

    updated = await service.update_registration(
        session, row.id, embed_origin=EMBED_ORIGIN
    )

    assert updated.status == AppServiceStatus.OK
    assert updated.manifest_hash == row.manifest_hash
    assert updated.last_verified_at is not None
    # The list was still the app's own origin, so it follows the app.
    assert updated.allowed_origins == [EMBED_ORIGIN]


async def test_an_operators_own_origin_list_survives_a_move(session):
    row = await service.create_registration(
        session,
        base_url=BASE_URL,
        secret=SECRET,
        allowed_origins=["https://chosen.example.com"],
        transport=make_transport(),
    )

    updated = await service.update_registration(
        session, row.id, embed_origin=EMBED_ORIGIN
    )

    assert updated.allowed_origins == ["https://chosen.example.com"]


async def test_clearing_the_browser_address_puts_both_surfaces_back(session):
    row = await service.create_registration(
        session,
        base_url=BASE_URL,
        secret=SECRET,
        embed_origin=EMBED_ORIGIN,
        transport=make_transport(),
    )

    updated = await service.update_registration(session, row.id, embed_origin="")

    assert updated.embed_origin is None
    assert updated.allowed_origins == [BASE_URL]


async def test_update_refuses_a_grant_outside_the_vocabulary(session):
    row = await service.create_registration(
        session, base_url=BASE_URL, secret=SECRET, transport=make_transport()
    )

    with pytest.raises(HTTPException) as excinfo:
        await service.update_registration(session, row.id, grants=["superuser"])

    assert excinfo.value.detail == AppServiceMessages.UNKNOWN_GRANT


# --- boot reconciliation -----------------------------------------------------


def _write_config(tmp_path, entries) -> str:
    path = tmp_path / "app-services.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return str(path)


async def test_reconcile_creates_registrations_from_the_mounted_file(
    session, tmp_path, monkeypatch
):
    monkeypatch.setenv("TEST_APP_SECRET", "from-the-environment")
    monkeypatch.setattr(
        settings,
        "APP_SERVICES_CONFIG",
        _write_config(
            tmp_path,
            [
                {
                    "public_id": "acme.declared",
                    "base_url": BASE_URL,
                    "secret_env": "TEST_APP_SECRET",
                    "allowed_origins": ["https://app.example.com"],
                    "grants": ["delegation"],
                    "mandatory": True,
                }
            ],
        ),
    )

    result = await service.reconcile_from_config(session)

    assert (result.created, result.skipped) == (1, 0)
    row = (
        await session.exec(
            select(AppServiceRegistration).where(
                AppServiceRegistration.public_id == "acme.declared"
            )
        )
    ).one()
    assert row.base_url == BASE_URL
    assert row.allowed_origins == ["https://app.example.com"]
    assert row.grants == ["delegation"]
    assert row.mandatory is True
    # Offline by design: reconciliation upserts and stops.
    assert row.status == AppServiceStatus.UNVERIFIED
    assert decrypt_field(row.secret_encrypted, SALT_APP_SERVICE_SECRET) == (
        "from-the-environment"
    )


async def test_reconcile_reads_the_browser_address_from_the_file(
    session, tmp_path, monkeypatch
):
    """A chart states both addresses, so the two-address case is wired with no
    admin clicks — and adding one later is an update, not a re-verification."""
    monkeypatch.setenv("TEST_APP_SECRET", "from-the-environment")
    entry = {
        "public_id": "acme.two-addresses",
        "base_url": BASE_URL,
        "secret_env": "TEST_APP_SECRET",
    }
    monkeypatch.setattr(
        settings, "APP_SERVICES_CONFIG", _write_config(tmp_path, [entry])
    )
    await service.reconcile_from_config(session)

    entry["embed_origin"] = EMBED_ORIGIN
    monkeypatch.setattr(
        settings, "APP_SERVICES_CONFIG", _write_config(tmp_path, [entry])
    )
    result = await service.reconcile_from_config(session)

    assert (result.created, result.updated, result.unchanged) == (0, 1, 0)
    row = (
        await session.exec(
            select(AppServiceRegistration).where(
                AppServiceRegistration.public_id == "acme.two-addresses"
            )
        )
    ).one()
    assert row.embed_origin == EMBED_ORIGIN
    assert row.allowed_origins == [EMBED_ORIGIN]


async def test_reconcile_is_idempotent(session, tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_APP_SECRET", "from-the-environment")
    monkeypatch.setattr(
        settings,
        "APP_SERVICES_CONFIG",
        _write_config(
            tmp_path,
            [
                {
                    "public_id": "acme.idempotent",
                    "base_url": BASE_URL,
                    "secret_env": "TEST_APP_SECRET",
                }
            ],
        ),
    )

    first = await service.reconcile_from_config(session)
    second = await service.reconcile_from_config(session)

    assert first.created == 1
    assert (second.created, second.updated, second.unchanged) == (0, 0, 1)


async def test_reconcile_never_re_enables_a_disabled_registration(
    session, tmp_path, monkeypatch
):
    """Deactivating an app is the operator's kill switch, so a restart must not
    quietly reverse it — the file still governs everything else."""
    monkeypatch.setenv("TEST_APP_SECRET", "from-the-environment")
    monkeypatch.setattr(
        settings,
        "APP_SERVICES_CONFIG",
        _write_config(
            tmp_path,
            [
                {
                    "public_id": "acme.killswitch",
                    "base_url": BASE_URL,
                    "secret_env": "TEST_APP_SECRET",
                    "mandatory": False,
                }
            ],
        ),
    )
    await service.reconcile_from_config(session)
    row = (
        await session.exec(
            select(AppServiceRegistration).where(
                AppServiceRegistration.public_id == "acme.killswitch"
            )
        )
    ).one()
    await service.update_registration(session, row.id, enabled=False)

    monkeypatch.setattr(
        settings,
        "APP_SERVICES_CONFIG",
        _write_config(
            tmp_path,
            [
                {
                    "public_id": "acme.killswitch",
                    "base_url": BASE_URL,
                    "secret_env": "TEST_APP_SECRET",
                    "mandatory": True,
                }
            ],
        ),
    )
    result = await service.reconcile_from_config(session)

    assert result.updated == 1
    session.expunge_all()
    stored = await session.get(AppServiceRegistration, row.id)
    assert stored.enabled is False
    assert stored.mandatory is True


async def test_reconcile_skips_an_entry_whose_secret_env_is_unset(
    session, tmp_path, monkeypatch
):
    monkeypatch.delenv("TEST_MISSING_APP_SECRET", raising=False)
    monkeypatch.setattr(
        settings,
        "APP_SERVICES_CONFIG",
        _write_config(
            tmp_path,
            [
                {
                    "public_id": "acme.nosecret",
                    "base_url": BASE_URL,
                    "secret_env": "TEST_MISSING_APP_SECRET",
                }
            ],
        ),
    )

    result = await service.reconcile_from_config(session)

    assert (result.created, result.skipped) == (0, 1)


async def test_reconcile_skips_an_entry_claiming_an_unknown_grant(
    session, tmp_path, monkeypatch
):
    monkeypatch.setenv("TEST_APP_SECRET", "from-the-environment")
    monkeypatch.setattr(
        settings,
        "APP_SERVICES_CONFIG",
        _write_config(
            tmp_path,
            [
                {
                    "public_id": "acme.overreach",
                    "base_url": BASE_URL,
                    "secret_env": "TEST_APP_SECRET",
                    "grants": ["superuser"],
                }
            ],
        ),
    )

    result = await service.reconcile_from_config(session)

    assert (result.created, result.skipped) == (0, 1)


async def test_reconcile_is_a_no_op_without_the_setting(session, monkeypatch):
    monkeypatch.setattr(settings, "APP_SERVICES_CONFIG", None)
    assert (await service.reconcile_from_config(session)).total == 0


async def test_reconcile_survives_an_unreadable_file(session, tmp_path, monkeypatch):
    """A malformed file costs the file, never the boot."""
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(settings, "APP_SERVICES_CONFIG", str(path))

    assert (await service.reconcile_from_config(session)).total == 0


async def test_a_repeated_public_id_costs_only_that_entry(
    session, tmp_path, monkeypatch
):
    """A duplicate in the file is one operator mistake, not a failed boot.

    Rows are pending rather than flushed during the pass, so a second entry
    naming the same app looks absent, inserts a duplicate, and fails the unique
    constraint at the shared commit — which would take every other registration
    in the file with it. The later entry is skipped instead.
    """
    monkeypatch.setenv("TEST_APP_SECRET", "from-the-environment")
    monkeypatch.setattr(
        settings,
        "APP_SERVICES_CONFIG",
        _write_config(
            tmp_path,
            [
                {
                    "public_id": "acme.twice",
                    "base_url": BASE_URL,
                    "secret_env": "TEST_APP_SECRET",
                },
                {
                    "public_id": "acme.twice",
                    "base_url": "https://other.example.com",
                    "secret_env": "TEST_APP_SECRET",
                },
                {
                    "public_id": "acme.innocent",
                    "base_url": BASE_URL,
                    "secret_env": "TEST_APP_SECRET",
                },
            ],
        ),
    )

    result = await service.reconcile_from_config(session)

    assert (result.created, result.skipped) == (2, 1)
    rows = (await session.exec(select(AppServiceRegistration))).all()
    assert sorted(row.public_id for row in rows) == ["acme.innocent", "acme.twice"]
    # The first entry won, so the duplicate did not quietly retarget the app.
    kept = next(row for row in rows if row.public_id == "acme.twice")
    assert kept.base_url == BASE_URL

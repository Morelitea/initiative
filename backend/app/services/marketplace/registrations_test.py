"""Tests for the app service registration service.

A registration is stated, not discovered: nothing here calls an app.
"""

import json

import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.core.config import settings
from app.core.messages import AppServiceMessages
from app.models.platform.app_service_registration import AppServiceRegistration
from app.models.platform.publisher import Publisher
from app.services.marketplace.vendor_values import load_vendor_values
from app.services.marketplace import registrations as service
from app.services.marketplace.registration_lookup import load_registrations

pytestmark = [pytest.mark.integration, pytest.mark.database]

#: Where the deployment calls the app.
BASE_URL = "http://127.0.0.1:9100"
#: An app served over https, for the key set address.
HTTPS_BASE_URL = "https://widgets.example.com"
#: A public address for the same app, standing in for what a reverse proxy
#: publishes while ``BASE_URL`` stays the address the deployment itself calls.
EMBED_ORIGIN = "https://widgets.example.com"
#: The catalog listing the app speaks for.
LISTING_UID = "K7M2QX8N4TVB9C"


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    """The app platform requires its own keypair; these tests are about the
    registry rather than the fail-closed path, so give it one."""
    monkeypatch.setattr(
        settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", "-----BEGIN PRIVATE KEY-----"
    )


def _rsa_jwk(kid: str) -> dict:
    """A usable public JWK, generated rather than pasted so the test asserts on
    the parser rather than on one frozen key."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jwt.algorithms import RSAAlgorithm

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = kid
    return jwk


def test_jwks_accepts_a_usable_key_set():
    key_set = {"keys": [_rsa_jwk("auto.core-1")]}
    assert service.normalize_jwks(key_set) == key_set


def test_jwks_treats_empty_as_cleared():
    assert service.normalize_jwks(None) is None
    assert service.normalize_jwks({}) is None


def test_jwks_requires_a_kid_on_every_key():
    keyless = _rsa_jwk("dropped")
    del keyless["kid"]
    with pytest.raises(HTTPException) as excinfo:
        service.normalize_jwks({"keys": [keyless]})
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == AppServiceMessages.INVALID_JWKS


def test_jwks_refuses_two_keys_sharing_a_kid():
    with pytest.raises(HTTPException) as excinfo:
        service.normalize_jwks({"keys": [_rsa_jwk("same"), _rsa_jwk("same")]})
    assert excinfo.value.detail == AppServiceMessages.INVALID_JWKS


def test_jwks_refuses_a_private_key():
    """The column is served in full to the owner's settings, so it holds the half
    that is meant to be read."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jwt.algorithms import RSAAlgorithm

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_jwk = json.loads(RSAAlgorithm.to_jwk(key))
    private_jwk["kid"] = "pasted-the-whole-key"

    with pytest.raises(HTTPException) as excinfo:
        service.normalize_jwks({"keys": [private_jwk]})
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == AppServiceMessages.INVALID_JWKS


def test_jwks_refuses_a_symmetric_key():
    with pytest.raises(HTTPException) as excinfo:
        service.normalize_jwks(
            {"keys": [{"kid": "shared", "kty": "oct", "k": "c2hhcmVkLXNlY3JldA"}]}
        )
    assert excinfo.value.detail == AppServiceMessages.INVALID_JWKS


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
def test_jwks_refuses_a_set_it_could_not_verify_with(value):
    with pytest.raises(HTTPException) as excinfo:
        service.normalize_jwks(value)
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == AppServiceMessages.INVALID_JWKS


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


async def _create(session, **overrides):
    fields = {
        "public_id": "acme.widgets",
        "listing_uid": LISTING_UID,
        "base_url": BASE_URL,
        **overrides,
    }
    return await service.create_registration(session, **fields)


async def test_registration_fails_closed_without_a_signing_key(session, monkeypatch):
    """The app-platform keypair is required and has no fallback to any other
    configured key, so the registry refuses rather than borrowing one."""
    monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", None)

    with pytest.raises(HTTPException) as excinfo:
        await _create(session)

    assert excinfo.value.status_code == 503
    assert excinfo.value.detail == AppServiceMessages.SIGNING_NOT_CONFIGURED


# --- create ------------------------------------------------------------------


async def test_create_stores_what_it_is_told(session):
    """Nothing is fetched: the id, the listing and the keys are the operator's."""
    key_set = {"keys": [_rsa_jwk("acme.widgets-1")]}
    row = await _create(session, jwks=key_set)

    assert row.public_id == "acme.widgets"
    assert row.listing_uid == LISTING_UID
    assert row.jwks == key_set
    assert row.jwks_uri is None


@pytest.mark.parametrize("value", ["", "short", "K7M2QX8N4TVB9CX", "k7m2qx8n4tvb9c"])
async def test_create_refuses_a_listing_uid_that_is_not_one(session, value):
    with pytest.raises(HTTPException) as excinfo:
        await _create(session, listing_uid=value)

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == AppServiceMessages.INVALID_LISTING_UID


async def test_duplicate_public_id_is_refused(session):
    await _create(session)

    with pytest.raises(HTTPException) as excinfo:
        await _create(session)

    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == AppServiceMessages.DUPLICATE_PUBLIC_ID


async def test_a_new_prefix_gets_an_unverified_publisher(session):
    row = await _create(session, public_id="newpub.widgets")

    publisher = await session.get(Publisher, row.publisher_id)
    assert publisher is not None
    assert publisher.prefix == "newpub"
    assert publisher.verified is False
    assert publisher.enabled is True


async def test_a_known_prefix_keeps_its_publisher_as_it_is(session):
    """A registration under a switched-off publisher joins it switched off."""
    session.add(Publisher(prefix="offpub", display_name="Off", enabled=False))
    await session.commit()

    row = await _create(session, public_id="offpub.widgets")

    publisher = await session.get(Publisher, row.publisher_id)
    assert publisher.enabled is False
    snapshot = (await load_registrations(force=True))["offpub.widgets"]
    assert snapshot.enabled is True
    assert snapshot.live is False


# --- keys --------------------------------------------------------------------


async def test_live_needs_a_key_set(session):
    await _create(session, public_id="acme.keyless")
    await _create(
        session,
        public_id="acme.keyed",
        jwks={"keys": [_rsa_jwk("acme.keyed-1")]},
    )
    await _create(
        session,
        public_id="acme.published",
        base_url=HTTPS_BASE_URL,
        jwks_uri=f"{HTTPS_BASE_URL}/.well-known/jwks.json",
    )

    snapshots = await load_registrations(force=True)
    assert snapshots["acme.keyless"].live is False
    assert snapshots["acme.keyed"].live is True
    assert snapshots["acme.published"].live is True


@pytest.mark.parametrize(
    "jwks_uri",
    [
        # Not https.
        "http://widgets.example.com/jwks.json",
        # Another host.
        "https://keys.example.net/jwks.json",
        # Another port.
        "https://widgets.example.com:8443/jwks.json",
        # A query.
        "https://widgets.example.com/jwks.json?v=1",
    ],
)
async def test_a_key_set_address_is_https_on_the_apps_own_origin(session, jwks_uri):
    with pytest.raises(HTTPException) as excinfo:
        await _create(session, base_url=HTTPS_BASE_URL, jwks_uri=jwks_uri)

    assert excinfo.value.detail == AppServiceMessages.INVALID_JWKS_URI


async def test_moving_the_base_url_rechecks_the_key_set_address(session):
    row = await _create(
        session,
        base_url=HTTPS_BASE_URL,
        jwks_uri=f"{HTTPS_BASE_URL}/jwks.json",
    )

    with pytest.raises(HTTPException) as excinfo:
        await service.update_registration(
            session, row.id, base_url="https://elsewhere.example.com"
        )
    assert excinfo.value.detail == AppServiceMessages.INVALID_JWKS_URI

    cleared = await service.update_registration(session, row.id, jwks_uri="")
    assert cleared.jwks_uri is None


async def test_keys_are_provisioned_and_cleared(session):
    key_set = {"keys": [_rsa_jwk("acme.shopify-1")]}
    row = await _create(session, jwks=key_set)
    assert row.jwks == key_set

    rotated = {"keys": [_rsa_jwk("acme.shopify-2")]}
    updated = await service.update_registration(session, row.id, jwks=rotated)
    assert updated.jwks == rotated

    cleared = await service.update_registration(session, row.id, jwks={})
    assert cleared.jwks is None


# --- addresses ---------------------------------------------------------------


async def test_the_browser_address_names_the_allowed_origins(session):
    row = await _create(session, embed_origin=EMBED_ORIGIN)

    assert row.embed_origin == EMBED_ORIGIN
    # Browser origins, so they come from the browser address.
    assert row.allowed_origins == [EMBED_ORIGIN]


async def test_moving_the_browser_address_moves_a_default_origin_list(session):
    row = await _create(session)
    assert row.allowed_origins == [BASE_URL]

    updated = await service.update_registration(
        session, row.id, embed_origin=EMBED_ORIGIN
    )

    # The list was still the app's own origin, so it follows the app.
    assert updated.allowed_origins == [EMBED_ORIGIN]


async def test_an_operators_own_origin_list_survives_a_move(session):
    row = await _create(session, allowed_origins=["https://chosen.example.com"])

    updated = await service.update_registration(
        session, row.id, embed_origin=EMBED_ORIGIN
    )

    assert updated.allowed_origins == ["https://chosen.example.com"]


async def test_clearing_the_browser_address_puts_both_surfaces_back(session):
    row = await _create(session, embed_origin=EMBED_ORIGIN)

    updated = await service.update_registration(session, row.id, embed_origin="")

    assert updated.embed_origin is None
    assert updated.allowed_origins == [BASE_URL]


async def test_update_changes_the_listing(session):
    row = await _create(session)

    updated = await service.update_registration(
        session, row.id, listing_uid="ABCDEFGHJKMNPQ"
    )

    assert updated.listing_uid == "ABCDEFGHJKMNPQ"


# --- scope ceiling -----------------------------------------------------------


def test_scope_ceiling_accepts_known_scopes_sorted_once():
    assert service.normalize_scope_ceiling(
        ["projects:write", "comments:read", "projects:write"]
    ) == ["comments:read", "projects:write"]
    assert service.normalize_scope_ceiling(None) == []
    assert service.normalize_scope_ceiling([]) == []


@pytest.mark.parametrize(
    "value",
    [
        ["projects:admin"],
        ["nothing:read"],
        # Members are read-only, so there is no write scope to cap at.
        ["members:write"],
        [7],
        "projects:read",
    ],
)
def test_scope_ceiling_outside_the_vocabulary_is_refused(value):
    with pytest.raises(HTTPException) as excinfo:
        service.normalize_scope_ceiling(value)
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == AppServiceMessages.UNKNOWN_SCOPE


async def test_create_and_update_store_the_scope_ceiling(session):
    row = await _create(session, scope_ceiling=["projects:write", "comments:read"])
    assert row.scope_ceiling == ["comments:read", "projects:write"]

    updated = await service.update_registration(
        session, row.id, scope_ceiling=["documents:read"]
    )
    assert updated.scope_ceiling == ["documents:read"]

    untouched = await service.update_registration(session, row.id, enabled=True)
    assert untouched.scope_ceiling == ["documents:read"]


async def test_a_registration_with_no_ceiling_names_none(session):
    row = await _create(session)
    assert row.scope_ceiling == []


async def test_update_refuses_a_scope_outside_the_vocabulary(session):
    row = await _create(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.update_registration(session, row.id, scope_ceiling=["all:write"])

    assert excinfo.value.detail == AppServiceMessages.UNKNOWN_SCOPE


# --- boot reconciliation -----------------------------------------------------


def _write_config(tmp_path, entries) -> str:
    path = tmp_path / "app-services.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return str(path)


async def test_reconcile_creates_registrations_from_the_mounted_file(
    session, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        settings,
        "APP_SERVICES_CONFIG",
        _write_config(
            tmp_path,
            [
                {
                    "public_id": "acme.declared",
                    "base_url": BASE_URL,
                    "listing_uid": LISTING_UID,
                    "allowed_origins": ["https://app.example.com"],
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
    assert row.mandatory is True
    assert row.listing_uid == LISTING_UID


async def test_reconcile_seals_the_vendor_values_it_names(
    session, tmp_path, monkeypatch
):
    """``vendor_env`` names environment variables; their values are sealed into
    the registration on every pass, so rotating one is changing the variable
    and restarting."""
    monkeypatch.setenv("TEST_VENDOR_SECRET", "first-secret")
    entry = {
        "public_id": "acme.vendored",
        "base_url": BASE_URL,
        "listing_uid": LISTING_UID,
        "vendor_env": {"client_secret": "TEST_VENDOR_SECRET", "absent": "NOT_SET_X"},
    }
    monkeypatch.setattr(
        settings, "APP_SERVICES_CONFIG", _write_config(tmp_path, [entry])
    )
    await service.reconcile_from_config(session)
    assert await load_vendor_values("acme.vendored") == {
        "client_secret": "first-secret"
    }

    monkeypatch.setenv("TEST_VENDOR_SECRET", "rotated-secret")
    result = await service.reconcile_from_config(session)
    assert result.updated == 1
    assert await load_vendor_values("acme.vendored") == {
        "client_secret": "rotated-secret"
    }
    row = (
        await session.exec(
            select(AppServiceRegistration).where(
                AppServiceRegistration.public_id == "acme.vendored"
            )
        )
    ).one()
    # Sealed, never stored as the variable held it.
    assert "rotated-secret" not in str(row.vendor_values)


async def test_reconcile_reads_the_browser_address_from_the_file(
    session, tmp_path, monkeypatch
):
    """A chart states both addresses, so the two-address case is wired with no
    owner clicks — and adding one later is an update."""
    entry = {
        "public_id": "acme.two-addresses",
        "base_url": BASE_URL,
        "listing_uid": LISTING_UID,
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
    monkeypatch.setattr(
        settings,
        "APP_SERVICES_CONFIG",
        _write_config(
            tmp_path,
            [
                {
                    "public_id": "acme.idempotent",
                    "base_url": BASE_URL,
                    "listing_uid": LISTING_UID,
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
    monkeypatch.setattr(
        settings,
        "APP_SERVICES_CONFIG",
        _write_config(
            tmp_path,
            [
                {
                    "public_id": "acme.killswitch",
                    "base_url": BASE_URL,
                    "listing_uid": LISTING_UID,
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
                    "listing_uid": LISTING_UID,
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


async def test_reconcile_skips_an_entry_naming_no_listing(
    session, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        settings,
        "APP_SERVICES_CONFIG",
        _write_config(
            tmp_path,
            [{"public_id": "acme.nolisting", "base_url": BASE_URL}],
        ),
    )

    result = await service.reconcile_from_config(session)

    assert (result.created, result.skipped) == (0, 1)


async def test_reconcile_reads_the_key_set_address(session, tmp_path, monkeypatch):
    entry = {
        "public_id": "acme.published",
        "listing_uid": LISTING_UID,
        "base_url": HTTPS_BASE_URL,
        "jwks_uri": f"{HTTPS_BASE_URL}/jwks.json",
    }
    monkeypatch.setattr(
        settings, "APP_SERVICES_CONFIG", _write_config(tmp_path, [entry])
    )

    assert (await service.reconcile_from_config(session)).created == 1
    row = (
        await session.exec(
            select(AppServiceRegistration).where(
                AppServiceRegistration.public_id == "acme.published"
            )
        )
    ).one()
    assert row.jwks_uri == f"{HTTPS_BASE_URL}/jwks.json"


async def test_reconcile_ignores_grants_in_a_file_written_for_an_earlier_release(
    session, tmp_path, monkeypatch, caplog
):
    """A registration no longer has grants. An entry that still names them is
    registered without them and the pass says so, so the file does not stop a
    boot."""
    monkeypatch.setattr(
        settings,
        "APP_SERVICES_CONFIG",
        _write_config(
            tmp_path,
            [
                {
                    "public_id": "acme.earlier",
                    "base_url": BASE_URL,
                    "listing_uid": LISTING_UID,
                    "grants": ["delegation", "app_directory"],
                }
            ],
        ),
    )

    with caplog.at_level("WARNING", logger="app.services.marketplace.registrations"):
        result = await service.reconcile_from_config(session)

    assert (result.created, result.skipped) == (1, 0)
    assert any("names grants" in record.getMessage() for record in caplog.records)
    row = (
        await session.exec(
            select(AppServiceRegistration).where(
                AppServiceRegistration.public_id == "acme.earlier"
            )
        )
    ).one()
    assert not hasattr(row, "grants")


async def test_reconcile_reads_the_scope_ceiling_from_the_file(
    session, tmp_path, monkeypatch
):
    entry = {
        "public_id": "acme.scoped",
        "base_url": BASE_URL,
        "listing_uid": LISTING_UID,
        "scope_ceiling": ["projects:write", "comments:read"],
    }
    monkeypatch.setattr(
        settings, "APP_SERVICES_CONFIG", _write_config(tmp_path, [entry])
    )
    assert (await service.reconcile_from_config(session)).created == 1

    row = (
        await session.exec(
            select(AppServiceRegistration).where(
                AppServiceRegistration.public_id == "acme.scoped"
            )
        )
    ).one()
    assert row.scope_ceiling == ["comments:read", "projects:write"]

    # Changing the ceiling in the file is an update on the next pass.
    entry["scope_ceiling"] = ["projects:read"]
    monkeypatch.setattr(
        settings, "APP_SERVICES_CONFIG", _write_config(tmp_path, [entry])
    )
    result = await service.reconcile_from_config(session)
    assert (result.updated, result.unchanged) == (1, 0)
    await session.refresh(row)
    assert row.scope_ceiling == ["projects:read"]


async def test_reconcile_skips_an_entry_naming_an_unknown_scope(
    session, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        settings,
        "APP_SERVICES_CONFIG",
        _write_config(
            tmp_path,
            [
                {
                    "public_id": "acme.overscoped",
                    "base_url": BASE_URL,
                    "listing_uid": LISTING_UID,
                    "scope_ceiling": ["everything:write"],
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
    monkeypatch.setattr(
        settings,
        "APP_SERVICES_CONFIG",
        _write_config(
            tmp_path,
            [
                {
                    "public_id": "acme.twice",
                    "base_url": BASE_URL,
                    "listing_uid": LISTING_UID,
                },
                {
                    "public_id": "acme.twice",
                    "base_url": "https://other.example.com",
                    "listing_uid": LISTING_UID,
                },
                {
                    "public_id": "acme.innocent",
                    "base_url": BASE_URL,
                    "listing_uid": LISTING_UID,
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

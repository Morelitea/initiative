"""The listings this build ships, and which of them a deployment offers.

Two things are worth pinning down here.

The first is that every shipped manifest actually lands. Seeding logs a bad
manifest and moves on — the right call at boot, since one broken file must not
take the catalog with it, but it means a packaging mistake is silent. It was:
a listing shipped with a uid outside the alphabet and never appeared in the
catalog at all, and nothing failed. So the manifests are seeded here for real
and the result is counted.

The second is the conditional listing. An app that opens the deployment's own
embed surface is offered only where an operator configured one — absent, not
broken, on an install without it — and taken back out of the catalog if that
configuration goes away.
"""

import pytest
from sqlmodel import select

from app.models.platform.marketplace import MarketplaceListing
from app.services.marketplace import catalog as catalog_service
from app.services.marketplace.builtin import (
    load_builtin_manifests,
    seed_builtin_listings,
)
from app.services.marketplace.definitions import (
    RESERVED_PUBLIC_ID_PREFIX,
    normalize_publisher,
    normalize_listing_definition,
)

pytestmark = pytest.mark.asyncio


async def _seeded(session) -> dict[str, MarketplaceListing]:
    listings = (await session.exec(select(MarketplaceListing))).all()
    return {listing.public_id: listing for listing in listings}


class TestShippedManifests:
    async def test_every_shipped_manifest_passes_the_validator(self):
        """The manifest-level checks, on every file, with no database in the way.

        Seeding logs and skips a manifest it cannot accept, so a shipped file
        that stopped validating would be missing from the catalog rather than
        loud. This runs the same checks directly, which is also what makes the
        author requirement real for the listings we ship rather than only for
        the ones other people write.
        """
        manifests = list(load_builtin_manifests())
        assert manifests, "no manifests ship with this build"

        for manifest in manifests:
            public_id = manifest.get("public_id", "?")
            publisher = normalize_publisher(manifest.get("publisher"))
            assert publisher, f"{public_id} ships without a publisher"
            normalize_listing_definition(
                manifest.get("kind", ""), manifest.get("definition")
            )
            # Everything shipped here is, by definition, shipped here.
            assert public_id.startswith(RESERVED_PUBLIC_ID_PREFIX), (
                f"{public_id} is a built-in and should publish under "
                f"{RESERVED_PUBLIC_ID_PREFIX}*"
            )

    async def test_every_shipped_manifest_seeds(self, session):
        """Not "seeding did not raise" — seeding logs and skips. Every file on
        disk has to end up as a row."""
        expected = {m["public_id"] for m in load_builtin_manifests()}
        assert expected, "no manifests ship with this build"

        landed = await seed_builtin_listings(session)
        await session.commit()

        assert landed == len(expected)
        assert set((await _seeded(session)).keys()) == expected

    async def test_every_shipped_listing_can_be_installed_now(self, session):
        """A built-in ships inside the app that renders it, so there is no build
        on which it is offered but refused. A version floor naming a release that
        has not happened yet would put every listing in exactly that state."""
        await seed_builtin_listings(session)
        await session.commit()

        for listing in (await _seeded(session)).values():
            version = await catalog_service.resolve_installable_version(
                session, listing
            )
            assert version is not None, f"{listing.public_id} is not installable"

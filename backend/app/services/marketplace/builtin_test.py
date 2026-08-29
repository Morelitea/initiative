"""The listings this build ships, and which of them a deployment offers.

Two things are worth pinning down here.

The first is that every shipped manifest actually lands. Seeding logs a bad
manifest and moves on — the right call at boot, since one broken file must not
take the catalog with it, but it means a packaging mistake is silent. It was:
a listing shipped with a uid outside the alphabet and never appeared in the
catalog at all, and nothing failed. So the manifests are seeded here for real
and the result is counted.

The second is that the files are the whole truth. A listing dropped from the
build has to leave the shelf everywhere, or it lingers in the catalog of every
database that ever saw it — which is exactly what happened when the advanced
tool was removed and its listing stayed, offered, alongside its replacement.
Withdrawing has to be careful in the other direction too: a file this build
ships but cannot read or validate must never take its own listing down.
"""

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


class TestWithdrawingWhatIsNoLongerShipped:
    """The catalog follows the files, in both directions."""

    async def _seed_dir(self, tmp_path, manifests: list[dict]) -> None:
        import json

        for manifest in manifests:
            (tmp_path / f"{manifest['public_id']}.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

    def _manifest(self, *, uid: str, public_id: str) -> dict:
        return {
            "uid": uid,
            "public_id": public_id,
            "kind": "app",
            "name": public_id,
            "publisher": "Tests",
            "description": "A shipped listing.",
            "version": "1.0.0",
            "definition": {"app_kind": "tool_instance", "tool": "calendar"},
        }

    async def test_a_listing_dropped_from_the_build_leaves_the_shelf(
        self, session, tmp_path
    ):
        keep = self._manifest(uid="KEEP0000000001", public_id="core.keep")
        drop = self._manifest(uid="DRPX0000000001", public_id="core.drop")
        await self._seed_dir(tmp_path, [keep, drop])
        await seed_builtin_listings(session, tmp_path)
        assert (await _seeded(session))["core.drop"].available is True

        # The next build ships only one of them.
        (tmp_path / "core.drop.json").unlink()
        await seed_builtin_listings(session, tmp_path)

        listings = await _seeded(session)
        assert listings["core.keep"].available is True
        # Withdrawn, not deleted: an install that pinned it still resolves.
        assert listings["core.drop"].available is False

    async def test_a_listing_that_fails_to_validate_is_not_withdrawn(
        self, session, tmp_path
    ):
        """A packaging bug must not become data loss. The file still ships, so
        the listing it replaces stays on the shelf while someone fixes it."""
        good = self._manifest(uid="KEEP0000000002", public_id="core.keep2")
        await self._seed_dir(tmp_path, [good])
        await seed_builtin_listings(session, tmp_path)

        broken = {**good, "definition": {"app_kind": "nonsense"}}
        await self._seed_dir(tmp_path, [broken])
        await seed_builtin_listings(session, tmp_path)

        assert (await _seeded(session))["core.keep2"].available is True

    async def test_an_unreadable_file_withdraws_nothing_at_all(self, session, tmp_path):
        """One corrupt file leaves no uid behind, so sweeping on what was read
        would withdraw listings this build does ship. The pass is skipped."""
        first = self._manifest(uid="KEEP0000000003", public_id="core.keep3")
        second = self._manifest(uid="KEEP0000000004", public_id="core.keep4")
        await self._seed_dir(tmp_path, [first, second])
        await seed_builtin_listings(session, tmp_path)

        (tmp_path / "core.keep4.json").write_text("{ not json", encoding="utf-8")
        await seed_builtin_listings(session, tmp_path)

        listings = await _seeded(session)
        assert listings["core.keep3"].available is True
        assert listings["core.keep4"].available is True

    def _bundling_manifest(self, *, uid: str, public_id: str, dash_uid: str) -> dict:
        """A service app that ships a dashboard arranged from its own widgets."""
        endpoint = f"app.{public_id}.open-items"
        return {
            "uid": uid,
            "public_id": public_id,
            "kind": "app",
            "name": public_id,
            "publisher": "Tests",
            "description": "A shipped app with a dashboard.",
            "version": "1.0.0",
            "definition": {
                "app_kind": "service",
                "service": {"public_id": public_id, "protocol": 1},
                "features": ["endpoints", "widgets", "dashboards"],
                "endpoints": [{"id": endpoint, "direction": "read"}],
                "widgets": [
                    {
                        "id": "open-items",
                        "meta": {"name": {"en": "Open items"}},
                        "module_source": "export default () => ({});",
                        "endpoints": [endpoint],
                    }
                ],
                "dashboards": [
                    {
                        "uid": dash_uid,
                        "public_id": f"{public_id}-overview",
                        "name": "Overview",
                        "widgets": [
                            {
                                "type": "open-items",
                                "binding": {"endpoint_id": endpoint},
                            }
                        ],
                    }
                ],
            },
        }

    async def test_a_bundled_dashboard_is_claimed_by_the_pass_that_publishes_it(
        self, session, tmp_path
    ):
        """Its uid lives inside its app's manifest, so the sweep has to read the
        manifest to know the build still ships it."""
        await self._seed_dir(
            tmp_path,
            [
                self._bundling_manifest(
                    uid="BNDAPP00000001",
                    public_id="core.bundler",
                    dash_uid="DASHB0ARD00002",
                )
            ],
        )
        await seed_builtin_listings(session, tmp_path)

        listings = await _seeded(session)
        assert listings["core.bundler"].available is True
        assert listings["core.bundler-overview"].available is True

    async def test_dropping_the_bundling_app_withdraws_its_dashboard(
        self, session, tmp_path
    ):
        await self._seed_dir(
            tmp_path,
            [
                self._bundling_manifest(
                    uid="BNDAPP00000002",
                    public_id="core.bundler2",
                    dash_uid="DASHB0ARD00003",
                )
            ],
        )
        await seed_builtin_listings(session, tmp_path)

        (tmp_path / "core.bundler2.json").unlink()
        await seed_builtin_listings(session, tmp_path)

        listings = await _seeded(session)
        assert listings["core.bundler2"].available is False
        assert listings["core.bundler2-overview"].available is False

    async def test_an_operator_listing_is_not_this_build_to_withdraw(
        self, session, tmp_path
    ):
        """Only shipped listings follow the files. What an operator added is
        theirs, and a build that ships nothing must not clear their catalog."""
        theirs = self._manifest(uid="ACME0000000001", public_id="acme.theirs")
        await catalog_service.upsert_listing(session, theirs, source="operator")
        await seed_builtin_listings(session, tmp_path)

        assert (await _seeded(session))["acme.theirs"].available is True

"""What the catalog will and will not accept.

The load-bearing cases are the identity ones. A uid is the code someone shares
or types, so it has to mean the same listing everywhere — which only holds if a
later publisher cannot take one that is already held. And a listing's definition
has to survive the tool's own validator, because installing copies it into a
guild's schema and the canvas that renders it knows nothing about where it came
from.
"""

import pytest
from sqlmodel import select

from app.models.platform.marketplace import MarketplaceListing
from app.services.marketplace import catalog as service
from app.services.marketplace.catalog import CatalogError
from app.testing import create_marketplace_listing

pytestmark = pytest.mark.asyncio


def _manifest(**overrides):
    manifest = {
        "uid": "ABCDEFGH123456",
        "public_id": "tests.example",
        "kind": "dashboard",
        "name": "Example",
        "publisher": "Tests",
        "description": "An example listing.",
        "avatar_url": "/marketplace/example.svg",
        "version": "1.0.0",
        "definition": {
            "widgets": [
                {"id": "w1", "type": "stat", "binding": {"source": "task_counts"}}
            ]
        },
    }
    manifest.update(overrides)
    return manifest


class TestIdentity:
    async def test_a_uid_cannot_be_taken_from_its_holder(self, session):
        """A shared code resolves to one product, so a uid already in use is
        refused rather than merged into."""
        await service.upsert_listing(session, _manifest(), source="builtin")
        with pytest.raises(CatalogError, match="refusing to reassign"):
            await service.upsert_listing(
                session,
                _manifest(public_id="another.publisher"),
                source="registry",
            )

    async def test_a_public_id_cannot_be_republished_under_a_new_uid(self, session):
        await service.upsert_listing(session, _manifest(), source="builtin")
        with pytest.raises(CatalogError, match="already published"):
            await service.upsert_listing(
                session, _manifest(uid="ZZZZZZZZ999999"), source="registry"
            )

    @pytest.mark.parametrize(
        "uid",
        [
            "TOOSHORT",
            "WAYTOOLONGFORAUID",
            # I, L, O and U are excluded so a code can be transcribed by hand.
            "ABCDEFGHIJ1234",
            "ABCDEFGH12345l",
        ],
    )
    async def test_a_malformed_uid_is_refused(self, session, uid):
        with pytest.raises(CatalogError, match="uid"):
            await service.upsert_listing(session, _manifest(uid=uid), source="builtin")

    async def test_a_public_id_must_name_its_publisher(self, session):
        with pytest.raises(CatalogError, match="publisher"):
            await service.upsert_listing(
                session, _manifest(public_id="noslug"), source="builtin"
            )


class TestDefinitions:
    async def test_a_listing_cannot_publish_a_widget_we_cannot_render(self, session):
        """Catalog content goes through the tool's own validator, so there is no
        laxer path into a guild's schema by way of the marketplace."""
        with pytest.raises(CatalogError, match="invalid dashboard definition"):
            await service.upsert_listing(
                session,
                _manifest(
                    definition={
                        "widgets": [
                            {
                                "id": "w1",
                                "type": "iframe",
                                "binding": {"source": "tasks"},
                            }
                        ]
                    }
                ),
                source="builtin",
            )

    async def test_a_listing_cannot_publish_a_source_we_cannot_fetch(self, session):
        with pytest.raises(CatalogError, match="invalid dashboard definition"):
            await service.upsert_listing(
                session,
                _manifest(
                    definition={
                        "widgets": [
                            {
                                "id": "w1",
                                "type": "stat",
                                "binding": {"source": "https://example.test/x"},
                            }
                        ]
                    }
                ),
                source="builtin",
            )

    async def test_a_published_definition_is_stored_normalized(self, session):
        listing = await service.upsert_listing(session, _manifest(), source="builtin")
        version = await service.get_listing_version(session, listing.latest_version_id)
        assert version is not None
        # Canonical shape, not whatever the manifest happened to carry.
        assert version.definition["kind"] == "dashboard"
        assert version.definition["layout"] == {"columns": 12}

    async def test_an_app_listing_must_name_a_mountable_tool(self, session):
        """An app definition is narrow on purpose: a kind, and which of this
        build's tools it mounts. It cannot name one we do not mount at guild
        scope."""
        with pytest.raises(CatalogError, match="cannot be mounted"):
            await service.upsert_listing(
                session,
                _manifest(
                    kind="app",
                    definition={"app_kind": "tool_instance", "tool": "dashboard"},
                ),
                source="builtin",
            )

    async def test_embed_apps_are_not_installable_yet(self, session):
        with pytest.raises(CatalogError, match="not installable"):
            await service.upsert_listing(
                session,
                _manifest(
                    kind="app",
                    definition={"app_kind": "embed", "url": "https://x.test"},
                ),
                source="builtin",
            )

    async def test_a_valid_app_listing_is_stored_canonically(self, session):
        listing = await service.upsert_listing(
            session,
            _manifest(
                kind="app",
                definition={
                    "app_kind": "tool_instance",
                    "tool": "calendar",
                    "default_name": "Guild calendar",
                    "unexpected": "dropped",
                },
            ),
            source="builtin",
        )
        version = await service.get_listing_version(session, listing.latest_version_id)
        assert version.definition == {
            "app_kind": "tool_instance",
            "tool": "calendar",
            "default_name": "Guild calendar",
        }


class TestVersions:
    async def test_republishing_a_version_unchanged_is_a_no_op(self, session):
        """Boot re-seeds the shipped listings on every start, so publishing the
        same manifest twice has to be harmless."""
        await service.upsert_listing(session, _manifest(), source="builtin")
        listing = await service.upsert_listing(session, _manifest(), source="builtin")
        assert len(await service.listing_versions(session, listing.id)) == 1

    async def test_a_published_version_cannot_be_rewritten(self, session):
        """The definition under a version is frozen once published.

        An instance pins its version, and the upgrade path has nothing to offer
        one already on it — so a changed body under an unchanged version could
        never reach whoever installed it. It would also mean `uid` + version
        named different content on different deployments, which is exactly what
        a shared code must not do.
        """
        await service.upsert_listing(session, _manifest(), source="builtin")
        with pytest.raises(CatalogError, match="already published with different"):
            await service.upsert_listing(
                session,
                _manifest(
                    definition={
                        "widgets": [
                            {
                                "id": "w1",
                                "type": "table",
                                "binding": {"source": "tasks"},
                            }
                        ]
                    }
                ),
                source="builtin",
            )

    async def test_a_published_version_cannot_move_its_app_floor(self, session):
        # Changing min_app_version would change who can install that exact
        # version, after the fact.
        await service.upsert_listing(session, _manifest(), source="builtin")
        with pytest.raises(CatalogError, match="already published with different"):
            await service.upsert_listing(
                session, _manifest(min_app_version="999.0.0"), source="builtin"
            )

    async def test_listing_metadata_stays_editable_without_a_new_version(self, session):
        """A publisher fixing a typo in their blurb should not need a release —
        the name, description and artwork belong to the listing, not the
        version."""
        await service.upsert_listing(session, _manifest(), source="builtin")
        listing = await service.upsert_listing(
            session,
            _manifest(name="Renamed", description="Reworded."),
            source="builtin",
        )
        assert (listing.name, listing.description) == ("Renamed", "Reworded.")
        assert len(await service.listing_versions(session, listing.id)) == 1

    async def test_a_new_version_becomes_the_latest(self, session):
        await service.upsert_listing(session, _manifest(), source="builtin")
        listing = await service.upsert_listing(
            session, _manifest(version="1.1.0"), source="builtin"
        )
        latest = await service.get_listing_version(session, listing.latest_version_id)
        assert latest is not None and latest.version == "1.1.0"
        assert len(await service.listing_versions(session, listing.id)) == 2

    async def test_a_version_needing_a_newer_app_is_not_installable(self, session):
        listing = await create_marketplace_listing(
            session,
            uid="FTRE0000000001",
            public_id="tests.future",
            min_app_version="999.0.0",
        )
        assert await service.resolve_installable_version(session, listing) is None

    async def test_a_version_this_build_can_run_resolves(self, session):
        listing = await create_marketplace_listing(
            session,
            uid="PRESENT0000001",
            public_id="tests.present",
            min_app_version="0.1.0",
        )
        version = await service.resolve_installable_version(session, listing)
        assert version is not None and version.version == "1.0.0"

    async def test_a_prerelease_floor_reads_as_its_release(self):
        # Only ever answers "is this deployment new enough", so 1.2.3-rc1 and
        # 1.2.3 are the same floor.
        assert service.version_is_compatible("0.0.1-rc1") is True
        assert service.version_is_compatible(None) is True


class TestSearch:
    async def test_search_matches_name_description_and_publisher(self, session):
        await create_marketplace_listing(
            session,
            uid="SEARCH00000001",
            public_id="tests.alpha",
            name="Burndown",
            publisher="Acme",
            description="Tracks velocity.",
        )
        await create_marketplace_listing(
            session,
            uid="SEARCH00000002",
            public_id="tests.beta",
            name="Roadmap",
            publisher="Initiative",
            description="Quarterly plan.",
        )
        for needle, expected in [
            ("burn", "tests.alpha"),
            ("velocity", "tests.alpha"),
            ("acme", "tests.alpha"),
            ("roadmap", "tests.beta"),
        ]:
            found, _ = await service.list_listings(session, query=needle)
            assert [listing.public_id for listing in found] == [expected], needle

    async def test_a_withdrawn_listing_is_not_browsable(self, session):
        await create_marketplace_listing(
            session, uid="GNE00000000001", public_id="tests.gone", available=False
        )
        found, total = await service.list_listings(session)
        assert "tests.gone" not in [listing.public_id for listing in found]
        # But it is still there, so an install that pinned it keeps its
        # provenance rather than pointing at nothing.
        assert await service.get_listing(session, "tests.gone") is not None
        found, _ = await service.list_listings(session, include_unavailable=True)
        assert "tests.gone" in [listing.public_id for listing in found]

    async def test_kind_filters(self, session):
        await create_marketplace_listing(
            session, uid="KND00000000001", public_id="tests.kind"
        )
        found, _ = await service.list_listings(session, kind="dashboard")
        assert "tests.kind" in [listing.public_id for listing in found]
        found, _ = await service.list_listings(session, kind="app")
        assert found == []


class TestInstallsCount:
    async def test_the_counter_records_a_number_and_nothing_else(self, session):
        listing = await create_marketplace_listing(
            session, uid="CNT00000000001", public_id="tests.count"
        )
        assert listing.installs_count == 0
        await service.bump_installs_count(session, listing.id)
        await session.commit()
        await session.refresh(listing)
        assert listing.installs_count == 1

    async def test_the_counter_increments_in_the_database(self, session, role_session):
        """Two installs that overlap must both count.

        Staged rather than raced, so it is deterministic: one connection has
        already loaded the row when a second install lands and commits. An
        increment computed in Python would write that connection's stale value
        back and lose the other install; one computed in SQL cannot.
        """
        listing = await create_marketplace_listing(
            session, uid="CNCRRENT000001", public_id="tests.concurrent"
        )

        first = await role_session("app_admin")
        second = await role_session("app_admin")
        # `first` reads the row at 0 and holds it.
        loaded = (
            await first.exec(
                select(MarketplaceListing).where(MarketplaceListing.id == listing.id)
            )
        ).one()
        assert loaded.installs_count == 0

        # A second install lands and commits in the meantime.
        await service.bump_installs_count(second, listing.id)
        await second.commit()

        # Then the first one does. It must not write back the 0 it is holding.
        await service.bump_installs_count(first, listing.id)
        await first.commit()

        await session.refresh(listing)
        assert listing.installs_count == 2
        # There is no column that could say *who* — the catalog must not be able
        # to answer that.
        assert not hasattr(listing, "guild_id")

    async def test_bumping_an_unknown_listing_is_a_no_op(self, session):
        # Best-effort by design: the bump happens after an install has already
        # committed, so it must never raise.
        await service.bump_installs_count(session, 999_999)

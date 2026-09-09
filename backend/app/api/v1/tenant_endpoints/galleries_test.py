"""Tests for the gallery endpoints — CRUD, the picture list and its paging,
uploads and their validation, versions, covers, tags, and the authorization
gates (feature gate, role create gate, DAC levels).

The gallery-specific concerns beyond the usual tool contract are the things a
collection of pictures owns: what an upload is allowed to be, that a picture
is reached only through its gallery, and how the list pages and anchors.
"""

import io
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete as sa_delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.tenant.gallery import GalleryImage, GalleryImageVersion
from app.models.tenant.resource_grant import ResourceGrant
from app.models.tenant.upload import Upload
from app.services.tenant import galleries as galleries_service
from app.testing import create_gallery, create_gallery_image, create_tag, png_bytes


async def _galleries_enabled(session: AsyncSession, initiative) -> None:
    initiative.galleries_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


async def _strip_non_owner_grants(session, gallery, owner_id: int) -> None:
    """Remove every grant except the owner's own — the gallery becomes
    invisible to other members."""
    await session.exec(
        sa_delete(ResourceGrant).where(
            ResourceGrant.resource_type == "gallery",
            ResourceGrant.resource_id == gallery.id,
            ResourceGrant.user_id.is_distinct_from(owner_id),
        )
    )
    await session.commit()


def _upload(name: str = "shot.png", data: bytes | None = None, **fields):
    """The multipart body the upload endpoints take."""
    return {
        "files": {"file": (name, io.BytesIO(data or png_bytes()), "image/png")},
        "data": fields,
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_gallery(client: AsyncClient, acting_user, session):
    """Creating seeds the creator's owner grant plus the default all-members
    read grant."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)

    response = await client.post(
        a.g("/galleries/"),
        headers=a.headers,
        json={
            "name": "Live screen, round 4",
            "description": "Every canvas from the fourth round.",
            "initiative_id": a.initiative.id,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Live screen, round 4"
    assert body["description"] == "Every canvas from the fourth round."
    assert body["my_permission_level"] == "owner"
    assert body["image_count"] == 0
    assert body["cover"] is None
    levels = {(g.get("all_initiative_members"), g["level"]) for g in body["grants"]}
    assert (True, "read") in levels


@pytest.mark.integration
async def test_create_requires_feature_enabled(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    a.initiative.galleries_enabled = False
    session.add(a.initiative)
    await session.commit()

    response = await client.post(
        a.g("/galleries/"),
        headers=a.headers,
        json={"name": "Nope", "initiative_id": a.initiative.id},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "GALLERIES_NOT_ENABLED"


@pytest.mark.integration
async def test_create_requires_the_create_permission(
    client: AsyncClient, acting_user, session
):
    """A plain member cannot open a gallery unless their role says so."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.post(
        b.g("/galleries/"),
        headers=b.headers,
        json={"name": "Unauthorized", "initiative_id": a.initiative.id},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "GALLERY_CREATE_PERMISSION_REQUIRED"


@pytest.mark.integration
async def test_list_carries_counts_and_newest_picture_as_cover(
    client: AsyncClient, acting_user, session
):
    """A list of galleries is itself visual: each row says how many pictures
    it holds and shows one, the newest unless one was chosen."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user, name="Store assets")
    older = await create_gallery_image(
        session,
        gallery,
        a.user,
        title="old",
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
        write_blob=False,
    )
    newer = await create_gallery_image(
        session, gallery, a.user, title="new", write_blob=False
    )

    listing = await client.get(
        a.g("/galleries/"), headers=a.headers, params={"initiative_id": a.initiative.id}
    )
    assert listing.status_code == 200, listing.text
    (item,) = listing.json()["items"]
    assert item["image_count"] == 2
    # Nothing chosen: no cover, and the preview is the newest first.
    assert item["cover"] is None
    assert item["cover_image_id"] is None
    assert [p["image_id"] for p in item["preview"]] == [newer.id, older.id]

    chosen = await client.patch(
        a.g(f"/galleries/{gallery.id}"),
        headers=a.headers,
        json={"cover_image_id": older.id},
    )
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["cover"]["image_id"] == older.id
    assert chosen.json()["cover_image_id"] == older.id
    assert len(chosen.json()["preview"]) == 2


@pytest.mark.integration
async def test_preview_is_capped_at_the_newest_few(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    made = [
        await create_gallery_image(
            session,
            gallery,
            a.user,
            created_at=base + timedelta(days=d),
            write_blob=False,
        )
        for d in range(6)
    ]

    listing = await client.get(a.g("/galleries/"), headers=a.headers)
    (item,) = listing.json()["items"]
    assert [p["image_id"] for p in item["preview"]] == [
        i.id for i in reversed(made[-galleries_service.PREVIEW_COUNT :])
    ]


@pytest.mark.integration
async def test_cover_must_be_one_of_the_gallerys_own(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    other = await create_gallery(session, a.initiative, a.user)
    stranger = await create_gallery_image(session, other, a.user, write_blob=False)

    response = await client.patch(
        a.g(f"/galleries/{gallery.id}"),
        headers=a.headers,
        json={"cover_image_id": stranger.id},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "GALLERY_COVER_NOT_IN_GALLERY"


@pytest.mark.integration
async def test_update_and_delete_follow_the_dac_levels(
    client: AsyncClient, acting_user, session
):
    """Write access renames; only the owner deletes."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user, name="Before")
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    session.add(
        ResourceGrant(
            resource_type="gallery",
            resource_id=gallery.id,
            user_id=b.user.id,
            level="write",
            guild_id=gallery.guild_id,
            initiative_id=gallery.initiative_id,
        )
    )
    await session.commit()

    renamed = await client.patch(
        b.g(f"/galleries/{gallery.id}"), headers=b.headers, json={"name": "After"}
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "After"

    refused = await client.delete(b.g(f"/galleries/{gallery.id}"), headers=b.headers)
    assert refused.status_code == 403

    deleted = await client.delete(a.g(f"/galleries/{gallery.id}"), headers=a.headers)
    assert deleted.status_code == 204
    gone = await client.get(a.g(f"/galleries/{gallery.id}"), headers=a.headers)
    assert gone.status_code == 404


@pytest.mark.integration
async def test_a_member_without_a_grant_cannot_see_it(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    await _strip_non_owner_grants(session, gallery, a.user.id)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    listing = await client.get(b.g("/galleries/"), headers=b.headers)
    assert listing.status_code == 200
    assert listing.json()["total_count"] == 0

    detail = await client.get(b.g(f"/galleries/{gallery.id}"), headers=b.headers)
    assert detail.status_code in (403, 404)

    pictures = await client.get(
        b.g(f"/galleries/{gallery.id}/images"), headers=b.headers
    )
    assert pictures.status_code in (403, 404)


@pytest.mark.integration
async def test_counts_by_initiative(client: AsyncClient, acting_user, session):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    await create_gallery(session, a.initiative, a.user)
    await create_gallery(session, a.initiative, a.user)

    response = await client.get(
        a.g("/galleries/counts/by-initiative"), headers=a.headers
    )

    assert response.status_code == 200
    assert response.json()["counts"] == {str(a.initiative.id): 2}


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_upload_a_picture(client: AsyncClient, acting_user, session):
    """An upload is identified from its bytes: the size comes from the PNG
    header, not from anything the client said."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)

    response = await client.post(
        a.g(f"/galleries/{gallery.id}/images"),
        headers=a.headers,
        **_upload("report-detail.png", png_bytes(12, 7), title="Report detail"),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "Report detail"
    assert body["original_filename"] == "report-detail.png"
    assert body["file_content_type"] == "image/png"
    assert (body["width"], body["height"]) == (12, 7)
    assert body["file_url"].startswith(f"/uploads/{a.guild.id}/")
    assert body["version_count"] == 1
    # A picture no larger than the thumbnail edge gets no thumbnail: the grid
    # would only be shown a copy of what it already has.
    assert body["thumbnail_url"] is None

    # The blob is tracked for the storage quota.
    uploads = (await session.exec(select(Upload))).all()
    assert any(u.filename == body["file_url"].split("/")[-1] for u in uploads)


@pytest.mark.integration
async def test_a_large_picture_gets_a_thumbnail(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)

    edge = galleries_service.THUMBNAIL_EDGE + 400
    response = await client.post(
        a.g(f"/galleries/{gallery.id}/images"),
        headers=a.headers,
        **_upload("big.png", png_bytes(edge, edge // 2)),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["thumbnail_url"] is not None
    assert body["thumbnail_url"].endswith(".webp")
    assert (body["width"], body["height"]) == (edge, edge // 2)


@pytest.mark.integration
async def test_upload_refuses_what_is_not_a_raster_image(
    client: AsyncClient, acting_user, session
):
    """An SVG is a document rather than a picture, and a mislabelled text file
    is nothing at all; both are refused on their bytes."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)

    svg = await client.post(
        a.g(f"/galleries/{gallery.id}/images"),
        headers=a.headers,
        files={
            "file": (
                "x.svg",
                io.BytesIO(b"<svg xmlns='http://www.w3.org/2000/svg'/>"),
                "image/svg+xml",
            )
        },
    )
    assert svg.status_code == 400
    assert svg.json()["detail"] == "GALLERY_INVALID_IMAGE"

    fake = await client.post(
        a.g(f"/galleries/{gallery.id}/images"),
        headers=a.headers,
        files={
            "file": ("x.png", io.BytesIO(b"not a png at all, honestly"), "image/png")
        },
    )
    assert fake.status_code == 400
    assert fake.json()["detail"] == "GALLERY_INVALID_IMAGE"

    empty = await client.post(
        a.g(f"/galleries/{gallery.id}/images"),
        headers=a.headers,
        files={"file": ("x.png", io.BytesIO(b""), "image/png")},
    )
    assert empty.status_code == 400
    assert empty.json()["detail"] == "GALLERY_IMAGE_EMPTY"


@pytest.mark.integration
async def test_upload_refuses_what_the_decoder_will_not_read(
    client: AsyncClient, acting_user, session
):
    """A header says what a file claims; the decode says whether it is one.
    A truncated PNG passes the first gate and must not pass the second — it
    would sit on the wall as a picture nothing can draw, served at full size
    to every viewer for want of a thumbnail."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)

    whole = png_bytes(64, 64)
    truncated = whole[: len(whole) // 2]
    # The header still reads: this is exactly the case a header check passes.
    assert galleries_service.validate_image(truncated)[0].width == 64

    response = await client.post(
        a.g(f"/galleries/{gallery.id}/images"),
        headers=a.headers,
        **_upload("truncated.png", truncated),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "GALLERY_INVALID_IMAGE"
    listing = await client.get(
        a.g(f"/galleries/{gallery.id}/images"), headers=a.headers
    )
    assert listing.json()["total_count"] == 0


@pytest.mark.integration
async def test_a_jump_lands_on_the_month_whichever_way_the_list_reads(
    client: AsyncClient, acting_user, session
):
    """The rail hands back both ends of a month. Newest first the page walks
    back from the last picture in it; oldest first, forward from the first."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    for month, days in ((1, (5, 20)), (3, (2, 9, 27)), (5, (11,))):
        for day in days:
            await create_gallery_image(
                session,
                gallery,
                a.user,
                title=f"{month:02d}-{day:02d}",
                created_at=datetime(2026, month, day, tzinfo=timezone.utc),
                write_blob=False,
            )

    rail = await client.get(
        a.g(f"/galleries/{gallery.id}/images/timeline"), headers=a.headers
    )
    march = next(b for b in rail.json()["buckets"] if b["period"] == "2026-03")
    assert march["count"] == 3

    backwards = await client.get(
        a.g(f"/galleries/{gallery.id}/images"),
        headers=a.headers,
        params={"until": march["anchor"]},
    )
    assert [i["title"] for i in backwards.json()["items"]][:3] == [
        "03-27",
        "03-09",
        "03-02",
    ]

    forwards = await client.get(
        a.g(f"/galleries/{gallery.id}/images"),
        headers=a.headers,
        params={"until": march["anchor_oldest"], "oldest_first": "true"},
    )
    assert [i["title"] for i in forwards.json()["items"]][:3] == [
        "03-02",
        "03-09",
        "03-27",
    ]


@pytest.mark.integration
async def test_upload_needs_write_access_on_the_gallery(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.post(
        b.g(f"/galleries/{gallery.id}/images"), headers=b.headers, **_upload()
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "GALLERY_WRITE_ACCESS_REQUIRED"


# ---------------------------------------------------------------------------
# The picture list
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_pictures_page_newest_first_and_anchor(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    made = []
    for day in range(5):
        made.append(
            await create_gallery_image(
                session,
                gallery,
                a.user,
                title=f"day {day}",
                created_at=base + timedelta(days=day),
                write_blob=False,
            )
        )

    first = await client.get(
        a.g(f"/galleries/{gallery.id}/images"),
        headers=a.headers,
        params={"page_size": 2},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert [i["title"] for i in body["items"]] == ["day 4", "day 3"]
    assert body["has_next"] is True
    assert body["total_count"] == 5

    last = await client.get(
        a.g(f"/galleries/{gallery.id}/images"),
        headers=a.headers,
        params={"page_size": 2, "page": 3},
    )
    assert [i["title"] for i in last.json()["items"]] == ["day 0"]
    assert last.json()["has_next"] is False

    anchored = await client.get(
        a.g(f"/galleries/{gallery.id}/images"),
        headers=a.headers,
        params={"until": (base + timedelta(days=2)).isoformat()},
    )
    assert [i["title"] for i in anchored.json()["items"]] == ["day 2", "day 1", "day 0"]

    oldest = await client.get(
        a.g(f"/galleries/{gallery.id}/images"),
        headers=a.headers,
        params={"oldest_first": "true", "page_size": 2},
    )
    assert [i["title"] for i in oldest.json()["items"]] == ["day 0", "day 1"]


@pytest.mark.integration
async def test_the_timeline_groups_pictures_by_month(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    for when in (
        datetime(2026, 1, 15, tzinfo=timezone.utc),
        datetime(2026, 3, 2, tzinfo=timezone.utc),
        datetime(2026, 3, 9, tzinfo=timezone.utc),
    ):
        await create_gallery_image(
            session, gallery, a.user, created_at=when, write_blob=False
        )

    response = await client.get(
        a.g(f"/galleries/{gallery.id}/images/timeline"), headers=a.headers
    )

    assert response.status_code == 200, response.text
    buckets = response.json()["buckets"]
    assert [b["period"] for b in buckets] == ["2026-03", "2026-01"]
    assert [b["count"] for b in buckets] == [2, 1]


@pytest.mark.integration
async def test_pictures_filter_by_tag_and_search(
    client: AsyncClient, acting_user, session
):
    """Tags on a picture are ANY-of, and the search box reads title, caption
    and filename."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    picked = await create_tag(session, a.guild, name="picked")
    waiting = await create_tag(session, a.guild, name="awaiting decision")
    one = await create_gallery_image(
        session, gallery, a.user, title="Hero", write_blob=False
    )
    two = await create_gallery_image(
        session, gallery, a.user, title="Settings sheet", write_blob=False
    )
    await create_gallery_image(
        session, gallery, a.user, title="Untagged", write_blob=False
    )

    tagged = await client.patch(
        a.g(f"/galleries/{gallery.id}/images/{one.id}"),
        headers=a.headers,
        json={"tag_ids": [picked.id], "caption": "The one we chose"},
    )
    assert tagged.status_code == 200, tagged.text
    assert [t["name"] for t in tagged.json()["tags"]] == ["picked"]
    assert tagged.json()["caption"] == "The one we chose"
    await client.patch(
        a.g(f"/galleries/{gallery.id}/images/{two.id}"),
        headers=a.headers,
        json={"tag_ids": [waiting.id]},
    )

    # Retagging a picture that already carries tags replaces them — the loaded
    # links are dropped underneath the row, and the save must not try to put
    # them back.
    retagged = await client.patch(
        a.g(f"/galleries/{gallery.id}/images/{one.id}"),
        headers=a.headers,
        json={"tag_ids": [waiting.id]},
    )
    assert retagged.status_code == 200, retagged.text
    assert [t["name"] for t in retagged.json()["tags"]] == ["awaiting decision"]
    cleared = await client.patch(
        a.g(f"/galleries/{gallery.id}/images/{one.id}"),
        headers=a.headers,
        json={"tag_ids": [picked.id]},
    )
    assert cleared.status_code == 200, cleared.text
    assert [t["name"] for t in cleared.json()["tags"]] == ["picked"]

    by_tag = await client.get(
        a.g(f"/galleries/{gallery.id}/images"),
        headers=a.headers,
        params={"tag_ids": [picked.id, waiting.id]},
    )
    assert {i["title"] for i in by_tag.json()["items"]} == {"Hero", "Settings sheet"}

    by_word = await client.get(
        a.g(f"/galleries/{gallery.id}/images"),
        headers=a.headers,
        params={"search": "chose"},
    )
    assert [i["title"] for i in by_word.json()["items"]] == ["Hero"]


@pytest.mark.integration
async def test_a_picture_is_reached_only_through_its_gallery(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    other = await create_gallery(session, a.initiative, a.user)
    image = await create_gallery_image(session, gallery, a.user, write_blob=False)

    response = await client.get(
        a.g(f"/galleries/{other.id}/images/{image.id}"), headers=a.headers
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "GALLERY_IMAGE_NOT_FOUND"


@pytest.mark.integration
async def test_removing_a_picture_trashes_it_and_clears_the_cover(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    image = await create_gallery_image(session, gallery, a.user, write_blob=False)
    gallery.cover_image_id = image.id
    session.add(gallery)
    await session.commit()

    response = await client.delete(
        a.g(f"/galleries/{gallery.id}/images/{image.id}"), headers=a.headers
    )
    assert response.status_code == 204

    detail = await client.get(a.g(f"/galleries/{gallery.id}"), headers=a.headers)
    assert detail.json()["image_count"] == 0
    assert detail.json()["cover"] is None
    assert detail.json()["cover_image_id"] is None
    assert detail.json()["preview"] == []

    trash = await client.get(a.g("/trash/"), headers=a.headers)
    assert trash.status_code == 200
    assert any(
        item["entity_type"] == "gallery_image" and item["entity_id"] == image.id
        for item in trash.json()["items"]
    )


@pytest.mark.integration
async def test_bulk_delete_trashes_a_selection_or_nothing(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    other = await create_gallery(session, a.initiative, a.user)
    mine = [
        await create_gallery_image(session, gallery, a.user, write_blob=False)
        for _ in range(3)
    ]
    stranger = await create_gallery_image(session, other, a.user, write_blob=False)
    gallery.cover_image_id = mine[0].id
    session.add(gallery)
    await session.commit()

    # One id from another gallery refuses the whole request.
    mixed = await client.post(
        a.g(f"/galleries/{gallery.id}/images/bulk-delete"),
        headers=a.headers,
        json={"image_ids": [mine[0].id, stranger.id]},
    )
    assert mixed.status_code == 404
    assert mixed.json()["detail"] == "GALLERY_IMAGE_NOT_FOUND"
    still = await client.get(a.g(f"/galleries/{gallery.id}/images"), headers=a.headers)
    assert still.json()["total_count"] == 3

    deleted = await client.post(
        a.g(f"/galleries/{gallery.id}/images/bulk-delete"),
        headers=a.headers,
        json={"image_ids": [mine[0].id, mine[1].id, mine[1].id]},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_count"] == 2
    left = await client.get(a.g(f"/galleries/{gallery.id}/images"), headers=a.headers)
    assert [i["id"] for i in left.json()["items"]] == [mine[2].id]
    detail = await client.get(a.g(f"/galleries/{gallery.id}"), headers=a.headers)
    assert detail.json()["cover_image_id"] is None


@pytest.mark.integration
async def test_bulk_delete_needs_write_access(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    image = await create_gallery_image(session, gallery, a.user, write_blob=False)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.post(
        b.g(f"/galleries/{gallery.id}/images/bulk-delete"),
        headers=b.headers,
        json={"image_ids": [image.id]},
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_bulk_tags_on_pictures_go_through_the_gallery(
    client: AsyncClient, acting_user, session
):
    """The shared bulk-tag endpoint takes pictures, authorized by their
    gallery's write gate; a picture from a gallery the caller cannot write
    refuses the whole request."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    first = await create_gallery_image(session, gallery, a.user, write_blob=False)
    second = await create_gallery_image(session, gallery, a.user, write_blob=False)
    picked = await create_tag(session, a.guild, name="picked")

    response = await client.post(
        a.g("/tags/bulk"),
        headers=a.headers,
        json={
            "target_type": "gallery_image",
            "target_ids": [first.id, second.id],
            "add_tag_ids": [picked.id],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["updated_count"] == 2
    listing = await client.get(
        a.g(f"/galleries/{gallery.id}/images"), headers=a.headers
    )
    assert all(
        [t["name"] for t in i["tags"]] == ["picked"] for i in listing.json()["items"]
    )

    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    refused = await client.post(
        b.g("/tags/bulk"),
        headers=b.headers,
        json={
            "target_type": "gallery_image",
            "target_ids": [first.id],
            "remove_tag_ids": [picked.id],
        },
    )
    assert refused.status_code == 403


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_versions_replace_the_picture_and_keep_history(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    image = await create_gallery_image(session, gallery, a.user, width=4, height=4)
    first_url = image.file_url

    uploaded = await client.post(
        a.g(f"/galleries/{gallery.id}/images/{image.id}/versions"),
        headers=a.headers,
        **_upload("round-2.png", png_bytes(9, 3)),
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["version_number"] == 2
    assert uploaded.json()["is_current"] is True

    current = await client.get(
        a.g(f"/galleries/{gallery.id}/images/{image.id}"), headers=a.headers
    )
    assert (current.json()["width"], current.json()["height"]) == (9, 3)
    assert current.json()["original_filename"] == "round-2.png"
    assert current.json()["version_count"] == 2
    assert current.json()["file_url"] != first_url

    versions = await client.get(
        a.g(f"/galleries/{gallery.id}/images/{image.id}/versions"), headers=a.headers
    )
    assert [v["version_number"] for v in versions.json()] == [2, 1]
    assert [v["is_current"] for v in versions.json()] == [True, False]


@pytest.mark.integration
async def test_deleting_the_current_version_promotes_the_previous(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    image = await create_gallery_image(session, gallery, a.user, width=4, height=4)
    uploaded = await client.post(
        a.g(f"/galleries/{gallery.id}/images/{image.id}/versions"),
        headers=a.headers,
        **_upload("round-2.png", png_bytes(9, 3)),
    )
    second_id = uploaded.json()["id"]

    deleted = await client.delete(
        a.g(f"/galleries/{gallery.id}/images/{image.id}/versions/{second_id}"),
        headers=a.headers,
    )
    assert deleted.status_code == 204

    current = await client.get(
        a.g(f"/galleries/{gallery.id}/images/{image.id}"), headers=a.headers
    )
    assert (current.json()["width"], current.json()["height"]) == (4, 4)
    remaining = (
        await session.exec(
            select(GalleryImageVersion).where(
                GalleryImageVersion.gallery_image_id == image.id
            )
        )
    ).all()
    assert [v.version_number for v in remaining] == [1]

    last = await client.delete(
        a.g(f"/galleries/{gallery.id}/images/{image.id}/versions/{remaining[0].id}"),
        headers=a.headers,
    )
    assert last.status_code == 400
    assert last.json()["detail"] == "GALLERY_CANNOT_DELETE_LAST_VERSION"


@pytest.mark.integration
async def test_deleting_a_version_is_the_owners_call(
    client: AsyncClient, acting_user, session
):
    """Write access replaces a picture; destroying its history is the owner's."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    image = await create_gallery_image(session, gallery, a.user)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    session.add(
        ResourceGrant(
            resource_type="gallery",
            resource_id=gallery.id,
            user_id=b.user.id,
            level="write",
            guild_id=gallery.guild_id,
            initiative_id=gallery.initiative_id,
        )
    )
    await session.commit()

    uploaded = await client.post(
        b.g(f"/galleries/{gallery.id}/images/{image.id}/versions"),
        headers=b.headers,
        **_upload("round-2.png", png_bytes(9, 3)),
    )
    assert uploaded.status_code == 201, uploaded.text

    refused = await client.delete(
        b.g(
            f"/galleries/{gallery.id}/images/{image.id}/versions/{uploaded.json()['id']}"
        ),
        headers=b.headers,
    )
    assert refused.status_code == 403


# ---------------------------------------------------------------------------
# What the image row looks like after a soft delete + purge
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_trashing_a_gallery_takes_its_pictures(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    image = await create_gallery_image(session, gallery, a.user, write_blob=False)

    deleted = await client.delete(a.g(f"/galleries/{gallery.id}"), headers=a.headers)
    assert deleted.status_code == 204

    from app.db.soft_delete_filter import select_including_deleted

    row = (
        await session.exec(
            select_including_deleted(GalleryImage).where(GalleryImage.id == image.id)
        )
    ).one()
    assert row.deleted_at is not None

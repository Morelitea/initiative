"""Tests for the attachment upload endpoint."""

import io

import pytest
from httpx import AsyncClient

from app.services.tenant.attachments import detect_document_image_type
from app.models.platform.guild import GuildRole

#: A real 1x1 PNG — the header reader walks IHDR, so a stub signature is not
#: enough to be identified as one.
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
    b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00"
    b"\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.integration
async def test_upload_image_too_large(client: AsyncClient, acting_user):
    """Uploading an image larger than MAX_IMAGE_BYTES returns 413."""
    a = await acting_user(guild_role=GuildRole.admin)

    oversized = b"\x89PNG\r\n\x1a\n" + b"X" * (11 * 1024 * 1024)
    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("big.png", io.BytesIO(oversized), "image/png")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "ATTACHMENT_TOO_LARGE"


@pytest.mark.integration
async def test_upload_image_within_limit(client: AsyncClient, acting_user):
    """A valid PNG under the size limit is accepted."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("pixel.png", io.BytesIO(TINY_PNG), "image/png")},
    )

    assert response.status_code == 201
    assert response.json()["url"].startswith("/uploads/")


@pytest.mark.integration
async def test_upload_names_the_file_after_its_bytes(client: AsyncClient, acting_user):
    """The stored name and type come from the bytes, not from what the client
    called the file — so the name a serve request reads back describes it."""
    a = await acting_user(guild_role=GuildRole.admin)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>'

    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("disguised.png", io.BytesIO(svg), "image/png")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["content_type"] == "image/svg+xml"
    assert payload["url"].endswith(".svg")


@pytest.mark.integration
async def test_upload_ignores_a_declared_svg_type(client: AsyncClient, acting_user):
    """A raster is identified as one however it is labelled."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("pixel.svg", io.BytesIO(TINY_PNG), "image/svg+xml")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["content_type"] == "image/png"
    assert payload["url"].endswith(".png")


@pytest.mark.integration
@pytest.mark.parametrize(
    "prolog",
    [
        b"\xef\xbb\xbf",
        b'<?xml version="1.0" encoding="UTF-8"?>\n',
        b"<!-- exported by a drawing program -->\n",
        b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
        b'"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n',
    ],
)
async def test_upload_accepts_an_svg_behind_a_prolog(
    client: AsyncClient, acting_user, prolog: bytes
):
    """Real SVGs open with a byte-order mark, a declaration, a comment or a
    doctype before the root element; all four are still SVGs."""
    a = await acting_user(guild_role=GuildRole.admin)
    svg = prolog + b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'

    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("image.svg", io.BytesIO(svg), "image/svg+xml")},
    )

    assert response.status_code == 201
    assert response.json()["url"].endswith(".svg")


@pytest.mark.integration
async def test_upload_refuses_bytes_that_are_no_image(client: AsyncClient, acting_user):
    """Nothing the detector recognizes means nothing is stored, whatever the
    client called it."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={
            "file": (
                "payload.png",
                io.BytesIO(b"MZ\x90\x00this is a program, not a picture"),
                "image/png",
            )
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "ATTACHMENT_INVALID_IMAGE"


@pytest.mark.unit
@pytest.mark.parametrize(
    "contents",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
        b"<svg/>",
        b'\xef\xbb\xbf<svg xmlns="x"></svg>',
        b'<?xml version="1.0"?>\n<svg xmlns="x"/>',
        b"<!-- drawn by a program -->\n<svg xmlns='x'/>",
        b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
        b'"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n<svg xmlns="x"/>',
        b'<?xml version="1.0"?><!-- one --><!-- two --><svg/>',
    ],
)
def test_an_svg_root_is_found_behind_its_prolog(contents: bytes):
    """Whatever an SVG carries ahead of its root element, the root is what
    decides."""
    assert detect_document_image_type(contents) == "image/svg+xml"


@pytest.mark.unit
@pytest.mark.parametrize(
    "contents",
    [
        b"<!-- <svg -->not an image",
        b"<svgfoo></svgfoo>",
        b"<html><svg/></html>",
        b"<!-- a comment that never closes <svg/>",
        b"plain text mentioning <svg",
        b"",
    ],
)
def test_markup_that_is_not_an_svg_is_not_an_image(contents: bytes):
    """Naming the element somewhere in the file is not being it — the root
    element is, so none of these are stored as pictures."""
    assert detect_document_image_type(contents) is None


@pytest.mark.unit
def test_a_raster_is_identified_before_markup():
    """A raster signature settles it; nothing goes looking for markup in a PNG."""
    assert detect_document_image_type(TINY_PNG) == "image/png"


# ---------------------------------------------------------------------------
# Pictures pasted into a task's description or a comment
# ---------------------------------------------------------------------------


async def _paste(client: AsyncClient, a) -> str:
    response = await client.post(
        a.g("/attachments/pasted"),
        headers=a.headers,
        files={"file": ("pasted.png", io.BytesIO(TINY_PNG), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()["url"]


async def _stored(session, guild_id: int, url: str) -> bool:
    """Whether the upload's row and its bytes are both still there."""
    from pathlib import Path

    from sqlmodel import select

    from app.models.tenant.upload import Upload
    from app.services.storage import get_guild_storage
    from app.testing.schema_harness import route_session_to_guild

    name = Path(url).name
    await route_session_to_guild(session, guild_id)
    row = (await session.exec(select(Upload).where(Upload.filename == name))).first()
    return row is not None and get_guild_storage(guild_id).exists(name)


async def _set_description(client: AsyncClient, a, task_id: int, text: str) -> None:
    response = await client.patch(
        a.g(f"/tasks/{task_id}"), headers=a.headers, json={"description": text}
    )
    assert response.status_code == 200, response.text


@pytest.mark.integration
async def test_a_pasted_picture_is_named_as_pasted(client: AsyncClient, acting_user):
    from app.services.tenant.attachments import PASTED_IMAGE_PREFIX

    a = await acting_user(guild_role=GuildRole.member)

    url = await _paste(client, a)

    assert url.startswith(f"/uploads/{a.guild.id}/{PASTED_IMAGE_PREFIX}")


@pytest.mark.integration
async def test_taking_a_picture_out_of_a_description_deletes_it(
    client: AsyncClient, session, acting_user
):
    from app.testing import create_task

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task = await create_task(session, a.project)
    await session.commit()
    url = await _paste(client, a)

    await _set_description(client, a, task.id, f"Look: ![shot]({url})")
    assert await _stored(session, a.guild.id, url)

    session.expunge_all()
    await _set_description(client, a, task.id, "Never mind")
    assert not await _stored(session, a.guild.id, url)


@pytest.mark.integration
async def test_a_picture_another_task_still_shows_stays(
    client: AsyncClient, session, acting_user
):
    """A duplicated task shares its original's pictures."""
    from app.testing import create_task

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    url = await _paste(client, a)
    task = await create_task(session, a.project, description=f"![shot]({url})")
    await create_task(session, a.project, description=f"copy ![shot]({url})")
    await session.commit()

    await _set_description(client, a, task.id, "Never mind")

    assert await _stored(session, a.guild.id, url)


@pytest.mark.integration
async def test_a_picture_that_is_not_a_description_s_is_never_deleted(
    client: AsyncClient, session, acting_user
):
    """An image pasted from a document keeps its own name, so taking it out of
    a description leaves the document's picture alone."""
    from app.testing import create_task

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("doc.png", io.BytesIO(TINY_PNG), "image/png")},
    )
    doc_url = response.json()["url"]
    task = await create_task(session, a.project, description=f"![doc]({doc_url})")
    await session.commit()

    await _set_description(client, a, task.id, "Never mind")

    assert await _stored(session, a.guild.id, doc_url)


@pytest.mark.integration
async def test_purging_a_task_deletes_its_pictures(
    client: AsyncClient, session, acting_user
):
    from app.services.tenant.soft_delete import hard_purge_entity, soft_delete_entity
    from app.testing import create_task
    from app.testing.schema_harness import route_session_to_guild

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    url = await _paste(client, a)
    task = await create_task(session, a.project, description=f"![shot]({url})")
    await session.commit()

    await route_session_to_guild(session, a.guild.id)
    await soft_delete_entity(
        session, task, deleted_by_user_id=a.user.id, retention_days=30
    )
    await session.commit()
    # In the trash it still pins its pictures — it may come back.
    assert await _stored(session, a.guild.id, url)

    await hard_purge_entity(session, task)
    await session.commit()

    assert not await _stored(session, a.guild.id, url)


async def _discard(client: AsyncClient, a, url: str) -> None:
    from pathlib import Path

    response = await client.delete(
        a.g(f"/attachments/pasted/{Path(url).name}"), headers=a.headers
    )
    assert response.status_code == 204, response.text


@pytest.mark.integration
async def test_a_picture_left_unsaved_is_discarded(
    client: AsyncClient, session, acting_user
):
    a = await acting_user(guild_role=GuildRole.member)
    url = await _paste(client, a)

    await _discard(client, a, url)

    assert not await _stored(session, a.guild.id, url)


@pytest.mark.integration
async def test_a_saved_picture_is_not_discarded(
    client: AsyncClient, session, acting_user
):
    """The page asks about everything it pasted; the ones a description kept
    stay."""
    from app.testing import create_task

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    url = await _paste(client, a)
    await create_task(session, a.project, description=f"![shot]({url})")
    await session.commit()

    await _discard(client, a, url)

    assert await _stored(session, a.guild.id, url)


@pytest.mark.integration
async def test_nobody_discards_somebody_else_s_picture(
    client: AsyncClient, session, acting_user
):
    a = await acting_user(guild_role=GuildRole.member)
    b = await acting_user(guild_role=GuildRole.member, guild=a.guild)
    url = await _paste(client, a)

    await _discard(client, b, url)

    assert await _stored(session, a.guild.id, url)


@pytest.mark.integration
async def test_only_a_pasted_picture_can_be_discarded(
    client: AsyncClient, session, acting_user
):
    a = await acting_user(guild_role=GuildRole.member)
    response = await client.post(
        a.g("/attachments/"),
        headers=a.headers,
        files={"file": ("doc.png", io.BytesIO(TINY_PNG), "image/png")},
    )
    doc_url = response.json()["url"]

    await _discard(client, a, doc_url)

    assert await _stored(session, a.guild.id, doc_url)


@pytest.mark.integration
async def test_the_sweep_takes_pictures_nobody_saved_once_their_grace_is_over(
    client: AsyncClient, session, acting_user
):
    """A tab closed rather than left never discards what it pasted."""
    from datetime import datetime, timedelta, timezone

    from app.services.tenant.attachments import (
        UNCLAIMED_PASTED_IMAGE_GRACE,
        release_unclaimed_pasted_images,
    )
    from app.testing import create_task
    from app.testing.schema_harness import route_session_to_guild

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    unsaved = await _paste(client, a)
    saved = await _paste(client, a)
    await create_task(session, a.project, description=f"![shot]({saved})")
    await session.commit()

    await route_session_to_guild(session, a.guild.id)
    now = datetime.now(timezone.utc)
    # Within the grace period, both stay: the draft may still be saved.
    assert await release_unclaimed_pasted_images(session, now=now) == set()

    later = now + UNCLAIMED_PASTED_IMAGE_GRACE + timedelta(minutes=1)
    released = await release_unclaimed_pasted_images(session, now=later)

    assert released == {unsaved.rsplit("/", 1)[1]}


async def _edit_comment(client: AsyncClient, a, comment_id: int, text: str) -> None:
    response = await client.patch(
        a.g(f"/comments/{comment_id}"), headers=a.headers, json={"content": text}
    )
    assert response.status_code == 200, response.text


@pytest.mark.integration
async def test_taking_a_picture_out_of_a_comment_deletes_it(
    client: AsyncClient, session, acting_user
):
    from app.testing import create_comment, create_task

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task = await create_task(session, a.project)
    url = await _paste(client, a)
    comment = await create_comment(
        session, a.user, task=task, content=f"Here: ![shot]({url})"
    )
    await session.commit()

    await _edit_comment(client, a, comment.id, "Never mind")

    assert not await _stored(session, a.guild.id, url)


@pytest.mark.integration
async def test_a_picture_a_comment_shows_outlives_the_description(
    client: AsyncClient, session, acting_user
):
    """A picture moved between a description and a comment is the same file;
    either one showing it keeps it."""
    from app.testing import create_comment, create_task

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    url = await _paste(client, a)
    task = await create_task(session, a.project, description=f"![shot]({url})")
    await create_comment(session, a.user, task=task, content=f"again ![shot]({url})")
    await session.commit()

    await _set_description(client, a, task.id, "Never mind")

    assert await _stored(session, a.guild.id, url)


@pytest.mark.integration
async def test_purging_a_task_takes_its_comments_pictures_too(
    client: AsyncClient, session, acting_user
):
    from app.services.tenant.soft_delete import hard_purge_entity, soft_delete_entity
    from app.testing import create_comment, create_task
    from app.testing.schema_harness import route_session_to_guild

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    url = await _paste(client, a)
    task = await create_task(session, a.project)
    await create_comment(session, a.user, task=task, content=f"![shot]({url})")
    await session.commit()

    await route_session_to_guild(session, a.guild.id)
    await soft_delete_entity(
        session, task, deleted_by_user_id=a.user.id, retention_days=30
    )
    await session.commit()
    await hard_purge_entity(session, task)
    await session.commit()

    assert not await _stored(session, a.guild.id, url)

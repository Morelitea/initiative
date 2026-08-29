"""Integration tests for guild icons and banners.

These are the only guild media a stranger can be shown, so most of what is
asserted here is the boundary: which variant reaches whom, and that everything
else is a 404 rather than a 403 — an unlisted guild has published nothing, its
existence at a given id included.
"""

import io
import struct

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import Guild, GuildRole, GuildStatus
from app.models.platform.guild_image import (
    IMAGE_SPECS,
    GuildImage,
    GuildImageVariant,
)
from app.services.platform import app_settings as app_settings_service
from app.testing.factories import (
    create_user,
    get_auth_headers,
)


def _png(width: int, height: int, padding: int = 0) -> bytes:
    """A PNG whose header states these dimensions.

    Only the header is read — nothing decodes these bytes — so the image data
    is whatever makes the file the size a given test needs.
    """
    header = (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    )
    return header + b"\x00" * padding


def _spec_png(variant: GuildImageVariant, padding: int = 0) -> bytes:
    spec = IMAGE_SPECS[variant]
    return _png(spec.width, spec.height, padding)


def _banner_files(
    full: bytes | None = None, card: bytes | None = None
) -> dict[str, tuple[str, io.BytesIO, str]]:
    return {
        "full": (
            "full.png",
            io.BytesIO(full if full is not None else _spec_png(GuildImageVariant.full)),
            "image/png",
        ),
        "card": (
            "card.png",
            io.BytesIO(card if card is not None else _spec_png(GuildImageVariant.card)),
            "image/png",
        ),
    }


def _icon_files(
    icon: bytes | None = None,
) -> dict[str, tuple[str, io.BytesIO, str]]:
    return {
        "icon": (
            "icon.png",
            io.BytesIO(icon if icon is not None else _spec_png(GuildImageVariant.icon)),
            "image/png",
        )
    }


async def _set_icon(client: AsyncClient, guild_id: int, headers: dict) -> dict:
    response = await client.put(
        f"/api/v1/guilds/{guild_id}/icon", headers=headers, files=_icon_files()
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _set_banner(client: AsyncClient, guild_id: int, headers: dict) -> dict:
    response = await client.put(
        f"/api/v1/guilds/{guild_id}/banner", headers=headers, files=_banner_files()
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _list_as_community(session: AsyncSession, guild: Guild) -> Guild:
    guild.is_community = True
    guild.categories = ["other"]
    guild.has_adult_content = False
    session.add(guild)
    await session.commit()
    await session.refresh(guild)
    return guild


async def _variant_url(
    session: AsyncSession, guild_id: int, variant: GuildImageVariant
) -> str:
    digest = (
        await session.exec(
            select(GuildImage.sha256).where(
                GuildImage.guild_id == guild_id,
                GuildImage.variant == variant.value,
            )
        )
    ).one()
    return f"/api/v1/guilds/{guild_id}/image/{digest}"


async def _card_url(session: AsyncSession, guild_id: int) -> str:
    return await _variant_url(session, guild_id, GuildImageVariant.card)


@pytest.fixture
async def community_directory_on(session: AsyncSession) -> None:
    await app_settings_service.update_community_settings(
        session, community_directory_enabled=True
    )


# --- setting one -------------------------------------------------------------


@pytest.mark.integration
async def test_admin_sets_banner_and_gets_its_url_back(
    client: AsyncClient, acting_user
):
    """One upload, two renditions, and the reply already names the full one."""
    a = await acting_user(guild_role=GuildRole.admin)

    payload = await _set_banner(client, a.guild.id, a.headers)

    assert payload["banner_url"] is not None
    assert payload["banner_url"].startswith(f"/api/v1/guilds/{a.guild.id}/image/")


@pytest.mark.integration
async def test_member_cannot_set_the_banner(client: AsyncClient, acting_user):
    """Branding is the guild admin's, like the name and the icon."""
    a = await acting_user(guild_role=GuildRole.member)

    response = await client.put(
        f"/api/v1/guilds/{a.guild.id}/banner", headers=a.headers, files=_banner_files()
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_replacing_a_banner_leaves_one_of_each_rendition(
    client: AsyncClient, acting_user, session: AsyncSession
):
    """The old renditions go with the new ones arriving, not afterwards."""
    a = await acting_user(guild_role=GuildRole.admin)
    await _set_banner(client, a.guild.id, a.headers)

    response = await client.put(
        f"/api/v1/guilds/{a.guild.id}/banner",
        headers=a.headers,
        files=_banner_files(full=_spec_png(GuildImageVariant.full, padding=64)),
    )
    assert response.status_code == 200

    rows = (
        await session.exec(
            select(GuildImage.variant).where(GuildImage.guild_id == a.guild.id)
        )
    ).all()
    assert sorted(rows) == ["card", "full"]


@pytest.mark.integration
async def test_clearing_a_banner_removes_both_renditions(
    client: AsyncClient, acting_user, session: AsyncSession
):
    a = await acting_user(guild_role=GuildRole.admin)
    await _set_banner(client, a.guild.id, a.headers)

    response = await client.delete(
        f"/api/v1/guilds/{a.guild.id}/banner", headers=a.headers
    )

    assert response.status_code == 200
    assert response.json()["banner_url"] is None
    rows = (
        await session.exec(select(GuildImage).where(GuildImage.guild_id == a.guild.id))
    ).all()
    assert rows == []


# --- what counts as a banner --------------------------------------------------


@pytest.mark.integration
async def test_svg_is_refused(client: AsyncClient, acting_user):
    """A banner is rendered rather than downloaded, so it is raster only."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.put(
        f"/api/v1/guilds/{a.guild.id}/banner",
        headers=a.headers,
        files={
            "full": (
                "b.svg",
                io.BytesIO(b'<svg xmlns="http://www.w3.org/2000/svg"/>'),
                "image/svg+xml",
            ),
            "card": (
                "c.svg",
                io.BytesIO(b'<svg xmlns="http://www.w3.org/2000/svg"/>'),
                "image/svg+xml",
            ),
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "IMAGE_INVALID"


@pytest.mark.integration
async def test_a_declared_content_type_does_not_decide(
    client: AsyncClient, acting_user
):
    """The bytes settle the format; the client's claim about them does not."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.put(
        f"/api/v1/guilds/{a.guild.id}/banner",
        headers=a.headers,
        files={
            "full": ("full.png", io.BytesIO(b"not an image at all"), "image/png"),
            "card": ("card.png", io.BytesIO(b"nor is this"), "image/png"),
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "IMAGE_INVALID"


@pytest.mark.integration
async def test_a_card_carrying_the_full_image_is_refused(
    client: AsyncClient, acting_user
):
    """Otherwise the directory pays full price for a page of thumbnails."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.put(
        f"/api/v1/guilds/{a.guild.id}/banner",
        headers=a.headers,
        files=_banner_files(card=_spec_png(GuildImageVariant.full)),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "IMAGE_WRONG_SIZE"


@pytest.mark.integration
async def test_a_rendition_that_is_not_four_to_one_is_refused(
    client: AsyncClient, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.put(
        f"/api/v1/guilds/{a.guild.id}/banner",
        headers=a.headers,
        files=_banner_files(full=_png(1200, 600)),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "IMAGE_WRONG_RATIO"


@pytest.mark.integration
async def test_an_oversized_rendition_is_refused(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin)
    over = IMAGE_SPECS[GuildImageVariant.card].max_bytes + 1

    response = await client.put(
        f"/api/v1/guilds/{a.guild.id}/banner",
        headers=a.headers,
        files=_banner_files(card=_spec_png(GuildImageVariant.card, padding=over)),
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "IMAGE_TOO_LARGE"


# --- who may fetch one --------------------------------------------------------


@pytest.mark.integration
async def test_a_member_gets_both_renditions(
    client: AsyncClient, acting_user, session: AsyncSession
):
    a = await acting_user(guild_role=GuildRole.admin)
    payload = await _set_banner(client, a.guild.id, a.headers)

    full = await client.get(payload["banner_url"], headers=a.headers)
    card = await client.get(await _card_url(session, a.guild.id), headers=a.headers)

    assert full.status_code == 200
    assert full.headers["content-type"].startswith("image/png")
    assert "private" in full.headers["cache-control"]
    assert card.status_code == 200


@pytest.mark.integration
async def test_a_stranger_gets_nothing_from_an_unlisted_guild(
    client: AsyncClient, acting_user, session: AsyncSession
):
    """Not in the directory and not in the guild: there is no banner to have."""
    a = await acting_user(guild_role=GuildRole.admin)
    payload = await _set_banner(client, a.guild.id, a.headers)
    stranger = await create_user(session, email="stranger@example.com")
    headers = get_auth_headers(stranger)

    full = await client.get(payload["banner_url"], headers=headers)
    card = await client.get(await _card_url(session, a.guild.id), headers=headers)

    assert full.status_code == 404
    assert card.status_code == 404


@pytest.mark.integration
async def test_a_stranger_gets_the_card_of_a_listed_guild_but_not_its_front_page(
    client: AsyncClient, acting_user, session: AsyncSession, community_directory_on
):
    """The card is what a listed guild published. The full banner is not."""
    a = await acting_user(guild_role=GuildRole.admin)
    payload = await _set_banner(client, a.guild.id, a.headers)
    await _list_as_community(session, a.guild)
    stranger = await create_user(session, email="browser@example.com")
    headers = get_auth_headers(stranger)

    card = await client.get(await _card_url(session, a.guild.id), headers=headers)
    full = await client.get(payload["banner_url"], headers=headers)

    assert card.status_code == 200
    assert full.status_code == 404


@pytest.mark.integration
async def test_un_listing_a_guild_stops_serving_its_card(
    client: AsyncClient, acting_user, session: AsyncSession, community_directory_on
):
    """The listing is re-read per request, not inherited from the page that
    minted the URL."""
    a = await acting_user(guild_role=GuildRole.admin)
    await _set_banner(client, a.guild.id, a.headers)
    await _list_as_community(session, a.guild)
    stranger = await create_user(session, email="lingering@example.com")
    headers = get_auth_headers(stranger)
    url = await _card_url(session, a.guild.id)
    assert (await client.get(url, headers=headers)).status_code == 200

    a.guild.is_community = False
    session.add(a.guild)
    await session.commit()

    assert (await client.get(url, headers=headers)).status_code == 404


@pytest.mark.integration
async def test_a_suspended_guild_serves_nobody(
    client: AsyncClient, acting_user, session: AsyncSession, community_directory_on
):
    """Suspension takes the guild out of the directory and out of its members'
    reach, and the banner goes with it."""
    a = await acting_user(guild_role=GuildRole.admin)
    payload = await _set_banner(client, a.guild.id, a.headers)
    await _list_as_community(session, a.guild)
    url = await _card_url(session, a.guild.id)
    stranger = await create_user(session, email="onlooker@example.com")

    a.guild.status = GuildStatus.suspended.value
    session.add(a.guild)
    await session.commit()

    assert (
        await client.get(url, headers=get_auth_headers(stranger))
    ).status_code == 404
    assert (
        await client.get(payload["banner_url"], headers=a.headers)
    ).status_code == 404


@pytest.mark.integration
async def test_a_replaced_banners_url_stops_resolving(client: AsyncClient, acting_user):
    """The digest is in the path, so a stale URL is a miss rather than a
    different picture under a cache key promised to be immutable."""
    a = await acting_user(guild_role=GuildRole.admin)
    first = await _set_banner(client, a.guild.id, a.headers)

    await client.put(
        f"/api/v1/guilds/{a.guild.id}/banner",
        headers=a.headers,
        files=_banner_files(full=_spec_png(GuildImageVariant.full, padding=128)),
    )

    assert (await client.get(first["banner_url"], headers=a.headers)).status_code == 404


@pytest.mark.integration
async def test_a_banner_needs_a_session(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin)
    payload = await _set_banner(client, a.guild.id, a.headers)

    assert (await client.get(payload["banner_url"])).status_code == 401


# --- how it reaches the two surfaces ------------------------------------------


@pytest.mark.integration
async def test_the_guild_list_names_the_banner(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin)
    await _set_banner(client, a.guild.id, a.headers)

    response = await client.get("/api/v1/guilds/", headers=a.headers)

    assert response.status_code == 200
    entry = next(g for g in response.json() if g["id"] == a.guild.id)
    assert entry["banner_url"] is not None


@pytest.mark.integration
async def test_the_directory_names_the_card_rendition(
    client: AsyncClient, acting_user, session: AsyncSession, community_directory_on
):
    """A URL, never the bytes — a directory page is up to sixty cards."""
    a = await acting_user(guild_role=GuildRole.admin)
    await _set_banner(client, a.guild.id, a.headers)
    await _list_as_community(session, a.guild)
    stranger = await create_user(session, email="visitor@example.com")

    response = await client.get(
        "/api/v1/guilds/communities", headers=get_auth_headers(stranger)
    )

    assert response.status_code == 200
    card = next(g for g in response.json()["items"] if g["id"] == a.guild.id)
    assert card["banner_card_url"] == await _card_url(session, a.guild.id)


@pytest.mark.integration
async def test_a_guild_without_a_banner_names_none(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.get("/api/v1/guilds/", headers=a.headers)

    entry = next(g for g in response.json() if g["id"] == a.guild.id)
    assert entry["banner_url"] is None


@pytest.mark.integration
async def test_deleting_a_guild_takes_its_banner(
    client: AsyncClient, acting_user, session: AsyncSession
):
    """The cascade off ``public.guilds``, asserted rather than assumed."""
    a = await acting_user(guild_role=GuildRole.admin)
    await _set_banner(client, a.guild.id, a.headers)
    guild_id = a.guild.id

    # Raw, because the cascade under test is the database's: an ORM delete
    # would walk relationships into the guild's own schema, which this
    # (unrouted) session cannot see.
    await session.exec(
        text("DELETE FROM public.guilds WHERE id = :id"), params={"id": guild_id}
    )
    await session.commit()

    rows = (
        await session.exec(select(GuildImage).where(GuildImage.guild_id == guild_id))
    ).all()
    assert rows == []


@pytest.mark.integration
async def test_a_pam_grantee_reads_the_full_banner(
    client: AsyncClient, acting_user, session: AsyncSession
):
    """Break-glass reaches a guild's front page as a member does, for its
    window."""
    from datetime import datetime, timedelta, timezone

    from app.models.platform.access_grant import AccessGrant

    a = await acting_user(guild_role=GuildRole.admin)
    payload = await _set_banner(client, a.guild.id, a.headers)
    operator = await create_user(session, email="operator@example.com")
    now = datetime.now(timezone.utc)
    session.add(
        AccessGrant(
            user_id=operator.id,
            guild_id=a.guild.id,
            access_level="read",
            status="approved",
            reason="ticket",
            requested_duration_minutes=60,
            requested_by_id=operator.id,
            approved_by_id=operator.id,
            decided_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    await session.commit()

    response = await client.get(
        payload["banner_url"], headers=get_auth_headers(operator)
    )

    assert response.status_code == 200


# --- the colour alternative ---------------------------------------------------


@pytest.mark.integration
async def test_a_guild_can_choose_a_colour_instead(client: AsyncClient, acting_user):
    """No artwork to find: the banner is a colour, and it costs no request."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.patch(
        f"/api/v1/guilds/{a.guild.id}",
        headers=a.headers,
        json={"banner_color": "#3F6FB5"},
    )

    assert response.status_code == 200
    assert response.json()["banner_color"] == "#3f6fb5"


@pytest.mark.integration
async def test_a_colour_that_is_not_one_is_refused(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.patch(
        f"/api/v1/guilds/{a.guild.id}",
        headers=a.headers,
        json={"banner_color": "rebeccapurple"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "BANNER_COLOR_INVALID"


@pytest.mark.integration
async def test_a_null_colour_is_a_reset_not_a_removal(client: AsyncClient, acting_user):
    """A banner is never colourless, so there is nothing for null to clear."""
    from app.models.platform.guild import DEFAULT_BANNER_COLOR

    a = await acting_user(guild_role=GuildRole.admin)
    await client.patch(
        f"/api/v1/guilds/{a.guild.id}",
        headers=a.headers,
        json={"banner_color": "#101010"},
    )

    response = await client.patch(
        f"/api/v1/guilds/{a.guild.id}", headers=a.headers, json={"banner_color": None}
    )

    assert response.status_code == 200
    assert response.json()["banner_color"] == DEFAULT_BANNER_COLOR


@pytest.mark.integration
async def test_every_guild_starts_with_a_banner(client: AsyncClient, acting_user):
    """No guild is ever without one, so nothing downstream renders a guild
    that has none."""
    from app.models.platform.guild import (
        DEFAULT_BANNER_COLOR,
        DEFAULT_BANNER_TEXT_COLOR,
    )

    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.get("/api/v1/guilds/", headers=a.headers)

    entry = next(g for g in response.json() if g["id"] == a.guild.id)
    assert entry["banner_color"] == DEFAULT_BANNER_COLOR
    assert entry["banner_text_color"] == DEFAULT_BANNER_TEXT_COLOR


@pytest.mark.integration
async def test_the_banner_text_colour_is_the_guilds_to_set(
    client: AsyncClient, acting_user
):
    """Artwork is not one colour, so what reads over it is not ours to guess."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.patch(
        f"/api/v1/guilds/{a.guild.id}",
        headers=a.headers,
        json={"banner_color": "#f5f0e8", "banner_text_color": "#000000"},
    )

    assert response.status_code == 200
    assert response.json()["banner_text_color"] == "#000000"


@pytest.mark.integration
async def test_the_picker_may_send_an_alpha_byte(client: AsyncClient, acting_user):
    """The shared colour picker emits ``#rrggbbaa``; a banner is a fill with
    nothing behind it, so the alpha is dropped rather than refused."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.patch(
        f"/api/v1/guilds/{a.guild.id}",
        headers=a.headers,
        json={"banner_color": "#2A9D8FFF"},
    )

    assert response.status_code == 200
    assert response.json()["banner_color"] == "#2a9d8f"


@pytest.mark.integration
async def test_the_directory_carries_the_colour(
    client: AsyncClient, acting_user, session: AsyncSession, community_directory_on
):
    """A card with no artwork still has a banner, and it arrives in the payload
    that was already being sent."""
    a = await acting_user(guild_role=GuildRole.admin)
    await client.patch(
        f"/api/v1/guilds/{a.guild.id}",
        headers=a.headers,
        json={"banner_color": "#2a9d8f"},
    )
    await _list_as_community(session, a.guild)
    stranger = await create_user(session, email="colourblind@example.com")

    response = await client.get(
        "/api/v1/guilds/communities", headers=get_auth_headers(stranger)
    )

    card = next(g for g in response.json()["items"] if g["id"] == a.guild.id)
    assert card["banner_color"] == "#2a9d8f"
    assert card["banner_card_url"] is None


# --- the artwork entitlement --------------------------------------------------


@pytest.mark.integration
async def test_a_guild_without_the_artwork_entitlement_cannot_upload(
    client: AsyncClient, acting_user, session: AsyncSession
):
    """The banner surface stays; the upload half of it does not."""
    from app.models.platform.guild_administration import GuildAdministration

    a = await acting_user(guild_role=GuildRole.admin)
    administration = (
        await session.exec(
            select(GuildAdministration).where(
                GuildAdministration.guild_id == a.guild.id
            )
        )
    ).one()
    administration.banner_image_enabled = False
    session.add(administration)
    await session.commit()

    response = await client.put(
        f"/api/v1/guilds/{a.guild.id}/banner", headers=a.headers, files=_banner_files()
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "BANNER_IMAGE_NOT_ENTITLED"


@pytest.mark.integration
async def test_the_colour_is_still_available_without_the_entitlement(
    client: AsyncClient, acting_user, session: AsyncSession
):
    """Every guild has a banner; not every guild has artwork."""
    from app.models.platform.guild_administration import GuildAdministration

    a = await acting_user(guild_role=GuildRole.admin)
    administration = (
        await session.exec(
            select(GuildAdministration).where(
                GuildAdministration.guild_id == a.guild.id
            )
        )
    ).one()
    administration.banner_image_enabled = False
    session.add(administration)
    await session.commit()

    response = await client.patch(
        f"/api/v1/guilds/{a.guild.id}",
        headers=a.headers,
        json={"banner_color": "#8d5524"},
    )

    assert response.status_code == 200
    assert response.json()["banner_color"] == "#8d5524"


@pytest.mark.integration
async def test_the_entitlement_is_on_by_default(acting_user, session: AsyncSession):
    """Nothing changes for an existing guild, or for a self-hosted install."""
    from app.models.platform.guild_administration import GuildAdministration

    a = await acting_user(guild_role=GuildRole.admin)

    administration = (
        await session.exec(
            select(GuildAdministration).where(
                GuildAdministration.guild_id == a.guild.id
            )
        )
    ).one()

    assert administration.banner_image_enabled is True


@pytest.mark.integration
async def test_a_guild_keeps_serving_artwork_it_already_had(
    client: AsyncClient, acting_user, session: AsyncSession
):
    """Losing the entitlement stops new uploads; it does not take down a
    banner the guild is already showing."""
    from app.models.platform.guild_administration import GuildAdministration

    a = await acting_user(guild_role=GuildRole.admin)
    payload = await _set_banner(client, a.guild.id, a.headers)
    administration = (
        await session.exec(
            select(GuildAdministration).where(
                GuildAdministration.guild_id == a.guild.id
            )
        )
    ).one()
    administration.banner_image_enabled = False
    session.add(administration)
    await session.commit()

    response = await client.get(payload["banner_url"], headers=a.headers)

    assert response.status_code == 200


# --- the icon -----------------------------------------------------------------


@pytest.mark.integration
async def test_admin_sets_the_icon_and_gets_its_url_back(
    client: AsyncClient, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin)

    payload = await _set_icon(client, a.guild.id, a.headers)

    assert payload["icon_url"] is not None
    assert payload["icon_url"].startswith(f"/api/v1/guilds/{a.guild.id}/image/")


@pytest.mark.integration
async def test_the_icon_and_the_banner_do_not_disturb_each_other(
    client: AsyncClient, acting_user
):
    """Two pictures on one table, replaced independently."""
    a = await acting_user(guild_role=GuildRole.admin)
    await _set_banner(client, a.guild.id, a.headers)

    payload = await _set_icon(client, a.guild.id, a.headers)

    assert payload["icon_url"] is not None
    assert payload["banner_url"] is not None

    cleared = await client.delete(
        f"/api/v1/guilds/{a.guild.id}/icon", headers=a.headers
    )
    assert cleared.status_code == 200
    assert cleared.json()["icon_url"] is None
    assert cleared.json()["banner_url"] is not None


@pytest.mark.integration
async def test_the_icon_is_not_gated_by_the_banner_entitlement(
    client: AsyncClient, acting_user, session: AsyncSession
):
    """A guild without banner artwork still has a mark in the switcher."""
    from app.models.platform.guild_administration import GuildAdministration

    a = await acting_user(guild_role=GuildRole.admin)
    administration = (
        await session.exec(
            select(GuildAdministration).where(
                GuildAdministration.guild_id == a.guild.id
            )
        )
    ).one()
    administration.banner_image_enabled = False
    session.add(administration)
    await session.commit()

    payload = await _set_icon(client, a.guild.id, a.headers)

    assert payload["icon_url"] is not None


@pytest.mark.integration
async def test_a_non_square_icon_is_refused(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.put(
        f"/api/v1/guilds/{a.guild.id}/icon",
        headers=a.headers,
        files=_icon_files(icon=_png(256, 128)),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "IMAGE_WRONG_RATIO"


@pytest.mark.integration
async def test_a_stranger_gets_a_listed_guilds_icon(
    client: AsyncClient, acting_user, session: AsyncSession, community_directory_on
):
    """The icon is published by listing, exactly as the card rendition is."""
    a = await acting_user(guild_role=GuildRole.admin)
    await _set_icon(client, a.guild.id, a.headers)
    await _list_as_community(session, a.guild)
    stranger = await create_user(session, email="icon-browser@example.com")
    url = await _variant_url(session, a.guild.id, GuildImageVariant.icon)

    response = await client.get(url, headers=get_auth_headers(stranger))

    assert response.status_code == 200


@pytest.mark.integration
async def test_a_stranger_gets_nothing_from_an_unlisted_guilds_icon(
    client: AsyncClient, acting_user, session: AsyncSession
):
    a = await acting_user(guild_role=GuildRole.admin)
    await _set_icon(client, a.guild.id, a.headers)
    stranger = await create_user(session, email="icon-stranger@example.com")
    url = await _variant_url(session, a.guild.id, GuildImageVariant.icon)

    response = await client.get(url, headers=get_auth_headers(stranger))

    assert response.status_code == 404


@pytest.mark.integration
async def test_the_directory_names_the_icon(
    client: AsyncClient, acting_user, session: AsyncSession, community_directory_on
):
    """A card names both its pictures; it carries neither."""
    a = await acting_user(guild_role=GuildRole.admin)
    await _set_icon(client, a.guild.id, a.headers)
    await _list_as_community(session, a.guild)
    stranger = await create_user(session, email="icon-visitor@example.com")

    response = await client.get(
        "/api/v1/guilds/communities", headers=get_auth_headers(stranger)
    )

    card = next(g for g in response.json()["items"] if g["id"] == a.guild.id)
    assert card["icon_url"] == await _variant_url(
        session, a.guild.id, GuildImageVariant.icon
    )
    assert "icon_base64" not in card


@pytest.mark.integration
async def test_the_guild_list_names_the_icon(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin)
    await _set_icon(client, a.guild.id, a.headers)

    response = await client.get("/api/v1/guilds/", headers=a.headers)

    entry = next(g for g in response.json() if g["id"] == a.guild.id)
    assert entry["icon_url"] is not None
    assert "icon_base64" not in entry


@pytest.mark.integration
async def test_a_guild_admin_reads_their_own_entitlements(
    client: AsyncClient, acting_user
):
    """How the settings page knows to offer the colour alone."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.get(
        f"/api/v1/guilds/{a.guild.id}/entitlements", headers=a.headers
    )

    assert response.status_code == 200
    assert response.json() == {"guild_id": a.guild.id, "banner_image_enabled": True}


@pytest.mark.integration
async def test_entitlements_follow_the_operator(
    client: AsyncClient, acting_user, session: AsyncSession
):
    from app.models.platform.guild_administration import GuildAdministration

    a = await acting_user(guild_role=GuildRole.admin)
    administration = (
        await session.exec(
            select(GuildAdministration).where(
                GuildAdministration.guild_id == a.guild.id
            )
        )
    ).one()
    administration.banner_image_enabled = False
    session.add(administration)
    await session.commit()

    response = await client.get(
        f"/api/v1/guilds/{a.guild.id}/entitlements", headers=a.headers
    )

    assert response.json()["banner_image_enabled"] is False


@pytest.mark.integration
async def test_a_member_does_not_read_entitlements(client: AsyncClient, acting_user):
    """Decisions made about a guild are its admins' business, not its roster's."""
    a = await acting_user(guild_role=GuildRole.member)

    response = await client.get(
        f"/api/v1/guilds/{a.guild.id}/entitlements", headers=a.headers
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_a_truncated_image_is_a_bad_upload_not_a_fault(
    client: AsyncClient, acting_user
):
    """A file can carry a format's opening marks and stop before its
    dimensions. That is an answer about the upload, not an error."""
    a = await acting_user(guild_role=GuildRole.admin)
    # PNG signature + IHDR marker and nothing after it.
    stub = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"

    response = await client.put(
        f"/api/v1/guilds/{a.guild.id}/icon",
        headers=a.headers,
        files=_icon_files(icon=stub),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "IMAGE_INVALID"


@pytest.mark.integration
async def test_dropping_below_the_seat_floor_stops_publishing_artwork(
    client: AsyncClient, acting_user, session: AsyncSession, community_directory_on
):
    """An operator can take a guild out of the directory without the guild
    doing anything, and what the listing published goes with it."""
    from app.models.platform.guild_administration import GuildAdministration

    a = await acting_user(guild_role=GuildRole.admin)
    await _set_icon(client, a.guild.id, a.headers)
    await _set_banner(client, a.guild.id, a.headers)
    await _list_as_community(session, a.guild)
    stranger = await create_user(session, email="seat-floor@example.com")
    headers = get_auth_headers(stranger)
    icon = await _variant_url(session, a.guild.id, GuildImageVariant.icon)
    card = await _card_url(session, a.guild.id)
    assert (await client.get(icon, headers=headers)).status_code == 200

    administration = (
        await session.exec(
            select(GuildAdministration).where(
                GuildAdministration.guild_id == a.guild.id
            )
        )
    ).one()
    administration.max_users = 1
    session.add(administration)
    await session.commit()

    assert (await client.get(icon, headers=headers)).status_code == 404
    assert (await client.get(card, headers=headers)).status_code == 404
    # The directory it left agrees.
    directory = await client.get("/api/v1/guilds/communities", headers=headers)
    assert all(g["id"] != a.guild.id for g in directory.json()["items"])


@pytest.mark.integration
async def test_banner_text_is_black_or_white_and_nothing_else(
    client: AsyncClient, acting_user
):
    """A fill the guild picked, or artwork of any colour, stays readable only
    at one end of the scale or the other — so those are the only two."""
    a = await acting_user(guild_role=GuildRole.admin)

    refused = await client.patch(
        f"/api/v1/guilds/{a.guild.id}",
        headers=a.headers,
        json={"banner_text_color": "#808080"},
    )
    accepted = await client.patch(
        f"/api/v1/guilds/{a.guild.id}",
        headers=a.headers,
        json={"banner_text_color": "#000000"},
    )

    assert refused.status_code == 400
    assert refused.json()["detail"] == "BANNER_TEXT_COLOR_INVALID"
    assert accepted.status_code == 200
    assert accepted.json()["banner_text_color"] == "#000000"

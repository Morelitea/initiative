"""My Contacts — the personal, cross-guild directory of people.

Everything here is served on ``UserSessionDep``: the guild rosters through the
per-guild routing loop every other ``/me`` aggregate uses, and the starred list
straight off ``public``. No system engine on any path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select

from app.api.deps import UserSessionDep, get_current_active_user
from app.core.messages import ContactMessages
from app.models.platform.profile_favorite import ProfileFavorite
from app.models.platform.user import User
from app.models.platform.user_profile_view import user_profiles
from app.schemas.platform.contact import (
    ContactSectionsResponse,
    FavoriteContactsResponse,
)
from app.services.platform import contacts as contacts_service
from app.services.platform import users as users_service

me_router = APIRouter()


SearchQuery = Annotated[
    Optional[str],
    Query(
        max_length=128,
        description=(
            "Narrows every section. Matches the handle, plus the real name in "
            "a guild that shows names; type a whole handle (`foobar#1234`) to "
            "pin one person."
        ),
    ),
]


@me_router.get("/contacts", response_model=ContactSectionsResponse)
async def list_contact_sections(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    search: SearchQuery = None,
    guild_ids: Annotated[Optional[List[int]], Query()] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=contacts_service.DEFAULT_PAGE_SIZE, ge=1, le=100),
) -> ContactSectionsResponse:
    """Every guild the caller is in, each with a page of its members.

    Sections come back in the caller's own rail order
    (``GuildMembership.position``), and each is paged **within** the guild —
    the response is grouped, so a flat offset across a merged list would not
    mean anything. Pass one ``guild_ids`` value to page a single section.

    A guild reachable only through a live PAM or break-glass grant has no
    section here: like every other ``/me`` aggregate, this walks real
    memberships.
    """
    guilds = await contacts_service.ordered_member_guilds(
        session, user_id=current_user.id, platform_role=current_user.role.value
    )
    if guild_ids:
        wanted = set(guild_ids)
        guilds = [row for row in guilds if row[0] in wanted]

    sections = await contacts_service.guild_sections(
        session,
        user_id=current_user.id,
        guilds=guilds,
        search=search,
        page=page,
        page_size=page_size,
        platform_role=current_user.role.value,
    )
    if search and search.strip():
        sections = [section for section in sections if section.items]
    return ContactSectionsResponse(sections=sections, page=page, page_size=page_size)


@me_router.get("/contacts/favorites", response_model=FavoriteContactsResponse)
async def list_favorite_contacts(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    search: SearchQuery = None,
) -> FavoriteContactsResponse:
    """The starred section.

    Not part of the guild aggregate: a favorite may be someone the caller
    shares no guild with.
    """
    return await contacts_service.favorites(
        session, user_id=current_user.id, search=search
    )


@me_router.put("/contacts/favorites/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_favorite_contact(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    user_id: Annotated[int, Path(ge=1)],
) -> Response:
    """Star somebody.

    Idempotent — the row's address is the pair, so starring twice is a no-op
    rather than a conflict. Any visible profile may be starred, including
    somebody the caller shares no guild with.
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ContactMessages.CANNOT_FAVORITE_SELF,
        )

    subject = (
        await session.exec(
            select(user_profiles.c.id).where(
                user_profiles.c.id == user_id,
                users_service.visible_to_other_people(user_profiles.c.status),
            )
        )
    ).first()
    if subject is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ContactMessages.USER_NOT_FOUND,
        )

    # Let the primary key decide, rather than reading first and inserting after:
    # two stars of the same person arriving together both find nothing and both
    # write, and the second one is what the pair constraint is for. The database
    # settles it in one statement.
    await session.exec(
        pg_insert(ProfileFavorite)
        .values(
            user_id=current_user.id,
            favorite_user_id=user_id,
            created_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(index_elements=["user_id", "favorite_user_id"])
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.delete(
    "/contacts/favorites/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_favorite_contact(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    user_id: Annotated[int, Path(ge=1)],
) -> Response:
    """Unstar somebody. Idempotent, and the only way a row is removed."""
    row = (
        await session.exec(
            select(ProfileFavorite).where(
                ProfileFavorite.user_id == current_user.id,
                ProfileFavorite.favorite_user_id == user_id,
            )
        )
    ).first()
    if row is not None:
        await session.delete(row)
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

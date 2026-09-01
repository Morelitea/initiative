"""What one person may dress their profile in.

One function answers it — :func:`owned_decorations` — over two sources: what
ships with the app, which everyone has, and what the account acquired, which is
a row in ``public.user_decorations``. Every caller goes through it, so the
picker offers exactly what the write path accepts.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.profile_decorations import SHIPPED_DECORATIONS
from app.core.profile_packs import PROFILE_PACKS, ProfilePack
from app.models.platform.user import User
from app.models.platform.user_decoration import UserDecoration
from app.schemas.platform.user import OwnedDecoration, ProfileDecorations


async def owned_decorations(
    session: AsyncSession, user_id: int
) -> list[OwnedDecoration]:
    """Everything this account may wear, shipped first and then acquired.

    Shipped decorations carry no ``source``: nobody granted them, they came
    with the app. An acquired row naming an id that also ships is dropped
    rather than listed twice — you cannot own a thing twice, and a pack that
    includes a default should not make the picker stutter.
    """
    owned = [
        OwnedDecoration(id=decoration_id, kind=kind, source=None)
        for decoration_id, kind in SHIPPED_DECORATIONS.items()
    ]
    rows = (
        await session.exec(
            select(UserDecoration)
            .where(UserDecoration.user_id == user_id)
            .order_by(
                UserDecoration.acquired_at.asc(), UserDecoration.decoration_id.asc()
            )
        )
    ).all()
    owned.extend(
        OwnedDecoration(id=row.decoration_id, kind=row.kind, source=row.source)
        for row in rows
        if row.decoration_id not in SHIPPED_DECORATIONS
    )
    return owned


async def owned_kinds(session: AsyncSession, user_id: int) -> dict[str, str]:
    """``id -> slot`` for everything this account may wear.

    The shape the write path checks against: an id has to be here, and it has
    to be here as the slot it is being put in.
    """
    return {item.id: item.kind for item in await owned_decorations(session, user_id)}


def unwearable(wanted: Iterable[tuple[str, str]], owned: dict[str, str]) -> list[str]:
    """Which of these ``(id, slot)`` pairs this library does not answer for.

    Both failures land here: an id the account does not have, and one it has
    in a different slot — a badge cannot be worn as a frame.
    """
    return [
        decoration_id
        for decoration_id, kind in wanted
        if owned.get(decoration_id) != kind
    ]


async def installed_pack_ids(session: AsyncSession, user_id: int) -> set[str]:
    """Which packs this account has. A pack is installed when its rows are
    there, so nothing else records it."""
    sources = (
        await session.exec(
            select(UserDecoration.source).where(
                UserDecoration.user_id == user_id,
                UserDecoration.source.is_not(None),
            )
        )
    ).all()
    return {source for source in sources if source in PROFILE_PACKS}


async def install_pack(
    session: AsyncSession, *, user_id: int, pack: ProfilePack
) -> None:
    """Put a pack's decorations in this account's library.

    Idempotent: taking a pack you already have changes nothing, which is what
    a second click on a slow connection should do. Runs on the system engine —
    the request path reads its library and never writes it.
    """
    held = set(
        (
            await session.exec(
                select(UserDecoration.decoration_id).where(
                    UserDecoration.user_id == user_id,
                    UserDecoration.decoration_id.in_(list(pack.decorations)),
                )
            )
        ).all()
    )
    for decoration_id, kind in pack.decorations.items():
        if decoration_id in held:
            continue
        session.add(
            UserDecoration(
                user_id=user_id,
                decoration_id=decoration_id,
                kind=kind,
                source=pack.id,
            )
        )


async def remove_pack(
    session: AsyncSession, *, user_id: int, pack: ProfilePack
) -> None:
    """Take a pack's decorations back out of this account's library.

    Scoped to rows this pack granted: a decoration that arrived from somewhere
    else and happens to share an id is not this pack's to remove.
    """
    await session.exec(
        delete(UserDecoration).where(
            UserDecoration.user_id == user_id,
            UserDecoration.source == pack.id,
        )
    )


def undress(worn: ProfileDecorations, gone: ProfilePack) -> ProfileDecorations:
    """The same look with anything from ``gone`` taken off.

    Removing a pack has to take its pieces off the profile as well as out of
    the library, or the profile would go on wearing something the account no
    longer has — which the write path would then refuse to save on the next
    unrelated edit.
    """
    return ProfileDecorations(
        banner=None if worn.banner in gone.decorations else worn.banner,
        frame=None if worn.frame in gone.decorations else worn.frame,
        badges=[badge for badge in worn.badges if badge not in gone.decorations],
    )


def user_is_wearing(user: User) -> ProfileDecorations:
    """What this account currently has on, as the typed shape."""
    return ProfileDecorations.model_validate(user.profile_decorations or {})

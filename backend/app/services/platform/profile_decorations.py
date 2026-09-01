"""What one person may dress their profile in.

One function answers it — :func:`owned_decorations` — over two sources: what
ships with the app, which everyone has, and what the account acquired, which is
a row in ``public.user_decorations``. Every caller goes through it, so the
picker offers exactly what the write path accepts.
"""

from __future__ import annotations

from typing import Iterable

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.profile_decorations import SHIPPED_DECORATIONS
from app.models.platform.user_decoration import UserDecoration
from app.schemas.platform.user import OwnedDecoration


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

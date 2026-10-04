"""A dashboard that shows everybody its owner's view.

A tile ordinarily answers from whoever is looking at it. A dashboard can
instead say "show what *I* see": ``Dashboard.view_as_user_id`` names the
person, and its query widgets then answer as that person for everybody who can
open the dashboard.

Three rules keep that from reaching further than it should:

* **Only for yourself.** The setting is written by the person it names, as
  them; nobody can point a dashboard at somebody else's access.
* **Only they choose what it asks.** While it is on, the widgets' statements
  are changed by that person alone. The statement decides which of their rows
  a reader sees, so changing one is the act of sharing them.
* **It rests on their standing now.** The context is re-derived from the
  community's own rows on every fetch, through the establishment seam, and a
  time-bound grant they hold is taken off it. Somebody who has left, been
  suspended, or lost their place falls back to each viewer's own view.

The dashboard's own gates still decide who can open it at all, and the canvas
stays narrowed to the dashboard's initiative.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

from app.db import cohorts
from app.db.request_context import Member
from app.db.session import routed_context
from app.models.tenant.dashboard import Dashboard


async def owner_context(dashboard: Dashboard, guild_id: int) -> Optional[Member]:
    """The context this dashboard's statements run as, or ``None`` to run as
    each viewer.

    ``None`` covers both "the dashboard shows each viewer their own" and "the
    person it shows no longer stands in the community". Both read the same to
    a fetch; the caller reports which through :func:`serves`.
    """
    user_id = dashboard.view_as_user_id
    if user_id is None:
        return None
    from app.services.tenant.published_views import _standing

    async with cohorts.request_sessionmaker(guild_id)() as session:
        standing = await _standing(session, user_id, guild_id)
        if standing is None:
            return None
        _, context = standing
        routed = routed_context(session)
    if not isinstance(routed, Member):
        return None
    return replace(routed, standing=context)


async def serves(dashboard: Dashboard, guild_id: int) -> bool:
    """Whether the owner's view is what readers are seeing right now."""
    return await owner_context(dashboard, guild_id) is not None

"""The direct-message policy row that hangs off an account.

One row per account, created with the account. It is seeded here rather than in
each of the three places an account is made — registration, provisioning from
an identity provider, and the bootstrap owner — so the operator's default is
applied wherever an account arrives from.

A missing row still reads as ``private`` in ``public.dm_can_ask``, so a path
that somehow skips this is closed rather than open; what it would lose is the
operator's choice, silently, which is what ``dm_settings_test`` is for.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform.user_dm_settings import UserDmSettings


async def seed_for_new_account(session: AsyncSession, *, user_id: int) -> None:
    """Give a newly created account the policy the operator set as the default.

    Runs on the session that created the account, which is the system engine on
    every path — the row belongs to an account that has no request context of
    its own yet.

    Idempotent by constraint: a second call for the same account does nothing,
    so a retried registration does not overwrite a policy its owner has since
    changed.
    """
    from app.services.platform import app_settings as app_settings_service

    app_settings = await app_settings_service.get_app_settings(session)
    # A core insert, so the model's default factories do not run: the
    # timestamps are named here.
    now = datetime.now(timezone.utc)
    await session.exec(
        pg_insert(UserDmSettings)
        .values(
            user_id=user_id,
            dm_policy=app_settings.default_dm_policy,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=["user_id"])
    )

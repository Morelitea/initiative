import pytest
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing import create_guild, create_initiative, create_project, create_user


@pytest.mark.integration
async def test_grants_polymorphic_relationship_loads(session: AsyncSession):
    """The viewonly grants relationship returns only this resource's grants."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    other = await create_project(session, initiative, user, name="Other")

    # create_project already seeded an owner user-grant on BOTH projects (one grant
    # per user per resource). `other`'s grant is itself a cross-resource_id decoy.
    # Add a same-id, different-resource_type decoy that must also be excluded.
    session.add(
        ResourceGrant(
            guild_id=guild.id,
            initiative_id=initiative.id,
            resource_type="document",
            resource_id=project.id,
            user_id=user.id,
            level=ResourceAccessLevel.read,
        )
    )
    await session.commit()

    loaded = (
        await session.exec(
            select(Project)
            .where(Project.id == project.id)
            .options(selectinload(Project.grants))
        )
    ).one()
    # Only this project's grants: the factory's owner grant, neither decoy
    # (not `other`'s project grant, not the same-id document grant).
    assert all(
        g.resource_type == "project" and g.resource_id == project.id
        for g in loaded.grants
    )
    assert all(g.resource_id != other.id for g in loaded.grants)
    assert any(
        g.user_id == user.id and g.level == ResourceAccessLevel.owner
        for g in loaded.grants
    )

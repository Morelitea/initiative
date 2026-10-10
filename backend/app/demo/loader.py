"""``python -m app.demo load``: seed the demo from its manifest.

Every run is safe to repeat. Personas and fixed accounts are found by handle
and a community by the persona that created it, so a second run creates only
what is missing. ``rebuild`` is the weekly run: it also deletes every seeded
community not marked ``keep`` and makes it again, so its dates stay current.

Everything goes through the paths the app itself uses: communities are made
by the create sequence and deleted by the purge, and a bundle is imported by
an ordinary backup import job, run as the community's creator.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlmodel import col, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import usernames
from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.image_headers import validate_image
from app.core.notification_categories import CATEGORY_SPECS, Channel
from app.core.password_policy import validate_new_password
from app.core.security import get_password_hash, verify_password
from app.db import cohorts
from app.db.holds import HoldsInForce
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.demo import shapes
from app.demo.manifest import (
    Community,
    DemoManifest,
    DirectoryCard,
    FixedAccount,
    Persona,
    SignIn,
    SignInFile,
    split_handle,
)
from app.models.platform.guild import CommunityStatus, Guild
from app.models.platform.guild_image import IMAGE_SPECS, GuildImageVariant
from app.models.platform.user import User
from app.models.tenant.import_job import ImportJob, ImportJobStatus
from app.models.tenant.initiative import Initiative
from app.services import audit as audit_service
from app.services.auth import addresses, sign_in_locks
from app.services.import_engine import backup as backup_service
from app.services.import_engine import engine as import_engine
from app.services.import_engine import worker as import_worker
from app.services.platform import app_settings as app_settings_service
from app.services.platform import dm_settings as dm_settings_service
from app.services.platform import guild_images, guild_purge, user_avatars, user_tokens
from app.services.platform import guilds as guilds_service
from app.services.platform.intake import configured_operations_guild_id
from app.services.platform.notification_prefs import save_prefs

logger = logging.getLogger(__name__)

#: How long the loader waits for a community's import, and how often it looks.
IMPORT_TIMEOUT_SECONDS = 30 * 60
IMPORT_POLL_SECONDS = 1.0


class DemoModeRequired(RuntimeError):
    """The loader runs only on a deployment started with ``DEMO_MODE``."""


#: A persona's notification settings: nothing leaves the app.
_SILENT = {
    "categories": {
        category.value: {
            channel.value: False
            for channel in spec.mutable_channels
            if channel is not Channel.in_app
        }
        for category, spec in CATEGORY_SPECS.items()
    }
}


async def load(
    manifest_path: Path, accounts_path: Path, *, rebuild: bool = False
) -> None:
    """Seed the demo from the manifest at ``manifest_path``, with the fixed
    accounts' sign-in details from ``accounts_path``."""
    if not settings.DEMO_MODE:
        raise DemoModeRequired("set DEMO_MODE=true to load the demo")
    manifest = DemoManifest.model_validate_json(manifest_path.read_text())
    sign_ins = SignInFile.model_validate_json(accounts_path.read_text()).root
    missing = {a.handle for a in manifest.accounts} - sign_ins.keys()
    if missing:
        raise ValueError(f"no sign-in details for {', '.join(sorted(missing))}")
    base = manifest_path.parent

    async with cohorts.system_session(None) as session:
        await set_rls_context(session, Unattributed())
        personas = {p.handle: await _persona(session, p) for p in manifest.personas}
        await session.commit()
        names = {p.handle: p.display_name for p in manifest.personas}
        seeded = {
            spec.creator: await _community(
                session, spec, personas, names, base, rebuild
            )
            for spec in manifest.all_communities()
        }
        fixed = {
            key: seeded[spec.creator].id
            for key, spec in manifest.fixed_communities.items()
        }
        for account in manifest.accounts:
            await _fixed_account(session, account, sign_ins[account.handle], fixed)
        await session.commit()

    operations = await configured_operations_guild_id()
    if manifest.shapes:
        if operations is None:
            raise ValueError(
                "shapes are kept in the operations community; set it first"
            )
        for shape in manifest.shapes:
            # Refused here rather than when a pitch is made from it.
            await asyncio.to_thread(
                backup_service.plan_backup,
                base / shape.bundle,
                existing_initiative_names=set(),
            )
    if operations is not None and (
        manifest.shapes
        or await asyncio.to_thread(shapes.read_library, operations) is not None
    ):
        editors = [a.handle for a in manifest.accounts if a.pitch_editor]
        await asyncio.to_thread(
            shapes.write_library, operations, manifest.shapes, editors, base
        )


async def _by_handle(session: AsyncSession, handle: str) -> User | None:
    name, number = split_handle(handle)
    return (
        await session.exec(
            select(User).where(
                func.lower(User.username) == name, User.discriminator == number
            )
        )
    ).one_or_none()


async def _persona(session: AsyncSession, persona: Persona) -> User:
    """The persona's account: no password, no address, and every notification
    that would leave the app off."""
    user = await _by_handle(session, persona.handle)
    if user is None:
        name, number = split_handle(persona.handle)
        user = User(
            username=name,
            discriminator=number,
            username_chosen=True,
            # Listed communities seat only accounts that answered the age
            # question, and a persona has nobody to answer it.
            age_confirmed_at=datetime.now(timezone.utc),
        )
        session.add(user)
        await session.flush()
        await dm_settings_service.seed_for_new_account(session, user_id=user.id)
        await audit_service.record(
            session,
            event_type=AuditEventType.USER_CREATED,
            actor_user_id=None,
            target_user_id=user.id,
            detail={"via": "demo"},
        )
    elif user.hashed_password is not None or await addresses.list_for_user(
        session, user_id=user.id
    ):
        raise ValueError(f"{persona.handle} is an account somebody signs in to")
    await save_prefs(session, user.id, _SILENT)
    if persona.avatar_seed:
        await user_avatars.store_avatar(
            session,
            user=user,
            avatar=user_avatars.validate_avatar(_picture(persona.avatar_seed, 256)),
        )
    return user


def _picture(seed: str, size: int) -> bytes:
    """A square PNG in two colours drawn from ``seed``."""
    from PIL import Image, ImageOps

    digest = hashlib.sha256(seed.encode()).digest()
    gradient = Image.linear_gradient("L").resize((size, size))
    image = ImageOps.colorize(
        gradient, black=tuple(digest[:3]), white=tuple(digest[3:6])
    )
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


async def _community(
    session: AsyncSession,
    spec: Community,
    personas: dict[str, User],
    names: dict[str, str],
    base: Path,
    rebuild: bool,
) -> Guild:
    """The community ``spec`` describes, made when it is missing, was never
    seeded in full or is being rebuilt, with its roster and listing brought up
    to date. One the platform holds content in is left as it is."""
    creator = personas[spec.creator]
    guild = (
        await session.exec(
            select(Guild).where(
                Guild.created_by == creator.id,
                Guild.status != CommunityStatus.deleted.value,
            )
        )
    ).first()
    seed = await _seed_result(guild.id) if guild is not None else None
    if guild is not None and (seed is None or (rebuild and not spec.keep)):
        try:
            await guild_purge.destroy_now(session, guild)
        except HoldsInForce:
            logger.warning("community %s is held; left as it is", guild.id)
        else:
            guild = None
    created = guild is None
    if guild is None:
        guild = await guilds_service.provision_new_guild(
            session, name=spec.name, creator=creator
        )
        await guilds_service.welcome_new_guild(guild.id, owner_user_id=creator.id)
        if spec.icon:
            data = (base / spec.icon).read_bytes()
            await guild_images.set_images(
                session,
                guild_id=guild.id,
                renditions={
                    GuildImageVariant.icon: validate_image(
                        IMAGE_SPECS[GuildImageVariant.icon], data
                    )
                },
            )

    seated = [spec.creator, *spec.members]
    for handle in spec.members:
        await guilds_service.ensure_membership(
            session,
            guild_id=guild.id,
            user_id=personas[handle].id,
            actor_user_id=creator.id,
        )
    for handle in seated:
        await guilds_service.set_member_display_name(
            session,
            guild_id=guild.id,
            user_id=personas[handle].id,
            display_name=names[handle],
        )
    if spec.directory is not None:
        await _list(session, guild, spec.directory)
    else:
        guild.is_community = False
        session.add(guild)
    await session.commit()

    if created:
        seed = await _import(
            guild.id,
            creator,
            base / spec.bundle,
            {handle: personas[handle].id for handle in seated},
        )
    if spec.directory is not None and seed is not None:
        imported = [initiative["initiative_id"] for initiative in seed["initiatives"]]
        async with cohorts.system_session(guild.id) as guild_session:
            await set_rls_context(guild_session, SystemGuild(guild.id))
            await guild_session.exec(
                update(Initiative)
                .where(col(Initiative.id).in_(imported))
                .values(join_policy=spec.directory.join_policy.value)
            )
            await guild_session.commit()
    return guild


def _failed_entries(result: dict[str, Any]) -> list[str]:
    """The entries a backup import's ``result`` reports as not applied."""
    return [
        f"{entry['path']} ({entry.get('error')})"
        for entry in result.get("entries", [])
        if entry["status"] == "failed"
    ]


async def _seed_result(guild_id: int) -> dict[str, Any] | None:
    """The result of the community's seed import, which is the one with an
    ``anchor``, when it finished with every entry applied."""
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id, read_only=True))
        results = await session.exec(
            select(ImportJob.result).where(
                ImportJob.status == ImportJobStatus.done,
                col(ImportJob.params).has_key("anchor"),
            )
        )
        for result in results:
            if result is not None and not _failed_entries(result):
                return result
    return None


async def _list(session: AsyncSession, guild: Guild, card: DirectoryCard) -> None:
    """Put the community in the directory with its card, and the directory on."""
    row = await app_settings_service.get_app_settings(session)
    row.community_directory_enabled = True
    session.add(row)
    guild.is_community = True
    guild.categories = guilds_service.normalize_categories(
        [category.value for category in card.categories]
    )
    # A listing declares its audience, and the demo's are all ages.
    guild.has_adult_content = False
    session.add(guild)
    await session.flush()


async def _import(
    guild_id: int, creator: User, bundle: Path, members: dict[str, int]
) -> dict[str, Any]:
    """Import ``bundle`` into the community as an ordinary backup job run as
    ``creator``, its dates moved from the bundle's export to now, and its
    people placed where a handle names a member exactly, as the import's own
    review would suggest. Returns the job's result once every entry applied.

    The job runs here unless a server's import worker claims it first, and is
    waited for either way."""
    plan = await asyncio.to_thread(
        backup_service.plan_backup,
        bundle,
        existing_initiative_names=set(),
        member_ids_by_handle=members,
    )
    payload_ref = await asyncio.to_thread(
        import_engine.stage_payload_file, guild_id, bundle, suffix="zip"
    )
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        job = ImportJob(
            created_by=creator.id,
            source="backup",
            params={
                "anchor": plan.exported_at,
                "people_map": {
                    person.handle: person.suggested_user_id
                    for person in plan.people
                    if person.suggested_user_id is not None
                },
            },
            payload_ref=payload_ref,
            plan=plan.model_dump(mode="json"),
            status=ImportJobStatus.queued,
        )
        session.add(job)
        await session.commit()
        job_id = job.id
    deadline = asyncio.get_running_loop().time() + IMPORT_TIMEOUT_SECONDS
    while True:
        async with cohorts.system_session(guild_id) as session:
            await set_rls_context(session, SystemGuild(guild_id))
            job = await session.get(ImportJob, job_id)
            if job is None or job.status not in (
                ImportJobStatus.queued,
                ImportJobStatus.running,
            ):
                break
            task = await import_worker.jobs.claim(session, guild_id)
        if task is not None:
            await task
        elif asyncio.get_running_loop().time() > deadline:
            raise TimeoutError(
                f"importing {bundle.name} into community {guild_id} did not "
                f"finish in {IMPORT_TIMEOUT_SECONDS}s"
            )
        else:
            await asyncio.sleep(IMPORT_POLL_SECONDS)
    if job is None or job.status != ImportJobStatus.done:
        raise RuntimeError(
            f"importing {bundle.name} into community {guild_id} ended "
            f"{job.status if job else 'missing'}: {job.error if job else ''}"
        )
    failed = _failed_entries(job.result or {})
    if failed:
        raise RuntimeError(
            f"importing {bundle.name} into community {guild_id} left out "
            f"{', '.join(failed)}"
        )
    return job.result or {}


async def _fixed_account(
    session: AsyncSession,
    account: FixedAccount,
    sign_in: SignIn,
    communities: dict[str, int],
) -> None:
    """The fixed account with this sign-in, at its tier, seated in its fixed
    communities with its roles. An account whose password no longer matches
    the secret gets the secret's, and signs in again."""
    password = sign_in.password.get_secret_value()
    user = await _by_handle(session, account.handle)
    if user is None:
        await validate_new_password(password)
        name, number = split_handle(account.handle)
        user = User(
            username=name,
            discriminator=number,
            username_chosen=True,
            hashed_password=get_password_hash(password),
            password_set_at=datetime.now(timezone.utc),
            role=account.tier,
        )
        session.add(user)
        await session.flush()
        addresses.record_address(
            session,
            user_id=user.id,
            email=str(sign_in.address),
            source=addresses.SOURCE_SIGNUP,
            verified=True,
        )
        await dm_settings_service.seed_for_new_account(session, user_id=user.id)
        await audit_service.record(
            session,
            event_type=AuditEventType.USER_CREATED,
            actor_user_id=None,
            target_user_id=user.id,
            detail={"via": "demo"},
        )
    else:
        await _sign_in_address(session, user, str(sign_in.address))
        if not verify_password(password, user.hashed_password):
            await validate_new_password(password)
            user.hashed_password = get_password_hash(password)
            user.password_set_at = datetime.now(timezone.utc)
            await sign_in_locks.lift(session, user.id)
            await user_tokens.revoke_user_sessions(session, user=user)
    user.role = account.tier
    session.add(user)
    await session.flush()
    for key, role in account.communities.items():
        await guilds_service.ensure_membership(
            session,
            guild_id=communities[key],
            user_id=user.id,
            role=role,
            force_role=True,
        )


async def _sign_in_address(session: AsyncSession, user: User, address: str) -> None:
    """Leave ``user`` signing in with ``address`` alone: proved, primary, and
    its other addresses removed."""
    row = await addresses.ensure_address(
        session,
        user_id=user.id,
        email=address,
        source=addresses.SOURCE_ADDED,
        verified=True,
    )
    if row is None:
        handle = usernames.format_handle(user.username, user.discriminator)
        raise ValueError(f"the address for {handle} belongs to another account")
    assert row.id is not None
    await addresses.set_primary_for_user(session, user_id=user.id, address_id=row.id)
    await session.flush()
    for other in await addresses.list_for_user(session, user_id=user.id):
        if other.id != row.id:
            await addresses.remove_for_user(
                session, user_id=user.id, address_id=other.id
            )

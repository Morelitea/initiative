from datetime import datetime, timezone
import asyncio
import logging
from contextlib import suppress

import asyncpg
from sqlalchemy import delete as sql_delete
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.security import app_platform_signing_enabled, get_password_hash
from app.core.version import __version__, get_version
from app.db.schema_provisioning import (
    deprovision_guild,
    ensure_shared_table_grants,
    ensure_system_engine_bypassrls,
    verify_effective_shared_grants,
    verify_engine_identities,
)
from app.db.session import (
    SystemSessionLocal,
    migration_chain,
    migration_lock,
    run_migrations,
)
from app.models.platform.guild import Guild
from app.models.platform.user import User, UserRole
from app.services import audit as audit_service
from app.services.auth import addresses
from app.services.platform import app_settings as app_settings_service
from app.services.platform import dm_settings as dm_settings_service
from app.services.platform import guilds as guilds_service
from app.core import usernames

logger = logging.getLogger(__name__)

# The squashed baseline (v0.53.5 snapshot). Databases stamped at an older
# revision must go through a v0.53.x release first — see check_pre_baseline_db.
BASELINE_REVISION = "20260626_0125"


async def init_owner() -> None:
    if not (settings.FIRST_OWNER_EMAIL and settings.FIRST_OWNER_PASSWORD):
        return

    async with SystemSessionLocal() as session:
        existing = await addresses.find_user_by_address(
            session, settings.FIRST_OWNER_EMAIL
        )
        if existing is not None:
            return  # already seeded

        # Create the first superuser (the platform owner)...
        user = User(
            full_name=settings.FIRST_OWNER_FULL_NAME,
            username=usernames.from_full_name(settings.FIRST_OWNER_FULL_NAME)
            or usernames.random_name(),
            discriminator=usernames.random_discriminator(),
            hashed_password=get_password_hash(settings.FIRST_OWNER_PASSWORD),
            password_set_at=datetime.now(timezone.utc),
            role=UserRole.owner,
        )
        session.add(user)
        await session.flush()
        addresses.record_address(
            session,
            user_id=user.id,
            email=settings.FIRST_OWNER_EMAIL,
            source=addresses.SOURCE_SIGNUP,
            verified=True,
        )
        await dm_settings_service.seed_for_new_account(session, user_id=user.id)
        # Nobody signed in made this account, so it carries no actor.
        await audit_service.record(
            session,
            event_type=AuditEventType.USER_CREATED,
            actor_user_id=None,
            target_user_id=user.id,
            detail={"via": "bootstrap"},
        )
        await session.commit()

        # ...and their guild the same way the API does: create the shared rows,
        # commit, then provision the schema and seed its content (settings +
        # default initiative). No bespoke seeding path — it's a real guild.
        guild = await guilds_service.create_guild(
            session, name="Primary Community", creator=user
        )
        await session.commit()
        # Capture ids before the seed: the rollback in the failure path expires the
        # ORM objects, so reading guild.id / user.id afterwards would reload.
        guild_id = guild.id
        user_id = user.id
        try:
            await guilds_service.seed_guild_content(
                session, guild_id=guild_id, owner=user
            )
            await session.commit()
        except Exception:
            # Undo the whole first-boot seed so a restart re-initializes cleanly.
            # Otherwise the committed user makes init_owner short-circuit on
            # every restart, stranding the primary guild without a schema. Mirrors
            # the API/registration cleanup. Roll back FIRST (an aborted session
            # would fault the cleanup queries, and it reverts the seed's SET ROLE
            # so deprovision can DROP the role); this is a system-engine
            # session, so the bulk DELETEs aren't RLS-filtered.
            await session.rollback()
            with suppress(Exception):
                await deprovision_guild(guild_id)
            await session.exec(sql_delete(Guild).where(Guild.id == guild_id))
            await session.exec(sql_delete(User).where(User.id == user_id))
            await session.commit()
            raise


def _is_dated_revision(revision: str) -> bool:
    """True for this repo's YYYYMMDD_NNNN revision ids (explicit check)."""
    return (
        len(revision) == 13
        and revision[8] == "_"
        and revision[:8].isdigit()
        and revision[9:].isdigit()
    )


def _require_image_knows(stamped: list[str]) -> None:
    """Exit with instructions if this image lacks a revision the database is
    stamped at — the mirror of the pre-baseline case below, and the same
    cryptic alembic failure ("can't locate revision") if nothing catches it.

    A database gets ahead of its image whenever the container comes back on an
    older one than last upgraded it: a pull that did not replace the tag it was
    meant to, a deliberate roll-back, or a half-finished rebuild whose leftover
    container is the one still being started.
    """
    revisions, head = migration_chain()
    if not revisions:
        return  # Chain unreadable; let alembic surface whatever is wrong with it
    ahead = [revision for revision in stamped if revision not in revisions]
    if not ahead:
        return

    raise SystemExit(
        f"\n{'=' * 70}\n"
        f"This image is older than the database.\n\n"
        f"  database stamped at:   {', '.join(sorted(ahead))}\n"
        f"  newest migration here: {head or '?'}\n"
        f"  this image:            {get_version()}\n\n"
        f"Migrations only run forward, so this version cannot serve this\n"
        f"database. Start the release that last upgraded it — or any newer\n"
        f"one — and the app comes up where it left off.\n\n"
        f"If it keeps coming back on the old image after you pull a new one,\n"
        f"look for a container the upgrade left behind and started instead:\n"
        f"compose renames the one it is replacing to <12 hex characters>_<name>\n"
        f"and leaves it there when the rebuild does not finish. Remove it and\n"
        f"bring the project up again.\n\n"
        f"Running this version deliberately means restoring the database\n"
        f"backup taken before that upgrade; there is no downgrade path.\n"
        f"{'=' * 70}"
    )


async def check_pre_baseline_db() -> None:
    """Exit with upgrade instructions if the database predates the v0.53.5
    baseline squash — its revision id no longer exists in this chain, so
    alembic would fail with a cryptic "can't locate revision" otherwise."""
    url = make_url(settings.DATABASE_URL)

    try:
        conn = await asyncpg.connect(
            user=url.username,
            password=url.password,
            database=url.database,
            host=url.host,
            port=url.port or 5432,
        )
    except Exception:
        return  # Can't connect; let alembic surface the error

    try:
        has_table = await conn.fetchval(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables "
            "  WHERE table_schema = 'public' AND table_name = 'alembic_version'"
            ")"
        )
        if not has_table:
            return  # Fresh database

        # Every row, not just one: a database left on a branch carries a stamp
        # per head, and a single image has to be able to run all of them.
        stamped = [
            row["version_num"]
            for row in await conn.fetch("SELECT version_num FROM alembic_version")
        ]
        if not stamped:
            return  # Fresh database (empty alembic_version)
        revision = stamped[0]

        if revision == BASELINE_REVISION:
            # Stamped at the baseline, but roles may be missing on a database
            # that never actually ran it (e.g. restored without roles). Clear
            # the stamp so the (idempotent) baseline migration re-runs — it
            # recreates roles, RLS policies, and grants as needed.
            has_roles = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user')"
            )
            if not has_roles:
                print(
                    "Baseline stamped but database roles missing. Re-running baseline migration..."
                )
                await conn.execute("DELETE FROM alembic_version")
            return

        if _is_dated_revision(revision) and revision > BASELINE_REVISION:
            # Post-squash, so alembic can run it — as long as this image is the
            # one that has it. Say so when it isn't, for the same reason the
            # pre-baseline message below exists.
            _require_image_knows(stamped)
            return  # normal upgrade

        raise SystemExit(
            f"\n{'=' * 70}\n"
            f"Pre-v0.53.2 database detected (revision: {revision}).\n\n"
            f"This version's migration history starts at the v0.53.5 baseline;\n"
            f"older databases must step through a v0.53.x release first:\n\n"
            f"  1. Deploy any v0.53.x image (e.g. morelitea/initiative:0.53.5)\n"
            f"     and let it boot once — its migrations and startup conversion\n"
            f"     bring the database to the baseline state.\n"
            f"  2. Then deploy this version and restart.\n\n"
            f"Step 1 is mandatory, not advisory: it is what copies guild content\n"
            f"into the per-guild schemas. This version DROPS the old copies in\n"
            f"the public schema (migration 20260811_0163) and cannot be rolled\n"
            f"back, so anything not converted by then is lost.\n\n"
            f"(Installs older than v0.30.0 are no longer supported for\n"
            f"in-place upgrade — restore into a fresh install instead.)\n"
            f"{'=' * 70}"
        )
    finally:
        await conn.close()


async def migrate_database() -> None:
    """Bring the database to head, one instance at a time.

    The pre-baseline check reads — and on one path clears — the alembic stamp
    that the upgrade then acts on, so the two share a lock rather than taking
    one each.
    """
    async with migration_lock():
        await check_pre_baseline_db()
        await run_migrations()


async def prepare_database() -> None:
    """Bring the database to what this release serves, and seed it.

    Every step is idempotent. The server's startup runs this before it serves
    anything, and ``python -m app.db.init_db`` runs it on its own.
    """
    # The prerequisites the app's own logins cannot create for themselves: the
    # logins, and the guild-search match operator. Applied from
    # DATABASE_URL_BOOTSTRAP when set, verified otherwise, before anything
    # connects as those logins.
    from app.db.bootstrap import ensure_database_bootstrap

    await ensure_database_bootstrap()
    # A deployment that removed DATABASE_URL_BOOTSTRAP (or never set it) has no
    # path that moves object ownership to the provisioning login, and every
    # boot heal below that rewrites a function or a community schema needs it.
    from app.db.bootstrap import warn_if_ownership_was_never_handed_over

    await warn_if_ownership_was_never_handed_over()
    # Before any DDL runs: check the connection is the least-privilege
    # provisioning login. Ahead of the migrations rather than beside the other
    # heals below, so a misconfigured connection is caught before it reshapes
    # the schema.
    from app.db.schema_provisioning import reject_privileged_database_url

    await reject_privileged_database_url()
    await migrate_database()
    # The functions every guild policy defers to, from the module that owns
    # them (app.db.authorization). Before the back-fill below, so a schema
    # rendered in this same boot finds each one its policies name.
    from app.db.authorization import ensure_authorization_functions
    from app.db.public_rls import ensure_public_rls

    await ensure_authorization_functions()
    # Whether plans are billing's, which the plan and status triggers read.
    from app.db.billing_managed import ensure_billing_managed

    await ensure_billing_managed()
    # The shared tables' row security, from its registry (app.db.public_rls),
    # the way the guild schemas get theirs from INITIATIVE_PATHS. Stamped on
    # the public schema, so a boot with nothing changed does nothing.
    await ensure_public_rls()
    # Re-run the idempotent per-guild provisioning for every guild so any
    # table/column/index/grant the live guild_template gained since a guild was
    # provisioned is back-filled, and any guild left without a schema (e.g. a
    # crash mid-provision) is healed. One broken guild is logged and skipped;
    # guilds stamped with the current artifact version are skipped entirely.
    from app.db.schema_provisioning import (
        backfill_guild_schemas,
        backfill_guild_search,
        warn_if_search_operator_missing,
    )

    # Before the heals: name the three DB logins in the log, and warn loudly
    # on wiring that collapses the role separation (app/admin URLs sharing a
    # login, a privileged app login) — so the operator sees which login each
    # repair below will act on.
    await verify_engine_identities()
    # Before anything touches the system engine: confirm its login holds
    # BYPASSRLS, which a restored database or a hand-created role can lack and
    # the seeding below needs (issue #835).
    await ensure_system_engine_bypassrls()
    # One gate deeper: a restored/recreated role can bypass RLS yet be missing
    # the per-table GRANTs (cluster state a stamped DB never re-applies), so
    # seeding dies on "permission denied for table guilds" instead. Re-assert
    # the audited shared-table grants from the registry (issue #835 follow-up).
    await ensure_shared_table_grants()
    # The heal above targets the canonical role names; verify the CONNECTED
    # logins actually hold the audited privileges, stopping with the exact
    # GRANTs when a deployment's URLs connect as other logins.
    await verify_effective_shared_grants()
    await warn_if_search_operator_missing()
    backfill = await backfill_guild_schemas()
    if backfill.failed:
        # WARNING so partial failure survives INFO-filtered logs (per-guild
        # tracebacks were already logged inside the back-fill).
        logger.warning(
            "guild schema back-fill: %d provisioned, %d FAILED (of %d) — guilds %s",
            backfill.provisioned,
            backfill.failed,
            backfill.total,
            backfill.failed_guild_ids,
        )
    else:
        logger.info(
            "guild schema back-fill: %d provisioned, %d up-to-date (of %d)",
            backfill.provisioned,
            backfill.skipped,
            backfill.total,
        )
    # Every schema the back-fill reached now binds its own copies of the
    # guild functions, so the copies the migrations left in public can go.
    # Postgres refuses each one that a schema still binds (a guild the
    # back-fill skipped); those are logged and tried again next boot.
    from app.db.authorization import ensure_public_copies_dropped

    retired = await ensure_public_copies_dropped()
    if retired.blocked:
        logger.warning(
            "public copies of guild functions still bound, kept for now: %s",
            ", ".join(f"{name} ({count})" for name, count in retired.blocked.items()),
        )
    elif retired.dropped:
        logger.info(
            "public copies of guild functions retired: %s",
            ", ".join(retired.dropped),
        )
    # After the schemas, never before: the sweep writes through functions and
    # into a table whose shape the pass above is what brings up to date.
    await backfill_guild_search()
    # Rotate SECRET_KEY-derived data (encrypted fields + email_hash) when
    # PREVIOUS_SECRET_KEY names a prior key. Runs after guild schemas exist and
    # before traffic is served, so a packaged deploy rotates itself on boot.
    # Idempotent — a no-op once rotated (then unset PREVIOUS_SECRET_KEY).
    from app.db.secret_key_rotation import maybe_rotate_at_startup

    await maybe_rotate_at_startup()
    # Note what this deployment is running, and what it was running before.
    # An announcement meant for people upgrading past some release has no way
    # to know that from a publication date; this pair is how it finds out.
    try:
        async with SystemSessionLocal() as version_session:
            previous = await app_settings_service.record_running_version(
                version_session, version=__version__
            )
        if previous and previous != __version__:
            logger.info("upgraded from %s to %s", previous, __version__)
    except Exception:  # pragma: no cover - never hold up boot for bookkeeping
        logger.exception("could not record the running version")
    # First-owner bootstrap (FIRST_OWNER_EMAIL / FIRST_OWNER_PASSWORD): create
    # the owner and their guild on first boot so a self-hosted instance is
    # usable straight from `docker run` with two env vars.
    # No-op when the env vars are unset (the /auth/bootstrap first-user
    # flow still applies) or the owner already exists.)
    try:
        await init_owner()
    except IntegrityError:
        # Unique violation on the owner's address: a concurrent replica won
        # the first-boot race and created the owner between our existence check
        # and commit.
        logger.info("first-owner bootstrap: created by a concurrent replica")
    async with SystemSessionLocal() as session:
        await app_settings_service.ensure_defaults(session)
    # First-boot seed: create the platform OIDC provider row from OIDC_* env
    # values (issuer + client id required; no-op once the row exists — after
    # that the settings UI owns it). Runs on the system engine because the
    # provider registry carries no request-path grants.
    from app.services.auth.platform_provider import seed_platform_provider_from_env

    try:
        async with SystemSessionLocal() as seed_session:
            await seed_platform_provider_from_env(seed_session)
    except Exception:
        logger.exception("Platform OIDC env seed failed; configure via settings UI")

    # The marketplace listings this build ships with. Idempotent upsert on the
    # system engine — the catalog has no request-path writer — so every install
    # has a working marketplace with no network and no configuration.
    from app.services.marketplace.builtin import seed_builtin_listings

    try:
        async with SystemSessionLocal() as catalog_session:
            seeded = await seed_builtin_listings(catalog_session)
            await catalog_session.commit()
        logger.info("marketplace: %d built-in listing(s) seeded", seeded)
    except Exception:
        # A catalog that failed to seed costs the marketplace, not the boot:
        # every already-installed dashboard keeps its own pinned definition.
        logger.exception("marketplace: built-in listing seed failed")

    # Listings the operator publishes themselves, from the directory
    # MARKETPLACE_EXTRA_CATALOG_DIR names. Same writer, same validation as the
    # built-ins; a manifest that has been removed retires its listing. With the
    # setting unset nothing is read and nothing is said.
    from app.services.marketplace.operator_catalog import (
        operator_catalog_dir,
        scan_operator_catalog,
    )

    if operator_catalog_dir() is not None:
        try:
            async with SystemSessionLocal() as operator_catalog_session:
                scan = await scan_operator_catalog(operator_catalog_session)
                await operator_catalog_session.commit()
            logger.info(
                "marketplace: operator catalog — %d published, %d withdrawn, "
                "%d skipped",
                scan.published,
                scan.withdrawn,
                scan.skipped,
            )
        except Exception:
            logger.exception("marketplace: operator catalog scan failed")
    # App services the deployment declares in a mounted file (APP_SERVICES_CONFIG).
    # Database-only: an app's container may boot after this one, so the handshake
    # is a separate step and a declared registration lands unverified rather than
    # holding up startup. No-op when the setting is unset.
    if settings.APP_SERVICES_CONFIG:
        if not app_platform_signing_enabled():
            # Registrations reconcile fine, but verifying one (and later minting
            # its context tokens) needs the platform's own keypair.
            logger.warning(
                "APP_SERVICES_CONFIG is set but APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM "
                "is not; app service verification will fail closed until a signing "
                "key is configured."
            )
        try:
            from app.services.marketplace import registrations as app_registrations

            async with SystemSessionLocal() as app_service_session:
                reconciled = await app_registrations.reconcile_from_config(
                    app_service_session
                )
            logger.info(
                "app services: %d created, %d updated, %d unchanged, %d skipped",
                reconciled.created,
                reconciled.updated,
                reconciled.unchanged,
                reconciled.skipped,
            )
        except Exception:
            # A registration that failed to reconcile costs that app, not the
            # boot; already-stored registrations keep working unchanged.
            logger.exception("app services: reconciliation from config failed")

    # Apps the deployment provides to every guild (§7.7). New guilds get theirs
    # at creation; this is how the flag reaches guilds that predate it, on the
    # same sweep pattern that reprovisions stale schemas. Returns immediately
    # when nothing is marked mandatory, which is every install that has not
    # asked for this.
    try:
        from app.services.tenant import mandatory_apps as mandatory_apps_service

        backfilled = await mandatory_apps_service.backfill_mandatory_apps()
        if backfilled.installed or backfilled.failed:
            logger.info(
                "mandatory apps: %d installed across %d guild(s), %d failed",
                backfilled.installed,
                backfilled.guilds,
                backfilled.failed,
            )
    except Exception:
        # A guild missing a mandatory app is a gap the next boot closes; it is
        # not a reason to refuse to start.
        logger.exception("mandatory apps: backfill failed")


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(prepare_database())

---
icon: lucide/save
---

# Backups & updates

Because Initiative is self-hosted, two ongoing jobs are yours: keeping a safety net (backups) and staying current (updates). Neither is hard, but both matter.

## Backups

There are exactly **two** things to back up:

1. **The database** — every project, task, document, comment, and setting.
2. **The uploads** — the files people have attached (mounted at `/app/uploads`, unless you use [object storage](object-storage.md)).

Back up both **together and regularly**, and store copies somewhere separate from the server itself.

### Backing up the database

A standard PostgreSQL dump works well. For the default Docker setup, something like:

```bash
# Adjust the service/container name and credentials to your compose file
docker compose exec -T db pg_dump -U postgres initiative > initiative-backup.sql
```

Automate this on a schedule (a nightly cron job, for example), keep several days of history, and **test a restore occasionally** — a backup you've never restored is a guess, not a safety net.

### Backing up uploads

Copy the uploads volume's contents to your backup location. If you've moved uploads to [S3-compatible storage](object-storage.md), back up the bucket instead (many object stores have their own snapshot/replication features).

!!! warning "Keep your SECRET_KEY with your backups — safely"
    Some stored data is encrypted using `SECRET_KEY`. A database restore won't be able to decrypt those fields without the same key. Record your `SECRET_KEY` somewhere secure and separate, so a restore is actually usable.

## Updating

Initiative ships as versioned Docker images. To update:

```bash
docker compose pull        # fetch the newer image
docker compose up -d       # recreate the container
```

Database **migrations run automatically** at startup, so there's usually nothing else to do. Still, **back up first** — it's the cheapest insurance there is.

### Choosing a version

- **`latest`** tracks the newest release.
- **Pin a version** (e.g. `morelitea/initiative:0.53`) if you prefer to update deliberately and read the changelog first.

Initiative follows semantic versioning, and the **changelog** lists what changed in each release. Reviewing it before a jump is wise, especially across minor versions.

### Knowing what's running

The running version is available at `<your-server>/api/v1/version`, and it's shown in the app's sidebar footer. The web app also notices when the server has been updated and prompts people to refresh.

### The mobile app

The mobile apps update their web portion **over the air** — when you update the server, installed apps pick up the matching web bundle automatically, with no app-store update needed. Occasionally a release changes the *native* part of the app and requires a store/APK update; Initiative tracks this with the `MIN_NATIVE_VERSION` marker and the app will prompt people to update when it's genuinely required. For day-to-day server updates, you don't need to think about it.

## A healthy maintenance routine

- [ ] **Nightly database backup**, with a few days retained.
- [ ] **Regular uploads backup** (or object-store snapshots).
- [ ] **`SECRET_KEY` stored securely** alongside your backup process.
- [ ] **Update promptly**, especially for security fixes — read the changelog, back up, then `pull` and `up`.
- [ ] **Occasionally test a restore** into a throwaway environment.

## Related

- [Installation](installation.md) — the initial setup and volumes.
- [Data & compliance](../security/data-and-compliance.md) — your responsibilities as the data owner.
- [Object storage](object-storage.md) — if uploads live in S3.

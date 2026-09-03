---
icon: lucide/save
---

# Backups & updates

Two ongoing jobs come with self-hosting: keeping a safety net, and staying current. Neither is hard. Both matter more than they feel like they do until the day they don't.

## Backups

There are exactly **two** things to back up:

1. **The database** — every project, task, document, comment and setting.
2. **The uploads** — the files people attached, at `/app/uploads` unless you've moved them to [object storage](object-storage.md).

Back up both **together and regularly**, and keep copies somewhere that isn't the server.

### The database

A standard PostgreSQL dump does the job:

```bash
# Adjust the service name and credentials to match your compose file
docker compose exec -T db pg_dump -U postgres initiative > initiative-backup.sql
```

Automate it (a nightly cron job), keep several days of history, and **test a restore occasionally**. A backup you've never restored is a guess, not a safety net.

### Uploads

Copy the uploads volume to your backup location. If uploads live in [S3-compatible storage](object-storage.md), back up the bucket instead — most object stores have their own snapshot or replication features.

!!! warning "Keep your SECRET_KEY with your backups — safely"
    Some stored data is encrypted with `SECRET_KEY`. A database restore can't decrypt those fields without the same key. Record it somewhere secure and separate, or your backup is only most of a backup.

## Updating

Initiative ships as versioned Docker images:

```bash
docker compose pull        # fetch the newer image
docker compose up -d       # recreate the container
```

Database **migrations run automatically** at startup, so there's usually nothing else to do. Back up first anyway — cheapest insurance going.

### Choosing a version

- **`latest`** tracks the newest release.
- **Pin one** (`morelitea/initiative:0.65`) if you'd rather update deliberately and read the changelog first.

Initiative follows semantic versioning, and the changelog lists what changed in each release. Worth a skim before a jump, especially across minor versions.

### Knowing what's running

The running version is at `<your-server>/api/v1/version`, and in the app's sidebar footer. The web app also notices when the server's been updated and prompts people to refresh.

### The mobile app

The mobile apps update their web portion **over the air** — update the server and installed apps pick up the matching bundle, no app-store update needed. Occasionally a release changes the *native* part and needs a store or APK update; Initiative tracks that with the `MIN_NATIVE_VERSION` marker and the app prompts people when it's genuinely required. For everyday server updates, you don't need to think about it.

## A healthy routine

- [ ] **Nightly database backup**, a few days retained.
- [ ] **Regular uploads backup** (or object-store snapshots).
- [ ] **`SECRET_KEY` stored securely** alongside the backup process.
- [ ] **Update promptly**, especially for security fixes — read the changelog, back up, pull, up.
- [ ] **Occasionally restore into a throwaway environment**, to prove it works.

## Related

- [Installation](installation.md) — initial setup and volumes.
- [Data & compliance](../security/data-and-compliance.md) — your responsibilities as the data owner.
- [Object storage](object-storage.md) — if uploads live in S3.

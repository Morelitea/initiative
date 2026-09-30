---
icon: lucide/save
---

# Backups & updates

Two ongoing jobs come with self-hosting: keeping a safety net, and staying current.

Neither is hard. Both matter far more than they feel like they do, right up until the one day they matter enormously.

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

Automate it (a nightly cron job will do), keep several days of history, and **actually test a restore occasionally**.

A backup you have never restored is not a safety net. It's a hypothesis.

### Uploads

Copy the uploads volume to your backup location. If uploads live in [S3-compatible storage](object-storage.md), back up the bucket instead — most object stores have their own snapshot or replication features.

!!! warning "Keep your SECRET_KEY with your backups — safely"
    Some stored data is encrypted with `SECRET_KEY`, and a database restore cannot decrypt those fields without the same key.

    Record it somewhere secure and separate from the backup itself. Otherwise what you have is not quite a backup, and you'll find that out at the worst possible moment.

## Updating

Initiative ships as versioned Docker images:

```bash
docker compose pull        # fetch the newer image
docker compose up -d       # recreate the container
```

Database **migrations run automatically** at startup, so there's usually nothing else to do at all.

Back up first anyway. It's the cheapest insurance available to you and it takes one command.

### Choosing a version

- **`latest`** tracks the newest release.
- **`stable`** tracks a release we have promoted after it spent a few days out in the world without a reported regression. See [Docker images](installation.md#docker-images).
- **Pin one** (`morelitea/initiative:0.65`) if you'd rather update deliberately and read the changelog first.

Initiative follows semantic versioning, and the changelog lists what changed in each release. Worth a skim before a jump, especially across minor versions.

### Knowing what's running

The running version is at `<your-server>/api/v1/version`, and in the app's sidebar footer. The web app also notices when the server's been updated and prompts people to refresh.

### If it won't start

Rare, and recoverable. First, read the end of the log:

```bash
docker compose logs initiative | tail -n 40
```

If the last thing it says is a message framed in `=` signs telling you what to do (the image being older than the database, say), that message is the whole answer. Do what it says.

Otherwise, find the report it wrote just before the traceback:

```bash
docker compose logs initiative | grep -A 16 "Initiative could not start"
```

It lists the version, how the database is set up, where the migrations stopped, and the error. The passwords and keys the server is configured with are taken out, but give it a read before you post it. Then paste it into [an issue](https://github.com/Morelitea/initiative/issues).

The fix is almost always a newer release, which picks up from exactly where this one stopped. Going back to the older version means restoring the backup you took before updating. You took one. It was one command.

### The mobile app

The mobile apps update their web portion **over the air** — update the server and installed apps pick up the matching bundle, no app-store update needed. Occasionally a release changes the *native* part and needs a store or APK update; Initiative tracks that with the `MIN_NATIVE_VERSION` marker and the app prompts people when it's genuinely required. For everyday server updates, you don't need to think about it.

## A healthy routine

- [ ] **Nightly database backup**, a few days retained.
- [ ] **Regular uploads backup** (or object-store snapshots).
- [ ] **`SECRET_KEY` stored securely** alongside the backup process.
- [ ] **Update promptly**, especially for security fixes — read the changelog, back up, pull, up.
- [ ] **Occasionally restore into a throwaway environment**, to prove the whole thing actually works.

## Related

- [Installation](installation.md) — initial setup and volumes.
- [Data & compliance](../security/data-and-compliance.md) — your responsibilities as the data owner.
- [Object storage](object-storage.md) — if uploads live in S3.

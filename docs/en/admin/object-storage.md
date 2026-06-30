---
icon: lucide/hard-drive
---

# File & object storage

Initiative stores uploaded files — image attachments, document files, and their versions — through a pluggable storage backend. By default everything lives on local disk, which is perfect for most deployments. If you'd rather keep uploads in S3-compatible object storage, that's a configuration change with no code change.

## Choosing a backend

The `STORAGE_BACKEND` environment variable selects where uploads live:

| `STORAGE_BACKEND` | Where uploads go |
|---|---|
| `local` *(default)* | The filesystem, under `UPLOADS_DIR`. |
| `s3` | Any S3-compatible object store you point it at. |

Nothing object-store-related runs unless you opt in with `STORAGE_BACKEND=s3`. Initiative never runs or bundles an object store of its own — you bring your own (for example, a [Garage](https://garagehq.deuxfleurs.fr/) node, MinIO, or a cloud provider's S3).

## How files are organized

Both backends namespace files **per guild**, mirroring the database's per-guild isolation:

- **Local:** `UPLOADS_DIR/guild_<id>/<file>`.
- **Object storage:** objects under a `guild_<id>/` key prefix.

In both cases the download URL stays the same (`/uploads/{guild_id}/{filename}`), and **every download is authorized on each request** — files are streamed back through the app only after the same guild-membership and access checks as everything else. Storage location never bypasses access control. See [How your data is kept separate](../security/how-your-data-is-kept-separate.md).

## Connecting an S3-compatible store

You'll need, from your store: an **S3 API endpoint**, the **region** it was configured with, an existing **bucket**, and an **access key** (id + secret) with read/write on that bucket. Then set:

```bash
STORAGE_BACKEND=s3
S3_BUCKET=initiative                  # an existing bucket on your store
S3_ENDPOINT_URL=http://garage:3900    # your store's S3 API endpoint
S3_REGION=garage                      # must match the store's configured region
S3_ACCESS_KEY_ID=GK...
S3_SECRET_ACCESS_KEY=...
S3_USE_PATH_STYLE=true                # true for Garage and most non-AWS stores
S3_KMS_KEY_ID=                        # optional SSE-KMS key id/ARN; blank otherwise
```

Notes:

- **`S3_USE_PATH_STYLE`** — `true` for Garage and most self-hosted stores (path-style URLs like `https://host/bucket/key`). Set `false` only for a store that uses virtual-host-style addressing.
- **`S3_REGION`** must match the region your store enforces in its request signature.
- **Credentials** — set the access key id/secret, or leave them unset to use the ambient credential chain where your store supports it.
- The **bucket must already exist**; Initiative reads and writes objects but doesn't create the bucket.

## Migrating an existing deployment from local to S3

Switching the backend only changes where **new** uploads go — files already on local disk must be copied across first. The process is designed to be zero-downtime.

**1. Backfill while still on `local`.** With the `S3_*` settings pointed at your store but `STORAGE_BACKEND` still `local`, copy existing files into the bucket:

```bash
python -m app.db.backfill_uploads_to_s3 --dry-run   # preview
python -m app.db.backfill_uploads_to_s3             # copy for real
```

It uploads each file with its recorded content type and verifies it, and it's **idempotent** — safe to re-run until it reports `failed=0`.

**2. Cut over with a fallback window.** Set:

```bash
STORAGE_BACKEND=s3
S3_LOCAL_FALLBACK=true
```

With the fallback on, a read that misses in S3 falls back to local disk, so nothing 404s during the transition. New uploads now go to S3.

**3. Finish.** Once everything serves from S3 and a final backfill reports `failed=0`, set `S3_LOCAL_FALLBACK=false` and retire the local uploads volume.

## Per-guild storage limits

Separately from *where* files are stored, the [owner](platform-roles.md) can cap **how much** each guild may store, from **Settings → Platform → Guilds**. Lowering a limit below a guild's current usage blocks *new* uploads but never deletes existing files.

## Related

- [Configuration](configuration.md) · [Backups & updates](backups-and-updates.md)
- [How your data is kept separate](../security/how-your-data-is-kept-separate.md) — why downloads stay gated.

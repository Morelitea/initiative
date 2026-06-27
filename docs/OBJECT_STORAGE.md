# Object Storage (S3-compatible)

Initiative stores uploaded files (image attachments, document files and their
versions) through a pluggable storage backend selected by the `STORAGE_BACKEND`
environment variable:

| `STORAGE_BACKEND` | Where uploads live |
|---|---|
| `local` (default) | Filesystem under `UPLOADS_DIR` |
| `s3` | Any S3-compatible object store you point it at |

The default is `local` — nothing object-store-related runs unless you opt in by
setting `STORAGE_BACKEND=s3`. Switching is purely configuration; **no code
change is required**, and the app does not run or bundle an object store of its
own — you bring your own.

> Migrating files that already exist on local disk into object storage is a
> separate backfill step (see [Migrating existing files](#migrating-existing-files)).

## How keys are laid out

Both backends namespace a guild's blobs per guild, mirroring the database's
schema-per-guild tenant boundary:

- **Local:** `UPLOADS_DIR/guild_<id>/<uuid>.png`.
- **Object storage:** objects under the `guild_<id>/` key prefix (e.g.
  `guild_7/<uuid>.png`) — exactly what the per-request S3 IAM policy scopes to.

(Installs from before this layout stored local files flat under `UPLOADS_DIR`; a
one-time, self-disabling startup migration relocates them into `guild_<id>/`
dirs. Only file locations change.)

In both cases the public URL stays `/uploads/{guild_id}/{filename}`, and every
download still passes the same authorization checks (guild membership / access
grant + an `uploads` row in that guild's schema). Objects are streamed back
through the app, so authorization is enforced on every request.

## Connect to your Garage (or other S3-compatible) instance

Self-hosters bring their own object store — typically a
[Garage](https://garagehq.deuxfleurs.fr/) node, though any S3-compatible store
works. Initiative only needs to be *pointed at* it; it never runs, bundles, or
provisions the store itself.

From your Garage instance you'll need its **S3 API endpoint**, the **region** it
was configured with (`s3_region`), an existing **bucket**, and an **access key**
(id + secret) granted read/write on that bucket. Then set these on the backend
(see `backend/.env.example`):

```bash
STORAGE_BACKEND=s3
S3_BUCKET=initiative                  # an existing bucket on your store
S3_ENDPOINT_URL=http://garage:3900    # your Garage S3 API endpoint
S3_REGION=garage                      # must match the node's s3_region
S3_ACCESS_KEY_ID=GK...
S3_SECRET_ACCESS_KEY=...
S3_USE_PATH_STYLE=true                 # Garage and most non-AWS stores need this
S3_KMS_KEY_ID=                         # optional SSE-KMS key id/ARN; blank otherwise
```

Notes:

- **`S3_USE_PATH_STYLE`** — `true` for Garage and most self-hosted/non-AWS stores
  (path-style addressing, `https://host/bucket/key`). Set `false` only for a store
  that uses virtual-host-style addressing.
- **`S3_REGION`** — must match the region your store enforces in the SigV4
  signature (for Garage, its configured `s3_region`).
- **Credentials** — set the access key id/secret, or leave them unset to use the
  ambient credential chain where your store supports it.
- The bucket must already exist; the app reads and writes objects but does not
  create the bucket.

See Garage's
[quick-start](https://garagehq.deuxfleurs.fr/documentation/quick-start/) for
standing up a node and creating the bucket + access key.

## Migrating an existing deployment from local to S3

Switching `STORAGE_BACKEND` to `s3` only changes where *new* uploads go — files
already on local disk must be copied into the bucket first. The migration is
designed to be zero-downtime:

**1. Configure S3 and run the backfill (while still on `local`).** With the
`S3_*` settings pointed at your store but `STORAGE_BACKEND` still `local`, copy
existing blobs into the bucket:

```bash
# preview first
python -m app.db.backfill_uploads_to_s3 --dry-run
# then copy for real
python -m app.db.backfill_uploads_to_s3
```

It walks `UPLOADS_DIR/guild_<id>/`, uploads each blob to the matching S3 key with
its recorded content-type, and verifies against the stored `content_hash`. It's
**idempotent** (an object already in the bucket is skipped), so it's safe to
re-run until it reports `failed=0`.

**2. Cut over with a fallback window.** Set:

```bash
STORAGE_BACKEND=s3
S3_LOCAL_FALLBACK=true
```

`S3_LOCAL_FALLBACK` makes a read that misses in S3 fall back to the local
filesystem, so anything the backfill hasn't copied still serves — no 404s during
the transition. New uploads now go to S3.

**3. Finish.** Once you've confirmed everything serves from S3 (and a final
backfill run reports `failed=0`), set `S3_LOCAL_FALLBACK=false` and retire the
local uploads volume.

# Object Storage (MinIO / S3-compatible)

Initiative stores uploaded files (image attachments, document files and their
versions) through a pluggable storage backend selected by the `STORAGE_BACKEND`
environment variable:

| `STORAGE_BACKEND` | Where uploads live |
|---|---|
| `local` (default) | Filesystem under `UPLOADS_DIR` |
| `s3` | Any S3-compatible object store (e.g. self-hosted MinIO) |

Switching backends is a config change; **no code change is required.** The local
filesystem remains the default — turning on `s3` only changes where *new*
uploads are written.

> Migrating files that already exist on local disk into object storage is a
> separate backfill step (see [Migrating existing files](#migrating-existing-files)).

## How keys are laid out

- **Local:** files are stored flat under `UPLOADS_DIR` (e.g. `uploads/<uuid>.png`),
  exactly as before.
- **Object storage:** objects are namespaced per guild under a `guild_<id>/` key
  prefix (e.g. `guild_7/<uuid>.png`). This mirrors the database's
  schema-per-guild tenant boundary.

In both cases the public URL stays `/uploads/{guild_id}/{filename}`, and every
download still passes the same authorization checks (guild membership / access
grant + an `uploads` row in that guild's schema). Objects are streamed back
through the app, so authorization is enforced on every request.

## Run it locally with MinIO

[MinIO](https://min.io/) is a self-hostable, S3-compatible object server. A
compose overlay runs MinIO alongside the app, creates the bucket, and points the
app at it:

```bash
docker compose -f docker-compose.yml -f docker-compose.minio.yml up --build
```

This starts:

- **MinIO** on `:9000` (S3 API) with a web console on <http://localhost:9001>
  (default login `minioadmin` / `minioadmin`).
- A one-shot `minio-init` container that creates the bucket (`initiative` by
  default) and enables versioning.
- The app with `STORAGE_BACKEND=s3` pointed at `http://minio:9000`.

Override the defaults with environment variables (e.g. in a `.env` file next to
the compose files):

```bash
MINIO_ROOT_USER=...        # MinIO root access key
MINIO_ROOT_PASSWORD=...    # MinIO root secret key (use a strong value)
S3_BUCKET=initiative       # bucket name to create/use
S3_REGION=us-east-1
```

Upload an image or a document in the app, then open the MinIO console — you'll
see the object under `guild_<id>/…` in the bucket.

## Configure it manually

If you run MinIO (or another S3-compatible store) separately, set these on the
backend (see `backend/.env.example`):

```bash
STORAGE_BACKEND=s3
S3_BUCKET=initiative
S3_ENDPOINT_URL=http://minio:9000   # your MinIO endpoint
S3_REGION=us-east-1
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_USE_PATH_STYLE=true              # required for MinIO
S3_KMS_KEY_ID=                      # optional SSE-KMS key; leave blank for MinIO
```

`S3_USE_PATH_STYLE=true` matters for MinIO: it uses path-style addressing
(`http://host/bucket/key`) rather than virtual-host style. Create the bucket
ahead of time (the app does not create it for you when configured manually) — for
example with the MinIO console or `mc mb local/initiative`.

## Migrating existing files

Switching `STORAGE_BACKEND` to `s3` only affects *new* uploads. Files already on
local disk are not moved automatically; a backfill job that copies
`UPLOADS_DIR/*` into the bucket under each file's `guild_<id>/` prefix is the
next phase of the storage rollout. Until that runs, keep both the local volume
and the object store available if you flip the switch on a deployment that
already has local uploads.

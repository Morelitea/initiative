"""The import engine's bounds (the counterpart of the export engine's)."""

#: Inline-vs-job auto-select: at or under this many rows the envelope applies
#: in-request; above it the payload is staged and a job queued.
IMPORT_INLINE_MAX_ROWS = 200
#: Hard ceiling on rows in one envelope import.
IMPORT_MAX_ROWS = 10_000
#: Per-user cap on jobs that are staged, queued, or running at once.
IMPORT_MAX_ACTIVE_JOBS_PER_USER = 5
#: Byte bound on a single envelope request body (rows bound the content, but a
#: single-field envelope must be bounded in bytes too).
IMPORT_MAX_ENVELOPE_BYTES = 20_971_520  # 20 MiB
#: Staged payloads awaiting confirm/apply expire after this.
IMPORT_STAGED_TTL_HOURS = 24

#: Backup-zip imports: upload byte cap, plus bounds independent of the transfer
#: cap — total declared uncompressed size and member count.
IMPORT_MAX_BACKUP_UPLOAD_BYTES = 268_435_456  # 256 MiB
IMPORT_MAX_BACKUP_UNCOMPRESSED_BYTES = 1_073_741_824  # 4x the upload cap
IMPORT_MAX_ZIP_MEMBERS = 20_000

#: The longest a fetch may spend reading a foreign site, from its first call
#: to its bundle being staged. Past it the job fails with
#: ``IMPORT_SOURCE_TOO_SLOW`` rather than holding its slot.
IMPORT_FETCH_DEADLINE_SECONDS = 4 * 60 * 60

#: How many imports one process runs at once, by kind. Fetches wait on a
#: foreign site; applies write to the database. One community has at most one
#: import fetching or running at a time, whatever the slots allow.
IMPORT_FETCH_SLOTS = 3
IMPORT_APPLY_SLOTS = 2

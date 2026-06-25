"""Ad-hoc S3 GET vs PUT diagnostic for an S3-compatible store.

Uses the app's *saved* storage config (so no secrets on the command line) to
round-trip a tiny object: PUT, HEAD, GET. With --debug it dumps the signed
request headers botocore sends, so a signature rejection that only happens on
GET (classically a CDN/proxy transforming GETs) is visible.

    cd backend
    python -m scripts.diagnose_s3_get            # quick pass/fail
    python -m scripts.diagnose_s3_get --debug    # + signed request wire log
    python -m scripts.diagnose_s3_get --endpoint http://garage-internal:3900
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid


async def _load_cfg():
    from app.db.session import AdminSessionLocal
    from app.services import storage_config

    async with AdminSessionLocal() as session:
        await storage_config.refresh_storage_config(session)
    return storage_config.current_storage_config()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--debug", action="store_true", help="log signed requests")
    parser.add_argument(
        "--endpoint",
        default=None,
        help="override S3_ENDPOINT_URL (e.g. a direct/internal Garage address) to "
        "test whether the public endpoint's proxy/CDN is the culprit",
    )
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
        # botocore logs the canonical request + signed headers at DEBUG.
        logging.getLogger("botocore").setLevel(logging.DEBUG)

    from dataclasses import replace

    from app.services import storage

    cfg = asyncio.run(_load_cfg())
    if args.endpoint:
        cfg = replace(cfg, endpoint_url=args.endpoint)

    print(
        f"backend={cfg.backend} bucket={cfg.bucket} region={cfg.region} "
        f"endpoint={cfg.endpoint_url} path_style={cfg.use_path_style}"
    )
    if cfg.backend != "s3" or not cfg.bucket:
        raise SystemExit(
            "Storage is not configured for s3 (set it in the Storage tab)."
        )

    client = storage.build_s3_client(cfg)
    key = f"_diag/{uuid.uuid4().hex}.txt"
    body = b"diagnostic"

    print(f"\nPUT  {key} ...")
    client.put_object(Bucket=cfg.bucket, Key=key, Body=body, ContentType="text/plain")
    print("PUT  ok")

    try:
        print(f"\nHEAD {key} ...")
        client.head_object(Bucket=cfg.bucket, Key=key)
        print("HEAD ok")

        print(f"\nGET  {key} ...")
        obj = client.get_object(Bucket=cfg.bucket, Key=key)
        data = obj["Body"].read()
        print(f"GET  ok ({len(data)} bytes)" if data == body else "GET  mismatch!")
    finally:
        try:
            client.delete_object(Bucket=cfg.bucket, Key=key)
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass


if __name__ == "__main__":
    main()

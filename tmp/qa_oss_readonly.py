#!/usr/bin/env python3
"""Read-only check of the configured OSS bucket ACLs.

Run with the API environment file injected into an ephemeral container. The
script requests bucket metadata only and does not upload, list, or delete any
object.
"""

from __future__ import annotations

import sys

import oss2

from app.core.config import settings


def check_bucket(bucket_name: str) -> dict[str, str]:
    required = {
        "OSS_ENDPOINT": settings.oss_endpoint,
        "OSS_ACCESS_KEY_ID": settings.oss_access_key_id,
        "OSS_ACCESS_KEY_SECRET": settings.oss_access_key_secret,
        "bucket": bucket_name,
    }
    missing = [name for name, value in required.items() if not value or value == "CHANGE_ME"]
    if missing:
        return {"bucket": bucket_name, "acl": f"NOT_CONFIGURED ({', '.join(missing)})"}
    auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
    bucket = oss2.Bucket(auth, settings.oss_endpoint, bucket_name)
    result = {"bucket": bucket_name, "acl": str(getattr(bucket.get_bucket_acl(), "acl", "UNKNOWN"))}
    try:
        versioning = bucket.get_bucket_versioning()
        result["versioning"] = str(getattr(versioning, "status", "UNKNOWN"))
    except Exception as exc:  # noqa: BLE001 - diagnostic output only
        result["versioning"] = f"ERROR:{type(exc).__name__}"
    try:
        encryption = bucket.get_bucket_encryption()
        algorithm = (
            encryption.rules[0].apply_server_side_encryption_by_default.sse_algorithm
            if getattr(encryption, "rules", None)
            else "NONE"
        )
        result["encryption"] = str(algorithm)
    except Exception as exc:  # noqa: BLE001 - diagnostic output only
        result["encryption"] = f"ERROR:{type(exc).__name__}"
    try:
        lifecycle = bucket.get_bucket_lifecycle()
        result["lifecycle_rules"] = str(len(getattr(lifecycle, "rules", []) or []))
    except Exception as exc:  # noqa: BLE001 - diagnostic output only
        result["lifecycle"] = f"ERROR:{type(exc).__name__}"
    return result


def main() -> int:
    failed = False
    for bucket_name in dict.fromkeys(
        (
            settings.oss_bucket,
            settings.oss_preview_bucket,
        )
    ):
        result = check_bucket(bucket_name)
        private = result.get("acl") == "private"
        failed = failed or not private
        print(f"[{'PASS' if private else 'FAIL'}] {result}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

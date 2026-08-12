"""Upload a generated PNG to Aliyun OSS to verify the configured connection.

Run from the backend directory:
    .venv\\Scripts\\python.exe scripts\\verify_oss.py
"""

from __future__ import annotations

import hashlib
import struct
import sys
import time
import zlib
from datetime import UTC, datetime
from pathlib import Path

import oss2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def make_test_png(width: int = 96, height: int = 96) -> bytes:
    """Create a small valid RGB PNG using only the Python standard library."""
    seed = int(time.time_ns())
    rows = []
    for y in range(height):
        row = bytearray([0])  # PNG filter type: None
        for x in range(width):
            value = (x * 17 + y * 31 + seed) & 0xFF
            row.extend((value, value ^ 0xA5, (value * 3) & 0xFF))
        rows.append(bytes(row))
    header = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return header + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(b"".join(rows))) + _chunk(b"IEND", b"")


def main() -> None:
    required = {
        "OSS_ENDPOINT": settings.oss_endpoint,
        "OSS_BUCKET": settings.oss_bucket,
        "OSS_ACCESS_KEY_ID": settings.oss_access_key_id,
        "OSS_ACCESS_KEY_SECRET": settings.oss_access_key_secret,
    }
    missing = [key for key, value in required.items() if not value or value == "CHANGE_ME"]
    if missing:
        raise RuntimeError(f"Missing OSS configuration: {', '.join(missing)}")

    image = make_test_png()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    object_key = f"{settings.oss_prefix.strip('/')}/connection-tests/{stamp}-{hashlib.sha256(image).hexdigest()[:12]}.png"
    auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
    bucket = oss2.Bucket(auth, settings.oss_endpoint, settings.oss_bucket)
    result = bucket.put_object(object_key, image, headers={"Content-Type": "image/png"})
    if result.status != 200:
        raise RuntimeError(f"OSS upload returned HTTP {result.status}")
    metadata = bucket.get_object_meta(object_key)
    print(f"OSS verification succeeded: oss://{settings.oss_bucket}/{object_key}")
    print(f"bytes={len(image)}, content_length={metadata.content_length}, etag={result.etag}")


if __name__ == "__main__":
    main()

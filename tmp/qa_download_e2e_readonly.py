#!/usr/bin/env python3
"""Read-only end-to-end check of the new batch download route.

The script selects one existing photo owned by an existing user, reads the
private OSS object through the application code, and verifies the returned ZIP.
It prints no identifiers, filenames, image data, or credentials.
"""

from __future__ import annotations

import asyncio
import io
import zipfile

import asyncpg

from app.api.feishu import DownloadBatchRequest, download_photo_batch
from app.core.config import settings


class FakeRequest:
    def __init__(self, user_id: str) -> None:
        self.session = {"user_id": user_id}


async def main() -> int:
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(dsn)
    try:
        row = await connection.fetchrow(
            """SELECT u.id::text AS user_id, p.id::text AS photo_id
               FROM users u
               JOIN photo_records p ON p.photographer_open_id = u.open_id
               ORDER BY p.captured_at DESC
               LIMIT 1"""
        )
    finally:
        await connection.close()
    if not row:
        print("[SKIP] No user-owned photo is available for an end-to-end check")
        return 0

    response = await download_photo_batch(
        DownloadBatchRequest(photo_ids=[str(row["photo_id"])], scope="mine"),
        FakeRequest(str(row["user_id"])),
    )
    archive_bytes = b"".join([chunk async for chunk in response.body_iterator])
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        names = archive.namelist()
        image = archive.read(names[0]) if names else b""

    passed = (
        response.status_code == 200
        and response.media_type == "application/zip"
        and len(names) == 1
        and image.startswith(b"\xff\xd8\xff")
    )
    print(
        f"[{'PASS' if passed else 'FAIL'}] live ZIP status={response.status_code} "
        f"entries={len(names)} image_bytes={len(image)}"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

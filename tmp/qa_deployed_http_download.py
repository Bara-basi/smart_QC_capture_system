#!/usr/bin/env python3
"""Authenticated HTTP smoke test for the deployed download routes.

Run inside the API container. It creates a short-lived signed session for one
existing user, reads one existing owned photo, and prints only status/size
metadata. No identifiers, filenames, credentials, or image bytes are exposed.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import zipfile

import asyncpg
import httpx
from itsdangerous import TimestampSigner

from app.core.config import settings


def session_cookie(user_id: str) -> str:
    payload = base64.b64encode(
        json.dumps({"user_id": user_id}, separators=(",", ":")).encode("utf-8")
    ).decode("utf-8")
    signer = TimestampSigner(str(settings.secret_key))
    return signer.sign(payload).decode("utf-8")


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
        print("[SKIP] No existing owned photo is available")
        return 0

    cookie = session_cookie(str(row["user_id"]))
    headers = {"Cookie": f"qc_session={cookie}"}
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=30) as client:
        single = await client.get(
            f"/api/v1/feishu/photos/{row['photo_id']}/download",
            params={"scope": "mine"},
            headers=headers,
        )
        batch = await client.post(
            "/api/v1/feishu/photos/download-batch",
            json={"photo_ids": [str(row["photo_id"])], "scope": "mine"},
            headers=headers,
        )
        native = await client.get(
            f"/api/v1/feishu/photos/{row['photo_id']}/download-url",
            params={"scope": "mine"},
            headers=headers,
        )
        native_url = str(native.json().get("url", "")) if native.status_code == 200 else ""
        signed = await client.get(native_url) if native_url else None

    try:
        with zipfile.ZipFile(io.BytesIO(batch.content)) as archive:
            entries = archive.namelist()
            image = archive.read(entries[0]) if entries else b""
    except zipfile.BadZipFile:
        entries = []
        image = b""

    single_ok = (
        single.status_code == 200
        and single.headers.get("content-type", "").startswith("image/jpeg")
        and single.content.startswith(b"\xff\xd8\xff")
    )
    batch_ok = (
        batch.status_code == 200
        and batch.headers.get("content-type", "").startswith("application/zip")
        and len(entries) == 1
        and image.startswith(b"\xff\xd8\xff")
    )
    native_ok = bool(
        signed
        and native.status_code == 200
        and signed.status_code == 200
        and signed.content.startswith(b"\xff\xd8\xff")
    )
    print(
        f"[{'PASS' if single_ok else 'FAIL'}] authenticated single "
        f"status={single.status_code} bytes={len(single.content)}"
    )
    print(
        f"[{'PASS' if batch_ok else 'FAIL'}] authenticated batch "
        f"status={batch.status_code} entries={len(entries)} bytes={len(batch.content)}"
    )
    print(
        f"[{'PASS' if native_ok else 'FAIL'}] native signed download "
        f"url_status={native.status_code} asset_status={signed.status_code if signed else 0}"
    )
    return 0 if single_ok and batch_ok and native_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

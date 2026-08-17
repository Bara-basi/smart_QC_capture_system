"""Durable delivery of completed task/order statuses to Feishu Bitable."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import httpx

from app.core.config import settings
from app.integrations.feishu_bitable import FeishuBitableClient, FeishuBitableError

logger = logging.getLogger(__name__)
SUBMITTED_STATUS = "已提交"


def _dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def enqueue_status_updates(
    connection: asyncpg.Connection,
    *,
    table_id: str,
    field_id: str,
    record_ids: list[str],
) -> list[int]:
    """Add idempotent status updates inside the caller's database transaction."""
    if not table_id or not field_id or not record_ids:
        return []
    job_ids: list[int] = []
    for record_id in sorted(set(record_ids)):
        row = await connection.fetchrow(
            """INSERT INTO feishu_status_sync_outbox
                 (table_id, record_id, field_id, field_value)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (table_id, record_id, field_id, field_value)
               DO UPDATE SET updated_at = NOW()
               RETURNING id""",
            table_id,
            record_id,
            field_id,
            SUBMITTED_STATUS,
        )
        job_ids.append(int(row["id"]))
    return job_ids


async def sync_pending_statuses(job_ids: list[int] | None = None, limit: int = 1000) -> dict[str, int]:
    """Try pending deliveries once and leave failures queued for a later retry."""
    if not settings.database_url:
        return {"synced": 0, "pending": 0}
    connection = await asyncpg.connect(_dsn())
    try:
        if job_ids:
            rows = await connection.fetch(
                """SELECT id, table_id, record_id, field_id, field_value, attempts
                   FROM feishu_status_sync_outbox
                   WHERE synced_at IS NULL AND id = ANY($1::bigint[])
                   ORDER BY id LIMIT $2""",
                job_ids,
                limit,
            )
        else:
            rows = await connection.fetch(
                """SELECT id, table_id, record_id, field_id, field_value, attempts
                   FROM feishu_status_sync_outbox
                   WHERE synced_at IS NULL AND next_attempt_at <= NOW()
                   ORDER BY id LIMIT $1""",
                limit,
            )
        grouped: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
        for row in rows:
            grouped[(str(row["table_id"]), str(row["field_id"]), str(row["field_value"]))].append(row)

        synced = 0
        client = FeishuBitableClient()
        for (table_id, field_id, value), jobs in grouped.items():
            ids = [int(job["id"]) for job in jobs]
            try:
                await client.update_record_field(table_id, field_id, [str(job["record_id"]) for job in jobs], value)
            except (FeishuBitableError, httpx.HTTPError) as exc:
                retry_at = datetime.now(UTC) + timedelta(seconds=min(3600, 30 * (2 ** min(int(jobs[0].get("attempts", 0)), 7))))
                await connection.execute(
                    """UPDATE feishu_status_sync_outbox
                       SET attempts = attempts + 1, next_attempt_at = $2, last_error = $3, updated_at = NOW()
                       WHERE id = ANY($1::bigint[])""",
                    ids,
                    retry_at,
                    str(exc)[:1000],
                )
                logger.warning("Feishu status update remains queued for table %s: %s", table_id, exc)
            else:
                await connection.execute(
                    """UPDATE feishu_status_sync_outbox
                       SET synced_at = NOW(), last_error = NULL, updated_at = NOW()
                       WHERE id = ANY($1::bigint[])""",
                    ids,
                )
                synced += len(ids)
        return {"synced": synced, "pending": len(rows) - synced}
    finally:
        await connection.close()


async def status_sync_worker(stop: asyncio.Event) -> None:
    """Retry the durable outbox periodically for the lifetime of the API process."""
    interval = max(10, settings.feishu_status_sync_interval_seconds)
    while not stop.is_set():
        try:
            await sync_pending_statuses()
        except Exception:
            logger.exception("Could not process the Feishu status outbox")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass

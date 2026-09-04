"""Import Feishu order records and their photo tasks into PostgreSQL."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from time import monotonic
from typing import Any

import asyncpg

from app.core.config import settings
from app.integrations.feishu_bitable import FeishuBitableClient, FeishuBitableError

logger = logging.getLogger(__name__)


class SyncValidationError(ValueError):
    pass


def _dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _find(fields: dict[str, Any], *names: str) -> Any:
    lookup = {
        key.strip().lower().replace(" ", ""): value for key, value in fields.items()
    }
    for name in names:
        value = lookup.get(name.lower().replace(" ", ""))
        if value not in (None, "", []):
            return value
    for key, value in lookup.items():
        if value in (None, "", []):
            continue
        if any(name.lower().replace(" ", "") in key for name in names):
            return value
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        pieces = [_text(item) for item in value]
        return ", ".join(piece for piece in pieces if piece) or None
    if isinstance(value, dict):
        return _text(value.get("text") or value.get("name") or value.get("value"))
    return str(value)


def _person_reference(value: Any) -> tuple[str | None, str | None]:
    people = value if isinstance(value, list) else [value]
    for person in people:
        if isinstance(person, dict):
            open_id = person.get("id") or person.get("open_id")
            name = person.get("name") or person.get("en_name")
            return _text(open_id), _text(name)
    return None, _text(value)


async def _union_id_or_none(
    client: FeishuBitableClient, open_id: str | None
) -> str | None:
    if not open_id:
        return None
    try:
        return await client.get_person_union_id(open_id)
    except FeishuBitableError as exc:
        # A missing Contact scope must not prevent a photo task from reaching
        # the inspector. The raw person name and open_id remain available.
        logger.warning("Could not resolve Feishu union_id for %s: %s", open_id, exc)
        return None


def _contract_no(fields: dict[str, Any]) -> str | None:
    return _text(_find(fields, "合同号", "合同编号", "contract_no", "contract number"))


def _product_type(fields: dict[str, Any]) -> str | None:
    return _text(_find(fields, "产品类型", "产品类别", "product_type", "product type"))


async def _upsert_order_item(
    connection: asyncpg.Connection,
    record: dict[str, Any],
    union_ids: dict[str, str | None],
) -> tuple[str, str]:
    fields = record.get("fields") or {}
    record_id = record.get("record_id")
    contract_no = _contract_no(fields)
    product_type = _product_type(fields)
    if not record_id or not contract_no or not product_type:
        raise SyncValidationError("Order record needs record_id, 合同号 and 产品类型")

    inspector_open_id, inspector_name = _person_reference(
        _find(fields, "质检员", "检验员", "inspector")
    )
    inspector_union_id = union_ids.get(inspector_open_id) if inspector_open_id else None
    inspection_status = _text(
        _find(fields, "质检状态", "检验状态", "inspection_status", "inspection status")
    )
    year_code = datetime.now(UTC).strftime("%y")
    await connection.execute(
        """INSERT INTO orders (contract_no, contract_year_code)
           VALUES ($1, $2)
           ON CONFLICT (contract_no) DO UPDATE SET updated_at = NOW()""",
        contract_no,
        year_code,
    )
    await connection.execute(
        """INSERT INTO order_items
           (order_id, contract_no, product_type, feishu_record_id, feishu_fields,
            inspection_status, inspector_open_id, inspector_union_id, inspector_name)
           SELECT id, $1::varchar, $3::varchar, $2::varchar, $4::jsonb, $5::varchar, $6::varchar, $7::varchar, $8::varchar
           FROM orders WHERE contract_no = $1::varchar
           ON CONFLICT (feishu_record_id) DO UPDATE SET
             contract_no = EXCLUDED.contract_no, product_type = EXCLUDED.product_type,
             feishu_fields = EXCLUDED.feishu_fields, inspection_status = EXCLUDED.inspection_status, inspector_open_id = EXCLUDED.inspector_open_id,
             inspector_union_id = EXCLUDED.inspector_union_id, inspector_name = EXCLUDED.inspector_name,
             updated_at = NOW()""",
        contract_no,
        record_id,
        product_type,
        json.dumps(fields, ensure_ascii=False),
        inspection_status,
        inspector_open_id,
        inspector_union_id,
        inspector_name,
    )
    return contract_no, product_type


async def _upsert_tasks(
    connection: asyncpg.Connection,
    contract_no: str,
    records: list[dict[str, Any]],
    union_ids: dict[str, str | None],
) -> int:
    count = 0
    for record in records:
        fields = record.get("fields") or {}
        if _contract_no(fields) != contract_no:
            continue
        record_id = record.get("record_id")
        if not record_id:
            continue
        inspector_open_id, inspector_name = _person_reference(
            _find(fields, "质检员", "检验员", "inspector")
        )
        inspector_union_id = (
            union_ids.get(inspector_open_id) if inspector_open_id else None
        )
        await connection.execute(
            """INSERT INTO inspection_photo_tasks
               (feishu_record_id, contract_no, sequence_no, task_id, product_type, specification, quantity, inspection_stage,
                inspector_name, inspection_status, inspector_open_id, inspector_union_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
               ON CONFLICT (feishu_record_id) DO UPDATE SET
                 contract_no = EXCLUDED.contract_no, sequence_no = EXCLUDED.sequence_no, task_id = EXCLUDED.task_id,
                 product_type = EXCLUDED.product_type, specification = EXCLUDED.specification, quantity = EXCLUDED.quantity,
                 inspection_stage = EXCLUDED.inspection_stage, inspector_name = EXCLUDED.inspector_name,
                 inspection_status = EXCLUDED.inspection_status, inspector_open_id = EXCLUDED.inspector_open_id,
                 inspector_union_id = EXCLUDED.inspector_union_id, updated_at = NOW()""",
            record_id,
            _text(fields.get("合同号")),
            _text(fields.get("序号")),
            _text(fields.get("任务ID")),
            _text(fields.get("产品类型")),
            _text(fields.get("规格")),
            _text(fields.get("数量")),
            _text(fields.get("质检阶段")),
            inspector_name,
            _text(fields.get("质检状态")),
            inspector_open_id,
            inspector_union_id,
        )
        count += 1
    return count


def _record_ids(payload: dict[str, Any]) -> set[str]:
    candidates: Iterable[Any] = (
        payload,
        payload.get("data", {}),
        payload.get("record", {}),
    )
    record_ids: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        for value in (item.get("record_id"), item.get("recordId")):
            record_id = str(value).strip() if value is not None else ""
            if record_id:
                record_ids.add(record_id)
    return record_ids


def _inspector_open_ids(records: Iterable[dict[str, Any]]) -> set[str]:
    open_ids: set[str] = set()
    for record in records:
        fields = record.get("fields") or {}
        open_id, _ = _person_reference(_find(fields, "质检员", "检验员", "inspector"))
        if open_id:
            open_ids.add(open_id)
    return open_ids


async def _resolve_union_ids(
    client: FeishuBitableClient,
    open_ids: set[str],
) -> dict[str, str | None]:
    ordered_ids = sorted(open_ids)
    resolved = await asyncio.gather(
        *(_union_id_or_none(client, open_id) for open_id in ordered_ids)
    )
    return dict(zip(ordered_ids, resolved, strict=True))


async def sync_order_webhook(payload: dict[str, Any]) -> dict[str, int]:
    started_at = monotonic()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    selected_ids = _record_ids(payload)
    if len(selected_ids) != 1:
        raise SyncValidationError(
            "The webhook request must contain exactly one record_id"
        )
    selected_id = next(iter(selected_ids))

    # Finish all remote reads before opening a database transaction. One shared
    # client reuses the HTTP connection and tenant token for the whole webhook.
    async with FeishuBitableClient() as client:
        order_record = await client.get_record(
            settings.feishu_bitable_order_table_id,
            selected_id,
        )
        order_fields = order_record.get("fields") or {}
        contract_no = _contract_no(order_fields)
        if (
            not order_record.get("record_id")
            or not contract_no
            or not _product_type(order_fields)
        ):
            raise SyncValidationError(
                "Order record needs record_id, 合同号 and 产品类型"
            )
        task_records = [
            record
            async for record in client.search_records(
                settings.feishu_bitable_table_id,
                settings.feishu_bitable_inspection_task_view_id,
                field_name="合同号",
                value=contract_no,
            )
            if _contract_no(record.get("fields") or {}) == contract_no
        ]
        union_ids = await _resolve_union_ids(
            client,
            _inspector_open_ids([order_record, *task_records]),
        )

    connection = await asyncpg.connect(_dsn())
    try:
        async with connection.transaction():
            await _upsert_order_item(connection, order_record, union_ids)
            synced_tasks = await _upsert_tasks(
                connection,
                contract_no,
                task_records,
                union_ids,
            )
        result = {"order_items": 1, "inspection_photo_tasks": synced_tasks}
        logger.info(
            "Feishu order sync complete: record_id=%s contract_no=%s tasks=%d elapsed=%.3fs",
            selected_id,
            contract_no,
            synced_tasks,
            monotonic() - started_at,
        )
        return result
    finally:
        await connection.close()

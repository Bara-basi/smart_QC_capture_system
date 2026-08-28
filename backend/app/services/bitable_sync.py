"""Import Feishu order records and their photo tasks into PostgreSQL."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
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
    lookup = {key.strip().lower().replace(" ", ""): value for key, value in fields.items()}
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


async def _union_id_or_none(client: FeishuBitableClient, open_id: str | None) -> str | None:
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


async def _upsert_order_item(connection: asyncpg.Connection, client: FeishuBitableClient, record: dict[str, Any]) -> tuple[str, str]:
    fields = record.get("fields") or {}
    record_id = record.get("record_id")
    contract_no = _contract_no(fields)
    product_type = _product_type(fields)
    if not record_id or not contract_no or not product_type:
        raise SyncValidationError("Order record needs record_id, 合同号 and 产品类型")

    inspector_open_id, inspector_name = _person_reference(_find(fields, "质检员", "检验员", "inspector"))
    inspector_union_id = await _union_id_or_none(client, inspector_open_id)
    inspection_status = _text(_find(fields, "质检状态", "检验状态", "inspection_status", "inspection status"))
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
        contract_no, record_id, product_type, json.dumps(fields, ensure_ascii=False), inspection_status, inspector_open_id, inspector_union_id, inspector_name,
    )
    return contract_no, product_type


async def _upsert_tasks(connection: asyncpg.Connection, contract_no: str) -> int:
    count = 0
    client = FeishuBitableClient()
    async for record in client.iter_records(settings.feishu_bitable_table_id, settings.feishu_bitable_inspection_task_view_id):
        fields = record.get("fields") or {}
        if _contract_no(fields) != contract_no:
            continue
        record_id = record.get("record_id")
        if not record_id:
            continue
        inspector_open_id, inspector_name = _person_reference(_find(fields, "质检员", "检验员", "inspector"))
        inspector_union_id = await _union_id_or_none(client, inspector_open_id)
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
            _text(fields.get("合同号")), _text(fields.get("序号")), _text(fields.get("任务ID")),
            _text(fields.get("产品类型")), _text(fields.get("规格")), _text(fields.get("数量")),
            _text(fields.get("质检阶段")), inspector_name, _text(fields.get("质检状态")),
            inspector_open_id, inspector_union_id,
        )
        count += 1
    return count


def _record_ids(payload: dict[str, Any]) -> set[str]:
    candidates: Iterable[Any] = (payload, payload.get("data", {}), payload.get("record", {}))
    return {str(value) for item in candidates if isinstance(item, dict) for value in (item.get("record_id"), item.get("recordId")) if value}


async def sync_order_webhook(payload: dict[str, Any]) -> dict[str, int]:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    selected_ids = _record_ids(payload)
    client = FeishuBitableClient()
    try:
        connection = await asyncpg.connect(_dsn())
        contracts: set[str] = set()
        synced_orders = 0
        async with connection.transaction():
            async for record in client.iter_records(settings.feishu_bitable_order_table_id, settings.feishu_bitable_order_view_id):
                if selected_ids and record.get("record_id") not in selected_ids:
                    continue
                contract_no, _ = await _upsert_order_item(connection, client, record)
                contracts.add(contract_no)
                synced_orders += 1
            if selected_ids and not synced_orders:
                raise SyncValidationError("The requested order record is not present in the configured order view")
            synced_tasks = sum([await _upsert_tasks(connection, contract_no) for contract_no in contracts])
        return {"order_items": synced_orders, "inspection_photo_tasks": synced_tasks}
    finally:
        if "connection" in locals():
            await connection.close()

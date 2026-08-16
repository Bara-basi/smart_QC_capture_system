"""Read-model queries for an inspector's homepage and capture task."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg

from app.core.config import settings

RULES_PATH = Path(__file__).resolve().parents[2] / "data" / "require_mapping.json"
DONE_STATUSES = {"已完成", "已提交", "completed", "submitted"}
CAPTURE_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _requirements(product_type: str | None) -> list[str]:
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    products: dict[str, list[str]] = rules["products"]
    return products.get(product_type or "", products["其它"])


def _mandatory_items() -> set[str]:
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return set(rules.get("mandatory_items", []))


def _is_complete(status: str | None) -> bool:
    return (status or "").strip().lower() in {item.lower() for item in DONE_STATUSES}


async def inspector_dashboard(user_id: str) -> dict[str, Any]:
    connection = await asyncpg.connect(_dsn())
    try:
        user = await connection.fetchrow("SELECT name, open_id FROM users WHERE id = $1::uuid", user_id)
        if not user:
            raise LookupError("Current user no longer exists")
        rows = await connection.fetch(
            """SELECT t.feishu_record_id, t.contract_no, t.sequence_no, t.task_id, t.product_type,
                      t.specification, t.quantity, t.inspection_stage, t.inspection_status,
                      t.created_at, oi.created_at AS order_created_at
               FROM inspection_photo_tasks t
               LEFT JOIN order_items oi ON oi.contract_no = t.contract_no AND oi.product_type = t.product_type
               WHERE t.inspector_open_id = $1
               ORDER BY oi.created_at DESC NULLS LAST, t.created_at DESC""",
            user["open_id"],
        )
        photo_rows = await connection.fetch(
            """SELECT p.task_feishu_record_id, p.inspection_item FROM photo_records p
               WHERE p.photographer_open_id = $1 AND p.task_feishu_record_id IS NOT NULL""",
            user["open_id"],
        )
        captured_items: dict[str, set[str]] = defaultdict(set)
        for photo in photo_rows:
            captured_items[str(photo["task_feishu_record_id"])].add(str(photo["inspection_item"]))
        grouped: dict[str, list[asyncpg.Record]] = defaultdict(list)
        for row in rows:
            grouped[row["contract_no"]].append(row)
        orders = []
        for contract_no, tasks in grouped.items():
            pending = [task for task in tasks if not _task_is_complete(task, captured_items)]
            first = tasks[0]
            orders.append(
                {
                    "contract_no": contract_no,
                    "started_at": first["order_created_at"] or first["created_at"],
                    "task_count": len(tasks),
                    "pending_count": len(pending),
                    "status": "completed" if not pending else "pending",
                    "products": [f"{task['specification'] or '未填写规格'} · {task['product_type'] or '未分类'}" for task in tasks],
                    "task_ids": [task["feishu_record_id"] for task in tasks],
                }
            )
        # The source query is newest first; Python's stable sort keeps that
        # order within each group while moving completed orders to the end.
        orders.sort(key=lambda order: order["status"] == "completed")
        return {"user": {"name": user["name"]}, "pending_task_count": sum(not _task_is_complete(row, captured_items) for row in rows), "orders": orders}
    finally:
        await connection.close()


async def capture_task(user_id: str, record_id: str) -> dict[str, Any]:
    """Return every assigned product task in one contract capture sheet."""
    connection = await asyncpg.connect(_dsn())
    try:
        user = await connection.fetchrow("SELECT open_id FROM users WHERE id = $1::uuid", user_id)
        selected = await connection.fetchrow(
            "SELECT contract_no FROM inspection_photo_tasks WHERE feishu_record_id = $1 AND inspector_open_id = $2",
            record_id, user["open_id"] if user else "",
        )
        if not selected:
            raise LookupError("Task not found")
        tasks = await connection.fetch(
            """SELECT t.feishu_record_id, t.product_type, t.specification, t.inspection_stage, t.sequence_no,
                      EXISTS(SELECT 1 FROM photo_records p WHERE p.task_feishu_record_id = t.feishu_record_id) AS uploaded
               FROM inspection_photo_tasks t WHERE t.contract_no = $1 AND t.inspector_open_id = $2
               ORDER BY sequence_no NULLS LAST, created_at""",
            selected["contract_no"], user["open_id"],
        )
        photos = await connection.fetch(
            """SELECT id, task_feishu_record_id, inspection_item, original_filename
               FROM photo_records WHERE contract_no = $1 AND photographer_open_id = $2 ORDER BY captured_at""",
            selected["contract_no"], user["open_id"],
        )
        by_task: dict[str, list[dict[str, str]]] = defaultdict(list)
        for photo in photos:
            by_task[str(photo["task_feishu_record_id"])].append({"id": str(photo["id"]), "inspection_item": str(photo["inspection_item"]), "name": str(photo["original_filename"] or "现场照片.jpg")})
        return {
            "contract_no": selected["contract_no"],
            "tasks": [
                {"feishu_record_id": task["feishu_record_id"], "product_type": task["product_type"],
                 "specification": task["specification"], "inspection_stage": task["inspection_stage"], "sequence_no": task["sequence_no"], "uploaded": {name for name in _requirements(task["product_type"]) if name in _mandatory_items()}.issubset({photo["inspection_item"] for photo in by_task[str(task["feishu_record_id"])]}),
                 "requirements": [{"name": name, "mandatory": name in _mandatory_items()} for name in _requirements(task["product_type"])], "photos": by_task[str(task["feishu_record_id"])]}
                for task in tasks
            ],
        }
    finally:
        await connection.close()


def _task_is_complete(task: asyncpg.Record, captured_items: dict[str, set[str]]) -> bool:
    mandatory = {name for name in _requirements(task["product_type"]) if name in _mandatory_items()}
    return mandatory.issubset(captured_items.get(str(task["feishu_record_id"]), set()))


async def watermark_task(user_id: str, record_id: str) -> asyncpg.Record:
    """Fetch watermark metadata only when the requested task belongs to the inspector."""
    connection = await asyncpg.connect(_dsn())
    try:
        row = await connection.fetchrow(
            """SELECT COALESCE(oi.contract_no, t.contract_no) AS contract_no, t.sequence_no, t.specification,
                      t.product_type, u.open_id AS photographer_open_id, u.name AS photographer_name
               FROM inspection_photo_tasks t JOIN users u ON u.id = $1::uuid
               LEFT JOIN order_items oi ON oi.contract_no = t.contract_no AND oi.product_type = t.product_type
               WHERE t.feishu_record_id = $2 AND t.inspector_open_id = u.open_id""",
            user_id, record_id,
        )
        if not row:
            raise LookupError("Task not found")
        return row
    finally:
        await connection.close()


async def create_photo_record(values: dict[str, Any]) -> str:
    connection = await asyncpg.connect(_dsn())
    try:
        record = await connection.fetchrow(
            """INSERT INTO photo_records
                 (task_feishu_record_id, photographer_open_id, captured_at, contract_no, product_type,
                  inspection_item, source, factory_initials, sequence_no, specification, photographer_name,
                  oss_object_key, preview_oss_object_key, original_filename, content_type, file_size_bytes,
                  sha256, metadata, search_text)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18::jsonb,$19)
               RETURNING id""",
            values["task_id"], values["photographer_open_id"], values["captured_at"], values["contract_no"],
            values["product_type"], values["inspection_item"], values["source"], values["factory_initials"],
            values["sequence_no"], values["specification"], values["photographer_name"], values["oss_object_key"],
            values["preview_oss_object_key"], values["original_filename"], values["content_type"], values["file_size_bytes"],
            values["sha256"], json.dumps(values["metadata"], ensure_ascii=False), values["search_text"],
        )
        return str(record["id"])
    finally:
        await connection.close()


async def commit_photo_records(user_id: str, values: list[dict[str, Any]]) -> list[str]:
    """Atomically validate ownership and persist an already-uploaded batch."""
    connection = await asyncpg.connect(_dsn())
    try:
        async with connection.transaction():
            user = await connection.fetchrow("SELECT open_id, name FROM users WHERE id = $1::uuid", user_id)
            if not user:
                raise LookupError("Current user no longer exists")
            task_ids = [value["task_id"] for value in values]
            tasks = await connection.fetch(
                """SELECT feishu_record_id, contract_no, sequence_no, specification, product_type
                   FROM inspection_photo_tasks WHERE feishu_record_id = ANY($1::varchar[]) AND inspector_open_id = $2""",
                task_ids, user["open_id"],
            )
            task_map = {str(task["feishu_record_id"]): task for task in tasks}
            if len(task_map) != len(set(task_ids)):
                raise LookupError("One or more capture tasks are unavailable")
            ids = []
            for value in values:
                task = task_map[value["task_id"]]
                if task["contract_no"] != value["contract_no"]:
                    raise LookupError("Photo does not belong to this contract")
                record = await connection.fetchrow(
                    """INSERT INTO photo_records
                       (task_feishu_record_id, photographer_open_id, captured_at, contract_no, product_type,
                        inspection_item, source, factory_initials, sequence_no, specification, photographer_name,
                        oss_object_key, preview_oss_object_key, original_filename, content_type, file_size_bytes,
                        sha256, metadata, search_text)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18::jsonb,$19)
                       RETURNING id""",
                    value["task_id"], user["open_id"], value["captured_at"], value["contract_no"],
                    task["product_type"] or "未分类", value["inspection_item"], value["source"], value["factory_initials"],
                    task["sequence_no"], task["specification"], user["name"], value["oss_object_key"],
                    value["preview_oss_object_key"], value["original_filename"], value["content_type"], value["file_size_bytes"],
                    value["sha256"], json.dumps(value["metadata"], ensure_ascii=False), value["search_text"],
                )
                ids.append(str(record["id"]))
            return ids
    finally:
        await connection.close()


async def commit_task_metadata(user_id: str, task_ids: list[str], contract_no: str) -> dict[str, asyncpg.Record]:
    connection = await asyncpg.connect(_dsn())
    try:
        user = await connection.fetchrow("SELECT open_id, name FROM users WHERE id = $1::uuid", user_id)
        if not user:
            raise LookupError("Current user no longer exists")
        rows = await connection.fetch(
            """SELECT t.feishu_record_id, t.contract_no, t.sequence_no, t.specification, t.product_type, u.open_id, u.name
               FROM inspection_photo_tasks t JOIN users u ON u.id = $1::uuid
               WHERE t.feishu_record_id = ANY($2::varchar[]) AND t.inspector_open_id = u.open_id AND t.contract_no = $3""",
            user_id, task_ids, contract_no,
        )
        result = {str(row["feishu_record_id"]): row for row in rows}
        if len(result) != len(set(task_ids)):
            raise LookupError("One or more capture tasks are unavailable")
        return result
    finally:
        await connection.close()


async def photo_object_for_user(user_id: str, photo_id: str, preview: bool, scope: str = "mine") -> str:
    if scope not in {"mine", "shared"}:
        raise ValueError("Invalid photo scope")
    connection = await asyncpg.connect(_dsn())
    try:
        column = "preview_oss_object_key" if preview else "oss_object_key"
        row = await connection.fetchrow(
            f"""SELECT p.{column} AS object_key FROM photo_records p
                JOIN users u ON u.id = $1::uuid
                WHERE p.id = $2::uuid AND ($3 = 'shared' OR p.photographer_open_id = u.open_id)""",
            user_id, photo_id, scope,
        )
        if not row or not row["object_key"]:
            raise LookupError("Photo not found")
        return str(row["object_key"])
    finally:
        await connection.close()


async def delete_photo_for_inspector(user_id: str, photo_id: str) -> tuple[str, str]:
    connection = await asyncpg.connect(_dsn())
    try:
        async with connection.transaction():
            row = await connection.fetchrow(
                """DELETE FROM photo_records p USING users u
                   WHERE p.id = $2::uuid AND u.id = $1::uuid AND p.photographer_open_id = u.open_id
                   RETURNING p.oss_object_key, p.preview_oss_object_key""",
                user_id, photo_id,
            )
            if not row:
                raise LookupError("Photo not found")
            return str(row["oss_object_key"]), str(row["preview_oss_object_key"])
    finally:
        await connection.close()


async def inspector_photos(
    user_id: str,
    *,
    product_type: str | None = None,
    inspection_category: str | None = None,
    captured_from: str | None = None,
    captured_to: str | None = None,
    sort: str = "desc",
    scope: str = "mine",
    search: str | None = None,
) -> list[dict[str, Any]]:
    """Return visible uploaded photos with SQL-side metadata and token filters."""
    category_prefixes = {
        "material": ["材质光谱"],
        "surface": ["内外表面"],
        "dimension": ["尺寸"],
        "marking": ["喷码"],
        "port": ["端口"],
        "weld": ["焊道"],
    }
    if inspection_category and inspection_category not in category_prefixes:
        raise ValueError("Invalid inspection category")
    if sort not in {"asc", "desc"}:
        raise ValueError("Invalid sort direction")
    if scope not in {"mine", "shared"}:
        raise ValueError("Invalid photo scope")

    captured_from_date = _filter_date(captured_from, "captured_from")
    captured_to_date = _filter_date(captured_to, "captured_to")
    if captured_from_date and captured_to_date and captured_from_date > captured_to_date:
        raise ValueError("captured_from cannot be later than captured_to")

    clauses = ["p.photographer_open_id = u.open_id"] if scope == "mine" else ["TRUE"]
    values: list[Any] = [user_id]
    if product_type:
        values.append(product_type)
        clauses.append(f"p.product_type = ${len(values)}")
    if inspection_category:
        prefixes = category_prefixes[inspection_category]
        values.append(prefixes)
        clauses.append(f"EXISTS (SELECT 1 FROM unnest(${len(values)}::text[]) prefix WHERE p.inspection_item LIKE prefix || '%')")
    if captured_from_date:
        values.append(datetime.combine(captured_from_date, time.min, CAPTURE_TIMEZONE))
        clauses.append(f"p.captured_at >= ${len(values)}")
    if captured_to_date:
        exclusive_end = datetime.combine(captured_to_date + timedelta(days=1), time.min, CAPTURE_TIMEZONE)
        values.append(exclusive_end)
        clauses.append(f"p.captured_at < ${len(values)}")
    for token in _search_tokens(search):
        values.append(token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_"))
        clauses.append(
            f"(p.search_text ILIKE '%' || ${len(values)} || '%' ESCAPE '\\' "
            f"OR COALESCE(p.photographer_name, '') ILIKE '%' || ${len(values)} || '%' ESCAPE '\\')"
        )

    connection = await asyncpg.connect(_dsn())
    try:
        rows = await connection.fetch(
            f"""SELECT p.id, p.original_filename, p.contract_no, p.product_type, p.specification,
                       p.inspection_item, p.captured_at, p.photographer_name
                FROM photo_records p JOIN users u ON u.id = $1::uuid
                WHERE {' AND '.join(clauses)}
                ORDER BY p.captured_at {'ASC' if sort == 'asc' else 'DESC'}, p.id DESC
                LIMIT 200""",
            *values,
        )
        return [
            {
                "id": str(row["id"]),
                "name": str(row["original_filename"] or "现场照片.jpg"),
                "contract_no": str(row["contract_no"] or ""),
                "product_type": str(row["product_type"] or "其它"),
                "specification": str(row["specification"] or ""),
                "inspection_item": str(row["inspection_item"] or ""),
                "captured_at": row["captured_at"].isoformat(),
                "photographer_name": str(row["photographer_name"] or ""),
            }
            for row in rows
        ]
    finally:
        await connection.close()


def _search_tokens(search: str | None) -> list[str]:
    """Split a user query while keeping Chinese terms intact for substring matching."""
    return [token for token in re.split(r"[\s,，、;；|]+", (search or "").strip()) if token][:8]


def _filter_date(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {field} date") from exc

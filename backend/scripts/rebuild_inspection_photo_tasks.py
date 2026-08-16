"""Rebuild the demo inspection task table with English Feishu field mappings.

Run from ``backend`` only after confirming that demo task data may be removed.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings

EXPECTED_COLUMNS = [
    "feishu_record_id", "contract_no", "sequence_no", "task_id", "product_type", "specification", "quantity",
    "inspection_stage", "inspector_name", "inspection_status", "inspector_open_id", "inspector_union_id",
    "created_at", "updated_at",
]


async def main() -> None:
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(dsn)
    try:
        columns = [
            "feishu_record_id VARCHAR(128) PRIMARY KEY",
            "contract_no TEXT NOT NULL",
            "sequence_no TEXT",
            "task_id TEXT",
            "product_type TEXT",
            "specification TEXT",
            "quantity TEXT",
            "inspection_stage TEXT",
            "inspector_name TEXT",
            "inspection_status TEXT",
            "inspector_open_id VARCHAR(128)",
            "inspector_union_id VARCHAR(128)",
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        ]
        async with connection.transaction():
            await connection.execute("DROP TABLE IF EXISTS inspection_photo_tasks CASCADE")
            await connection.execute(f"CREATE TABLE inspection_photo_tasks ({', '.join(columns)})")
            await connection.execute(
                "CREATE INDEX ix_photo_tasks_contract_product ON inspection_photo_tasks (contract_no, product_type)"
            )
            await connection.execute(
                "CREATE INDEX ix_photo_tasks_inspector_status ON inspection_photo_tasks (inspector_union_id, inspection_status)"
            )
            await connection.execute(
                "CREATE TRIGGER trg_inspection_photo_tasks_updated_at BEFORE UPDATE ON inspection_photo_tasks "
                "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
            )
        rows = await connection.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'inspection_photo_tasks' ORDER BY ordinal_position"
        )
        actual = [row["column_name"] for row in rows]
        if actual != EXPECTED_COLUMNS:
            raise RuntimeError(f"Unexpected inspection_photo_tasks columns: {actual}")
        print("Rebuilt inspection_photo_tasks with the English task schema.")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())

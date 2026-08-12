from __future__ import annotations

import json

import asyncpg

from app.core.config import settings
from app.services.feishu_auth import FeishuUser


class DatabaseUnavailable(RuntimeError):
    pass


def _dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def upsert_feishu_user(feishu_user: FeishuUser) -> asyncpg.Record:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    try:
        connection = await asyncpg.connect(_dsn())
    except (OSError, asyncpg.PostgresError) as exc:
        raise DatabaseUnavailable("PostgreSQL is unavailable; start the database and retry login") from exc
    try:
        return await connection.fetchrow(
            """
            INSERT INTO users (feishu_user_id, tenant_key, open_id, union_id, name, department_ids, character)
            VALUES ($1, COALESCE($2, ''), $3, $4, $5, $6::jsonb, 'inspector')
            ON CONFLICT (tenant_key, feishu_user_id) DO UPDATE SET
                open_id = EXCLUDED.open_id,
                union_id = EXCLUDED.union_id,
                name = EXCLUDED.name,
                department_ids = EXCLUDED.department_ids,
                is_active = TRUE,
                updated_at = NOW()
            RETURNING id
            """,
            feishu_user.user_id,
            feishu_user.tenant_key,
            feishu_user.open_id,
            feishu_user.union_id,
            feishu_user.name,
            json.dumps(feishu_user.department_ids),
        )
    except (OSError, asyncpg.PostgresError) as exc:
        raise DatabaseUnavailable("PostgreSQL write failed; check the database service and retry login") from exc
    finally:
        await connection.close()

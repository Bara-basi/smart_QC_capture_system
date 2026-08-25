from __future__ import annotations

import json
import logging

import asyncpg

from app.core.config import settings
from app.services.feishu_auth import FeishuUser

logger = logging.getLogger(__name__)


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
        try:
            return await _upsert_with_avatar(connection, feishu_user)
        except asyncpg.UndefinedColumnError:
            # Existing deployments may not yet have applied 006_user_avatar.sql.
            # Authentication must continue to work; the UI will show the surname
            # until the optional avatar migration is installed.
            logger.warning("avatar_url migration is not installed; logging in without a stored avatar")
            return await _upsert_without_avatar(connection, feishu_user)
    except (OSError, asyncpg.PostgresError) as exc:
        logger.exception("Unable to upsert the Feishu user")
        raise DatabaseUnavailable("PostgreSQL write failed; check the database service and retry login") from exc
    finally:
        await connection.close()


async def current_user_profile(user_id: str) -> dict[str, str | None]:
    """Return only the profile fields needed to identify the signed-in user."""
    try:
        connection = await asyncpg.connect(_dsn())
    except (OSError, asyncpg.PostgresError) as exc:
        raise DatabaseUnavailable("PostgreSQL is unavailable; retry shortly") from exc
    try:
        try:
            row = await connection.fetchrow(
                "SELECT id, name, avatar_url FROM users WHERE id = $1::uuid AND is_active = TRUE", user_id
            )
        except asyncpg.UndefinedColumnError:
            row = await connection.fetchrow(
                "SELECT id, name FROM users WHERE id = $1::uuid AND is_active = TRUE", user_id
            )
        if not row:
            raise DatabaseUnavailable("Current user no longer exists")
        return {"id": str(row["id"]), "name": str(row["name"]), "avatar_url": row.get("avatar_url")}
    finally:
        await connection.close()


async def _upsert_with_avatar(connection: asyncpg.Connection, user: FeishuUser) -> asyncpg.Record:
    return await connection.fetchrow(
        """
        INSERT INTO users (feishu_user_id, tenant_key, open_id, union_id, name, avatar_url, department_ids, character)
        VALUES ($1, COALESCE($2, ''), $3, $4, $5, $6, $7::jsonb, 'inspector')
        ON CONFLICT (tenant_key, feishu_user_id) DO UPDATE SET
            open_id = EXCLUDED.open_id, union_id = EXCLUDED.union_id, name = EXCLUDED.name,
            avatar_url = EXCLUDED.avatar_url, department_ids = EXCLUDED.department_ids,
            is_active = TRUE, updated_at = NOW()
        RETURNING id
        """,
        user.user_id, user.tenant_key, user.open_id, user.union_id, user.name,
        user.avatar_url, json.dumps(user.department_ids),
    )


async def _upsert_without_avatar(connection: asyncpg.Connection, user: FeishuUser) -> asyncpg.Record:
    return await connection.fetchrow(
        """
        INSERT INTO users (feishu_user_id, tenant_key, open_id, union_id, name, department_ids, character)
        VALUES ($1, COALESCE($2, ''), $3, $4, $5, $6::jsonb, 'inspector')
        ON CONFLICT (tenant_key, feishu_user_id) DO UPDATE SET
            open_id = EXCLUDED.open_id, union_id = EXCLUDED.union_id, name = EXCLUDED.name,
            department_ids = EXCLUDED.department_ids, is_active = TRUE, updated_at = NOW()
        RETURNING id
        """,
        user.user_id, user.tenant_key, user.open_id, user.union_id, user.name,
        json.dumps(user.department_ids),
    )

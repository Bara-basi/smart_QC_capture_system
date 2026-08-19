"""Create the project database (if needed) and apply its idempotent schema.

Run from the backend directory:
    .venv\\Scripts\\python.exe scripts\\init_database.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402

DATABASE_NAME = "smart_qc_capture_system"
DATABASE_DIR = Path(__file__).resolve().parents[2] / "database"
SCHEMA_PATH = DATABASE_DIR / "init" / "001_schema.sql"
MIGRATION_PATHS = sorted((DATABASE_DIR / "migrations").glob("*.sql"))


def asyncpg_dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def main() -> None:
    dsn = asyncpg_dsn()
    if not dsn or "CHANGE_ME" in dsn:
        raise RuntimeError("Set DATABASE_URL in backend/.env before initializing PostgreSQL.")

    admin_connection = await asyncpg.connect(dsn=dsn, database="postgres")
    try:
        exists = await admin_connection.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", DATABASE_NAME)
        if not exists:
            await admin_connection.execute(f'CREATE DATABASE "{DATABASE_NAME}"')
            print(f"Created database: {DATABASE_NAME}")
    finally:
        await admin_connection.close()

    connection = await asyncpg.connect(dsn=dsn, database=DATABASE_NAME)
    try:
        await connection.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
        for migration in MIGRATION_PATHS:
            await connection.execute(migration.read_text(encoding="utf-8"))
        print(f"Schema initialized successfully: {DATABASE_NAME}")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())

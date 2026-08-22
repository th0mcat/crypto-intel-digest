from pathlib import Path

import asyncpg

from app.config import settings
from app.log import log

_pool: asyncpg.Pool | None = None

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=8)
    return _pool


async def ping() -> bool:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:
        return False


async def schema_version() -> int | None:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval("SELECT max(version) FROM schema_version")
    except Exception:
        return None


async def migrate() -> None:
    """Apply numbered SQL files in app/migrations that haven't run yet.

    Idempotent and self-sufficient: ensures the vector extension and the
    schema_version table exist first, so it works whether or not the compose
    init script seeded the database. Each file is <NNN>_<name>.sql; the number
    is the version, recorded on success inside the same transaction.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "version integer PRIMARY KEY, "
            "applied_at timestamptz NOT NULL DEFAULT now())"
        )
        applied = {
            r["version"]
            for r in await conn.fetch("SELECT version FROM schema_version")
        }

    files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    for path in files:
        version = int(path.name[:3])
        if version in applied:
            continue
        sql = path.read_text()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_version (version) VALUES ($1)"
                    " ON CONFLICT DO NOTHING",
                    version,
                )
        log.info("migration_applied", version=version, file=path.name)

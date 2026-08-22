import json
from dataclasses import dataclass
from datetime import datetime

from app import db
from app.models import Event


@dataclass
class CollectorState:
    cursor: dict
    consecutive_failures: int


async def get_state(source: str) -> CollectorState:
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT cursor, consecutive_failures FROM collector_state WHERE source = $1",
            source,
        )
    if row is None:
        return CollectorState(cursor={}, consecutive_failures=0)
    return CollectorState(
        cursor=json.loads(row["cursor"]) if isinstance(row["cursor"], str) else row["cursor"],
        consecutive_failures=row["consecutive_failures"],
    )


async def save_state(source: str, cursor: dict, status: str, failures: int) -> None:
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO collector_state (source, cursor, last_run_at, last_status,
                                         consecutive_failures)
            VALUES ($1, $2, now(), $3, $4)
            ON CONFLICT (source) DO UPDATE SET
                cursor = EXCLUDED.cursor,
                last_run_at = EXCLUDED.last_run_at,
                last_status = EXCLUDED.last_status,
                consecutive_failures = EXCLUDED.consecutive_failures
            """,
            source,
            json.dumps(cursor),
            status[:500],
            failures,
        )


async def insert_raw(source_type: str, payload: dict, raw_hash: str) -> None:
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO raw_events (source_type, raw_hash, payload) VALUES ($1, $2, $3)",
            source_type,
            raw_hash,
            json.dumps(payload, default=str),
        )


async def seen_title_recent(title_hash: str, days: int) -> bool:
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        return bool(
            await conn.fetchval(
                "SELECT 1 FROM events WHERE title_hash = $1"
                " AND ingested_at > now() - ($2 || ' days')::interval LIMIT 1",
                title_hash,
                str(days),
            )
        )


async def insert_event(event: Event) -> bool:
    """Insert a normalised event. Returns False if it was an exact duplicate."""
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            """
            INSERT INTO events (source, source_type, author, url, title, raw_text,
                published_at, entities, source_reputation, raw_hash, title_hash,
                triage_score, triage_kept, triage_reasons)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            ON CONFLICT (raw_hash) DO NOTHING
            RETURNING id
            """,
            event.source,
            event.source_type,
            event.author,
            event.url,
            event.title,
            event.raw_text,
            event.published_at,
            json.dumps(event.entities),
            event.source_reputation,
            event.raw_hash,
            event.title_hash,
            event.triage_score,
            event.triage_kept,
            json.dumps(event.triage_reasons),
        )
    return result is not None


async def digest_candidates(limit: int = 30) -> list[dict]:
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, source, source_type, title, url, published_at,
                   triage_score, entities
            FROM events
            WHERE triage_kept = true AND digested = false
            ORDER BY triage_score DESC, published_at DESC NULLS LAST
            LIMIT $1
            """,
            limit,
        )
    return [dict(r) for r in rows]


async def mark_digested(ids: list) -> None:
    if not ids:
        return
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE events SET digested = true WHERE id = ANY($1::uuid[])", ids
        )


async def counts_since(hours: int) -> dict:
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                count(*) FILTER (WHERE triage_kept) AS kept,
                count(*) FILTER (WHERE NOT triage_kept) AS killed
            FROM events
            WHERE ingested_at > now() - ($1 || ' hours')::interval
            """,
            str(hours),
        )
    return {"kept": row["kept"], "killed": row["killed"]}


async def collector_health() -> list[dict]:
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT source, last_run_at, last_status, consecutive_failures"
            " FROM collector_state ORDER BY source"
        )
    return [dict(r) for r in rows]

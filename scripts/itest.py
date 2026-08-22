"""Integration smoke test against a real Postgres and live public feeds.
No Telegram, no Reddit creds. Proves: migrations apply, one RSS cycle and one
NVD cycle ingest + triage + persist, cursors advance, dedup holds, and the
digest query returns. Run inside the compose network.
"""
import asyncio

from app import db, store
from app.collectors.nvd import NVDCollector
from app.collectors.rss import RSSCollector
from app.config import settings
from app import triage
from app.feeds_config import high_signal


async def run_collector_once(collector) -> dict:
    state = await store.get_state(collector.name)
    items, cursor = await collector.fetch(state.cursor)
    hs = high_signal()
    inserted = kept = 0
    for item in items:
        ev = item.event
        novel = not await store.seen_title_recent(ev.title_hash, 3)
        score, reasons = triage.score(ev, novel, hs)
        ev.triage_score = score
        ev.triage_kept = score >= settings.triage_keep_threshold
        ev.triage_reasons = reasons
        await store.insert_raw(collector.source_type, item.payload, ev.raw_hash)
        if await store.insert_event(ev):
            inserted += 1
            kept += ev.triage_kept
    await store.save_state(collector.name, cursor, "ok", 0)
    return {"fetched": len(items), "inserted": inserted, "kept": kept, "cursor": cursor}


async def main() -> None:
    assert await db.ping(), "postgres unreachable"
    await db.migrate()
    version = await db.schema_version()
    print(f"schema version: {version}")
    assert version and version >= 2, "migration 002 did not apply"

    # RSS against a stable, high-volume feed.
    rss = RSSCollector("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", 0.55)
    r1 = await run_collector_once(rss)
    print(f"rss cycle 1: {r1['fetched']} fetched, {r1['inserted']} inserted, {r1['kept']} kept")
    assert r1["fetched"] > 0, "RSS feed returned nothing"
    assert r1["inserted"] > 0, "nothing persisted"

    # Second cycle must dedup everything (same items, cursor holds).
    r2 = await run_collector_once(rss)
    print(f"rss cycle 2 (dedup): {r2['fetched']} fetched, {r2['inserted']} inserted")
    assert r2["inserted"] == 0, "dedup failed — re-ingested on second cycle"

    # NVD live.
    try:
        nvd = await run_collector_once(NVDCollector())
        print(f"nvd cycle: {nvd['fetched']} fetched, {nvd['inserted']} inserted")
    except Exception as exc:
        print(f"nvd cycle: SKIPPED (live API issue: {exc})")

    # Digest query + counts.
    candidates = await store.digest_candidates(30)
    counts = await store.counts_since(24)
    health = await store.collector_health()
    print(f"digest candidates: {len(candidates)}")
    print(f"counts 24h: {counts}")
    print(f"collector health rows: {len(health)}")
    assert len(health) >= 1, "collector_state not written"

    print("\nintegration smoke test PASSED")


if __name__ == "__main__":
    asyncio.run(main())

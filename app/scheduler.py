import asyncio

from app import store
from app.collectors.base import Collector
from app.collectors.nvd import NVDCollector
from app.collectors.reddit import RedditCollector
from app.collectors.rss import RSSCollector
from app.config import settings
from app.feeds_config import high_signal, load
from app.log import log
from app import triage

# Circuit breaker: after repeated failures, back off up to this multiple of the
# base interval so a down source stops hammering (and stops spamming logs).
MAX_BACKOFF_MULTIPLIER = 12


def build_collectors() -> list[tuple[Collector, int]]:
    """Return (collector, base_interval_seconds) pairs from feeds.yaml."""
    cfg = load()
    collectors: list[tuple[Collector, int]] = []

    for feed in cfg["rss"]:
        collectors.append(
            (
                RSSCollector(feed["name"], feed["url"], feed.get("reputation", 0.5)),
                settings.rss_interval_seconds,
            )
        )

    if RedditCollector.enabled():
        for sub in cfg["reddit"]:
            collectors.append(
                (
                    RedditCollector(sub["name"], sub.get("reputation", 0.4)),
                    settings.reddit_interval_seconds,
                )
            )
    else:
        log.warning("reddit_disabled", reason="REDDIT_CLIENT_ID/SECRET not set")

    collectors.append((NVDCollector(), settings.nvd_interval_seconds))
    return collectors


async def _run_once(collector: Collector) -> None:
    state = await store.get_state(collector.name)
    items, cursor = await collector.fetch(state.cursor)

    kept = inserted = 0
    hs = high_signal()
    for item in items:
        event = item.event
        is_novel = not await store.seen_title_recent(event.title_hash, 3)
        score, reasons = triage.score(event, is_novel, hs)
        event.triage_score = score
        event.triage_kept = score >= settings.triage_keep_threshold
        event.triage_reasons = reasons

        await store.insert_raw(collector.source_type, item.payload, event.raw_hash)
        if await store.insert_event(event):
            inserted += 1
            if event.triage_kept:
                kept += 1

    await store.save_state(collector.name, cursor, "ok", 0)
    log.info(
        "collector_cycle",
        collector=collector.name,
        fetched=len(items),
        inserted=inserted,
        kept=kept,
    )


async def _collector_loop(collector: Collector, base_interval: int) -> None:
    while True:
        try:
            await _run_once(collector)
            await asyncio.sleep(base_interval)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state = await store.get_state(collector.name)
            failures = state.consecutive_failures + 1
            await store.save_state(
                collector.name, state.cursor, f"error: {exc}", failures
            )
            backoff = base_interval * min(2 ** failures, MAX_BACKOFF_MULTIPLIER)
            log.error(
                "collector_failed",
                collector=collector.name,
                failures=failures,
                backoff_s=backoff,
                error=str(exc),
            )
            await asyncio.sleep(backoff)


def start(tasks: set[asyncio.Task]) -> None:
    """Launch one supervised task per collector; caller owns cancellation."""
    for collector, interval in build_collectors():
        tasks.add(asyncio.create_task(_collector_loop(collector, interval)))
    log.info("scheduler_started", collectors=len(tasks))

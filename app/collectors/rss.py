import asyncio
from datetime import datetime, timezone

import aiohttp
import feedparser

from app.collectors.base import Collector
from app.feeds_config import keywords
from app.models import Event, RawItem
from app.normalise import extract_entities

# Cap per cycle so a first run against a fat feed can't flood triage.
MAX_ITEMS = 40


def _published(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


class RSSCollector(Collector):
    source_type = "rss"

    def __init__(self, name: str, url: str, reputation: float) -> None:
        self.name = f"rss:{name}"
        self.url = url
        self.reputation = reputation

    async def fetch(self, cursor: dict) -> tuple[list[RawItem], dict]:
        seen: set[str] = set(cursor.get("seen_ids", []))
        async with aiohttp.ClientSession(
            headers={"User-Agent": "intel-system/0.2"}
        ) as session:
            async with session.get(
                self.url, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                resp.raise_for_status()
                body = await resp.text()

        # feedparser is CPU-bound C parsing; keep the event loop responsive.
        parsed = await asyncio.to_thread(feedparser.parse, body)

        items: list[RawItem] = []
        fresh_ids: list[str] = []
        for entry in parsed.entries[:MAX_ITEMS]:
            uid = entry.get("id") or entry.get("link") or entry.get("title", "")
            if not uid:
                continue
            fresh_ids.append(uid)
            if uid in seen:
                continue
            title = (entry.get("title") or "").strip()
            if not title:
                continue
            summary = (entry.get("summary") or "").strip()
            text = f"{title}\n{summary}"
            event = Event(
                source=self.name,
                source_type=self.source_type,
                title=title,
                url=entry.get("link", ""),
                author=entry.get("author"),
                raw_text=summary,
                published_at=_published(entry),
                entities=extract_entities(text, keywords()),
                source_reputation=self.reputation,
            )
            items.append(RawItem(payload=dict(entry), event=event))

        # Bound the cursor: keep the most recent ids we saw this cycle.
        new_cursor = {"seen_ids": (fresh_ids + list(seen))[:200]}
        return items, new_cursor

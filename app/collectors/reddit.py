import time
from datetime import datetime, timezone

import aiohttp

from app.collectors.base import Collector
from app.config import settings
from app.feeds_config import keywords
from app.models import Event, RawItem
from app.normalise import extract_entities

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"
MAX_ITEMS = 25


class RedditCollector(Collector):
    """App-only OAuth against a single subreddit's /new. No user password:
    grant_type=client_credentials. Disabled entirely if creds are absent.
    """

    source_type = "reddit"

    def __init__(self, subreddit: str, reputation: float) -> None:
        self.subreddit = subreddit
        self.name = f"reddit:{subreddit}"
        self.reputation = reputation
        self._token: str | None = None
        self._token_expiry = 0.0

    @staticmethod
    def enabled() -> bool:
        return bool(settings.reddit_client_id and settings.reddit_client_secret)

    async def _get_token(self, session: aiohttp.ClientSession) -> str:
        if self._token and time.monotonic() < self._token_expiry - 60:
            return self._token
        auth = aiohttp.BasicAuth(
            settings.reddit_client_id, settings.reddit_client_secret
        )
        async with session.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=auth,
            headers={"User-Agent": settings.reddit_user_agent},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
        self._token = data["access_token"]
        self._token_expiry = time.monotonic() + data.get("expires_in", 3600)
        return self._token

    async def fetch(self, cursor: dict) -> tuple[list[RawItem], dict]:
        last_seen = float(cursor.get("last_created_utc", 0))
        async with aiohttp.ClientSession(
            headers={"User-Agent": settings.reddit_user_agent}
        ) as session:
            token = await self._get_token(session)
            async with session.get(
                f"{API_BASE}/r/{self.subreddit}/new",
                params={"limit": MAX_ITEMS},
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        children = data.get("data", {}).get("children", [])
        items: list[RawItem] = []
        max_created = last_seen
        for child in children:
            post = child.get("data", {})
            created = float(post.get("created_utc", 0))
            max_created = max(max_created, created)
            # First run (no cursor) seeds the cursor without emitting history.
            if last_seen == 0 or created <= last_seen:
                continue
            title = (post.get("title") or "").strip()
            if not title:
                continue
            body = (post.get("selftext") or "").strip()
            text = f"{title}\n{body}"
            permalink = post.get("permalink", "")
            event = Event(
                source=self.name,
                source_type=self.source_type,
                title=title,
                url=f"https://reddit.com{permalink}" if permalink else post.get("url", ""),
                author=post.get("author"),
                raw_text=body,
                published_at=datetime.fromtimestamp(created, tz=timezone.utc),
                entities=extract_entities(text, keywords()),
                source_reputation=self.reputation,
            )
            items.append(RawItem(payload=post, event=event))

        return items, {"last_created_utc": max_created}

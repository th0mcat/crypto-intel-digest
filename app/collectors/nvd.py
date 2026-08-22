from datetime import datetime, timedelta, timezone

import aiohttp

from app.collectors.base import Collector
from app.config import settings
from app.feeds_config import keywords, nvd_keywords
from app.models import Event, RawItem
from app.normalise import extract_entities

API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
# NVD wants naive ISO with millis. First run looks back this far, then the
# cursor takes over.
FIRST_RUN_LOOKBACK = timedelta(days=1)
MAX_ITEMS = 60


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000")


class NVDCollector(Collector):
    """Recently published CVEs from the NVD 2.0 API. Works keyless (rate
    limited); an optional apiKey raises the limit.
    """

    name = "nvd:recent"
    source_type = "nvd"

    def __init__(self, reputation: float = 0.7) -> None:
        self.reputation = reputation

    async def fetch(self, cursor: dict) -> tuple[list[RawItem], dict]:
        now = datetime.now(timezone.utc)
        last = cursor.get("last_pub")
        start = (
            datetime.fromisoformat(last)
            if last
            else now - FIRST_RUN_LOOKBACK
        )

        headers = {"User-Agent": "intel-system/0.2"}
        if settings.nvd_api_key:
            headers["apiKey"] = settings.nvd_api_key

        params = {
            "pubStartDate": _fmt(start),
            "pubEndDate": _fmt(now),
            "resultsPerPage": MAX_ITEMS,
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(
                API_URL, params=params, timeout=aiohttp.ClientTimeout(total=40)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        items: list[RawItem] = []
        max_pub = start
        for vuln in data.get("vulnerabilities", []):
            cve = vuln.get("cve", {})
            cve_id = cve.get("id", "")
            if not cve_id:
                continue
            published = cve.get("published")
            pub_dt = (
                datetime.fromisoformat(published).replace(tzinfo=timezone.utc)
                if published
                else now
            )
            max_pub = max(max_pub, pub_dt)
            descs = cve.get("descriptions", [])
            desc = next(
                (d["value"] for d in descs if d.get("lang") == "en"),
                descs[0]["value"] if descs else "",
            )
            text = f"{cve_id} {desc}"
            # NVD is a firehose of mostly-irrelevant CVEs, and generic terms
            # ("vulnerability", "exploit") match nearly all of them. Scope it
            # to named primitives/libraries/protocols instead. This is source
            # scoping, not hidden triage — unmatched CVEs are never ingested
            # rather than ingested-then-killed, because logging the entire
            # global CVE feed as kills would bloat the DB for no signal.
            lowered = text.lower()
            if not any(kw.lower() in lowered for kw in nvd_keywords()):
                continue
            # Tag with both the general watchlist and the NVD-specific terms so
            # triage materiality reflects what actually matched.
            entities = extract_entities(text, keywords() + nvd_keywords())
            title = f"{cve_id}: {desc[:120]}"
            entities.append({"type": "cve", "value": cve_id})
            event = Event(
                source=self.name,
                source_type=self.source_type,
                title=title,
                url=f"https://nvd.nist.gov/vuln/detail/{cve_id}",
                raw_text=desc,
                published_at=pub_dt,
                entities=entities,
                source_reputation=self.reputation,
            )
            items.append(RawItem(payload=cve, event=event))

        return items, {"last_pub": max_pub.isoformat()}

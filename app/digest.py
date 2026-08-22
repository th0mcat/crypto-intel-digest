import asyncio
import html
from datetime import datetime, timedelta, timezone

from app import store
from app.config import settings
from app.log import log
from app.notifier import Notifier, Priority

MAX_ITEMS = 30
# Volume floor from the spec: precision is meaningless if the filter games it
# by going silent. Below this many kept items/day, flag the quiet, don't hide it.
QUIET_FLOOR = 5


def _seconds_until_next_run() -> float:
    now = datetime.now(timezone.utc)
    target = now.replace(
        hour=settings.digest_hour_utc, minute=0, second=0, microsecond=0
    )
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _format(candidates: list[dict], counts: dict) -> str:
    lines: list[str] = []
    by_type: dict[str, list[dict]] = {}
    for c in candidates:
        by_type.setdefault(c["source_type"], []).append(c)

    for source_type in sorted(by_type):
        lines.append(f"\n<b>{source_type.upper()}</b>")
        for c in by_type[source_type]:
            title = html.escape(c["title"][:200])
            url = c["url"]
            score = c["triage_score"]
            src = html.escape(c["source"])
            head = f'<a href="{html.escape(url)}">{title}</a>' if url else title
            lines.append(f"• {head}\n  <i>{src} · score {score:.2f}</i>")

    footer = (
        f"\n\n<i>{counts['kept']} kept / {counts['killed']} killed in 24h.</i>"
    )
    if counts["kept"] < QUIET_FLOOR:
        footer += (
            f"\n<i>⚠ Below volume floor ({QUIET_FLOOR}/day) — check the "
            f"filter isn't silently over-killing.</i>"
        )
    return "\n".join(lines) + footer


async def send_now(notifier: Notifier) -> None:
    candidates = await store.digest_candidates(MAX_ITEMS)
    counts = await store.counts_since(24)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if not candidates:
        body = (
            f"Nothing cleared triage in the last cycle.\n\n"
            f"<i>{counts['killed']} items killed in 24h.</i>"
        )
        if counts["killed"] == 0:
            body += "\n<i>⚠ Zero items ingested — collectors may be down. /sources</i>"
        await notifier.send(Priority.P2, f"Daily brief · {date}", body)
        return

    body = _format(candidates, counts)
    await notifier.send(Priority.P2, f"Daily brief · {date}", body)
    await store.mark_digested([c["id"] for c in candidates])
    log.info("digest_sent", items=len(candidates))


async def digest_loop(notifier: Notifier) -> None:
    while True:
        wait = _seconds_until_next_run()
        log.info("digest_scheduled", seconds=int(wait))
        await asyncio.sleep(wait)
        try:
            await send_now(notifier)
        except Exception as exc:
            log.error("digest_failed", error=str(exc))

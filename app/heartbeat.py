"""External dead-man's switch.

Pings HEALTHCHECK_URL only when the core dependencies answer, so a wedged
database shows up as a missed ping on healthchecks.io — which alerts from
*their* infrastructure. A dead VPS cannot report itself dead; this can't
either, and that's the point of keeping the switch off-box.
"""
import asyncio

import aiohttp

from app import db
from app.config import settings
from app.log import log


async def heartbeat_loop() -> None:
    if not settings.healthcheck_url:
        log.warning("heartbeat_disabled", reason="HEALTHCHECK_URL not set")
        return
    while True:
        db_ok = await db.ping()
        if db_ok:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        settings.healthcheck_url,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        log.info("heartbeat_ping", status=resp.status)
            except Exception as exc:
                log.warning("heartbeat_ping_failed", error=str(exc))
        else:
            log.error("heartbeat_skipped", reason="db unreachable")
        await asyncio.sleep(settings.heartbeat_interval_seconds)

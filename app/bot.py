import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app import VERSION, db, digest, store
from app.config import settings
from app.log import log
from app.notifier import Notifier

START_TIME = time.monotonic()

router = Router()
# Operator-only: every message from any other id is silently dropped.
router.message.filter(F.from_user.id == settings.telegram_operator_id)


def _uptime() -> str:
    seconds = int(time.monotonic() - START_TIME)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    return f"{days}d {hours}h {minutes}m"


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Online. Commands:\n"
        "/status — health\n"
        "/sources — collector health\n"
        "/kills — triage stats (24h)\n"
        "/digest — send the daily brief now"
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    db_ok = await db.ping()
    version = await db.schema_version()
    lines = [
        f"version: {VERSION}",
        f"uptime: {_uptime()}",
        f"postgres: {'ok' if db_ok else 'UNREACHABLE'}",
        f"schema: {version if version is not None else 'unknown'}",
        f"dead-man switch: {'armed' if settings.healthcheck_url else 'NOT CONFIGURED'}",
    ]
    log.info("status_requested", db_ok=db_ok)
    await message.answer("\n".join(lines))


@router.message(Command("sources"))
async def cmd_sources(message: Message) -> None:
    health = await store.collector_health()
    if not health:
        await message.answer("No collectors have run yet.")
        return
    lines = []
    for h in health:
        flag = "⚠️" if h["consecutive_failures"] else "✅"
        last = h["last_run_at"].strftime("%H:%M") if h["last_run_at"] else "never"
        status = (h["last_status"] or "")[:60]
        lines.append(f"{flag} {h['source']} · {last} · {status}")
    await message.answer("\n".join(lines))


@router.message(Command("kills"))
async def cmd_kills(message: Message) -> None:
    counts = await store.counts_since(24)
    total = counts["kept"] + counts["killed"]
    rate = (counts["killed"] / total * 100) if total else 0
    await message.answer(
        f"Last 24h: {counts['kept']} kept, {counts['killed']} killed "
        f"({rate:.0f}% kill rate)."
    )


@router.message(Command("digest"))
async def cmd_digest(message: Message, notifier: Notifier) -> None:
    await message.answer("Building brief…")
    await digest.send_now(notifier)

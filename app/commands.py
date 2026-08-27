"""Channel-agnostic command implementations.

Both the Telegram bot (app/bot.py) and the Matrix bot (app/matrix_bot.py)
call these helpers, which return plain-text / HTML strings that the caller
then sends through its own channel adapter.  Business logic lives here once;
formatting adapters live in the callers.
"""
import time
from typing import TYPE_CHECKING

from app import VERSION, db, store
from app.log import log

if TYPE_CHECKING:
    from app.notifier import Notifier

# Start time shared across both adapters so /status and !status agree.
_START_TIME = time.monotonic()


def uptime() -> str:
    seconds = int(time.monotonic() - _START_TIME)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    return f"{days}d {hours}h {minutes}m"


def start_text(command_prefix: str = "/") -> str:
    p = command_prefix
    lines = [
        "Online. Commands:",
        f"{p}status — health",
        f"{p}sources — collector health",
        f"{p}kills — triage stats (24h)",
        f"{p}digest — send the daily brief now",
    ]
    # For the bang-prefix channel (Matrix) also list start/help explicitly,
    # since there is no built-in slash-command discovery like Telegram has.
    if p == "!":
        lines.append(f"{p}start / {p}help — show this message")
    return "\n".join(lines)


async def status_text(*, healthcheck_url: str) -> str:
    db_ok = await db.ping()
    version = await db.schema_version()
    log.info("status_requested", db_ok=db_ok)
    lines = [
        f"version: {VERSION}",
        f"uptime: {uptime()}",
        f"postgres: {'ok' if db_ok else 'UNREACHABLE'}",
        f"schema: {version if version is not None else 'unknown'}",
        f"dead-man switch: {'armed' if healthcheck_url else 'NOT CONFIGURED'}",
    ]
    return "\n".join(lines)


async def sources_text() -> str:
    health = await store.collector_health()
    if not health:
        return "No collectors have run yet."
    lines = []
    for h in health:
        flag = "⚠️" if h["consecutive_failures"] else "✅"
        last = h["last_run_at"].strftime("%H:%M") if h["last_run_at"] else "never"
        status = (h["last_status"] or "")[:60]
        lines.append(f"{flag} {h['source']} · {last} · {status}")
    return "\n".join(lines)


async def kills_text() -> str:
    counts = await store.counts_since(24)
    total = counts["kept"] + counts["killed"]
    rate = (counts["killed"] / total * 100) if total else 0
    return (
        f"Last 24h: {counts['kept']} kept, {counts['killed']} killed "
        f"({rate:.0f}% kill rate)."
    )


def parse_bang_command(text: str) -> str | None:
    """Return the bare command name (e.g. 'status') if *text* is a valid
    bang command (``!status``, ``!digest``, …), else ``None``.

    Leading/trailing whitespace and any trailing arguments are tolerated.
    Only the first word is examined.
    """
    text = text.strip()
    if not text.startswith("!"):
        return None
    first_word = text.split()[0]  # "!status" or "!status some args"
    command = first_word[1:].lower()
    if command and command.isalpha():
        return command
    return None

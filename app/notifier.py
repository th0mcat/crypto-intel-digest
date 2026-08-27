"""Channel-agnostic notification layer.

Telegram is the primary channel.  Matrix is an optional second channel.
Both implement the ``Notifier`` ABC so callers are unaware of which channel
they're talking to.  When both are configured, ``CompositeNotifier`` fans
out to all of them transparently.
"""
from abc import ABC, abstractmethod
from enum import IntEnum
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.enums import ParseMode

from app.log import log

if TYPE_CHECKING:
    import nio

TELEGRAM_LIMIT = 4096
MATRIX_LIMIT = 16384  # conservative cap; spec has no hard limit but large events are bad


class Priority(IntEnum):
    P0 = 0  # immediate
    P1 = 1  # hourly digest
    P2 = 2  # daily brief
    P3 = 3  # weekly review


_PREFIX = {
    Priority.P0: "\U0001F6A8 P0",
    Priority.P1: "\U0001F535 P1",
    Priority.P2: "\U0001F4F0 P2",
    Priority.P3: "\U0001F4CA P3",
}


def _chunk(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            if current:
                chunks.append(current)
            # A single over-long line is hard-split.
            while len(line) > limit:
                chunks.append(line[:limit])
                line = line[limit:]
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


class Notifier(ABC):
    @abstractmethod
    async def send(self, priority: Priority, title: str, body: str) -> None: ...


class TelegramNotifier(Notifier):
    def __init__(self, bot: Bot, operator_id: int) -> None:
        self._bot = bot
        self._operator_id = operator_id

    async def send(self, priority: Priority, title: str, body: str) -> None:
        header = f"<b>{_PREFIX[priority]} — {title}</b>"
        message = f"{header}\n\n{body}" if body else header
        for chunk in _chunk(message):
            await self._bot.send_message(
                self._operator_id,
                chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        log.info("notify_sent", channel="telegram", priority=priority.name, title=title)


class MatrixNotifier(Notifier):
    """Sends notifications to a Matrix room via an ``nio.AsyncClient``."""

    def __init__(self, client: "nio.AsyncClient", room_id: str) -> None:
        self._client = client
        self._room_id = room_id

    async def send(self, priority: Priority, title: str, body: str) -> None:
        header = f"**{_PREFIX[priority]} — {title}**"
        message = f"{header}\n\n{body}" if body else header
        for chunk in _chunk(message, limit=MATRIX_LIMIT):
            await self._client.room_send(
                room_id=self._room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.notice",
                    "body": chunk,
                },
            )
        log.info("notify_sent", channel="matrix", priority=priority.name, title=title)


class CompositeNotifier(Notifier):
    """Fan-out to multiple notifiers.  All of them receive every message."""

    def __init__(self, notifiers: list[Notifier]) -> None:
        if not notifiers:
            raise ValueError("CompositeNotifier requires at least one Notifier")
        self._notifiers = notifiers

    async def send(self, priority: Priority, title: str, body: str) -> None:
        for notifier in self._notifiers:
            await notifier.send(priority, title, body)


class WhatsAppNotifier(Notifier):
    """Placeholder for a future WhatsApp Business Cloud API adapter.

    Not implemented: outside the 24h session window WhatsApp permits only
    pre-approved template messages, so P0 alerts (unpredictable, out-of-window)
    would need a template-teaser -> reply -> in-session-detail flow. Build only
    if a concrete need outweighs that friction. Kept here so the Notifier
    contract is visibly channel-agnostic.
    """

    def __init__(self, *_, **__) -> None:  # pragma: no cover
        raise NotImplementedError(
            "WhatsApp adapter is a documented stub; Telegram is the Phase 1 channel."
        )

    async def send(self, priority: Priority, title: str, body: str) -> None:  # pragma: no cover
        raise NotImplementedError


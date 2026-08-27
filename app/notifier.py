"""Notification layer — maubot edition.

``MaubotNotifier`` uses the maubot plugin's ``self.client`` (a
``mautrix.client.Client`` subclass) to send HTML notices to a Matrix room.
The ``Notifier`` ABC and ``Priority`` enum are retained so the rest of the
code (``digest.py``, command handlers, etc.) stays channel-agnostic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import IntEnum
from typing import TYPE_CHECKING

from app.log import log

if TYPE_CHECKING:
    from mautrix.client import Client

MATRIX_LIMIT = 16_384  # conservative cap; large events are bad UX


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


def _chunk(text: str, limit: int = MATRIX_LIMIT) -> list[str]:
    """Split *text* along line boundaries so no chunk exceeds *limit* chars."""
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            if current:
                chunks.append(current)
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


class MaubotNotifier(Notifier):
    """Sends HTML notices to a Matrix room via the maubot plugin client.

    The ``client`` is the ``MaubotMatrixClient`` exposed as ``self.client``
    on the plugin instance.  ``room_id`` is the target room
    (e.g. ``!abc123:example.org``).
    """

    def __init__(self, client: "Client", room_id: str) -> None:
        self._client = client
        self._room_id = room_id

    async def send(self, priority: Priority, title: str, body: str) -> None:
        prefix = _PREFIX[priority]
        # Build an HTML version with bold header; fall back to plain text.
        html_header = f"<strong>{prefix} — {title}</strong>"
        plain_header = f"{prefix} — {title}"

        html_message = f"{html_header}<br><br>{body}" if body else html_header
        plain_message = f"{plain_header}\n\n{body}" if body else plain_header

        for plain_chunk, html_chunk in zip(
            _chunk(plain_message), _chunk(html_message)
        ):
            await self._client.send_notice(
                self._room_id,
                text=plain_chunk,
                html=html_chunk,
            )
        log.info(
            "notify_sent",
            channel="matrix",
            priority=priority.name,
            title=title,
            room=self._room_id,
        )


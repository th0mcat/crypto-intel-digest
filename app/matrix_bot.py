"""Matrix client: inbound command handling and outbound notifications.

Uses ``matrix-nio``'s ``AsyncClient``.  The bot logs in with an access token
(preferred) or password, syncs with ``sync_forever``, and responds only to
messages from ``matrix_operator_user_id`` in ``matrix_room_id`` that begin
with a bang prefix (``!status``, ``!sources``, ``!kills``, ``!digest``,
``!start`` / ``!help``).

Start with ``run_matrix_bot(notifier)`` as a supervised asyncio task from
``app/main.py``.
"""
from __future__ import annotations

import asyncio

import nio

from app import digest
from app.commands import (
    kills_text,
    parse_bang_command,
    sources_text,
    start_text,
    status_text,
)
from app.config import channel_mode, settings
from app.log import log
from app.notifier import MATRIX_LIMIT, Notifier


def matrix_enabled() -> bool:
    """Return True when the active channel mode is Matrix."""
    try:
        return channel_mode() == "matrix"
    except RuntimeError:
        return False


async def _send_notice(client: nio.AsyncClient, room_id: str, text: str) -> None:
    """Send *text* as an ``m.notice`` event, chunking if necessary."""
    if not text:
        return
    # Chunk along line boundaries, same philosophy as TelegramNotifier.
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > MATRIX_LIMIT:
            if current:
                chunks.append(current)
            while len(line) > MATRIX_LIMIT:
                chunks.append(line[:MATRIX_LIMIT])
                line = line[MATRIX_LIMIT:]
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)

    for chunk in chunks:
        await client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={"msgtype": "m.notice", "body": chunk},
        )


async def _handle_message(
    client: nio.AsyncClient,
    room: nio.MatrixRoom,
    event: nio.RoomMessageText,
    notifier: Notifier,
) -> None:
    """Dispatch a single inbound Matrix message event."""
    # Only act in the configured room.
    if room.room_id != settings.matrix_room_id:
        return
    # Ignore the bot's own messages.
    if event.sender == settings.matrix_user_id:
        return
    # Operator-only: silently drop everyone else.
    if settings.matrix_operator_user_id and event.sender != settings.matrix_operator_user_id:
        return

    body: str = event.body or ""
    command = parse_bang_command(body)
    if command is None:
        return  # not a bang command — ignore

    log.info("matrix_command", command=command, sender=event.sender)
    room_id = settings.matrix_room_id

    if command in ("start", "help"):
        text = start_text("!")
    elif command == "status":
        text = await status_text(healthcheck_url=settings.healthcheck_url)
    elif command == "sources":
        text = await sources_text()
    elif command == "kills":
        text = await kills_text()
    elif command == "digest":
        await _send_notice(client, room_id, "Building brief…")
        await digest.send_now(notifier)
        return
    else:
        text = f"Unknown command: !{command}. Try !help"

    await _send_notice(client, room_id, text)


async def run_matrix_bot(
    notifier: Notifier, client: nio.AsyncClient | None = None
) -> None:
    """Long-running Matrix sync loop.  Designed to run as an asyncio task.

    If *client* is provided it must already be authenticated; ``run_matrix_bot``
    will register the message callback and start ``sync_forever`` without
    performing login or closing the client (the caller owns the lifecycle).
    If *client* is None (legacy / standalone usage) this function creates,
    authenticates, and closes its own client.
    """
    if not matrix_enabled():
        log.warning("matrix_disabled", reason="required Matrix settings not set")
        return

    caller_owns_client = client is not None
    if client is None:
        client = nio.AsyncClient(settings.matrix_homeserver_url, settings.matrix_user_id)

    try:
        if not caller_owns_client:
            # Authenticate: token preferred, password as fallback.
            if settings.matrix_access_token:
                client.access_token = settings.matrix_access_token
                client.user_id = settings.matrix_user_id
                log.info("matrix_authenticated", method="token", user=settings.matrix_user_id)
            else:
                resp = await client.login(settings.matrix_password)
                if isinstance(resp, nio.LoginError):
                    log.error("matrix_login_failed", error=str(resp))
                    return
                log.info("matrix_authenticated", method="password", user=settings.matrix_user_id)

        # Register message callback.
        async def _on_message(
            room: nio.MatrixRoom, event: nio.RoomMessageText
        ) -> None:
            try:
                await _handle_message(client, room, event, notifier)  # type: ignore[arg-type]
            except Exception as exc:
                log.error("matrix_handler_error", error=str(exc))

        client.add_event_callback(_on_message, nio.RoomMessageText)  # type: ignore[arg-type]

        log.info("matrix_sync_starting", room=settings.matrix_room_id)
        await client.sync_forever(timeout=30_000)

    except asyncio.CancelledError:
        log.info("matrix_loop_cancelled")
    except Exception as exc:
        log.error("matrix_loop_error", error=str(exc))
    finally:
        if not caller_owns_client:
            await client.close()
        log.info("matrix_client_closed")

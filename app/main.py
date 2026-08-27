import asyncio

from aiogram import Bot, Dispatcher

from app import VERSION, db, scheduler
from app.bot import router
from app.config import settings
from app.digest import digest_loop
from app.heartbeat import heartbeat_loop
from app.log import configure_logging, log
from app.matrix_bot import matrix_enabled, run_matrix_bot
from app.notifier import (
    CompositeNotifier,
    MatrixNotifier,
    Notifier,
    Priority,
    TelegramNotifier,
)

import nio


async def main() -> None:
    configure_logging()
    log.info("starting", version=VERSION)

    if not await db.ping():
        raise RuntimeError("postgres unreachable at startup")
    await db.migrate()

    bot = Bot(token=settings.telegram_bot_token)
    tg_notifier: Notifier = TelegramNotifier(bot, settings.telegram_operator_id)

    matrix_client: nio.AsyncClient | None = None
    notifiers: list[Notifier] = [tg_notifier]

    if matrix_enabled():
        matrix_client = nio.AsyncClient(
            settings.matrix_homeserver_url, settings.matrix_user_id
        )
        if settings.matrix_access_token:
            matrix_client.access_token = settings.matrix_access_token
            matrix_client.user_id = settings.matrix_user_id
            log.info("matrix_authenticated", method="token", user=settings.matrix_user_id)
        else:
            resp = await matrix_client.login(settings.matrix_password)
            if isinstance(resp, nio.LoginError):
                await matrix_client.close()
                raise RuntimeError(f"Matrix password login failed: {resp}")
            log.info("matrix_authenticated", method="password", user=settings.matrix_user_id)
        notifiers.append(MatrixNotifier(matrix_client, settings.matrix_room_id))
        log.info("matrix_enabled", room=settings.matrix_room_id)

    notifier: Notifier = (
        CompositeNotifier(notifiers) if len(notifiers) > 1 else notifiers[0]
    )

    dp = Dispatcher()
    dp["notifier"] = notifier  # injected into handlers that declare it
    dp.include_router(router)

    tasks: set[asyncio.Task] = set()
    tasks.add(asyncio.create_task(heartbeat_loop()))
    tasks.add(asyncio.create_task(digest_loop(notifier)))
    if matrix_enabled():
        tasks.add(asyncio.create_task(run_matrix_bot(notifier)))
    scheduler.start(tasks)

    try:
        await notifier.send(
            Priority.P2, "System online", f"Collectors starting (v{VERSION})."
        )
        log.info("polling_started")
        await dp.start_polling(bot)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await bot.session.close()
        if matrix_client is not None:
            await matrix_client.close()


if __name__ == "__main__":
    asyncio.run(main())


import asyncio

from aiogram import Bot, Dispatcher

from app import VERSION, db, scheduler
from app.bot import router
from app.config import settings
from app.digest import digest_loop
from app.heartbeat import heartbeat_loop
from app.log import configure_logging, log
from app.notifier import Priority, TelegramNotifier


async def main() -> None:
    configure_logging()
    log.info("starting", version=VERSION)

    if not await db.ping():
        raise RuntimeError("postgres unreachable at startup")
    await db.migrate()

    bot = Bot(token=settings.telegram_bot_token)
    notifier = TelegramNotifier(bot, settings.telegram_operator_id)

    dp = Dispatcher()
    dp["notifier"] = notifier  # injected into handlers that declare it
    dp.include_router(router)

    tasks: set[asyncio.Task] = set()
    tasks.add(asyncio.create_task(heartbeat_loop()))
    tasks.add(asyncio.create_task(digest_loop(notifier)))
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


if __name__ == "__main__":
    asyncio.run(main())

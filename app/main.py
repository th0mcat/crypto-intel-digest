import asyncio

from app import VERSION, db, scheduler
from app.config import channel_mode, settings
from app.digest import digest_loop
from app.heartbeat import heartbeat_loop
from app.log import configure_logging, log
from app.notifier import MatrixNotifier, Notifier, Priority, TelegramNotifier

import nio


async def main() -> None:
    configure_logging()
    log.info("starting", version=VERSION)

    if not await db.ping():
        raise RuntimeError("postgres unreachable at startup")
    await db.migrate()

    mode = channel_mode()
    log.info("channel_mode", mode=mode)

    tasks: set[asyncio.Task] = set()

    if mode == "telegram":
        from aiogram import Bot, Dispatcher
        from app.bot import router

        bot = Bot(token=settings.telegram_bot_token)
        notifier: Notifier = TelegramNotifier(bot, settings.telegram_operator_id)

        dp = Dispatcher()
        dp["notifier"] = notifier
        dp.include_router(router)

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

    else:  # matrix mode
        from app.matrix_bot import run_matrix_bot

        matrix_client = nio.AsyncClient(
            settings.matrix_homeserver_url, settings.matrix_user_id
        )
        try:
            if settings.matrix_access_token:
                matrix_client.access_token = settings.matrix_access_token
                matrix_client.user_id = settings.matrix_user_id
                log.info("matrix_authenticated", method="token", user=settings.matrix_user_id)
            else:
                resp = await matrix_client.login(settings.matrix_password)
                if isinstance(resp, nio.LoginError):
                    raise RuntimeError(f"Matrix password login failed: {resp}")
                log.info("matrix_authenticated", method="password", user=settings.matrix_user_id)

            notifier = MatrixNotifier(matrix_client, settings.matrix_room_id)

            tasks.add(asyncio.create_task(heartbeat_loop()))
            tasks.add(asyncio.create_task(digest_loop(notifier)))
            tasks.add(asyncio.create_task(run_matrix_bot(notifier, matrix_client)))
            scheduler.start(tasks)

            await notifier.send(
                Priority.P2, "System online", f"Collectors starting (v{VERSION})."
            )
            log.info("matrix_main_loop_started")
            # Block until cancelled (e.g. SIGTERM) or all tasks finish.
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            # Cancel any tasks that are still running (e.g. due to an early
            # exception before or during gather), then close the client.
            running = [t for t in tasks if not t.done()]
            for task in running:
                task.cancel()
            if running:
                await asyncio.gather(*running, return_exceptions=True)
            await matrix_client.close()


if __name__ == "__main__":
    asyncio.run(main())

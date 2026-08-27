from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app import digest
from app.commands import kills_text, sources_text, start_text, status_text
from app.config import settings
from app.log import log
from app.notifier import Notifier

router = Router()
# Operator-only: every message from any other id is silently dropped.
router.message.filter(F.from_user.id == settings.telegram_operator_id)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(start_text("/"))


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    text = await status_text(healthcheck_url=settings.healthcheck_url)
    await message.answer(text)


@router.message(Command("sources"))
async def cmd_sources(message: Message) -> None:
    await message.answer(await sources_text())


@router.message(Command("kills"))
async def cmd_kills(message: Message) -> None:
    await message.answer(await kills_text())


@router.message(Command("digest"))
async def cmd_digest(message: Message, notifier: Notifier) -> None:
    await message.answer("Building brief…")
    await digest.send_now(notifier)


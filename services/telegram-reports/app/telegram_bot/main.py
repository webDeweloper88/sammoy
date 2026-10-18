from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from contextlib import suppress
from datetime import datetime, time
from zoneinfo import ZoneInfo

import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from app.common.config import settings
from app.common.schemas import AggregateReport, AggregateTariffs
from app.telegram_bot.dedup import DuplicateMessageMiddleware
from app.telegram_bot.formatter import (
    format_payments,
    format_posts,
    format_report,
    format_status,
    format_tariffs,
)
from app.telegram_bot.health import HealthEvent, HealthTracker
from app.telegram_bot.store import PairingStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)
router = Router()
store = PairingStore(settings.hub_database_path)

MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Bugungi hisobot"), KeyboardButton(text="📅 Haftalik hisobot")],
        [KeyboardButton(text="🗓 Oylik hisobot"), KeyboardButton(text="⚠️ Postlar holati")],
        [KeyboardButton(text="💰 Joriy tariflar")],
        [KeyboardButton(text="🏪 Postlar bo‘yicha"), KeyboardButton(text="💳 Naqd / Click")],
    ],
    resize_keyboard=True,
)


async def fetch_aggregate(period: str, *, refresh: bool = False) -> AggregateReport:
    value = datetime.now(ZoneInfo(settings.timezone)).date().isoformat()
    params: dict[str, str | bool] = {"value": value}
    if refresh:
        params["refresh"] = True
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.get(
            f"http://127.0.0.1:8092/api/v1/aggregate/{period}",
            params=params,
        )
        response.raise_for_status()
    return AggregateReport.model_validate(response.json())


async def fetch_tariffs(*, refresh: bool = False) -> AggregateTariffs:
    params = {"refresh": True} if refresh else None
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.get("http://127.0.0.1:8092/api/v1/tariffs", params=params)
        response.raise_for_status()
    return AggregateTariffs.model_validate(response.json())


async def allowed(message: Message) -> bool:
    if message.chat.type != "private" or not message.from_user or not store.is_owner(message.from_user.id):
        if settings.unauthorized_behavior == "message":
            await message.answer("Ushbu botga kirish uchun ruxsat mavjud emas.")
        return False
    return True


@router.message(CommandStart(deep_link=True))
async def pairing(message: Message, command: CommandObject) -> None:
    if message.chat.type != "private" or not message.from_user or not command.args:
        return
    ok = store.claim(
        command.args,
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    await message.answer(
        "Owner muvaffaqiyatli ulandi." if ok else "Pairing kodi noto‘g‘ri, eskirgan yoki ishlatilgan.",
        reply_markup=MENU if ok else None,
    )


@router.message(CommandStart())
async def start(message: Message) -> None:
    if await allowed(message):
        await message.answer("RTU WASH hisobot botiga xush kelibsiz.", reply_markup=MENU)


async def send_report(message: Message, period: str) -> None:
    if not await allowed(message):
        return
    try:
        report = await fetch_aggregate(period)
        await message.answer(format_report(report), reply_markup=MENU)
    except (httpx.HTTPError, ValueError):
        await message.answer("Hisobot servisiga ulanib bo‘lmadi. Keyinroq qayta urinib ko‘ring.")


async def daily_aggregate(message: Message) -> AggregateReport | None:
    if not await allowed(message):
        return None
    try:
        return await fetch_aggregate("daily")
    except (httpx.HTTPError, ValueError):
        await message.answer("Hisobot servisiga ulanib bo‘lmadi. Keyinroq qayta urinib ko‘ring.")
        return None


@router.message(Command("today"))
@router.message(F.text == "📊 Bugungi hisobot")
async def today(message: Message) -> None:
    await send_report(message, "daily")


@router.message(Command("week"))
@router.message(F.text == "📅 Haftalik hisobot")
async def week(message: Message) -> None:
    await send_report(message, "weekly")


@router.message(Command("month"))
@router.message(F.text == "🗓 Oylik hisobot")
async def month(message: Message) -> None:
    await send_report(message, "monthly")


@router.message(Command("status"))
@router.message(F.text == "⚠️ Postlar holati")
async def post_status(message: Message) -> None:
    report = await daily_aggregate(message)
    if report:
        await message.answer(format_status(report), reply_markup=MENU)


@router.message(Command("posts"))
@router.message(F.text == "🏪 Postlar bo‘yicha")
async def posts(message: Message) -> None:
    report = await daily_aggregate(message)
    if report:
        await message.answer(format_posts(report), reply_markup=MENU)


@router.message(F.text == "💳 Naqd / Click")
async def payments(message: Message) -> None:
    report = await daily_aggregate(message)
    if report:
        await message.answer(format_payments(report), reply_markup=MENU)


@router.message(Command("tariffs"))
@router.message(F.text == "💰 Joriy tariflar")
async def tariffs(message: Message) -> None:
    if not await allowed(message):
        return
    try:
        report = await fetch_tariffs(refresh=True)
        await message.answer(format_tariffs(report), reply_markup=MENU)
    except (httpx.HTTPError, ValueError):
        await message.answer("Tarif servisiga ulanib bo‘lmadi. Keyinroq qayta urinib ko‘ring.")


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    if await allowed(message):
        await message.answer(
            "Hisobot yoki joriy tariflarni pastdagi menyudan tanlang. "
            "Telegram orqali tariflarni o‘zgartirish o‘chirilgan.",
            reply_markup=MENU,
        )


def automatic_report_time() -> time:
    try:
        return time.fromisoformat(settings.automatic_daily_report_time)
    except ValueError as exc:
        raise RuntimeError("AUTOMATIC_DAILY_REPORT_TIME must use HH:MM format") from exc


async def automatic_daily_report(bot: Bot, scheduled_at: time) -> None:
    timezone = ZoneInfo(settings.timezone)
    state_key = "automatic_daily_report_date"
    while True:
        now = datetime.now(timezone)
        today = now.date().isoformat()
        owner = store.owner()
        if (
            settings.automatic_daily_report_enabled
            and owner is not None
            and now.time() >= scheduled_at
            and store.state(state_key) != today
        ):
            try:
                # Claim the automatic send before talking to Telegram. A lost
                # delivery/claim response is not automatically re-sent by a
                # promoted primary. Manual report requests remain available.
                key=os.environ.get('TELEGRAM_SETUP_KEY','')
                if key:
                    async with httpx.AsyncClient(timeout=12) as client:
                        claim=await client.post(settings.wash_engine_url.rstrip('/')+'/api/wallet/report-claim',
                            headers={'Authorization':'Bearer '+key},json={'day':today})
                    claim.raise_for_status()
                    if not claim.json().get('allowed'):
                        store.set_state(state_key,today)
                        await asyncio.sleep(max(10,settings.automatic_report_poll_seconds))
                        continue
                report = await fetch_aggregate("daily", refresh=True)
                await bot.send_message(
                    int(owner["telegram_user_id"]),
                    "⏰ Kunlik avtomatik hisobot\n\n" + format_report(report),
                    reply_markup=MENU,
                )
                store.set_state(state_key, today)
                logger.info("Automatic daily report sent for %s", today)
            except (httpx.HTTPError, ValueError, RuntimeError, sqlite3.Error, TelegramAPIError):
                logger.exception("Automatic daily report failed for %s", today)
        await asyncio.sleep(max(10, settings.automatic_report_poll_seconds))


def health_message(event: HealthEvent, name: str, error: str | None = None) -> str:
    if event.kind == "recovered":
        return f"🟢 Aloqa tiklandi\n{name} qayta onlayn."
    reason = error or "connection unavailable"
    return (
        f"🔴 Post bilan aloqa yo‘q\n{name}\n"
        f"Sabab: {reason}\nKetma-ket tekshiruvlar: {event.failures}"
    )


async def post_health_monitor(bot: Bot) -> None:
    tracker = HealthTracker(store, settings.health_failure_threshold)
    while True:
        owner = store.owner()
        if settings.health_alerts_enabled and owner is not None:
            try:
                report = await fetch_aggregate("daily", refresh=True)
                hub_event = tracker.observe("hub", True)
                if hub_event:
                    await bot.send_message(
                        int(owner["telegram_user_id"]),
                        health_message(hub_event, "RTU WASH Report Hub"),
                        reply_markup=MENU,
                    )
                    tracker.acknowledge(hub_event)
                for post in report.posts:
                    event = tracker.observe(f"post:{post.post_id}", post.status == "online")
                    if event:
                        await bot.send_message(
                            int(owner["telegram_user_id"]),
                            health_message(event, post.name, post.error),
                            reply_markup=MENU,
                        )
                        tracker.acknowledge(event)
            except (httpx.HTTPError, ValueError):
                event = tracker.observe("hub", False)
                if event:
                    try:
                        await bot.send_message(
                            int(owner["telegram_user_id"]),
                            health_message(event, "RTU WASH Report Hub", "local hub unavailable"),
                            reply_markup=MENU,
                        )
                        tracker.acknowledge(event)
                    except (sqlite3.Error, TelegramAPIError):
                        logger.exception("Failed to send Hub health alert")
            except (sqlite3.Error, TelegramAPIError):
                logger.exception("Post health monitor iteration failed")
        await asyncio.sleep(max(10, settings.health_poll_seconds))


async def run() -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    dispatcher = Dispatcher()
    dispatcher.message.outer_middleware(DuplicateMessageMiddleware())
    dispatcher.include_router(router)
    bot = Bot(settings.telegram_bot_token)
    background_tasks = [
        asyncio.create_task(automatic_daily_report(bot, automatic_report_time())),
        asyncio.create_task(post_health_monitor(bot)),
    ]
    try:
        await dispatcher.start_polling(bot)
    finally:
        for task in background_tasks:
            task.cancel()
        for task in background_tasks:
            with suppress(asyncio.CancelledError):
                await task
        await bot.session.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()

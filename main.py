"""Entry point for Norin AI Hisobot Bot (Aiogram 3 + SQLAlchemy Async + Gemini Flash + SaaS Subscription)."""

from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import socket

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers import get_main_router
from bot.keyboards import subscription_status_kb
from bot.middlewares import SubscriptionMiddleware
from config import get_settings
from database.crud import (
    evaluate_subscription_status,
    format_local_dt,
    list_authorized_users,
    list_tenants,
    mark_reminder_sent,
    today_iso,
)
from database.session import async_session_maker, init_db
from services.gemini_ai import format_uzs


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("norin_bot")


class IPv4AiohttpSession(AiohttpSession):
    """Force IPv4 connections to api.telegram.org to avoid IPv6 timeout stalls on VPS."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._connector_init["family"] = socket.AF_INET


async def subscription_watcher(bot: Bot) -> None:
    """Periodically check each tenant's subscription expiry and send daily reminders."""
    settings = get_settings()
    while True:
        try:
            today = today_iso()
            notifications = []
            async with async_session_maker() as db:
                tenants = await list_tenants(db)
                for tenant in tenants:
                    sub_status = await evaluate_subscription_status(db, tenant_id=tenant.id)
                    sub = sub_status.state
                    should_remind = (
                        not sub.is_suspended
                        and sub.last_reminder_date != today
                        and (
                            (
                                sub_status.status in ("active", "expiring")
                                and sub_status.days_left in (3, 1, 0)
                            )
                            or sub_status.status == "grace"
                        )
                    )
                    if not should_remind:
                        continue
                    db_users = await list_authorized_users(
                        db, active_only=True, tenant_id=sub.id
                    )
                    recipients = {u.telegram_id for u in db_users}
                    if sub.id == 1:
                        recipients |= set(settings.admin_id_list)
                    if recipients:
                        await mark_reminder_sent(db, today, tenant_id=sub.id)
                        notifications.append((sub, recipients))

            for sub, recipients in notifications:
                exp_str = format_local_dt(sub.expires_at, "%d.%m.%Y")
                msg = (
                    "🔔 <b>Obuna muddati yaqinlashmoqda!</b>\n\n"
                    f"🏢 Sex: <b>{html.escape(sub.tenant_name)}</b> (#{sub.id})\n"
                    f"📦 Tarif: <b>{html.escape(sub.plan_name)}</b>\n"
                    f"💳 Oylik to'lov: <b>{format_uzs(sub.monthly_price)} so'm</b>\n"
                    f"📅 Tugash sanasi: <b>{exp_str}</b>\n\n"
                    f"Bot to'xtab qolmasligi uchun to'lovni amalga oshiring. Aloqa: <b>{html.escape(sub.owner_contact)}</b>"
                )
                for uid in recipients:
                    try:
                        await bot.send_message(
                            chat_id=uid,
                            text=msg,
                            parse_mode="HTML",
                            reply_markup=subscription_status_kb(),
                        )
                    except Exception:
                        pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("subscription_watcher error: %s", exc)

        await asyncio.sleep(6 * 3600)


async def run_bot() -> None:
    """Initialize database, attach middlewares/routers, and start long polling."""
    settings = get_settings()
    if not settings.BOT_TOKEN or settings.BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        raise RuntimeError(
            "BOT_TOKEN sozlanmagan! .env fayliga @BotFather dan olingan tokenni kiriting."
        )

    await init_db()
    logger.info("Database initialized successfully.")

    bot = Bot(
        token=settings.BOT_TOKEN,
        session=IPv4AiohttpSession(timeout=60),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    sub_mw = SubscriptionMiddleware()
    dp.message.middleware(sub_mw)
    dp.callback_query.middleware(sub_mw)
    dp.my_chat_member.middleware(sub_mw)

    dp.include_router(get_main_router())

    watcher_task = asyncio.create_task(subscription_watcher(bot))
    logger.info("Starting Norin AI Hisobot Bot polling...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(
            bot,
            polling_timeout=20,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        watcher_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher_task
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run_bot())

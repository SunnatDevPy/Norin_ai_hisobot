"""Entry point for Norin AI Hisobot Bot (Aiogram 3 + SQLAlchemy Async + Gemini Flash + SaaS Subscription)."""

from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import socket
import time

from aiohttp import ClientError
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    ErrorEvent,
)

from bot.handlers import get_main_router
from bot.handlers.clients_products import set_cached_bot_username
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
    """Force IPv4 connections and recycle long-poll getUpdates sockets every 4 minutes."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._connector_init["family"] = socket.AF_INET
        self._connector_init["keepalive_timeout"] = 45
        self._connector_init["ttl_dns_cache"] = 300
        self._connector_init["enable_cleanup_closed"] = True
        self._connector_init["limit"] = 30
        self._last_poll_recycle = time.monotonic()

    async def make_request(self, bot: Bot, method, timeout: int | None = None):
        if (
            getattr(method, "__api_method__", None) == "getUpdates"
            and (time.monotonic() - self._last_poll_recycle) >= 240.0
        ):
            self._last_poll_recycle = time.monotonic()
            session = await self.create_session()
            url = self.api.api_url(token=bot.token, method=method.__api_method__)
            form = self.build_form_data(bot=bot, method=method)
            eff_timeout = self.timeout if timeout is None else timeout
            try:
                async with session.post(
                    url,
                    data=form,
                    timeout=eff_timeout,
                    headers={"Connection": "close"},
                ) as resp:
                    raw_result = await resp.text()
            except asyncio.TimeoutError as exc:
                raise TelegramNetworkError(method=method, message="Request timeout error") from exc
            except ClientError as exc:
                raise TelegramNetworkError(method=method, message=f"{type(exc).__name__}: {exc}") from exc
            response = self.check_response(
                bot=bot,
                method=method,
                status_code=resp.status,
                content=raw_result,
            )
            return response.result
        return await super().make_request(bot, method, timeout=timeout)


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


async def _configure_bot_commands(bot: Bot) -> None:
    """Configure Telegram '/' command menu: basic commands for users, /menu & /superadmin ONLY for Super Admins."""
    settings = get_settings()
    default_cmds = [
        BotCommand(command="start", description="Bosh menyuni ochish"),
        BotCommand(command="myid", description="Telegram ID ni ko'rish"),
        BotCommand(command="cancel", description="Amalni bekor qilish"),
    ]
    super_cmds = [
        BotCommand(command="menu", description="Super Admin tezkor menyusi"),
        BotCommand(command="superadmin", description="Filiallar & Obuna boshqaruvi"),
        BotCommand(command="clear", description="Tanlangan filial bazasini tozalash"),
        BotCommand(command="start", description="Asosiy menyu"),
        BotCommand(command="myid", description="Telegram ID"),
    ]
    try:
        await bot.set_my_commands(default_cmds, scope=BotCommandScopeDefault())
    except Exception as exc:
        logger.warning("Failed setting default bot commands: %s", exc)
    for sid in settings.super_admin_id_list:
        try:
            await bot.set_my_commands(super_cmds, scope=BotCommandScopeChat(chat_id=sid))
        except Exception as exc:
            logger.warning("Failed setting superadmin commands for %s: %s", sid, exc)


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
        session=IPv4AiohttpSession(timeout=25),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    @dp.error()
    async def global_error_handler(event: ErrorEvent) -> bool:
        logger.exception("Unhandled update error: %s", event.exception)
        cb = getattr(event.update, "callback_query", None)
        if cb is not None:
            with contextlib.suppress(Exception):
                await cb.answer(
                    "⚠️ Xatolik yuz berdi, qaytadan urinib ko'ring.",
                    show_alert=True,
                )
        return True

    sub_mw = SubscriptionMiddleware()
    dp.message.middleware(sub_mw)
    dp.callback_query.middleware(sub_mw)
    dp.my_chat_member.middleware(sub_mw)

    dp.include_router(get_main_router())

    watcher_task = asyncio.create_task(subscription_watcher(bot))
    logger.info("Starting Norin AI Hisobot Bot polling...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        with contextlib.suppress(Exception):
            me = await bot.get_me()
            set_cached_bot_username(me.username)
        await _configure_bot_commands(bot)
        await dp.start_polling(
            bot,
            polling_timeout=15,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        watcher_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher_task
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run_bot())

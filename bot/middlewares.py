"""Subscription enforcement middleware for Norin AI Hisobot Bot."""

from __future__ import annotations

import html
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, TelegramObject

from config import get_settings
from database.crud import evaluate_subscription_status, format_local_dt, is_user_authorized
from database.session import async_session_maker
from services.gemini_ai import format_uzs


def build_subscription_blocked_kb() -> InlineKeyboardMarkup:
    """Inline buttons shown when subscription has expired or been suspended."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 To'lov qildim (Tasdiqlash so'rash)",
                    callback_data="sub:paid_notify",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📥 Excel tarixni yuklash",
                    callback_data="export:history",
                )
            ],
        ]
    )


class SubscriptionMiddleware(BaseMiddleware):
    """Gate active bot operations behind valid SaaS subscription (Super Admins always bypass)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        settings = get_settings()
        user = getattr(event, "from_user", None)
        user_id = user.id if user else None

        # Super Admins always bypass subscription lock
        if user_id and user_id in settings.super_admin_id_list:
            return await handler(event, data)

        # Allow essential commands and renewal/export callbacks even when expired
        if isinstance(event, Message):
            text = (event.text or "").strip()
            if text.startswith("/start") or text.startswith("/myid"):
                return await handler(event, data)
        elif isinstance(event, CallbackQuery):
            cb_data = event.data or ""
            if cb_data.startswith("sub:") or cb_data.startswith("export:"):
                return await handler(event, data)

        async with async_session_maker() as db:
            sub_status = await evaluate_subscription_status(db)
            if sub_status.is_allowed:
                return await handler(event, data)
            authorized = await is_user_authorized(db, user_id, allow_group_anon=True)

        # Never expose billing notices inside client Telegram groups
        if isinstance(event, Message) and event.chat.type != "private":
            return None

        if not authorized:
            return await handler(event, data)

        sub = sub_status.state
        exp_str = format_local_dt(sub.expires_at, "%d.%m.%Y")
        status_label = "⏸ Vaqtincha to'xtatilgan" if sub_status.status == "suspended" else f"⏰ Muddati tugagan ({exp_str})"
        msg_text = (
            "🔒 <b>Bot obunasi faol emas!</b>\n\n"
            f"🏢 Sex: <b>{html.escape(sub.tenant_name)}</b>\n"
            f"📦 Tarif: <b>{html.escape(sub.plan_name)}</b>\n"
            f"💳 Oylik to'lov: <b>{format_uzs(sub.monthly_price)} so'm</b>\n"
            f"📌 Holat: {status_label}\n\n"
            f"Davom ettirish uchun to'lovni amalga oshiring va quyidagi tugmani bosing.\n"
            f"📞 Aloqa: <b>{html.escape(sub.owner_contact)}</b>"
        )

        if isinstance(event, CallbackQuery):
            await event.answer("🔒 Obuna muddati tugagan!", show_alert=True)
            if event.message:
                await event.message.answer(
                    msg_text,
                    parse_mode="HTML",
                    reply_markup=build_subscription_blocked_kb(),
                )
            return None

        if isinstance(event, Message):
            await event.answer(
                msg_text,
                parse_mode="HTML",
                reply_markup=build_subscription_blocked_kb(),
            )
            return None

        return None

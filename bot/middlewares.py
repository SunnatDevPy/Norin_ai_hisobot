"""Subscription enforcement middleware for Norin AI Hisobot Bot."""

from __future__ import annotations

import html
import time
from typing import Any, Awaitable, Callable, Dict, Tuple

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, TelegramObject

from config import get_settings
from database.crud import (
    CURRENT_USER_AUTHORIZED,
    SubscriptionStatus,
    evaluate_subscription_status,
    format_local_dt,
    get_auth_cache_epoch,
    is_user_authorized,
    resolve_user_tenant_id,
    tenant_scope,
)
from database.session import async_session_maker
from services.gemini_ai import format_uzs

_MW_CACHE_TTL_SEC = 15.0
_MW_CACHE_MAX_SIZE = 512
# Key: (user_id, chat_id, chat_type) -> (expires_at_mono, epoch, tid, sub_status, authorized)
_MW_CACHE: Dict[
    Tuple[int, int, str], Tuple[float, int, int, SubscriptionStatus, bool]
] = {}


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
        chat = getattr(event, "chat", None)
        if chat is None and isinstance(event, CallbackQuery) and event.message:
            chat = event.message.chat
        chat_id = chat.id if chat else None
        chat_type = getattr(chat, "type", "private") if chat else "private"

        cache_key = (int(user_id or 0), int(chat_id or 0), str(chat_type))
        now_m = time.monotonic()
        epoch = get_auth_cache_epoch()
        cached = _MW_CACHE.get(cache_key)
        if cached is not None and cached[0] > now_m and cached[1] == epoch:
            _, _, tid, sub_status, authorized = cached
        else:
            async with async_session_maker() as db:
                tid = await resolve_user_tenant_id(
                    db, user_id=user_id, chat_id=chat_id, chat_type=chat_type
                )
                sub_status = await evaluate_subscription_status(db, tenant_id=tid)
                authorized = await is_user_authorized(
                    db, user_id, allow_group_anon=True, tenant_id=tid
                )
            if len(_MW_CACHE) >= _MW_CACHE_MAX_SIZE:
                _MW_CACHE.clear()
            _MW_CACHE[cache_key] = (
                now_m + _MW_CACHE_TTL_SEC,
                epoch,
                tid,
                sub_status,
                authorized,
            )

        async def _call_handler() -> Any:
            auth_token = CURRENT_USER_AUTHORIZED.set(authorized)
            try:
                return await handler(event, data)
            except TelegramBadRequest as exc:
                err_msg = str(exc).lower()
                if (
                    "query is too old" in err_msg
                    or "query id is invalid" in err_msg
                    or "message is not modified" in err_msg
                ):
                    return None
                raise
            finally:
                CURRENT_USER_AUTHORIZED.reset(auth_token)

        data["tenant_id"] = tid
        with tenant_scope(tid):
            # Super Admins always bypass subscription lock
            if user_id and user_id in settings.super_admin_id_list:
                return await _call_handler()

            # Block unauthorized users from pressing any inline callback buttons
            if isinstance(event, CallbackQuery) and not authorized:
                await event.answer("⛔ Sizda ushbu tugmani bosish huquqi yo'q!", show_alert=True)
                return None

            # Allow essential commands and renewal/export callbacks even when expired
            if isinstance(event, Message):
                text = (event.text or "").strip()
                if text.startswith("/start") or text.startswith("/myid"):
                    return await _call_handler()
            elif isinstance(event, CallbackQuery):
                cb_data = event.data or ""
                if cb_data.startswith("sub:") or cb_data.startswith("export:"):
                    return await _call_handler()

            if sub_status.is_allowed:
                return await _call_handler()

            # Never expose billing notices inside client Telegram groups
            if chat is not None and chat_type != "private":
                return None

            if not authorized:
                return await _call_handler()

            sub = sub_status.state
            exp_str = format_local_dt(sub.expires_at, "%d.%m.%Y")
            status_label = (
                "⏸ Vaqtincha to'xtatilgan"
                if sub_status.status == "suspended"
                else f"⏰ Muddati tugagan ({exp_str})"
            )
            msg_text = (
                "🔒 <b>Bot obunasi faol emas!</b>\n\n"
                f"🏢 Sex: <b>{html.escape(sub.tenant_name)}</b> (#{sub.id})\n"
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

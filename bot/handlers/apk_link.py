"""Telegram bot /apk panel for downloading the Android APK, getting OTP codes, and managing devices."""

from __future__ import annotations

import html
import logging
from datetime import timedelta
from typing import List, Optional, Tuple

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import desc, select

from api import apk_meta
from api.security import hash_secret, make_otp
from bot.ui_helpers import fast_edit, send_inline_panel
from config import get_settings
from database import session as db_session
from database.crud import format_local_dt, get_raw_app_setting, now_utc, set_raw_app_setting
from database.models import ApiLoginCode, ApiSession

router = Router(name="apk_link")
logger = logging.getLogger("norin_bot.apk_link")


def _is_super_admin(user_id: Optional[int]) -> bool:
    return bool(user_id and user_id in get_settings().super_admin_id_list)


async def _issue_bot_otp(telegram_id: int) -> str:
    """Create a fresh 6-digit single-use OTP in api_login_codes and return the plain code."""
    settings = get_settings()
    code = make_otp()
    ttl = max(1, settings.API_OTP_TTL_MIN)
    async with db_session.async_session_maker() as db:
        db.add(
            ApiLoginCode(
                telegram_id=telegram_id,
                code_hash=hash_secret(code),
                expires_at=now_utc() + timedelta(minutes=ttl),
            )
        )
        await db.commit()
    return code


async def _list_active_sessions(telegram_id: int) -> List[ApiSession]:
    now = now_utc()
    async with db_session.async_session_maker() as db:
        res = await db.execute(
            select(ApiSession)
            .where(
                ApiSession.telegram_id == telegram_id,
                ApiSession.is_revoked.is_(False),
                ApiSession.expires_at > now,
            )
            .order_by(desc(ApiSession.last_used_at), desc(ApiSession.id))
        )
        return list(res.scalars().all())


def _apk_panel_kb(device_count: int) -> InlineKeyboardMarkup:
    pub_url = (get_settings().API_PUBLIC_URL or "").strip().rstrip("/")
    rows: List[List[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="📥 APK ilovani yuklab olish (Telegramda)",
                callback_data="apk:download_file",
            )
        ],
    ]
    if pub_url.startswith("https://") or pub_url.startswith("http://"):
        rows.append(
            [
                InlineKeyboardButton(
                    text="🌐 Brauzerdan yuklab olish (Tezkor)",
                    url=f"{pub_url}/download/norin_ai.apk",
                )
            ]
        )
    rows.extend(
        [
            [InlineKeyboardButton(text="🔑 Yangi 6 xonali kod", callback_data="apk:new_code")],
            [
                InlineKeyboardButton(
                    text=f"📱 Ulangan qurilmalar ({device_count})",
                    callback_data="apk:devices",
                )
            ],
            [
                InlineKeyboardButton(text="👑 Bosh panel", callback_data="sa:menu"),
                InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="menu:home"),
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_apk_home(user_id: int, code: Optional[str] = None) -> Tuple[str, InlineKeyboardMarkup]:
    settings = get_settings()
    if code is None:
        code = await _issue_bot_otp(user_id)
    sessions = await _list_active_sessions(user_id)
    meta = apk_meta.get_apk_version_metadata()
    ver_label = f"v{meta['version']} (build #{meta['build']})"
    size_bytes = int(meta.get("size_bytes") or 0)
    size_line = (
        f"📦 Fayl hajmi: <b>{size_bytes / (1024 * 1024):.1f} MB</b>"
        if meta.get("apk_available") and size_bytes > 0
        else "⚠️ <i>Serverga hali APK fayli yuklanmagan</i>"
    )
    pub_url = (settings.API_PUBLIC_URL or "").strip().rstrip("/")
    url_line = f"\n🌐 Server: <code>{html.escape(pub_url)}</code>" if pub_url else ""
    ttl = max(1, settings.API_OTP_TTL_MIN)

    text = (
        "📱 <b>Norin AI — Android APK & Kirish</b>\n"
        "===============================\n"
        f"🆕 Versiya: <b>{html.escape(ver_label)}</b>\n"
        f"{size_line}\n"
        f"🔑 Bir martalik kirish kodi ({ttl} daqiqa):\n\n"
        f"👉  <code>{code}</code>\n"
        f"{url_line}\n"
        "===============================\n"
        f"📲 Faol qurilmalar: <b>{len(sessions)} ta</b>\n\n"
        "<i>Ilovani bir marta o'rnating — keyingi barcha yangilanishlar to'g'ridan-to'g'ri ilovaning o'zida avtomatik yuklab olinadi!</i>"
    )
    return text, _apk_panel_kb(len(sessions))


@router.message(StateFilter("*"), Command("apk"), F.chat.type == "private")
async def cmd_apk(message: Message, state: FSMContext) -> None:
    """Super Admin /apk entry point showing APK download and OTP code."""
    uid = message.from_user.id if message.from_user else None
    if not _is_super_admin(uid):
        await message.answer("🔒 Mobil ilova (APK) hozircha faqat Super Admin uchun ochiq.")
        return
    await state.clear()
    text, kb = await _render_apk_home(int(uid))
    await send_inline_panel(message, text, kb, delete_prev=False, force_hide_kb=True)


@router.callback_query(F.data == "apk:home")
async def cb_apk_home(cb: CallbackQuery) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not _is_super_admin(uid):
        await cb.answer("🔒 Faqat Super Admin uchun", show_alert=True)
        return
    text, kb = await _render_apk_home(int(uid))
    await fast_edit(cb, text, reply_markup=kb)


@router.callback_query(F.data == "apk:new_code")
async def cb_apk_new_code(cb: CallbackQuery) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not _is_super_admin(uid):
        await cb.answer("🔒 Faqat Super Admin uchun", show_alert=True)
        return
    code = await _issue_bot_otp(int(uid))
    text, kb = await _render_apk_home(int(uid), code=code)
    await fast_edit(cb, text, reply_markup=kb, alert_text=f"🔑 Yangi kod: {code}")


@router.callback_query(F.data == "apk:download_file")
async def cb_apk_download_file(cb: CallbackQuery) -> None:
    """Send norin_ai.apk directly in Telegram chat using cached file_id when unchanged."""
    uid = cb.from_user.id if cb.from_user else None
    if not _is_super_admin(uid):
        await cb.answer("🔒 Faqat Super Admin uchun", show_alert=True)
        return
    settings = get_settings()
    pub_url = (settings.API_PUBLIC_URL or "").strip().rstrip("/")
    dl_link = f"{pub_url}/download/norin_ai.apk" if pub_url else ""

    if not apk_meta.APK_BINARY_PATH.is_file():
        await cb.answer("⚠️ Serverda APK fayli topilmadi", show_alert=True)
        if cb.message and dl_link:
            await cb.message.answer(
                f"📥 <b>Norin AI APK yuklab olish havolasi:</b>\n👉 <a href=\"{html.escape(dl_link)}\">{html.escape(dl_link)}</a>",
                parse_mode="HTML",
            )
        return

    await cb.answer("📥 APK yuborilmoqda...")
    stat = apk_meta.APK_BINARY_PATH.stat()
    sig = f"{stat.st_size}:{int(stat.st_mtime)}"
    async with db_session.async_session_maker() as db:
        cached_sig = await get_raw_app_setting(db, "norin_apk_tg_sig", "")
        cached_fid = await get_raw_app_setting(db, "norin_apk_tg_fid", "")

    code = await _issue_bot_otp(int(uid))
    meta = apk_meta.get_apk_version_metadata()
    ver_num = str(meta.get("version") or "1.0.0")
    ver_label = f"v{ver_num} (build #{meta.get('build', 1)})"
    url_line = f"🌐 Server: <code>{html.escape(pub_url)}/api/v1</code>\n" if pub_url else ""
    caption = (
        f"📱 <b>Norin AI Android — {html.escape(ver_label)}</b>\n\n"
        f"{url_line}"
        f"👤 Telegram ID: <code>{uid}</code>\n"
        f"🔑 Kirish kodi (5 daqiqa): <code>{code}</code>\n\n"
        "<i>APK ni telefoningizga o'rnatib, ID va kodni kiriting.</i>"
    )

    if not cb.message:
        return

    try:
        if cached_fid and cached_sig == sig:
            await cb.message.answer_document(
                document=cached_fid,
                caption=caption,
                parse_mode="HTML",
            )
            return
    except Exception:
        pass

    try:
        wait_msg = await cb.message.answer(
            "⏳ <i>APK fayli Telegramga yuklanmoqda (10-15 soniya)...</i>",
            parse_mode="HTML",
        )
        sent = await cb.message.answer_document(
            document=FSInputFile(apk_meta.APK_BINARY_PATH, filename=f"Norin_AI_v{ver_num}.apk"),
            caption=caption,
            parse_mode="HTML",
        )
        try:
            await wait_msg.delete()
        except Exception:
            pass
        if sent.document and sent.document.file_id:
            async with db_session.async_session_maker() as db:
                await set_raw_app_setting(db, "norin_apk_tg_sig", sig)
                await set_raw_app_setting(db, "norin_apk_tg_fid", sent.document.file_id)
    except Exception as exc:
        logger.warning("Failed to send APK document via Telegram: %s", exc)
        if dl_link:
            await cb.message.answer(
                f"📥 <b>Norin AI APK havolasi:</b>\n"
                f"👉 <a href=\"{html.escape(dl_link)}\">{html.escape(dl_link)}</a>\n\n"
                f"🔑 Kirish kodi: <code>{code}</code>",
                parse_mode="HTML",
            )


@router.callback_query(F.data == "apk:devices")
async def cb_apk_devices(cb: CallbackQuery, alert_text: Optional[str] = None) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not _is_super_admin(uid):
        await cb.answer("🔒 Faqat Super Admin uchun", show_alert=True)
        return
    sessions = await _list_active_sessions(int(uid))
    lines = ["📱 <b>Ulangan APK qurilmalari</b>\n"]
    rows: List[List[InlineKeyboardButton]] = []
    if not sessions:
        lines.append("<i>Hozircha ulangan faol qurilmalar yo'q.</i>")
    else:
        for s in sessions[:12]:
            dev = html.escape(s.device_name or "Android")
            dt = format_local_dt(s.last_used_at or s.created_at)
            lines.append(f"• <b>#{s.id} {dev}</b> — {dt}")
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"❌ #{s.id} {s.device_name or 'Android'} ni uzish",
                        callback_data=f"apk:revoke:{s.id}",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="apk:home")])
    await fast_edit(
        cb,
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        alert_text=alert_text,
    )


@router.callback_query(F.data.startswith("apk:revoke:"))
async def cb_apk_revoke(cb: CallbackQuery) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not _is_super_admin(uid):
        await cb.answer("🔒 Faqat Super Admin uchun", show_alert=True)
        return
    raw_id = (cb.data or "").split(":")[-1]
    if not raw_id.isdigit():
        await cb.answer("Noto'g'ri ID", show_alert=True)
        return
    sid = int(raw_id)
    async with db_session.async_session_maker() as db:
        sess = await db.get(ApiSession, sid)
        if sess is not None and sess.telegram_id == int(uid):
            sess.is_revoked = True
            await db.commit()
    await cb_apk_devices(cb, alert_text="✅ Qurilma sessiyasi uzildi")

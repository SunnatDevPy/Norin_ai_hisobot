"""Telegram bot /apk panel and 1-tap deep-link login handler for Norin AI Android app."""

from __future__ import annotations

import html
import logging
from datetime import timedelta
from typing import List, Optional, Tuple

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import desc, select

from api import apk_meta
from api.security import hash_secret, make_otp
from bot.keyboards import BTN_APK
from bot.ui_helpers import fast_edit, send_inline_panel
from config import get_settings
from database import session as db_session
from database.crud import (
    evaluate_subscription_status,
    format_local_dt,
    get_raw_app_setting,
    is_user_authorized,
    now_utc,
    resolve_user_tenant_id,
    set_raw_app_setting,
    to_utc_dt,
)
from database.models import ApiLoginCode, ApiSession

router = Router(name="apk_link")
logger = logging.getLogger("norin_bot.apk_link")


def _is_super_admin(user_id: Optional[int]) -> bool:
    return bool(user_id and user_id in get_settings().super_admin_id_list)


async def _authorize_apk_bot_user(user_id: Optional[int]) -> Tuple[bool, str, str]:
    """Return (allowed, tenant_name, denial_message) for any bot user."""
    if not user_id:
        return False, "", "🔒 Foydalanuvchi aniqlanmadi."
    uid = int(user_id)
    async with db_session.async_session_maker() as db:
        tid = await resolve_user_tenant_id(db, user_id=uid, chat_type="private")
        auth_ok = await is_user_authorized(db, uid, allow_group_anon=False, tenant_id=tid)
        if not auth_ok:
            return (
                False,
                "",
                f"🔒 Sizga Norin AI tizimiga ruxsat berilmagan.\n🆔 Telegram ID: <code>{uid}</code>",
            )
        sub = await evaluate_subscription_status(db, tenant_id=tid)
        if not sub.is_allowed and not _is_super_admin(uid):
            return False, sub.state.tenant_name, "🔒 Filial obuna muddati tugagan yoki muzlatilgan."
        return True, sub.state.tenant_name, ""


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


def _apk_panel_kb(device_count: int, is_sa: bool = False) -> InlineKeyboardMarkup:
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
                *(
                    [InlineKeyboardButton(text="👑 Bosh panel", callback_data="sa:menu")]
                    if is_sa
                    else []
                ),
                InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="menu:home"),
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_apk_home(
    user_id: int,
    tenant_name: str = "",
    code: Optional[str] = None,
) -> Tuple[str, InlineKeyboardMarkup]:
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
    branch_line = f"\n🏢 Filial: <b>{html.escape(tenant_name)}</b>" if tenant_name else ""
    ttl = max(1, settings.API_OTP_TTL_MIN)

    text = (
        "📱 <b>Norin AI — Android APK & Kirish</b>\n"
        "==============================="
        f"{branch_line}\n"
        f"🆕 Versiya: <b>{html.escape(ver_label)}</b>\n"
        f"{size_line}\n"
        f"🔑 Kirish kodi ({ttl} daqiqa — ID kiritish shart emas):\n\n"
        f"👉  <code>{code}</code>\n"
        f"{url_line}\n"
        "===============================\n"
        f"📲 Faol qurilmalar: <b>{len(sessions)} ta</b>\n\n"
        "<i>Ilovada «Telegram orqali 1-bosishda kirish» ni bosing yoki yuqoridagi 6 xonali kodni tering.</i>"
    )
    return text, _apk_panel_kb(len(sessions), is_sa=_is_super_admin(user_id))


@router.message(
    StateFilter("*"),
    CommandStart(deep_link=True),
    F.chat.type == "private",
    F.text.startswith("/start apk_"),
)
async def cmd_start_apk_ticket(message: Message, state: FSMContext) -> None:
    """Approve a 1-tap APK deep-link login ticket when the user opens /start apk_<ticket>."""
    uid = message.from_user.id if message.from_user else None
    allowed, tenant_name, err_msg = await _authorize_apk_bot_user(uid)
    if not allowed:
        await message.answer(err_msg, parse_mode="HTML")
        return
    await state.clear()

    raw_text = (message.text or "").strip()
    ticket = raw_text.split("apk_", 1)[1].strip().split()[0]
    approved = False
    async with db_session.async_session_maker() as db:
        row = await db.scalar(
            select(ApiLoginCode)
            .where(ApiLoginCode.code_hash == hash_secret(f"tkt:{ticket}"))
            .order_by(desc(ApiLoginCode.id))
            .limit(1)
        )
        if row is not None and not row.used and to_utc_dt(row.expires_at) >= now_utc():
            if int(row.telegram_id) in (0, int(uid)):
                row.telegram_id = int(uid)
                await db.commit()
                approved = True

    backup_code = await _issue_bot_otp(int(uid))
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 APK & Qurilmalar", callback_data="apk:home")]
        ]
    )
    if approved:
        await message.answer(
            "✅ <b>Norin AI ilovasiga kirish tasdiqlandi!</b>\n"
            f"🏢 Filial: <b>{html.escape(tenant_name)}</b>\n\n"
            "📲 <b>Endi Norin AI ilovasiga qayting</b> — ilova avtomatik ravishda tizimga kiradi.\n\n"
            f"<i>Agar avtomatik kirmasa, ushbu kodni kiriting:</i> <code>{backup_code}</code>",
            parse_mode="HTML",
            reply_markup=kb,
        )
    else:
        await message.answer(
            "⏳ <b>Kirish havolasi eskirgan yoki ishlatilgan.</b>\n\n"
            "Ilovada <b>«Telegram orqali 1-bosishda kirish»</b> tugmasini qayta bosing "
            f"yoki ushbu kodni tering: <code>{backup_code}</code>",
            parse_mode="HTML",
            reply_markup=kb,
        )


@router.message(StateFilter("*"), Command("apk"), F.chat.type == "private")
@router.message(StateFilter("*"), F.text == BTN_APK, F.chat.type == "private")
async def cmd_apk(message: Message, state: FSMContext) -> None:
    """Authorized /apk entry point showing APK download and OTP code."""
    uid = message.from_user.id if message.from_user else None
    allowed, tenant_name, err_msg = await _authorize_apk_bot_user(uid)
    if not allowed:
        await message.answer(err_msg, parse_mode="HTML")
        return
    await state.clear()
    text, kb = await _render_apk_home(int(uid), tenant_name=tenant_name)
    await send_inline_panel(message, text, kb, delete_prev=False, force_hide_kb=True)


@router.callback_query(F.data == "apk:home")
async def cb_apk_home(cb: CallbackQuery) -> None:
    uid = cb.from_user.id if cb.from_user else None
    allowed, tenant_name, err_msg = await _authorize_apk_bot_user(uid)
    if not allowed:
        await cb.answer(err_msg.replace("<b>", "").replace("</b>", ""), show_alert=True)
        return
    text, kb = await _render_apk_home(int(uid), tenant_name=tenant_name)
    await fast_edit(cb, text, reply_markup=kb)


@router.callback_query(F.data == "apk:new_code")
async def cb_apk_new_code(cb: CallbackQuery) -> None:
    uid = cb.from_user.id if cb.from_user else None
    allowed, tenant_name, _ = await _authorize_apk_bot_user(uid)
    if not allowed:
        await cb.answer("🔒 Ruxsat yo'q", show_alert=True)
        return
    code = await _issue_bot_otp(int(uid))
    text, kb = await _render_apk_home(int(uid), tenant_name=tenant_name, code=code)
    await fast_edit(cb, text, reply_markup=kb, alert_text=f"🔑 Yangi kod: {code}")


@router.callback_query(F.data == "apk:download_file")
async def cb_apk_download_file(cb: CallbackQuery) -> None:
    """Send norin_ai.apk directly in Telegram chat using cached file_id when unchanged."""
    uid = cb.from_user.id if cb.from_user else None
    allowed, _, _ = await _authorize_apk_bot_user(uid)
    if not allowed:
        await cb.answer("🔒 Ruxsat yo'q", show_alert=True)
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
        f"🔑 Kirish kodi (5 daqiqa): <code>{code}</code>\n\n"
        "<i>APK ni o'rnatib, «Telegram orqali 1-bosishda kirish» ni bosing yoki yuqoridagi kodni kiriting.</i>"
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
    allowed, _, _ = await _authorize_apk_bot_user(uid)
    if not allowed:
        await cb.answer("🔒 Ruxsat yo'q", show_alert=True)
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
    allowed, _, _ = await _authorize_apk_bot_user(uid)
    if not allowed:
        await cb.answer("🔒 Ruxsat yo'q", show_alert=True)
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

"""Super Admin subscription management, authorized users, and client renewal notifications."""

from __future__ import annotations

import asyncio
import html
import logging
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from api import apk_meta
from bot.keyboards import (
    BTN_STATUS,
    MAIN_MENU_BUTTONS,
    cancel_reply_keyboard,
    confirm_delete_kb,
    main_menu_keyboard,
    subscription_status_kb,
    superadmin_clear_confirm_kb,
    superadmin_default_name_reply_kb,
    superadmin_menu_kb,
    superadmin_pick_user_reply_kb,
    superadmin_quick_menu_kb,
    superadmin_renewal_request_kb,
    superadmin_tenant_settings_kb,
    superadmin_tenants_kb,
    superadmin_user_detail_kb,
    superadmin_users_kb,
)
from bot.states import SuperAdminStates
from bot.ui_helpers import fast_edit, mark_reply_kb_sent, send_inline_panel
from config import get_settings
from database.crud import (
    add_authorized_user,
    check_tenant_ai_quota,
    create_tenant,
    delete_tenant,
    evaluate_subscription_status,
    extend_subscription,
    format_local_dt,
    get_ai_usage_summary,
    get_app_setting,
    get_authorized_user,
    get_global_saas_analytics,
    get_group_config,
    get_raw_app_setting,
    get_tenant_overview_stats,
    is_user_authorized,
    list_all_broadcast_recipients,
    list_authorized_users,
    list_clients,
    list_subscription_payments,
    list_tenants,
    now_utc,
    reassign_authorized_user,
    remove_authorized_user,
    reset_full_database,
    reset_test_transactions,
    resolve_user_tenant_id,
    set_app_setting,
    set_raw_app_setting,
    tenant_scope,
    update_subscription_settings,
)
from database.models import ApiSession
from database.session import async_session_maker
from services.gemini_ai import format_uzs, parse_uzbek_amount


router = Router(name="superadmin")
logger = logging.getLogger("norin_bot.superadmin")


def is_super_admin(user_id: int | None) -> bool:
    """Check if Telegram user ID is listed in SUPER_ADMIN_IDS."""
    if user_id is None:
        return False
    return user_id in get_settings().super_admin_id_list


_selected_sa_tenant: dict[int, int] = {}


async def _get_sa_tenant(uid: int | None) -> int:
    """Return currently selected tenant_id for a Super Admin (persisted in DB)."""
    if not uid:
        return 1
    uid_int = int(uid)
    if uid_int in _selected_sa_tenant:
        return _selected_sa_tenant[uid_int]
    try:
        async with async_session_maker() as db:
            raw = await get_raw_app_setting(db, f"sa_sel:{uid_int}", "1")
        tid = max(1, int(raw or "1"))
    except Exception:
        tid = 1
    _selected_sa_tenant[uid_int] = tid
    return tid


async def _set_sa_tenant(uid: int | None, tenant_id: int) -> None:
    """Remember selected tenant_id in memory cache and persist in DB."""
    if not uid:
        return
    uid_int = int(uid)
    tid = max(1, int(tenant_id))
    _selected_sa_tenant[uid_int] = tid
    try:
        async with async_session_maker() as db:
            await set_raw_app_setting(db, f"sa_sel:{uid_int}", str(tid))
    except Exception as exc:
        logger.warning("Could not persist selected SA tenant for %s: %s", uid_int, exc)


async def _superadmin_panel(uid: int | None) -> tuple[str, InlineKeyboardMarkup]:
    """Render Super Admin dashboard text and multi-tenant keyboard for selected tenant."""
    tid = await _get_sa_tenant(uid)
    text, is_susp, tenant_count, resolved_tid = await _render_superadmin_dashboard(tid)
    if resolved_tid != tid and uid:
        await _set_sa_tenant(uid, resolved_tid)
    kb = superadmin_menu_kb(
        is_susp,
        tenant_label=f"Filiallar ({tenant_count} ta)",
        tenant_id=resolved_tid,
    )
    return text, kb


async def _render_superadmin_dashboard(tenant_id: int = 1) -> tuple[str, bool, int, int]:
    """Render Super Admin dashboard text, suspension flag, total tenants, and resolved tenant_id."""
    async with async_session_maker() as db:
        tenants = await list_tenants(db)
        sub_status = await evaluate_subscription_status(db, tenant_id=tenant_id)
        sub = sub_status.state
        users = await list_authorized_users(db, active_only=True, tenant_id=sub.id)
        ai_usage = await get_ai_usage_summary(db, days=30, tenant_id=sub.id)
        stats = await get_tenant_overview_stats(db, sub.id)
    exp_str = format_local_dt(sub.expires_at, "%d.%m.%Y %H:%M")

    status_map = {
        "active": f"🟢 Faol ({sub_status.days_left} kun qoldi)",
        "expiring": f"🟡 Tugamoqda ({sub_status.days_left} kun qoldi)",
        "grace": f"🟠 Imtiyoz davri ({sub_status.grace_days_left} kun qoldi)",
        "expired": "🔴 Muddati tugagan (Bloklangan)",
        "suspended": "⏸ Qo'lda to'xtatilgan",
    }

    settings = get_settings()
    env_admins = html.escape(settings.formatted_admin_entries)
    role_tag = "🧪 Test / Shaxsiy filial" if sub.id == 1 else "👤 Mijoz filiali (Alohida baza)"
    env_line = (
        f"\n👥 Ruxsat etilganlar (.env): <code>{env_admins}</code>" if sub.id == 1 else ""
    )
    text = (
        "👑 <b>SUPER ADMIN PANEL — Multi-Tenant SaaS</b>\n"
        "===============================\n"
        f"🏢 Filial: <b>#{sub.id} {html.escape(sub.tenant_name)}</b>\n"
        f"🧩 Turi: <i>{role_tag}</i> (Jami filiallar: <b>{len(tenants)} ta</b>)\n"
        f"📦 Tarif: <b>{html.escape(sub.plan_name)}</b>\n"
        f"💳 Oylik narx: <b>{format_uzs(sub.monthly_price)} so'm</b>\n"
        f"📅 Tugash sanasi: <b>{exp_str}</b>\n"
        f"⏳ Imtiyoz (Grace): <b>{sub.grace_days} kun</b>\n"
        f"📌 Holat: <b>{status_map.get(sub_status.status, sub_status.status)}</b>\n"
        f"📞 Kontakt: <b>{html.escape(sub.owner_contact)}</b>\n"
        f"📊 Baza: <b>{stats['clients']}</b> mijoz (guruh: <b>{stats['groups']}</b>) | <b>{stats['sales']}</b> sotuv | <b>{stats['products']}</b> mahsulot\n"
        f"🤖 AI (30 kun): rasm <b>{ai_usage['image_calls']}</b> | ovoz <b>{ai_usage['audio_calls']}</b> | token: <b>{format_uzs(ai_usage['total_tokens'])}</b>\n"
        "-------------------------------"
        f"{env_line}\n"
        f"👥 Shu filial xodimlari (baza): <b>{len(users)} ta</b>"
    )
    return text, sub.is_suspended, len(tenants), sub.id


async def _render_client_subscription_text(user_id: Optional[int] = None) -> str:
    """Render enriched tenant subscription, AI quota, groups, and APK device status card."""
    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db)
        sub = sub_status.state
        _, ai_used, ai_limit = await check_tenant_ai_quota(db, tenant_id=sub.id)
        clients = await list_clients(db, active_only=True)
        report_grp = await get_group_config(db, "report")
        dev_count = 0
        if user_id:
            dev_count = int(
                await db.scalar(
                    select(func.count(ApiSession.id)).where(
                        ApiSession.telegram_id == int(user_id),
                        ApiSession.is_revoked.is_(False),
                        ApiSession.expires_at > now_utc(),
                    )
                )
                or 0
            )
    exp_str = format_local_dt(sub.expires_at, "%d.%m.%Y")
    bound_clients = sum(1 for c in clients if c.group_chat_id)
    rep_status = (
        f"✅ {html.escape(report_grp.title)}"
        if report_grp
        else "⚠️ Ulanmagan"
    )
    ai_line = (
        f"♾️ Cheksiz (bugun: <b>{ai_used}</b> so'rov)"
        if ai_limit <= 0
        else f"<b>{ai_used} / {ai_limit}</b> so'rov (bugun)"
    )
    meta = apk_meta.get_apk_version_metadata()
    ver_lbl = f"v{meta.get('version', '1.0.0')}"

    status_map = {
        "active": f"🟢 Faol ({sub_status.days_left} kun qoldi)",
        "expiring": f"🟡 Tez orada tugaydi ({sub_status.days_left} kun qoldi)",
        "grace": f"🟠 Imtiyoz davri ({sub_status.grace_days_left} kun ichida to'lang)",
        "expired": "🔴 Muddati tugagan",
        "suspended": "⏸ Vaqtincha to'xtatilgan",
    }

    return (
        "💎 <b>Norin AI — Obuna va Filial Statusi</b>\n"
        "===============================\n"
        f"🏢 Sex / Filial: <b>{html.escape(sub.tenant_name)}</b> (<code>#{sub.id}</code>)\n"
        f"📦 Tarif: <b>{html.escape(sub.plan_name)}</b> — <b>{format_uzs(sub.monthly_price)} so'm/oy</b>\n"
        f"📅 Amal qilish muddati: <b>{exp_str}</b>\n"
        f"📌 Obuna holati: <b>{status_map.get(sub_status.status, sub_status.status)}</b>\n"
        "-------------------------------\n"
        f"🤖 Kunlik AI kvota: {ai_line}\n"
        f"🏪 Mijoz guruhlari: <b>{bound_clients} / {len(clients)} ta</b> ulangan\n"
        f"📊 Hisobot guruhi: {rep_status}\n"
        f"📱 Mobil ilova ({html.escape(ver_lbl)}): <b>{dev_count} ta</b> faol qurilma\n"
        "-------------------------------\n"
        f"To'lovni amalga oshirib, <b>«💳 To'lov qildim»</b> tugmasini bosing — "
        f"administrator darhol muddatni uzaytirib beradi.\n"
        f"📞 Aloqa: <b>{html.escape(sub.owner_contact)}</b>"
    )


# ---------------------------------------------------------------------------
# /myid, /status & Client Subscription Views
# ---------------------------------------------------------------------------


@router.message(Command("myid"))
async def cmd_myid(message: Message) -> None:
    """Show the sender's Telegram user ID and current chat ID."""
    uid = message.from_user.id if message.from_user else 0
    full_name = html.escape(message.from_user.full_name) if message.from_user else ""
    await message.answer(
        f"👤 Foydalanuvchi: <b>{full_name}</b>\n"
        f"🆔 Sizning Telegram ID: <code>{uid}</code>\n"
        f"💬 Chat ID: <code>{message.chat.id}</code>",
        parse_mode="HTML",
    )


@router.message(Command("status"), F.chat.type == "private")
@router.message(F.text == BTN_STATUS, F.chat.type == "private")
async def cmd_tenant_status(message: Message, state: FSMContext) -> None:
    """Show live filial, subscription, AI quota, groups, and APK device status."""
    uid = message.from_user.id if message.from_user else None
    async with async_session_maker() as db:
        if not await is_user_authorized(db, uid):
            return
    await state.clear()
    text = await _render_client_subscription_text(user_id=uid)
    await send_inline_panel(
        message,
        text,
        reply_markup=subscription_status_kb(is_super_admin=is_super_admin(uid)),
        delete_prev=True,
    )


@router.callback_query(F.data == "sub:status")
async def cb_subscription_status(cb: CallbackQuery) -> None:
    """Show client subscription & filial status screen."""
    uid = cb.from_user.id if cb.from_user else None
    async with async_session_maker() as db:
        if not await is_user_authorized(db, uid):
            await cb.answer("Ruxsat yo'q", show_alert=True)
            return
    text = await _render_client_subscription_text(user_id=uid)
    await fast_edit(
        cb,
        text,
        reply_markup=subscription_status_kb(is_super_admin=is_super_admin(uid)),
    )


@router.callback_query(F.data == "sub:paid_notify")
async def cb_subscription_paid_notify(cb: CallbackQuery) -> None:
    """Notify Super Admins when the client clicks 'I paid for renewal'."""
    uid = cb.from_user.id if cb.from_user else 0
    uname = f"@{cb.from_user.username}" if cb.from_user and cb.from_user.username else ""
    full_name = cb.from_user.full_name if cb.from_user else f"User {uid}"

    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db)
    sub = sub_status.state

    super_ids = get_settings().super_admin_id_list
    sent_count = 0
    for sid in super_ids:
        try:
            await cb.bot.send_message(
                chat_id=sid,
                text=(
                    "💳 <b>OBUNA TO'LOVI SO'ROVI!</b>\n\n"
                    f"🏢 Filial: <b>#{sub.id} {html.escape(sub.tenant_name)}</b>\n"
                    f"👤 Mijoz: <b>{html.escape(full_name)}</b> {html.escape(uname)}\n"
                    f"🆔 Telegram ID: <code>{uid}</code>\n"
                    f"💰 Oylik tarif: <b>{format_uzs(sub.monthly_price)} so'm</b>\n\n"
                    "To'lov tushgan bo'lsa, 1 bosishda tasdiqlang:"
                ),
                parse_mode="HTML",
                reply_markup=superadmin_renewal_request_kb(uid, tenant_id=sub.id),
            )
            sent_count += 1
        except Exception as exc:
            logger.warning("Could not notify super admin %s: %s", sid, exc)

    if sent_count > 0:
        await cb.answer("✅ So'rov adminga yuborildi!", show_alert=True)
        await cb.message.answer(
            "✅ <b>To'lov haqida so'rovingiz dasturchiga yuborildi!</b>\n"
            f"Tasdiqlanishi bilan bot sizga xabar beradi. Aloqa: <b>{html.escape(sub.owner_contact)}</b>",
            parse_mode="HTML",
        )
    else:
        await cb.answer(f"Iltimos bog'laning: {sub.owner_contact}", show_alert=True)


# ---------------------------------------------------------------------------
# /superadmin Panel (Restricted to SUPER_ADMIN_IDS)
# ---------------------------------------------------------------------------


@router.message(F.text.in_({"❌ Bekor qilish", "/cancel"}), F.chat.type == "private")
async def cancel_superadmin_or_any_state(message: Message, state: FSMContext) -> None:
    """Cancel any active FSM state (including SuperAdminStates) at highest priority."""
    uid = message.from_user.id if message.from_user else None
    async with async_session_maker() as db:
        if not await is_user_authorized(db, uid):
            return
    cur = await state.get_state()
    await state.clear()
    await message.answer("❌ Amal bekor qilindi.", reply_markup=main_menu_keyboard())
    mark_reply_kb_sent(message.chat.id)
    if is_super_admin(uid) and cur and cur.startswith("SuperAdminStates:"):
        text, kb = await _superadmin_panel(uid)
        await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.message(Command("menu"), F.chat.type == "private")
async def cmd_superadmin_quick_menu(message: Message, state: FSMContext) -> None:
    """Quick command dashboard visible STRICTLY to Super Admin (silent no-op for everyone else)."""
    uid = message.from_user.id if message.from_user else None
    if not is_super_admin(uid):
        return
    await state.clear()
    tid = await _get_sa_tenant(uid)
    async with async_session_maker() as db:
        tenants = await list_tenants(db)
        sub_status = await evaluate_subscription_status(db, tenant_id=tid)
    sub = sub_status.state
    if sub.id != tid:
        await _set_sa_tenant(uid, sub.id)
    await send_inline_panel(
        message,
        "⚡ <b>SUPER ADMIN TEZKOR MENYUSI</b>\n"
        f"🎯 Tanlangan filial: <b>#{sub.id} {html.escape(sub.tenant_name)}</b> (Jami: <b>{len(tenants)} ta</b>)\n"
        "Kerakli tezkor amalni tanlang:",
        reply_markup=superadmin_quick_menu_kb(sub.id, len(tenants)),
        delete_prev=True,
        force_hide_kb=True,
    )


@router.message(Command("superadmin", "supaeradmin"), F.chat.type == "private")
async def cmd_superadmin(message: Message, state: FSMContext) -> None:
    """Open Super Admin subscription control panel."""
    uid = message.from_user.id if message.from_user else None
    if not is_super_admin(uid):
        await message.answer("⛔ Bu bo'lim faqat tizim egasi (Super Admin) uchun.")
        return
    await state.clear()
    text, kb = await _superadmin_panel(uid)
    await send_inline_panel(
        message,
        text,
        reply_markup=kb,
        delete_prev=True,
        force_hide_kb=True,
    )


@router.callback_query(F.data == "sa:menu")
async def cb_superadmin_menu(cb: CallbackQuery, state: FSMContext) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await state.clear()
    text, kb = await _superadmin_panel(uid)
    await fast_edit(cb, text, reply_markup=kb)


@router.callback_query(F.data == "sa:analytics")
async def cb_superadmin_analytics(cb: CallbackQuery, state: FSMContext) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await state.clear()
    async with async_session_maker() as db:
        a = await get_global_saas_analytics(db, days=30)

    sc = a["status_counts"]
    ai = a["ai_global"]
    lines = [
        "📈 <b>UMUMIY SAAS STATISTIKA (Barcha Filiallar)</b>",
        "===============================",
        f"🏢 Jami filiallar: <b>{a['total_tenants']} ta</b> (Pullik aktiv: <b>{a['paying_tenants']} ta</b>)",
        (
            f"📌 Holatlar: 🟢 <b>{sc.get('active', 0)}</b> | "
            f"🟡 <b>{sc.get('expiring', 0)}</b> | "
            f"🟠 <b>{sc.get('grace', 0)}</b> | "
            f"🔴 <b>{sc.get('expired', 0)}</b> | "
            f"⏸ <b>{sc.get('suspended', 0)}</b>"
        ),
        "-------------------------------",
        f"💳 <b>Aktiv pullik MRR (#2+): {format_uzs(a['paying_mrr'])} so'm/oy</b>",
        f"💎 Jami tarif qiymati (barchasi): <b>{format_uzs(a['total_mrr'])} so'm/oy</b>",
        f"💰 30 kun yig'ilgan obuna: <b>{format_uzs(a['collected_30d'])} so'm</b>",
        f"🏦 Jami tushgan to'lovlar: <b>{format_uzs(a['collected_all'])} so'm</b>",
        "-------------------------------",
        f"👥 Xodimlar: <b>{a['total_users']}</b> | 🏪 Mijozlar: <b>{a['total_clients']}</b> (guruh: <b>{a['total_groups']}</b>) | 📦 Sotuv: <b>{a['total_sales']}</b>",
        f"🤖 AI (30 kun, global): rasm <b>{ai['image_calls']}</b> | ovoz <b>{ai['audio_calls']}</b> | token: <b>{format_uzs(ai['total_tokens'])}</b>",
        "-------------------------------",
        "🏢 <b>Filiallar holati:</b>",
    ]
    st_ico = {
        "active": "🟢",
        "expiring": "🟡",
        "grace": "🟠",
        "expired": "🔴",
        "suspended": "⏸",
    }
    for t in a["tenants_breakdown"][:12]:
        ico = st_ico.get(t["status"], "•")
        lines.append(
            f"{ico} <b>#{t['id']} {html.escape(t['name'])}</b> — {format_uzs(t['price'])}/oy | 👥 {t['users']}"
        )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Yangilash", callback_data="sa:analytics"),
                InlineKeyboardButton(text="⬅️ Super Admin", callback_data="sa:menu"),
            ]
        ]
    )
    await fast_edit(cb, "\n".join(lines), reply_markup=kb)


@router.callback_query(F.data == "sa:tenants")
async def cb_superadmin_tenants(cb: CallbackQuery, state: FSMContext) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await state.clear()
    sel_id = await _get_sa_tenant(uid)
    async with async_session_maker() as db:
        tenants = await list_tenants(db)
    lines = ["🏢 <b>Filiallar / Tenantlar boshqaruvi</b>\n"]
    for t in tenants:
        st = "⏸ Bloklangan" if t.is_suspended else f"📅 {format_local_dt(t.expires_at, '%d.%m.%Y')}"
        mark = "✅ " if t.id == sel_id else ""
        lines.append(f"{mark}<b>#{t.id} {html.escape(t.tenant_name)}</b> — {st}")
    lines.append("\n<i>Boshqarish uchun filialni tanlang yoki yangi mijozga alohida filial oching:</i>")
    await fast_edit(
        cb,
        "\n".join(lines),
        reply_markup=superadmin_tenants_kb(tenants, selected_id=sel_id),
    )


@router.callback_query(F.data.startswith("sa:sel_ten:"))
async def cb_superadmin_select_tenant(cb: CallbackQuery, state: FSMContext) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    tid = int(cb.data.split(":")[-1])
    await _set_sa_tenant(uid, tid)
    await state.clear()
    text, kb = await _superadmin_panel(uid)
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer(f"✅ Filial #{tid} tanlandi!")


@router.callback_query(F.data == "sa:new_tenant")
async def cb_superadmin_new_tenant_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await state.set_state(SuperAdminStates.waiting_new_tenant_name)
    await cb.message.answer(
        "🏢 Yangi bo'sh filial nomini kiriting (masalan: <code>Chorsu Norin Sexi</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(
    SuperAdminStates.waiting_new_tenant_name,
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
    F.text != "❌ Bekor qilish",
)
async def process_superadmin_new_tenant(message: Message, state: FSMContext) -> None:
    uid = message.from_user.id if message.from_user else None
    if not is_super_admin(uid):
        return
    name = (message.text or "").strip()
    if not name:
        await message.answer("⚠️ Filial nomini kiriting:")
        return
    async with async_session_maker() as db:
        sub = await create_tenant(db, tenant_name=name)
    await _set_sa_tenant(uid, sub.id)
    await state.clear()
    text, kb = await _superadmin_panel(uid)
    merged_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔗 Shu filialga odam bog'lash (Telegramdan tanlash)",
                    callback_data="sa:add_user",
                )
            ],
            *kb.inline_keyboard,
        ]
    )
    await message.answer(
        f"✅ Yangi filial yaratildi: <b>#{sub.id} {html.escape(sub.tenant_name)}</b>!",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    await message.answer(text, parse_mode="HTML", reply_markup=merged_kb)


@router.callback_query(F.data.startswith("sa:ext:"))
async def cb_superadmin_extend_quick(cb: CallbackQuery) -> None:
    uid = cb.from_user.id if cb.from_user else 0
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    days = int(cb.data.split(":")[-1])
    tid = await _get_sa_tenant(uid)
    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db, tenant_id=tid)
        monthly = float(sub_status.state.monthly_price)
        pay_amount = round((monthly / 30.0) * days)
        await extend_subscription(
            db,
            days=days,
            amount=pay_amount,
            recorded_by=uid,
            note=f"SuperAdmin +{days} kun",
            tenant_id=tid,
        )
    text, kb = await _superadmin_panel(uid)
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer(f"✅ #{tid} uchun +{days} kun qo'shildi!")


@router.callback_query(F.data == "sa:ext_custom")
async def cb_superadmin_extend_custom_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await state.set_state(SuperAdminStates.waiting_custom_extend_days)
    await cb.message.answer(
        "🗓 Necha kun qo'shmoqchisiz? (masalan: <code>30</code> yoki <code>365</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(
    SuperAdminStates.waiting_custom_extend_days,
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
    F.text != "❌ Bekor qilish",
)
async def process_superadmin_custom_days(message: Message, state: FSMContext) -> None:
    uid = message.from_user.id if message.from_user else 0
    if not is_super_admin(uid):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("⚠️ Musbat butun son kiriting (masalan: 30):")
        return
    days = int(raw)
    tid = await _get_sa_tenant(uid)
    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db, tenant_id=tid)
        pay_amount = round((float(sub_status.state.monthly_price) / 30.0) * days)
        await extend_subscription(
            db,
            days=days,
            amount=pay_amount,
            recorded_by=uid,
            note=f"Maxsus +{days} kun",
            tenant_id=tid,
        )
    await state.clear()
    text, kb = await _superadmin_panel(uid)
    await message.answer(
        f"✅ Filial #{tid} obunasi +{days} kunga uzaytirildi!",
        reply_markup=main_menu_keyboard(),
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "sa:edit_price")
async def cb_superadmin_edit_price(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await state.set_state(SuperAdminStates.waiting_monthly_price)
    await cb.message.answer(
        "💳 Yangi oylik obuna narxini kiriting (masalan: <code>400 000</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(
    SuperAdminStates.waiting_monthly_price,
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
    F.text != "❌ Bekor qilish",
)
async def process_superadmin_price(message: Message, state: FSMContext) -> None:
    uid = message.from_user.id if message.from_user else None
    if not is_super_admin(uid):
        return
    amt = parse_uzbek_amount(message.text or "")
    if not amt or amt <= 0:
        await message.answer("⚠️ To'g'ri summa kiriting:")
        return
    tid = await _get_sa_tenant(uid)
    async with async_session_maker() as db:
        await update_subscription_settings(db, monthly_price=amt, tenant_id=tid)
    await state.clear()
    text, kb = await _render_tenant_settings_view(tid)
    await message.answer(f"✅ Oylik narx yangilandi: {format_uzs(amt)} so'm", reply_markup=main_menu_keyboard())
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "sa:edit_tenant")
async def cb_superadmin_edit_tenant(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await state.set_state(SuperAdminStates.waiting_tenant_name)
    await cb.message.answer(
        "🏢 Buyurtmachi (Sex) nomini kiriting (masalan: <code>Iftiqor Norin Sexi</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(
    SuperAdminStates.waiting_tenant_name,
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
    F.text != "❌ Bekor qilish",
)
async def process_superadmin_tenant(message: Message, state: FSMContext) -> None:
    uid = message.from_user.id if message.from_user else None
    if not is_super_admin(uid):
        return
    name = (message.text or "").strip()
    if not name:
        await message.answer("⚠️ Nom kiriting:")
        return
    tid = await _get_sa_tenant(uid)
    async with async_session_maker() as db:
        await update_subscription_settings(db, tenant_name=name, tenant_id=tid)
    await state.clear()
    text, kb = await _render_tenant_settings_view(tid)
    await message.answer(
        f"✅ Filial #{tid} nomi yangilandi: {html.escape(name)}",
        reply_markup=main_menu_keyboard(),
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "sa:edit_contact")
async def cb_superadmin_edit_contact(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await state.set_state(SuperAdminStates.waiting_owner_contact)
    await cb.message.answer(
        "📞 Bog'lanish kontaktini kiriting (masalan: <code>@SunnatDevPy / +998901234567</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(
    SuperAdminStates.waiting_owner_contact,
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
    F.text != "❌ Bekor qilish",
)
async def process_superadmin_contact(message: Message, state: FSMContext) -> None:
    uid = message.from_user.id if message.from_user else None
    if not is_super_admin(uid):
        return
    contact = (message.text or "").strip()
    if not contact:
        await message.answer("⚠️ Kontakt kiriting:")
        return
    tid = await _get_sa_tenant(uid)
    async with async_session_maker() as db:
        await update_subscription_settings(db, owner_contact=contact, tenant_id=tid)
    await state.clear()
    text, kb = await _render_tenant_settings_view(tid)
    await message.answer("✅ Kontakt yangilandi!", reply_markup=main_menu_keyboard())
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


async def _render_tenant_settings_view(tenant_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Render Super Admin settings screen for the currently selected tenant."""
    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db, tenant_id=tenant_id)
        sub = sub_status.state
        stats = await get_tenant_overview_stats(db, sub.id)
        with tenant_scope(sub.id):
            auto_confirm = (await get_app_setting(db, "auto_confirm", "on")) == "on"
            group_auto = (await get_app_setting(db, "group_auto_calc", "on")) == "on"
            round_mode = await get_app_setting(db, "round_mode", "none")
            _, ai_used, ai_limit = await check_tenant_ai_quota(db, tenant_id=sub.id)

    round_desc = {
        "nearest_1000": "Eng yaqin 1 000 so'm",
        "floor_1000": "1 000 so'm pastga",
        "none": "Yaxlitlamaslik (aniq)",
    }.get(round_mode, round_mode)
    ai_limit_desc = (
        f"{ai_limit}/kun (bugun: {ai_used})" if ai_limit > 0 else f"Cheksiz (bugun: {ai_used})"
    )
    text = (
        f"⚙️ <b>FILIAL SOZLAMALARI — #{sub.id} {html.escape(sub.tenant_name)}</b>\n"
        "===============================\n"
        f"🏢 Filial nomi: <b>{html.escape(sub.tenant_name)}</b>\n"
        f"📦 Tarif: <b>{html.escape(sub.plan_name)}</b>\n"
        f"💳 Oylik narx: <b>{format_uzs(sub.monthly_price)} so'm</b>\n"
        f"⏳ Imtiyoz (Grace): <b>{sub.grace_days} kun</b>\n"
        f"📞 Aloqa kontakti: <b>{html.escape(sub.owner_contact)}</b>\n"
        "-------------------------------\n"
        f"⚡ DM Avto-tasdiq: <b>{'✅ Yoqilgan' if auto_confirm else '❌ O‘chiq'}</b>\n"
        f"👥 Guruhda Avto-hisob: <b>{'✅ Yoqilgan' if group_auto else '❌ O‘chiq'}</b>\n"
        f"🔢 Summa yaxlitlash: <b>{round_desc}</b>\n"
        f"🤖 Kunlik AI limit: <b>{ai_limit_desc}</b>\n"
        "-------------------------------\n"
        f"📊 Xodim: <b>{stats['users']}</b> | Mijoz: <b>{stats['clients']}</b> (guruh: <b>{stats['groups']}</b>) | Sotuv: <b>{stats['sales']}</b>"
    )
    kb = superadmin_tenant_settings_kb(
        sub.id, auto_confirm, group_auto, round_mode, ai_daily_limit=ai_limit
    )
    return text, kb


@router.callback_query(F.data == "sa:settings")
async def cb_superadmin_tenant_settings(cb: CallbackQuery, state: FSMContext) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await state.clear()
    tid = await _get_sa_tenant(uid)
    text, kb = await _render_tenant_settings_view(tid)
    await fast_edit(cb, text, reply_markup=kb)


@router.callback_query(F.data == "sa:edit_plan")
async def cb_superadmin_edit_plan(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await state.set_state(SuperAdminStates.waiting_plan_name)
    await cb.message.answer(
        "📦 Yangi tarif nomini kiriting (masalan: <code>Pro Oylik</code> yoki <code>VIP</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(
    SuperAdminStates.waiting_plan_name,
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
    F.text != "❌ Bekor qilish",
)
async def process_superadmin_plan_name(message: Message, state: FSMContext) -> None:
    uid = message.from_user.id if message.from_user else None
    if not is_super_admin(uid):
        return
    plan = (message.text or "").strip()
    if not plan:
        await message.answer("⚠️ Tarif nomini kiriting:")
        return
    tid = await _get_sa_tenant(uid)
    async with async_session_maker() as db:
        await update_subscription_settings(db, plan_name=plan, tenant_id=tid)
    await state.clear()
    text, kb = await _render_tenant_settings_view(tid)
    await message.answer(
        f"✅ Tarif nomi yangilandi: <b>{html.escape(plan)}</b>",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "sa:edit_grace")
async def cb_superadmin_edit_grace(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await state.set_state(SuperAdminStates.waiting_grace_days)
    await cb.message.answer(
        "⏳ Imtiyoz (Grace) kunlari sonini kiriting (<code>0</code> dan <code>60</code> gacha):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(
    SuperAdminStates.waiting_grace_days,
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
    F.text != "❌ Bekor qilish",
)
async def process_superadmin_grace_days(message: Message, state: FSMContext) -> None:
    uid = message.from_user.id if message.from_user else None
    if not is_super_admin(uid):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (0 <= int(raw) <= 60):
        await message.answer("⚠️ 0 dan 60 gacha butun son kiriting:")
        return
    grace = int(raw)
    tid = await _get_sa_tenant(uid)
    async with async_session_maker() as db:
        await update_subscription_settings(db, grace_days=grace, tenant_id=tid)
    await state.clear()
    text, kb = await _render_tenant_settings_view(tid)
    await message.answer(
        f"✅ Imtiyoz davri yangilandi: <b>{grace} kun</b>",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("sa:ten_toggle:"))
async def cb_superadmin_tenant_toggle(cb: CallbackQuery) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    key = cb.data.split(":")[-1]
    tid = await _get_sa_tenant(uid)
    async with async_session_maker() as db:
        with tenant_scope(tid):
            if key in ("auto_confirm", "group_auto_calc"):
                cur = await get_app_setting(db, key, "on")
                await set_app_setting(db, key, "off" if cur == "on" else "on")
            elif key == "round_mode":
                cur = await get_app_setting(db, "round_mode", "none")
                cycle = {"none": "nearest_1000", "nearest_1000": "floor_1000", "floor_1000": "none"}
                await set_app_setting(db, "round_mode", cycle.get(cur, "none"))
            elif key == "ai_daily_limit":
                cur = (await get_app_setting(db, "ai_daily_limit", "0")).strip() or "0"
                cycle = {"0": "50", "50": "100", "100": "200", "200": "500", "500": "0"}
                await set_app_setting(db, "ai_daily_limit", cycle.get(cur, "0"))
            else:
                await cb.answer("Noma'lum sozlama")
                return
    text, kb = await _render_tenant_settings_view(tid)
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer("✅ Sozlama saqlandi!")


@router.callback_query(F.data == "sa:toggle_suspend")
async def cb_superadmin_toggle_suspend(cb: CallbackQuery) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    tid = await _get_sa_tenant(uid)
    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db, tenant_id=tid)
        new_val = not sub_status.state.is_suspended
        await update_subscription_settings(db, is_suspended=new_val, tenant_id=tid)
    text, kb = await _superadmin_panel(uid)
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer("⏸ Filial bloklandi" if new_val else "▶️ Filial faollashtirildi")


@router.callback_query(F.data == "sa:users")
async def cb_superadmin_users(cb: CallbackQuery) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    tid = await _get_sa_tenant(uid)
    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db, tenant_id=tid)
        users = await list_authorized_users(db, active_only=True, tenant_id=sub_status.state.id)
    settings = get_settings()
    env_block = (
        f"• <code>.env ADMIN_IDS</code>: <code>{html.escape(settings.formatted_admin_entries)}</code>\n"
        if sub_status.state.id == 1
        else ""
    )
    await fast_edit(
        cb,
        f"👥 <b>#{sub_status.state.id} {html.escape(sub_status.state.tenant_name)} — Foydalanuvchilar</b>\n\n"
        f"{env_block}"
        "• Foydalanuvchini boshqarish (rol, boshqa filialga ko'chirish, o'chirish) uchun ustiga bosing.\n"
        "• Telegramdan odam tanlab bog'lash uchun pastdagi <b>«🔗 Shu filialga odam bog'lash»</b> yoki <b>«🆕 Yangi mijoz + yangi filial»</b> ni bosing.",
        reply_markup=superadmin_users_kb(users, tenant_id=sub_status.state.id),
    )


async def _render_user_detail_view(tg_id: int) -> Optional[tuple[str, InlineKeyboardMarkup]]:
    async with async_session_maker() as db:
        user = await get_authorized_user(db, tg_id)
        if user is None:
            return None
        tenants = await list_tenants(db)
        sub_status = await evaluate_subscription_status(db, tenant_id=user.tenant_id)
    role_lbl = "👑 Filial Admini (owner)" if user.role == "owner" else "👤 Xodim (staff)"
    text = (
        "👤 <b>FOYDALANUVCHI PROFILI</b>\n"
        "===============================\n"
        f"• Ism: <b>{html.escape(user.full_name)}</b>\n"
        f"• Telegram ID: <code>{user.telegram_id}</code>\n"
        f"• Rol: <b>{role_lbl}</b>\n"
        f"• Filial: <b>#{sub_status.state.id} {html.escape(sub_status.state.tenant_name)}</b>\n\n"
        "Rolni o'zgartirishingiz, boshqa filialga ko'chirishingiz yoki o'chirishingiz mumkin:"
    )
    kb = superadmin_user_detail_kb(user.telegram_id, user.role, tenants, user.tenant_id)
    return text, kb


@router.callback_query(F.data.startswith("sa:user_info:"))
async def cb_superadmin_user_info(cb: CallbackQuery) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    tg_id = int(cb.data.split(":")[-1])
    res = await _render_user_detail_view(tg_id)
    if not res:
        await cb.answer("Foydalanuvchi topilmadi", show_alert=True)
        return
    text, kb = res
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("sa:user_role:"))
async def cb_superadmin_user_role(cb: CallbackQuery) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    tg_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        user = await get_authorized_user(db, tg_id)
        if user is None:
            await cb.answer("Foydalanuvchi topilmadi", show_alert=True)
            return
        new_role = "staff" if user.role == "owner" else "owner"
        await reassign_authorized_user(db, tg_id, user.tenant_id, role=new_role)
    res = await _render_user_detail_view(tg_id)
    if res:
        text, kb = res
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer("✅ Rol yangilandi!")


@router.callback_query(F.data.startswith("sa:user_move:"))
async def cb_superadmin_user_move(cb: CallbackQuery) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    parts = cb.data.split(":")
    tg_id = int(parts[2])
    target_tid = int(parts[3])
    async with async_session_maker() as db:
        moved = await reassign_authorized_user(db, tg_id, target_tid)
    if not moved:
        await cb.answer("Ko'chirib bo'lmadi", show_alert=True)
        return
    await _set_sa_tenant(uid, target_tid)
    res = await _render_user_detail_view(tg_id)
    if res:
        text, kb = res
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer(f"✅ Filial #{target_tid} ga ko'chirildi!")


_SA_PICK_USER_FILTER = (
    F.users_shared
    | F.user_shared
    | F.forward_origin
    | F.forward_from
    | (
        F.text
        & ~F.text.startswith("/")
        & ~F.text.in_(MAIN_MENU_BUTTONS)
        & (F.text != "❌ Bekor qilish")
    )
)


def _extract_picked_user(message: Message) -> tuple[Optional[int], str, str, bool]:
    """
    Extract (telegram_id, full_name, username, is_hidden_forward) from:
    - Telegram native user picker (`users_shared` / `user_shared`)
    - Forwarded message (`forward_origin` / `forward_from`)
    - Manual numeric ID in `message.text`
    """
    if getattr(message, "users_shared", None):
        shared = message.users_shared
        if getattr(shared, "users", None):
            u = shared.users[0]
            name = " ".join(
                x for x in (getattr(u, "first_name", None) or "", getattr(u, "last_name", None) or "") if x
            ).strip()
            uname = f"@{u.username}" if getattr(u, "username", None) else ""
            return int(u.user_id), name, uname, False
        if getattr(shared, "user_ids", None):
            return int(shared.user_ids[0]), "", "", False

    if getattr(message, "user_shared", None):
        return int(message.user_shared.user_id), "", "", False

    origin = getattr(message, "forward_origin", None)
    if origin is not None:
        sender = getattr(origin, "sender_user", None)
        if sender is not None:
            uname = f"@{sender.username}" if getattr(sender, "username", None) else ""
            return int(sender.id), (sender.full_name or "").strip(), uname, False
        return None, "", "", True

    fwd = getattr(message, "forward_from", None)
    if fwd is not None:
        uname = f"@{fwd.username}" if getattr(fwd, "username", None) else ""
        return int(fwd.id), (fwd.full_name or "").strip(), uname, False

    raw = (message.text or "").strip()
    if raw:
        first = raw.split(maxsplit=1)[0]
        if first.lstrip("-").isdigit():
            return int(first), "", "", False

    return None, "", "", False


async def _finalize_sa_user_binding(
    message: Message,
    state: FSMContext,
    sa_uid: int | None,
    tg_id: int,
    full_name: str,
    mode: str,
    target_tid: int,
    custom_tenant: str = "",
) -> None:
    """Create new tenant or bind user to target_tid, send welcome DM, and show confirmation."""
    await state.clear()
    async with async_session_maker() as db:
        if mode == "new_tenant":
            user = await add_authorized_user(
                db,
                telegram_id=tg_id,
                full_name=full_name,
                role="owner",
                create_new_tenant=True,
                new_tenant_name=custom_tenant or None,
            )
            final_tid = user.tenant_id
        else:
            user = await add_authorized_user(
                db,
                telegram_id=tg_id,
                full_name=full_name,
                role="staff",
                tenant_id=target_tid,
            )
            final_tid = user.tenant_id
        sub_status = await evaluate_subscription_status(db, tenant_id=final_tid)
        users = await list_authorized_users(db, active_only=True, tenant_id=final_tid)

    await _set_sa_tenant(sa_uid, final_tid)
    try:
        await message.bot.send_message(
            chat_id=tg_id,
            text=(
                "🎉 <b>Norin AI Hisobot botiga xush kelibsiz!</b>\n\n"
                f"🏢 Siz <b>#{final_tid} {html.escape(sub_status.state.tenant_name)}</b> filialiga ulandingiz.\n"
                "Boshlash uchun /start tugmasini bosing 👇"
            ),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
    except Exception as exc:
        logger.info("Welcome DM not delivered to %s: %s", tg_id, exc)

    title_msg = (
        "✅ <b>Yangi mijoz va alohida baza (Filial) ochildi!</b>\n\n"
        if mode == "new_tenant"
        else f"✅ <b>Foydalanuvchi #{final_tid} filialiga bog'landi!</b>\n\n"
    )
    await message.answer(
        f"{title_msg}"
        f"👤 Foydalanuvchi: <b>{html.escape(user.full_name)}</b> (<code>{tg_id}</code>)\n"
        f"🏢 Filial: <b>#{final_tid} {html.escape(sub_status.state.tenant_name)}</b>\n"
        "<i>U /start bosganda faqat shu filial bazasini ko'radi.</i>",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    await message.answer(
        f"👥 <b>#{final_tid} {html.escape(sub_status.state.tenant_name)}</b> odamlari:",
        parse_mode="HTML",
        reply_markup=superadmin_users_kb(users, tenant_id=final_tid),
    )


async def _handle_picked_user_step(
    message: Message, state: FSMContext, mode: str
) -> None:
    uid = message.from_user.id if message.from_user else None
    if not is_super_admin(uid):
        return

    tg_id, picked_name, picked_uname, is_hidden = _extract_picked_user(message)
    if is_hidden:
        await message.answer(
            "🔒 Bu foydalanuvchining profiling yopiq (forward yashirilgan).\n"
            "Pastdagi <b>«👤 Telegramdan odam tanlash»</b> tugmasini bosing — Telegram ID ni o'zi chiqaradi:",
            parse_mode="HTML",
        )
        return
    if tg_id is None:
        await message.answer(
            "⚠️ Pastdagi <b>«👤 Telegramdan odam tanlash»</b> tugmasini bosing, xabar forward qiling "
            "yoki ID yozing (masalan: <code>123456789 Sardor | Chorsu</code>):",
            parse_mode="HTML",
        )
        return
    if tg_id in get_settings().super_admin_id_list:
        await message.answer(
            "⚠️ Bu ID Super Admin sifatida Test Filial (#1) ga biriktirilgan.",
            reply_markup=main_menu_keyboard(),
        )
        await state.clear()
        return

    # 1-line text shortcut backward compatibility: "123456789 Sardor" or "123456789 Sardor | Chorsu"
    is_picker_or_fwd = bool(
        getattr(message, "users_shared", None)
        or getattr(message, "user_shared", None)
        or getattr(message, "forward_origin", None)
        or getattr(message, "forward_from", None)
    )
    if not is_picker_or_fwd and message.text:
        parts = message.text.strip().split(maxsplit=1)
        if len(parts) > 1 and parts[1].strip():
            rest = parts[1].strip()
            if mode == "new_tenant" and "|" in rest:
                full_name, custom_tenant = (x.strip() for x in rest.split("|", 1))
                full_name = full_name or f"Mijoz {tg_id}"
            else:
                full_name = rest
                custom_tenant = ""
            target_tid = 0 if mode == "new_tenant" else await _get_sa_tenant(uid)
            await _finalize_sa_user_binding(
                message, state, uid, tg_id, full_name, mode, target_tid, custom_tenant
            )
            return

    target_tid = 0 if mode == "new_tenant" else await _get_sa_tenant(uid)
    existing_note = ""
    async with async_session_maker() as db:
        existing = await get_authorized_user(db, tg_id)
        if existing is not None:
            ex_sub = await evaluate_subscription_status(db, tenant_id=existing.tenant_id)
            existing_note = (
                f"\n⚠️ <i>Bu ID avval <b>#{existing.tenant_id} {html.escape(ex_sub.state.tenant_name)}</b> "
                "filialiga biriktirilgan — davom etsangiz ko'chiriladi.</i>"
            )

    await state.set_state(SuperAdminStates.waiting_add_user_name)
    await state.update_data(
        picked_tg_id=tg_id,
        picked_tg_name=picked_name,
        picked_uname=picked_uname,
        bind_mode=mode,
        bind_tenant_id=target_tid,
    )
    uname_lbl = f" ({html.escape(picked_uname)})" if picked_uname else ""
    prof_lbl = html.escape(picked_name) if picked_name else f"User {tg_id}"
    hint_prompt = (
        "✏️ Endi mijoz ismini (yoki <code>Ism | Filial nomi</code> shaklida) tering, "
        "yoki pastdagi tayyor nom tugmasini bosing:"
        if mode == "new_tenant"
        else f"✏️ <b>Filial #{target_tid}</b> uchun xodim ismini tering yoki pastdagi tayyor nomni bosing:"
    )
    await message.answer(
        f"✅ <b>Topildi!</b>\n"
        f"👤 Profil: <b>{prof_lbl}</b>{uname_lbl}\n"
        f"🆔 ID: <code>{tg_id}</code>"
        f"{existing_note}\n\n"
        f"{hint_prompt}",
        parse_mode="HTML",
        reply_markup=superadmin_default_name_reply_kb(picked_name),
    )


@router.callback_query(F.data == "sa:add_user_new")
async def cb_superadmin_add_user_new_tenant_prompt(
    cb: CallbackQuery, state: FSMContext
) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await state.set_state(SuperAdminStates.waiting_add_user_id)
    await cb.message.answer(
        "🆕 <b>Yangi mijoz + alohida filial (baza) ochish</b>\n\n"
        "1️⃣ Pastdagi <b>«👤 Telegramdan odam tanlash»</b> tugmasini bosing — Telegram ro'yxatingizdan tanlaysiz va bot ID ni avtomatik oladi!\n"
        "<i>(Yoki foydalanuvchi xabarini shu yerga forward qiling yoxud <code>123456789 Sardor | Chorsu</code> deb yozing.)</i>",
        parse_mode="HTML",
        reply_markup=superadmin_pick_user_reply_kb(request_id=101),
    )
    await cb.answer()


@router.callback_query(F.data == "sa:add_user")
async def cb_superadmin_add_user_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    tid = await _get_sa_tenant(uid)
    await state.set_state(SuperAdminStates.waiting_add_user_same_tenant_id)
    await cb.message.answer(
        f"🔗 <b>Filial #{tid}</b> ga odam bog'lash\n\n"
        "Pastdagi <b>«👤 Telegramdan odam tanlash»</b> tugmasini bosing — ro'yxatdan tanlasangiz ID avtomatik olinadi!\n"
        "<i>(Yoki xabarini forward qiling yoxud <code>123456789 Sardor</code> deb yozing.)</i>",
        parse_mode="HTML",
        reply_markup=superadmin_pick_user_reply_kb(request_id=102),
    )
    await cb.answer()


@router.message(
    SuperAdminStates.waiting_add_user_id,
    F.chat.type == "private",
    _SA_PICK_USER_FILTER,
)
async def process_superadmin_add_user_new_tenant(
    message: Message, state: FSMContext
) -> None:
    await _handle_picked_user_step(message, state, mode="new_tenant")


@router.message(
    SuperAdminStates.waiting_add_user_same_tenant_id,
    F.chat.type == "private",
    _SA_PICK_USER_FILTER,
)
async def process_superadmin_add_user_same_tenant(
    message: Message, state: FSMContext
) -> None:
    await _handle_picked_user_step(message, state, mode="same_tenant")


@router.message(
    SuperAdminStates.waiting_add_user_name,
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
    F.text != "❌ Bekor qilish",
)
async def process_superadmin_picked_user_name(
    message: Message, state: FSMContext
) -> None:
    uid = message.from_user.id if message.from_user else None
    if not is_super_admin(uid):
        return
    raw = (message.text or "").strip()
    if raw.startswith("✅ "):
        raw = raw[2:].strip()
    data = await state.get_data()
    tg_id = data.get("picked_tg_id")
    if not tg_id:
        await state.clear()
        await message.answer("⚠️ Sessiya eskirdi, qaytadan urinib ko'ring.", reply_markup=main_menu_keyboard())
        return
    mode = str(data.get("bind_mode") or "same_tenant")
    target_tid = int(data.get("bind_tenant_id") or 1)
    default_name = str(data.get("picked_tg_name") or "").strip() or f"Mijoz {tg_id}"

    if mode == "new_tenant" and "|" in raw:
        full_name, custom_tenant = (x.strip() for x in raw.split("|", 1))
        full_name = full_name or default_name
    else:
        full_name = raw or default_name
        custom_tenant = ""

    await _finalize_sa_user_binding(
        message=message,
        state=state,
        sa_uid=uid,
        tg_id=int(tg_id),
        full_name=full_name,
        mode=mode,
        target_tid=target_tid,
        custom_tenant=custom_tenant,
    )


@router.callback_query(F.data.startswith("sa:del_user:"))
async def cb_superadmin_del_user(cb: CallbackQuery) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    tg_id = int(cb.data.split(":")[-1])
    tid = await _get_sa_tenant(uid)
    await cb.message.edit_text(
        f"⚠️ Foydalanuvchi <code>{tg_id}</code> ni Filial #{tid} dan o'chirmoqchimisiz?",
        parse_mode="HTML",
        reply_markup=confirm_delete_kb(f"sa:del_user_ok:{tg_id}", "sa:users"),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sa:del_user_ok:"))
async def cb_superadmin_del_user_ok(cb: CallbackQuery) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    tg_id = int(cb.data.split(":")[-1])
    tid = await _get_sa_tenant(uid)
    async with async_session_maker() as db:
        await remove_authorized_user(db, tg_id, tenant_id=tid)
        sub_status = await evaluate_subscription_status(db, tenant_id=tid)
        users = await list_authorized_users(db, active_only=True, tenant_id=sub_status.state.id)
    await cb.message.edit_text(
        f"👥 <b>#{sub_status.state.id} {html.escape(sub_status.state.tenant_name)} — Foydalanuvchilar</b>",
        parse_mode="HTML",
        reply_markup=superadmin_users_kb(users, tenant_id=sub_status.state.id),
    )
    await cb.answer("🗑 Foydalanuvchi o'chirildi!")


@router.callback_query(F.data.startswith("sa:del_tenant:"))
async def cb_superadmin_del_tenant_prompt(cb: CallbackQuery) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    tid = int(cb.data.split(":")[-1])
    if tid <= 1:
        await cb.answer("⛔ #1 Asosiy/Test filialni o'chirib bo'lmaydi!", show_alert=True)
        return
    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db, tenant_id=tid)
    await cb.message.edit_text(
        f"🗑 <b>Filial #{sub_status.state.id} {html.escape(sub_status.state.tenant_name)}</b> ni butunlay o'chirmoqchimisiz?\n\n"
        "⚠️ Ushbu filialning barcha sotuvlari, mijozlari, xodimlari va kassa tarixi <b>qaytmas bo'lib o'chadi!</b>",
        parse_mode="HTML",
        reply_markup=confirm_delete_kb(f"sa:del_tenant_ok:{tid}", "sa:menu"),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sa:del_tenant_ok:"))
async def cb_superadmin_del_tenant_ok(cb: CallbackQuery) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    tid = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        deleted = await delete_tenant(db, tid)
    if deleted:
        await _set_sa_tenant(uid, 1)
    text, kb = await _superadmin_panel(uid)
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer("🗑 Filial o'chirildi!" if deleted else "⚠️ O'chirib bo'lmadi", show_alert=True)


@router.callback_query(F.data == "sa:broadcast")
async def cb_superadmin_broadcast_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await state.set_state(SuperAdminStates.waiting_broadcast_text)
    await cb.message.answer(
        "📢 <b>Barcha filiallar va foydalanuvchilarga e'lon yuborish</b>\n\n"
        "Yuboriladigan xabar matnini yozing:",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(
    SuperAdminStates.waiting_broadcast_text,
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
    F.text != "❌ Bekor qilish",
)
async def process_superadmin_broadcast(message: Message, state: FSMContext) -> None:
    uid = message.from_user.id if message.from_user else None
    if not is_super_admin(uid):
        return
    msg_text = (message.text or "").strip()
    if not msg_text:
        await message.answer("⚠️ Xabar matnini kiriting:")
        return
    await state.clear()
    async with async_session_maker() as db:
        recipients = await list_all_broadcast_recipients(db)

    sent = 0
    for target_uid in recipients:
        try:
            await message.bot.send_message(
                chat_id=target_uid,
                text=f"📢 <b>Tizim e'loni:</b>\n\n{html.escape(msg_text)}",
                parse_mode="HTML",
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as exc:
            logger.warning("Broadcast failed for %s: %s", target_uid, exc)

    await message.answer(
        f"📢 E'lon yuborildi: <b>{sent}/{len(recipients)}</b> ta foydalanuvchiga.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    text, kb = await _superadmin_panel(uid)
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "sa:payments")
async def cb_superadmin_payments(cb: CallbackQuery) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    tid = await _get_sa_tenant(uid)
    async with async_session_maker() as db:
        payments = await list_subscription_payments(db, limit=15, tenant_id=tid)
    if not payments:
        await cb.answer(f"Filial #{tid} uchun to'lovlar tarixi yo'q.", show_alert=True)
        return
    lines = [f"📜 <b>Filial #{tid} Obuna To'lovlari Tarixi:</b>\n"]
    for idx, p in enumerate(payments, start=1):
        dt = format_local_dt(p.paid_at, "%d.%m.%Y %H:%M")
        lines.append(
            f"{idx}) <code>{dt}</code> | +{p.days_added} kun | <b>{format_uzs(p.amount)} so'm</b> <i>({html.escape(p.note or p.plan_name)})</i>"
        )
    await cb.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ Super Admin", callback_data="sa:menu")]]
        ),
    )
    await cb.answer()


@router.callback_query(F.data == "sa:send_reminder")
async def cb_superadmin_send_reminder(cb: CallbackQuery) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    tid = await _get_sa_tenant(uid)
    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db, tenant_id=tid)
        db_users = await list_authorized_users(db, active_only=True, tenant_id=sub_status.state.id)
    sub = sub_status.state
    exp_str = format_local_dt(sub.expires_at, "%d.%m.%Y")
    recipients = {u.telegram_id for u in db_users}
    if sub.id == 1:
        recipients |= set(get_settings().admin_id_list)
    recipients -= set(get_settings().super_admin_id_list)
    if sub.id == 1 and not recipients:
        recipients = set(get_settings().admin_id_list)

    sent = 0
    for target_uid in recipients:
        try:
            await cb.bot.send_message(
                chat_id=target_uid,
                text=(
                    "🔔 <b>Obuna eslatmasi — Norin AI Hisobot</b>\n\n"
                    f"🏢 Filial: <b>#{sub.id} {html.escape(sub.tenant_name)}</b>\n"
                    f"📦 Tarif: <b>{html.escape(sub.plan_name)}</b>\n"
                    f"💳 Oylik to'lov: <b>{format_uzs(sub.monthly_price)} so'm</b>\n"
                    f"📅 Tugash sanasi: <b>{exp_str}</b>\n\n"
                    f"Bot uzluksiz ishlashi uchun to'lovni amalga oshiring. Aloqa: <b>{html.escape(sub.owner_contact)}</b>"
                ),
                parse_mode="HTML",
                reply_markup=subscription_status_kb(),
            )
            sent += 1
        except Exception:
            pass
    await cb.answer(f"🔔 #{sub.id}: {sent} ta foydalanuvchiga eslatma yuborildi!", show_alert=True)


@router.callback_query(F.data.startswith("sa:approve:"))
async def cb_superadmin_approve_renewal(cb: CallbackQuery) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    parts = cb.data.split(":")
    uid = cb.from_user.id if cb.from_user else 0

    async with async_session_maker() as db:
        if len(parts) >= 5:
            ten_id = int(parts[2])
            requester_id = int(parts[3])
            days = int(parts[4])
        else:
            requester_id = int(parts[2])
            days = int(parts[3])
            ten_id = await resolve_user_tenant_id(db, requester_id)

        sub_status = await evaluate_subscription_status(db, tenant_id=ten_id)
        amount = round((float(sub_status.state.monthly_price) / 30.0) * days)
        updated = await extend_subscription(
            db,
            days=days,
            amount=amount,
            recorded_by=uid,
            note=f"Mijoz ({requester_id}) so'rovi bo'yicha +{days} kun",
            tenant_id=sub_status.state.id,
        )
    exp_str = format_local_dt(updated.expires_at, "%d.%m.%Y")

    try:
        await cb.bot.send_message(
            chat_id=requester_id,
            text=(
                f"✅ <b>Tabriklaymiz! Obunangiz +{days} kunga uzaytirildi!</b>\n"
                f"🏢 Filial: <b>#{updated.id} {html.escape(updated.tenant_name)}</b>\n"
                f"📅 Yangi amal qilish muddati: <b>{exp_str}</b>\n"
                "Botdan bemalol foydalanishingiz mumkin."
            ),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
    except Exception:
        pass

    await cb.message.edit_text(
        f"✅ Tasdiqlandi! Filial <b>#{updated.id} {html.escape(updated.tenant_name)}</b> "
        f"(ID: <code>{requester_id}</code>) obunasi <b>+{days} kunga</b> uzaytirildi.\n"
        f"📅 Yangi muddat: <b>{exp_str}</b>",
        parse_mode="HTML",
    )
    await cb.answer("✅ Uzaytirildi!")


@router.callback_query(F.data.startswith("sa:reject:"))
async def cb_superadmin_reject_renewal(cb: CallbackQuery) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    parts = cb.data.split(":")
    async with async_session_maker() as db:
        if len(parts) >= 4:
            ten_id = int(parts[2])
            requester_id = int(parts[3])
        else:
            requester_id = int(parts[-1])
            ten_id = await resolve_user_tenant_id(db, requester_id)
        sub_status = await evaluate_subscription_status(db, tenant_id=ten_id)
    contact = sub_status.state.owner_contact
    try:
        await cb.bot.send_message(
            chat_id=requester_id,
            text=(
                "❌ <b>To'lov hali tasdiqlanmadi.</b>\n"
                f"Iltimos chekni yuboring yoki administrator bilan bog'laning: <b>{html.escape(contact)}</b>"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await cb.message.edit_text(
        f"❌ So'rov rad etildi (Filial #{ten_id}, ID: <code>{requester_id}</code>).",
        parse_mode="HTML",
    )
    await cb.answer("Rad etildi")


# ---------------------------------------------------------------------------
# Database Reset (/clear) for Super Admin
# ---------------------------------------------------------------------------


def _render_clear_menu_text(tenant_id: int, tenant_name: str) -> str:
    """Build /clear confirmation warning showing the exact target tenant."""
    return (
        "🧹 <b>BAZANI TOZALASH (/clear)</b>\n"
        "===============================\n"
        f"🎯 Tanlangan filial: <b>#{tenant_id} {html.escape(tenant_name)}</b>\n"
        "<i>Faqat shu filial ma'lumotlari tozalanadi, boshqa mijozlarga ta'sir qilmaydi!</i>\n\n"
        "1️⃣ <b>Faqat test savdo/qarz/kassa:</b>\n"
        "   • Sotuvlar, to'lovlar, xarajatlar va kassa tarixi o'chadi;\n"
        "   • Mijozlar, individual narxlar va ulangan guruhlar <b>saqlanib qoladi</b> (eski qarzlari 0 bo'ladi).\n\n"
        "2️⃣ <b>To'liq tozalash (Hammasi 0 dan):</b>\n"
        "   • Mijozlar, guruhlar, narxlar, sotuvlar va barcha hisobotlar o'chadi;\n"
        "   • Standart Ot/Mol norin mahsulotlari qaytadan tiklanadi;\n"
        "   • <b>Obuna muddati va ruxsat etilgan foydalanuvchilar saqlanadi.</b>"
    )


@router.message(Command("clear"), F.chat.type == "private")
async def cmd_superadmin_clear(message: Message, state: FSMContext) -> None:
    """Ask Super Admin confirmation before clearing test data or resetting the selected tenant DB."""
    uid = message.from_user.id if message.from_user else None
    if not is_super_admin(uid):
        await message.answer("⛔ Bu buyruq faqat tizim egasi (Super Admin) uchun.")
        return
    await state.clear()
    tid = await _get_sa_tenant(uid)
    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db, tenant_id=tid)
    await message.answer(
        _render_clear_menu_text(sub_status.state.id, sub_status.state.tenant_name),
        parse_mode="HTML",
        reply_markup=superadmin_clear_confirm_kb(),
    )


@router.callback_query(F.data == "sa:clear_menu")
async def cb_superadmin_clear_menu(cb: CallbackQuery) -> None:
    uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    tid = await _get_sa_tenant(uid)
    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db, tenant_id=tid)
    await cb.message.edit_text(
        _render_clear_menu_text(sub_status.state.id, sub_status.state.tenant_name),
        parse_mode="HTML",
        reply_markup=superadmin_clear_confirm_kb(),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sa:clear_exec:"))
async def cb_superadmin_clear_execute(cb: CallbackQuery) -> None:
    sa_uid = cb.from_user.id if cb.from_user else None
    if not is_super_admin(sa_uid):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    mode = cb.data.split(":")[-1]
    if mode not in ("tx", "full"):
        await cb.answer("Noto'g'ri rejim")
        return

    tid = await _get_sa_tenant(sa_uid)
    settings = get_settings()
    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db, tenant_id=tid)
        target_tid = sub_status.state.id
        target_name = sub_status.state.tenant_name
        if mode == "full":
            stats = await reset_full_database(db, tenant_id=target_tid)
            client_notice = (
                f"🧹 <b>#{target_tid} {html.escape(target_name)} bazasi to'liq tozalandi!</b>\n"
                "Endi asosiy ishni 0 dan boshlashingiz mumkin."
            )
            title = f"💣 <b>#{target_tid} {html.escape(target_name)} — TO'LIQ TOZALANDI (0 dan)!</b>"
            extra_line = f"• Mijozlar o'chirildi: <b>{stats['clients']} ta</b> (mahsulotlar qayta yaratildi)\n"
        else:
            stats = await reset_test_transactions(db, tenant_id=target_tid)
            client_notice = (
                f"🧹 <b>#{target_tid} {html.escape(target_name)} — test savdo, qarz va kassa tozalandi!</b>\n"
                "Mijozlar va ulangan guruhlar saqlab qolindi — asosiy ishni boshlashingiz mumkin."
            )
            title = f"🧹 <b>#{target_tid} {html.escape(target_name)} — TEST SAVDO/QARZ/KASSA TOZALANDI!</b>"
            extra_line = "• Mijozlar va ulangan guruhlar saqlab qolindi (qarzlari 0 qilindi)\n"

        db_users = await list_authorized_users(db, active_only=True, tenant_id=target_tid)

    recipients = {u.telegram_id for u in db_users}
    if target_tid == 1:
        recipients |= set(settings.admin_id_list)
    recipients -= set(settings.super_admin_id_list)

    notified = 0
    for target_uid in recipients:
        try:
            await cb.bot.send_message(
                chat_id=target_uid,
                text=client_notice,
                parse_mode="HTML",
                reply_markup=main_menu_keyboard(),
            )
            notified += 1
        except Exception as exc:
            logger.warning("Failed to notify user %s after /clear: %s", target_uid, exc)

    if recipients:
        notify_line = f"📢 Filial foydalanuvchilariga xabar yuborildi: <b>{notified}/{len(recipients)} ta</b>"
    else:
        notify_line = "ℹ️ Ushbu filialda alohida foydalanuvchi ID ulanmagan."

    back_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Super Admin", callback_data="sa:menu")]]
    )
    await cb.message.edit_text(
        f"{title}\n"
        "===============================\n"
        f"• Sotuvlar o'chirildi: <b>{stats['sales']} ta</b>\n"
        f"• To'lovlar o'chirildi: <b>{stats['payments']} ta</b>\n"
        f"• Kassa/xarajat yozuvlari: <b>{stats['cash_txs']} ta</b>\n"
        f"• Kunlik sessiyalar: <b>{stats['sessions']} ta</b>\n"
        f"{extra_line}\n"
        f"{notify_line}",
        parse_mode="HTML",
        reply_markup=back_kb,
    )
    await cb.answer("✅ Tozalandi!")

"""Super Admin subscription management, authorized users, and client renewal notifications."""

from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.keyboards import (
    cancel_reply_keyboard,
    main_menu_keyboard,
    subscription_status_kb,
    superadmin_clear_confirm_kb,
    superadmin_menu_kb,
    superadmin_renewal_request_kb,
    superadmin_users_kb,
)
from bot.states import SuperAdminStates
from config import get_settings
from database.crud import (
    add_authorized_user,
    evaluate_subscription_status,
    extend_subscription,
    format_local_dt,
    is_user_authorized,
    list_authorized_users,
    list_subscription_payments,
    remove_authorized_user,
    reset_full_database,
    reset_test_transactions,
    update_subscription_settings,
)
from database.session import async_session_maker
from services.gemini_ai import format_uzs, parse_uzbek_amount


router = Router(name="superadmin")
logger = logging.getLogger("norin_bot.superadmin")


def is_super_admin(user_id: int | None) -> bool:
    """Check if Telegram user ID is listed in SUPER_ADMIN_IDS."""
    if user_id is None:
        return False
    return user_id in get_settings().super_admin_id_list


async def _render_superadmin_dashboard() -> tuple[str, bool]:
    """Render Super Admin subscription dashboard text and suspension flag."""
    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db)
        users = await list_authorized_users(db, active_only=True)
    sub = sub_status.state
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
    text = (
        "👑 <b>SUPER ADMIN PANEL — SaaS Obuna Boshqaruvi</b>\n"
        "===============================\n"
        f"🏢 Sex / Loyiha: <b>{html.escape(sub.tenant_name)}</b>\n"
        f"📦 Tarif: <b>{html.escape(sub.plan_name)}</b>\n"
        f"💳 Oylik narx: <b>{format_uzs(sub.monthly_price)} so'm</b>\n"
        f"📅 Tugash sanasi: <b>{exp_str}</b>\n"
        f"⏳ Imtiyoz (Grace): <b>{sub.grace_days} kun</b>\n"
        f"📌 Holat: <b>{status_map.get(sub_status.status, sub_status.status)}</b>\n"
        f"📞 Kontakt: <b>{html.escape(sub.owner_contact)}</b>\n"
        "-------------------------------\n"
        f"👥 Ruxsat etilganlar (.env): <code>{env_admins}</code>\n"
        f"👥 Qo'shilganlar (baza): <b>{len(users)} ta</b>"
    )
    return text, sub.is_suspended


async def _render_client_subscription_text() -> str:
    """Render subscription status card visible to client admins."""
    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db)
    sub = sub_status.state
    exp_str = format_local_dt(sub.expires_at, "%d.%m.%Y")

    status_map = {
        "active": f"🟢 Faol ({sub_status.days_left} kun qoldi)",
        "expiring": f"🟡 Tez orada tugaydi ({sub_status.days_left} kun qoldi)",
        "grace": f"🟠 Imtiyoz davri ({sub_status.grace_days_left} kun ichida to'lang)",
        "expired": "🔴 Muddati tugagan",
        "suspended": "⏸ Vaqtincha to'xtatilgan",
    }

    return (
        "💎 <b>Norin AI Obuna Holati</b>\n"
        "===============================\n"
        f"🏢 Sex: <b>{html.escape(sub.tenant_name)}</b>\n"
        f"📦 Tarif: <b>{html.escape(sub.plan_name)}</b>\n"
        f"💳 Oylik to'lov: <b>{format_uzs(sub.monthly_price)} so'm</b>\n"
        f"📅 Amal qilish muddati: <b>{exp_str}</b>\n"
        f"📌 Holat: <b>{status_map.get(sub_status.status, sub_status.status)}</b>\n\n"
        f"To'lovni amalga oshirib, <b>«💳 To'lov qildim»</b> tugmasini bosing — "
        f"administrator darhol muddatni uzaytirib beradi.\n"
        f"📞 Yordam / Aloqa: <b>{html.escape(sub.owner_contact)}</b>"
    )


# ---------------------------------------------------------------------------
# /myid & Client Subscription Views
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


@router.callback_query(F.data == "sub:status")
async def cb_subscription_status(cb: CallbackQuery) -> None:
    """Show client subscription status screen."""
    uid = cb.from_user.id if cb.from_user else None
    async with async_session_maker() as db:
        if not await is_user_authorized(db, uid):
            await cb.answer("Ruxsat yo'q", show_alert=True)
            return
    text = await _render_client_subscription_text()
    await cb.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=subscription_status_kb(),
    )
    await cb.answer()


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
                    f"🏢 Sex: <b>{html.escape(sub.tenant_name)}</b>\n"
                    f"👤 Mijoz: <b>{html.escape(full_name)}</b> {html.escape(uname)}\n"
                    f"🆔 Telegram ID: <code>{uid}</code>\n"
                    f"💰 Oylik tarif: <b>{format_uzs(sub.monthly_price)} so'm</b>\n\n"
                    "To'lov tushgan bo'lsa, 1 bosishda tasdiqlang:"
                ),
                parse_mode="HTML",
                reply_markup=superadmin_renewal_request_kb(uid),
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


@router.message(Command("superadmin"), F.chat.type == "private")
async def cmd_superadmin(message: Message, state: FSMContext) -> None:
    """Open Super Admin subscription control panel."""
    uid = message.from_user.id if message.from_user else None
    if not is_super_admin(uid):
        await message.answer("⛔ Bu bo'lim faqat tizim egasi (Super Admin) uchun.")
        return
    await state.clear()
    text, is_susp = await _render_superadmin_dashboard()
    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=superadmin_menu_kb(is_susp),
    )


@router.callback_query(F.data == "sa:menu")
async def cb_superadmin_menu(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await state.clear()
    text, is_susp = await _render_superadmin_dashboard()
    await cb.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=superadmin_menu_kb(is_susp),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sa:ext:"))
async def cb_superadmin_extend_quick(cb: CallbackQuery) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    days = int(cb.data.split(":")[-1])
    uid = cb.from_user.id if cb.from_user else 0
    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db)
        monthly = float(sub_status.state.monthly_price)
        pay_amount = round((monthly / 30.0) * days)
        await extend_subscription(
            db,
            days=days,
            amount=pay_amount,
            recorded_by=uid,
            note=f"SuperAdmin +{days} kun",
        )
    text, is_susp = await _render_superadmin_dashboard()
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=superadmin_menu_kb(is_susp))
    await cb.answer(f"✅ +{days} kun qo'shildi!")


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


@router.message(SuperAdminStates.waiting_custom_extend_days, F.chat.type == "private")
async def process_superadmin_custom_days(message: Message, state: FSMContext) -> None:
    if not is_super_admin(message.from_user.id if message.from_user else None):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("⚠️ Musbat butun son kiriting (masalan: 30):")
        return
    days = int(raw)
    uid = message.from_user.id if message.from_user else 0
    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db)
        pay_amount = round((float(sub_status.state.monthly_price) / 30.0) * days)
        await extend_subscription(
            db,
            days=days,
            amount=pay_amount,
            recorded_by=uid,
            note=f"Maxsus +{days} kun",
        )
    await state.clear()
    text, is_susp = await _render_superadmin_dashboard()
    await message.answer(
        f"✅ Obuna +{days} kunga uzaytirildi!",
        reply_markup=main_menu_keyboard(),
    )
    await message.answer(text, parse_mode="HTML", reply_markup=superadmin_menu_kb(is_susp))


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


@router.message(SuperAdminStates.waiting_monthly_price, F.chat.type == "private")
async def process_superadmin_price(message: Message, state: FSMContext) -> None:
    if not is_super_admin(message.from_user.id if message.from_user else None):
        return
    amt = parse_uzbek_amount(message.text or "")
    if not amt or amt <= 0:
        await message.answer("⚠️ To'g'ri summa kiriting:")
        return
    async with async_session_maker() as db:
        await update_subscription_settings(db, monthly_price=amt)
    await state.clear()
    text, is_susp = await _render_superadmin_dashboard()
    await message.answer(f"✅ Oylik narx yangilandi: {format_uzs(amt)} so'm", reply_markup=main_menu_keyboard())
    await message.answer(text, parse_mode="HTML", reply_markup=superadmin_menu_kb(is_susp))


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


@router.message(SuperAdminStates.waiting_tenant_name, F.chat.type == "private")
async def process_superadmin_tenant(message: Message, state: FSMContext) -> None:
    if not is_super_admin(message.from_user.id if message.from_user else None):
        return
    name = (message.text or "").strip()
    if not name:
        await message.answer("⚠️ Nom kiriting:")
        return
    async with async_session_maker() as db:
        await update_subscription_settings(db, tenant_name=name)
    await state.clear()
    text, is_susp = await _render_superadmin_dashboard()
    await message.answer("✅ Sex nomi yangilandi!", reply_markup=main_menu_keyboard())
    await message.answer(text, parse_mode="HTML", reply_markup=superadmin_menu_kb(is_susp))


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


@router.message(SuperAdminStates.waiting_owner_contact, F.chat.type == "private")
async def process_superadmin_contact(message: Message, state: FSMContext) -> None:
    if not is_super_admin(message.from_user.id if message.from_user else None):
        return
    contact = (message.text or "").strip()
    if not contact:
        await message.answer("⚠️ Kontakt kiriting:")
        return
    async with async_session_maker() as db:
        await update_subscription_settings(db, owner_contact=contact)
    await state.clear()
    text, is_susp = await _render_superadmin_dashboard()
    await message.answer("✅ Kontakt yangilandi!", reply_markup=main_menu_keyboard())
    await message.answer(text, parse_mode="HTML", reply_markup=superadmin_menu_kb(is_susp))


@router.callback_query(F.data == "sa:toggle_suspend")
async def cb_superadmin_toggle_suspend(cb: CallbackQuery) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db)
        new_val = not sub_status.state.is_suspended
        await update_subscription_settings(db, is_suspended=new_val)
    text, is_susp = await _render_superadmin_dashboard()
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=superadmin_menu_kb(is_susp))
    await cb.answer("⏸ Bot bloklandi" if is_susp else "▶️ Bot faollashtirildi")


@router.callback_query(F.data == "sa:users")
async def cb_superadmin_users(cb: CallbackQuery) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    async with async_session_maker() as db:
        users = await list_authorized_users(db, active_only=True)
    settings = get_settings()
    env_list = html.escape(settings.formatted_admin_entries)
    await cb.message.edit_text(
        "👥 <b>Ruxsat etilgan foydalanuvchilar</b>\n\n"
        f"• <code>.env ADMIN_IDS</code>: <code>{env_list}</code>\n"
        "• Bazadan qo'shilganlar (o'chirish uchun ustiga bosing):\n"
        "<i>Foydalanuvchi o'z ID sini bilish uchun botga /myid yozishi kifoya.</i>",
        parse_mode="HTML",
        reply_markup=superadmin_users_kb(users),
    )
    await cb.answer()


@router.callback_query(F.data == "sa:add_user")
async def cb_superadmin_add_user_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await state.set_state(SuperAdminStates.waiting_add_user_id)
    await cb.message.answer(
        "👤 Yangi foydalanuvchi Telegram ID sini kiriting (ixtiyoriy ism bilan, masalan: <code>123456789 Sardor</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(SuperAdminStates.waiting_add_user_id, F.chat.type == "private")
async def process_superadmin_add_user(message: Message, state: FSMContext) -> None:
    if not is_super_admin(message.from_user.id if message.from_user else None):
        return
    raw = (message.text or "").strip()
    parts = raw.split(maxsplit=1)
    if not parts or not parts[0].lstrip("-").isdigit():
        await message.answer("⚠️ Birinchi so'z raqamli Telegram ID bo'lishi kerak (masalan: <code>123456789 Sardor</code>):", parse_mode="HTML")
        return
    tg_id = int(parts[0])
    full_name = parts[1].strip() if len(parts) > 1 else f"Xodim {tg_id}"
    async with async_session_maker() as db:
        await add_authorized_user(db, telegram_id=tg_id, full_name=full_name, role="staff")
        users = await list_authorized_users(db, active_only=True)
    await state.clear()
    await message.answer(f"✅ Qo'shildi: <b>{html.escape(full_name)}</b> (<code>{tg_id}</code>)", parse_mode="HTML", reply_markup=main_menu_keyboard())
    await message.answer("👥 Foydalanuvchilar:", reply_markup=superadmin_users_kb(users))


@router.callback_query(F.data.startswith("sa:del_user:"))
async def cb_superadmin_del_user(cb: CallbackQuery) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    tg_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        await remove_authorized_user(db, tg_id)
        users = await list_authorized_users(db, active_only=True)
    await cb.message.edit_reply_markup(reply_markup=superadmin_users_kb(users))
    await cb.answer("🗑 O'chirildi")


@router.callback_query(F.data == "sa:payments")
async def cb_superadmin_payments(cb: CallbackQuery) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    async with async_session_maker() as db:
        payments = await list_subscription_payments(db, limit=15)
    if not payments:
        await cb.answer("Hali obuna to'lovlari tarixi yo'q.", show_alert=True)
        return
    lines = ["📜 <b>Obuna To'lovlari Tarixi:</b>\n"]
    for idx, p in enumerate(payments, start=1):
        dt = format_local_dt(p.paid_at, "%d.%m.%Y %H:%M")
        lines.append(
            f"{idx}) <code>{dt}</code> | +{p.days_added} kun | <b>{format_uzs(p.amount)} so'm</b> <i>({html.escape(p.note or p.plan_name)})</i>"
        )
    await cb.message.answer("\n".join(lines), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "sa:send_reminder")
async def cb_superadmin_send_reminder(cb: CallbackQuery) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db)
        db_users = await list_authorized_users(db, active_only=True)
    sub = sub_status.state
    exp_str = format_local_dt(sub.expires_at, "%d.%m.%Y")
    recipients = set(get_settings().admin_id_list) | {u.telegram_id for u in db_users}
    recipients -= set(get_settings().super_admin_id_list)
    if not recipients:
        recipients = set(get_settings().admin_id_list)

    sent = 0
    for uid in recipients:
        try:
            await cb.bot.send_message(
                chat_id=uid,
                text=(
                    "🔔 <b>Obuna eslatmasi — Norin AI Hisobot</b>\n\n"
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
    await cb.answer(f"🔔 {sent} ta foydalanuvchiga eslatma yuborildi!", show_alert=True)


@router.callback_query(F.data.startswith("sa:approve:"))
async def cb_superadmin_approve_renewal(cb: CallbackQuery) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    parts = cb.data.split(":")
    requester_id = int(parts[2])
    days = int(parts[3])
    uid = cb.from_user.id if cb.from_user else 0

    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db)
        amount = round((float(sub_status.state.monthly_price) / 30.0) * days)
        updated = await extend_subscription(
            db,
            days=days,
            amount=amount,
            recorded_by=uid,
            note=f"Mijoz ({requester_id}) so'rovi bo'yicha +{days} kun",
        )
    exp_str = format_local_dt(updated.expires_at, "%d.%m.%Y")

    try:
        await cb.bot.send_message(
            chat_id=requester_id,
            text=(
                f"✅ <b>Tabriklaymiz! Obunangiz +{days} kunga uzaytirildi!</b>\n"
                f"📅 Yangi amal qilish muddati: <b>{exp_str}</b>\n"
                "Botdan bemalol foydalanishingiz mumkin."
            ),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
    except Exception:
        pass

    await cb.message.edit_text(
        f"✅ Tasdiqlandi! Mijoz (<code>{requester_id}</code>) obunasi <b>+{days} kunga</b> uzaytirildi.\n"
        f"📅 Yangi muddat: <b>{exp_str}</b>",
        parse_mode="HTML",
    )
    await cb.answer("✅ Uzaytirildi!")


@router.callback_query(F.data.startswith("sa:reject:"))
async def cb_superadmin_reject_renewal(cb: CallbackQuery) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    requester_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db)
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
    await cb.message.edit_text(f"❌ So'rov rad etildi (ID: <code>{requester_id}</code>).", parse_mode="HTML")
    await cb.answer("Rad etildi")


# ---------------------------------------------------------------------------
# Database Reset (/clear) for Super Admin
# ---------------------------------------------------------------------------


CLEAR_MENU_TEXT = (
    "🧹 <b>BAZANI TOZALASH (/clear)</b>\n"
    "===============================\n"
    "Mijoz test qilib bo'lgach, asosiy ishni toza sahifadan boshlash uchun tanlang:\n\n"
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
    """Ask Super Admin confirmation before clearing test data or resetting the database."""
    if not is_super_admin(message.from_user.id if message.from_user else None):
        await message.answer("⛔ Bu buyruq faqat tizim egasi (Super Admin) uchun.")
        return
    await state.clear()
    await message.answer(
        CLEAR_MENU_TEXT,
        parse_mode="HTML",
        reply_markup=superadmin_clear_confirm_kb(),
    )


@router.callback_query(F.data == "sa:clear_menu")
async def cb_superadmin_clear_menu(cb: CallbackQuery) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    await cb.message.edit_text(
        CLEAR_MENU_TEXT,
        parse_mode="HTML",
        reply_markup=superadmin_clear_confirm_kb(),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sa:clear_exec:"))
async def cb_superadmin_clear_execute(cb: CallbackQuery) -> None:
    if not is_super_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    mode = cb.data.split(":")[-1]
    if mode not in ("tx", "full"):
        await cb.answer("Noto'g'ri rejim")
        return

    settings = get_settings()
    async with async_session_maker() as db:
        if mode == "full":
            stats = await reset_full_database(db)
            client_notice = (
                "🧹 <b>Baza to'liq tozalandi!</b>\n"
                "Endi asosiy ishni 0 dan boshlashingiz mumkin."
            )
            title = "💣 <b>BAZA TO'LIQ TOZALANDI (0 dan)!</b>"
            extra_line = f"• Mijozlar o'chirildi: <b>{stats['clients']} ta</b> (mahsulotlar qayta yaratildi)\n"
        else:
            stats = await reset_test_transactions(db)
            client_notice = (
                "🧹 <b>Test savdo, qarz va kassa tozalandi!</b>\n"
                "Mijozlar va ulangan guruhlar saqlab qolindi — asosiy ishni boshlashingiz mumkin."
            )
            title = "🧹 <b>TEST SAVDO, QARZ VA KASSA TOZALANDI!</b>"
            extra_line = "• Mijozlar va ulangan guruhlar saqlab qolindi (qarzlari 0 qilindi)\n"

        db_users = await list_authorized_users(db, active_only=True)

    recipients = (set(settings.admin_id_list) | {u.telegram_id for u in db_users}) - set(
        settings.super_admin_id_list
    )
    notified = 0
    for uid in recipients:
        try:
            await cb.bot.send_message(
                chat_id=uid,
                text=client_notice,
                parse_mode="HTML",
                reply_markup=main_menu_keyboard(),
            )
            notified += 1
        except Exception as exc:
            logger.warning("Failed to notify user %s after /clear: %s", uid, exc)

    if recipients:
        notify_line = f"📢 Mijozlarga xabar yuborildi: <b>{notified}/{len(recipients)} ta</b>"
    else:
        notify_line = "ℹ️ Alohida mijoz ID ulanmagan (serverda buyurtmachi ID qo'shilganda unga ham xabar boradi)."

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

"""Start, settings, Norin product catalog, clients, custom prices, group binding, and debt ledger."""

from __future__ import annotations

import asyncio
import html
import logging
import time
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from bot.handlers.superadmin import is_super_admin
from bot.keyboards import (
    BTN_DEBTS,
    BTN_SETTINGS,
    ai_prefs_kb,
    bind_group_clients_kb,
    cancel_reply_keyboard,
    client_debt_detail_kb,
    client_detail_kb,
    client_prices_kb,
    clients_list_kb,
    debts_list_kb,
    main_menu_keyboard,
    product_detail_kb,
    products_list_kb,
    report_group_config_kb,
    settings_menu_kb,
)
from bot.states import ClientStates, ProductStates, WalletStates
from database.crud import (
    ClientDebtSummary,
    append_product_alias,
    bind_client_group,
    compute_client_debt,
    create_client,
    create_product,
    delete_client,
    delete_product,
    evaluate_subscription_status,
    format_local_dt,
    get_app_setting,
    get_client,
    get_client_by_group,
    get_client_prices_map,
    get_group_config,
    get_product,
    is_user_authorized,
    list_all_client_debts,
    list_clients,
    list_products,
    set_app_setting,
    set_client_product_price,
    set_group_config,
    unbind_client_group,
    update_client,
    update_product,
)
from database.session import async_session_maker
from services.gemini_ai import format_kg, format_uzs, parse_uzbek_amount


router = Router(name="clients_products")
logger = logging.getLogger("norin_bot.clients_products")

_BOT_USERNAME: str | None = None
_recently_bound_chats: dict[int, float] = {}
# Tracks the latest DM client-card message per user: user_id -> (chat_id, message_id, client_id)
_last_client_card: dict[int, tuple[int, int, int]] = {}


async def _refresh_open_client_card(bot, user_id: Optional[int], client_id: int) -> None:
    """Edit the user's open DM client card in place so the group status button flips immediately."""
    if not user_id or user_id == 1087968824:
        return
    entry = _last_client_card.get(user_id)
    if not entry:
        return
    chat_id, msg_id, open_cid = entry
    if open_cid != client_id:
        return
    text, cli = await _render_client_card_text(client_id)
    if not cli:
        return
    uname = await get_bot_username(bot)
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=text,
            parse_mode="HTML",
            reply_markup=client_detail_kb(cli, uname),
        )
    except Exception:
        pass


async def get_bot_username(bot) -> str:
    """Fetch and cache the bot username."""
    global _BOT_USERNAME
    if not _BOT_USERNAME:
        me = await bot.get_me()
        _BOT_USERNAME = me.username or "norin_ai_bot"
    return _BOT_USERNAME


async def is_authorized_async(
    user_id: Optional[int], allow_group_anon: bool = False
) -> bool:
    """Check if Telegram user is authorized via .env or database AuthorizedUser."""
    async with async_session_maker() as db:
        return await is_user_authorized(db, user_id, allow_group_anon=allow_group_anon)


def render_debts_overview_text(debts: list[ClientDebtSummary]) -> str:
    """Format overview of all clients' debt balances."""
    if not debts:
        return (
            "💳 <b>Mijozlar Qarz Daftari</b>\n\n"
            "<i>Hozircha mijozlar qo'shilmagan. «➕ Yangi mijoz qo'shish» tugmasidan boshlang!</i>"
        )
    total_debt = sum(d.current_debt for d in debts)
    total_kg = sum(d.total_kg for d in debts)
    lines = [
        "💳 <b>MIJOZLAR QARZ DAFTARI</b>",
        "===============================",
        f"💰 <b>Jami olinadigan qarz: {format_uzs(total_debt)} so'm</b>",
        f"⚖️ Jami sotilgan mahsulot: <b>{format_kg(total_kg)} kg</b>",
        "-------------------------------",
    ]
    for idx, d in enumerate(debts, start=1):
        icon = "🔴" if d.current_debt > 0 else ("🟢" if d.current_debt == 0 else "🔵")
        grp_tag = " 🔗" if d.client.group_chat_id else ""
        lines.append(
            f"{idx}) {icon} <b>{html.escape(d.client.name)}</b>{grp_tag} — <b>{format_uzs(d.current_debt)} so'm</b>"
        )
    lines.append("\n<i>Batafsil Akt Sverka yoki pul qabul qilish uchun mijozni tanlang:</i>")
    return "\n".join(lines)


def render_client_sverka_text(
    debt: ClientDebtSummary, for_group: bool = False
) -> str:
    """
    Build client Akt Sverka text.

    STRICT SAFETY: Never contains cost_price or profit! Safe to post directly into client group.
    """
    cli = debt.client
    title = f"📋 <b>AKT SVERKA — {html.escape(cli.name)}</b>"
    lines = [
        title,
        "===============================",
        f"📌 Boshlang'ich qarz: {format_uzs(debt.opening_debt)} so'm",
        f"🥩 Jami yuk ({format_kg(debt.total_kg)} kg): <b>{format_uzs(debt.total_sales)} so'm</b>",
        f"💵 Jami to'langan: <b>{format_uzs(debt.total_paid)} so'm</b>",
        f"💳 <b>Hozirgi qarz qoldig'i: {format_uzs(debt.current_debt)} so'm</b>",
    ]
    if debt.recent_sales:
        lines.append("\n📦 <b>Oxirgi yuklar:</b>")
        for s in debt.recent_sales[:8]:
            dt = format_local_dt(s.created_at, "%d.%m %H:%M") if s.created_at else s.report_date
            items_lbl = ", ".join(
                f"{i.product_name.replace('Norin ', '')} {format_kg(i.weight_kg)}kg"
                for i in s.items
            )
            lines.append(
                f"• <code>{dt}</code> {html.escape(items_lbl)} = <b>{format_uzs(s.total_amount)}</b>"
            )
    if debt.recent_payments:
        m_icons = {"cash": "Naqd", "card": "Karta", "transfer": "Pereches"}
        lines.append("\n💵 <b>Oxirgi to'lovlar:</b>")
        for p in debt.recent_payments[:8]:
            dt = format_local_dt(p.created_at, "%d.%m %H:%M") if p.created_at else ""
            lines.append(
                f"• <code>{dt}</code> {m_icons.get(p.payment_method, p.payment_method)}: <b>+{format_uzs(p.amount)}</b>"
            )
    if not for_group and cli.phone:
        lines.append(f"\n📞 Tel: <code>{html.escape(cli.phone)}</code>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /start & Cancel
# ---------------------------------------------------------------------------


@router.message(CommandStart(deep_link=False), F.chat.type == "private")
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Handle /start in private chat."""
    uid = message.from_user.id if message.from_user else None
    if not await is_authorized_async(uid):
        await message.answer(
            "⛔ Sizda ushbu botdan foydalanish huquqi yo'q.\n"
            f"🆔 Sizning Telegram ID: <code>{uid or 0}</code>",
            parse_mode="HTML",
        )
        return
    await state.clear()
    async with async_session_maker() as db:
        sub_status = await evaluate_subscription_status(db)

    warn_line = ""
    if sub_status.status in ("expiring", "grace"):
        exp_str = format_local_dt(sub_status.state.expires_at, "%d.%m.%Y")
        warn_line = f"\n\n⚠️ <b>Eslatma:</b> Obuna muddati <code>{exp_str}</code> da tugaydi."
    elif not sub_status.is_allowed and not is_super_admin(uid):
        warn_line = "\n\n🔒 <b>Obuna muddati tugagan.</b> Davom ettirish uchun Sozlamalar → Obuna holatiga kiring."

    await message.answer(
        "👋 <b>Assalomu alaykum! Norin AI Hisobot botiga xush kelibsiz.</b>\n"
        f"🏢 Filial: <b>{html.escape(sub_status.state.tenant_name)}</b> (<code>#{sub_status.state.id}</code>)\n\n"
        "Botda quyidagilarni 1 soniyada bajarasiz:\n"
        "• 📸 <b>Tarozi/do'kon cheki rasmi</b> — AI faqat <b>kg va go'sht turini</b> o'qiydi (chekdagi do'kon narxini e'tiborsiz qoldiradi) va mijoz narxida hisoblab guruhiga tashlaydi\n"
        "• 🎤 <b>Ovoz / matn</b> — <i>«Iftiqor 80 notin ot 25 kg»</i> desangiz avtomatik hisoblaydi\n"
        "• 💰 <b>Individual narx & Tannarx</b> — har bir mijozga alohida narx, o'zingizga sof foyda & marja\n"
        "• 💳 <b>Qarz daftari & Akt Sverka</b> — naqd/karta to'lovlar va kun yakunidagi kassa sverkasi\n"
        f"{warn_line}\n\n"
        f"🆔 Sizning ID: <code>{uid or 0}</code>",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


@router.message(F.text == "❌ Bekor qilish", F.chat.type == "private")
async def cancel_any_state(message: Message, state: FSMContext) -> None:
    """Cancel current FSM operation and return to main menu."""
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    await state.clear()
    await message.answer("❌ Amal bekor qilindi.", reply_markup=main_menu_keyboard())


# ---------------------------------------------------------------------------
# Group Binding (Deep-link, /bind_group, & my_chat_member auto-detect)
# ---------------------------------------------------------------------------


@router.message(CommandStart(deep_link=True), F.chat.type.in_({"group", "supergroup"}))
async def cmd_start_group_bind(message: Message, command: CommandObject) -> None:
    """Auto-bind group when bot is added via Telegram startgroup=bind_client_<id> or bind_report."""
    uid = message.from_user.id if message.from_user else None
    if not await is_authorized_async(uid, allow_group_anon=True):
        return

    arg = (command.args or "").strip()
    title = message.chat.title or f"Guruh ({message.chat.id})"
    _recently_bound_chats[message.chat.id] = time.monotonic()

    if arg == "bind_report":
        async with async_session_maker() as db:
            await set_group_config(db, "report", message.chat.id, title)
        await message.answer(
            f"✅ Ushbu guruh <b>📊 Rahbariyat hisobot guruhi</b> sifatida biriktirildi!\n"
            f"🆔 Chat ID: <code>{message.chat.id}</code>",
            parse_mode="HTML",
        )
        return

    if arg.startswith("bind_client_"):
        raw_id = arg.replace("bind_client_", "", 1)
        if not raw_id.isdigit():
            return
        client_id = int(raw_id)
        async with async_session_maker() as db:
            cli = await bind_client_group(db, client_id, message.chat.id, title)
        if cli is None:
            await message.answer("⚠️ Mijoz topilmadi.")
            return
        await message.answer(
            f"✅ Ushbu guruh <b>{html.escape(cli.name)}</b> mijoziga muvaffaqiyatli biriktirildi!\n"
            f"Endi bu guruhga chek rasmi yoki <i>«norin ot 25 kg»</i> yuborsangiz bot avtomatik hisoblaydi.",
            parse_mode="HTML",
        )
        await _refresh_open_client_card(message.bot, uid, cli.id)
        if uid and uid != 1087968824:
            try:
                bot_uname = await get_bot_username(message.bot)
                card_text, loaded_cli = await _render_client_card_text(cli.id)
                sent = await message.bot.send_message(
                    chat_id=uid,
                    text=(
                        f"✅ <b>{html.escape(cli.name)}</b> mijoz guruhi ulandi: "
                        f"<b>{html.escape(title)}</b> (<code>{message.chat.id}</code>)\n\n"
                        + (card_text or "")
                    ),
                    parse_mode="HTML",
                    reply_markup=client_detail_kb(loaded_cli or cli, bot_uname),
                )
                _last_client_card[uid] = (sent.chat.id, sent.message_id, cli.id)
            except Exception:
                pass


@router.message(Command("bind_group"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_bind_group_in_chat(message: Message) -> None:
    """Allow an authorized admin inside a group to bind that group to a client or report role."""
    uid = message.from_user.id if message.from_user else None
    if not await is_authorized_async(uid, allow_group_anon=True):
        return
    async with async_session_maker() as db:
        clients = await list_clients(db, active_only=True)
    await message.answer(
        f"🔗 <b>Ushbu guruhni qaysi mijozga biriktiramiz?</b>\n"
        f"Guruh: <b>{html.escape(message.chat.title or '')}</b> (<code>{message.chat.id}</code>)",
        parse_mode="HTML",
        reply_markup=bind_group_clients_kb(message.chat.id, clients),
    )


@router.my_chat_member(F.chat.type.in_({"group", "supergroup"}))
async def on_bot_added_to_group(event: ChatMemberUpdated) -> None:
    """Auto-detect when bot is added to a group and offer 1-tap client binding in admin DM."""
    new_status = event.new_chat_member.status
    old_status = event.old_chat_member.status
    if new_status not in ("member", "administrator") or new_status == old_status:
        return

    uid = event.from_user.id if event.from_user else None
    if not uid or not await is_authorized_async(uid):
        return

    await asyncio.sleep(1.5)
    bound_ts = _recently_bound_chats.get(event.chat.id, 0.0)
    if time.monotonic() - bound_ts < 10.0:
        return

    title = event.chat.title or f"Guruh ({event.chat.id})"
    async with async_session_maker() as db:
        existing_cli = await get_client_by_group(db, event.chat.id)
        if existing_cli and new_status == "administrator":
            await bind_client_group(db, existing_cli.id, event.chat.id, title)
            return
        clients = await list_clients(db, active_only=True)

    try:
        await event.bot.send_message(
            chat_id=uid,
            text=(
                f"🆕 <b>Yangi guruh aniqlandi!</b>\n"
                f"📌 Nomi: <b>{html.escape(title)}</b>\n"
                f"🆔 Chat ID: <code>{event.chat.id}</code>\n\n"
                "Ushbu guruhni qaysi mijozga biriktiramiz?"
            ),
            parse_mode="HTML",
            reply_markup=bind_group_clients_kb(event.chat.id, clients),
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("grp:qbind_cli:"))
async def cb_quick_bind_client(cb: CallbackQuery) -> None:
    if not await is_authorized_async(cb.from_user.id if cb.from_user else None, allow_group_anon=True):
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    parts = cb.data.split(":")
    client_id = int(parts[2])
    chat_id = int(parts[3])
    title = f"Guruh ({chat_id})"
    try:
        chat = await cb.bot.get_chat(chat_id)
        if chat.title:
            title = chat.title
    except Exception:
        pass

    async with async_session_maker() as db:
        cli = await bind_client_group(db, client_id, chat_id, title)
    if not cli:
        await cb.answer("Mijoz topilmadi", show_alert=True)
        return
    uid = cb.from_user.id if cb.from_user else None
    await _refresh_open_client_card(cb.bot, uid, cli.id)
    if cb.message.chat.type == "private":
        uname = await get_bot_username(cb.bot)
        card_text, loaded_cli = await _render_client_card_text(cli.id)
        await cb.message.edit_text(
            f"✅ <b>{html.escape(title)}</b> guruhi <b>{html.escape(cli.name)}</b> mijoziga ulandi!\n\n"
            + (card_text or ""),
            parse_mode="HTML",
            reply_markup=client_detail_kb(loaded_cli or cli, uname),
        )
        if uid:
            _last_client_card[uid] = (cb.message.chat.id, cb.message.message_id, cli.id)
    else:
        await cb.message.edit_text(
            f"✅ <b>{html.escape(title)}</b> guruhi <b>{html.escape(cli.name)}</b> mijoziga ulandi!",
            parse_mode="HTML",
        )
    await cb.answer("✅ Ulandi!")


@router.callback_query(F.data.startswith("grp:qbind_rep:"))
async def cb_quick_bind_report(cb: CallbackQuery) -> None:
    if not await is_authorized_async(cb.from_user.id if cb.from_user else None, allow_group_anon=True):
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    chat_id = int(cb.data.split(":")[-1])
    title = f"Guruh ({chat_id})"
    try:
        chat = await cb.bot.get_chat(chat_id)
        if chat.title:
            title = chat.title
    except Exception:
        pass
    async with async_session_maker() as db:
        await set_group_config(db, "report", chat_id, title)
    await cb.message.edit_text(
        f"✅ <b>{html.escape(title)}</b> guruhi <b>📊 Rahbariyat hisobot guruhi</b> sifatida saqlandi!",
        parse_mode="HTML",
    )
    await cb.answer("✅ Saqlandi!")


# ---------------------------------------------------------------------------
# Settings Menu & AI Preferences
# ---------------------------------------------------------------------------


@router.message(F.text == BTN_SETTINGS, F.chat.type == "private")
async def open_settings_menu(message: Message, state: FSMContext) -> None:
    uid = message.from_user.id if message.from_user else None
    if not await is_authorized_async(uid):
        return
    await state.clear()
    await message.answer(
        "⚙️ <b>Sozlamalar, Mahsulotlar, Mijozlar va Arxiv</b>\nKerakli bo'limni tanlang:",
        parse_mode="HTML",
        reply_markup=settings_menu_kb(is_super_admin=is_super_admin(uid)),
    )


@router.callback_query(F.data == "set:back")
async def cb_settings_back(cb: CallbackQuery, state: FSMContext) -> None:
    uid = cb.from_user.id if cb.from_user else None
    await state.clear()
    await cb.message.edit_text(
        "⚙️ <b>Sozlamalar, Mahsulotlar, Mijozlar va Arxiv</b>\nKerakli bo'limni tanlang:",
        parse_mode="HTML",
        reply_markup=settings_menu_kb(is_super_admin=is_super_admin(uid)),
    )
    await cb.answer()


async def _render_ai_prefs() -> tuple[str, bool, bool, str]:
    async with async_session_maker() as db:
        auto_confirm = (await get_app_setting(db, "auto_confirm", "on")) == "on"
        group_auto = (await get_app_setting(db, "group_auto_calc", "on")) == "on"
        round_mode = await get_app_setting(db, "round_mode", "none")
    round_desc = {
        "nearest_1000": "Eng yaqin 1 000 ga",
        "floor_1000": "1 000 ga pastga",
        "none": "Yaxlitlamaslik (aniq)",
    }.get(round_mode, round_mode)
    text = (
        "⚡ <b>Tez rejim, Guruhda Avto-Hisob va Yaxlitlash</b>\n\n"
        f"• <b>DM Avto-tasdiqlash:</b> {'✅ YOQILGAN' if auto_confirm else '❌ O‘CHIQ'}\n"
        f"• <b>Mijoz guruhida avto-hisob:</b> {'✅ YOQILGAN (guruhga rasm/matn tashlansa darhol hisoblaydi)' if group_auto else '❌ O‘CHIQ'}\n"
        f"• <b>Summani yaxlitlash:</b> <b>{round_desc}</b>"
    )
    return text, auto_confirm, group_auto, round_mode


@router.callback_query(F.data == "set:ai_prefs")
async def cb_ai_prefs_menu(cb: CallbackQuery) -> None:
    text, auto_on, grp_on, r_mode = await _render_ai_prefs()
    await cb.message.edit_text(
        text, parse_mode="HTML", reply_markup=ai_prefs_kb(auto_on, grp_on, r_mode)
    )
    await cb.answer()


@router.callback_query(F.data == "pref:toggle_auto")
async def cb_toggle_auto(cb: CallbackQuery) -> None:
    async with async_session_maker() as db:
        cur = await get_app_setting(db, "auto_confirm", "on")
        await set_app_setting(db, "auto_confirm", "off" if cur == "on" else "on")
    text, auto_on, grp_on, r_mode = await _render_ai_prefs()
    await cb.message.edit_text(
        text, parse_mode="HTML", reply_markup=ai_prefs_kb(auto_on, grp_on, r_mode)
    )
    await cb.answer("✅ Saqlandi")


@router.callback_query(F.data == "pref:toggle_grp")
async def cb_toggle_grp(cb: CallbackQuery) -> None:
    async with async_session_maker() as db:
        cur = await get_app_setting(db, "group_auto_calc", "on")
        await set_app_setting(db, "group_auto_calc", "off" if cur == "on" else "on")
    text, auto_on, grp_on, r_mode = await _render_ai_prefs()
    await cb.message.edit_text(
        text, parse_mode="HTML", reply_markup=ai_prefs_kb(auto_on, grp_on, r_mode)
    )
    await cb.answer("✅ Saqlandi")


@router.callback_query(F.data.startswith("pref:round:"))
async def cb_set_round_mode(cb: CallbackQuery) -> None:
    mode = cb.data.split(":")[-1]
    if mode not in ("nearest_1000", "floor_1000", "none"):
        await cb.answer("Noto'g'ri rejim")
        return
    async with async_session_maker() as db:
        await set_app_setting(db, "round_mode", mode)
    text, auto_on, grp_on, r_mode = await _render_ai_prefs()
    await cb.message.edit_text(
        text, parse_mode="HTML", reply_markup=ai_prefs_kb(auto_on, grp_on, r_mode)
    )
    await cb.answer("✅ Yaxlitlash saqlandi")


# ---------------------------------------------------------------------------
# Report Group Configuration
# ---------------------------------------------------------------------------


async def _render_report_group_text() -> str:
    async with async_session_maker() as db:
        cfg = await get_group_config(db, "report")
    if cfg:
        grp_line = f"✅ Ulangan: <b>{html.escape(cfg.title)}</b> (<code>{cfg.chat_id}</code>)"
    else:
        grp_line = "<i>Hali ulanmagan (ixtiyoriy — kun yopilganda hisobot shu guruhga ham boradi)</i>"
    return (
        "📊 <b>Rahbariyat Hisobot Guruhi</b>\n\n"
        f"Holat: {grp_line}\n\n"
        "<i>Kun yakunlanganda sof foyda va kassa sverka natijasi shu guruhga avtomatik yuboriladi.</i>"
    )


@router.callback_query(F.data == "set:report_group")
async def cb_report_group_menu(cb: CallbackQuery) -> None:
    text = await _render_report_group_text()
    username = await get_bot_username(cb.bot)
    async with async_session_maker() as db:
        cfg = await get_group_config(db, "report")
    await cb.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=report_group_config_kb(username, group_title=cfg.title if cfg else None),
    )
    await cb.answer()


@router.callback_query(F.data == "repgrp:set_id")
async def cb_report_group_id_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(WalletStates.waiting_report_group_id)
    await cb.message.answer(
        "🆔 Rahbariyat hisobot guruhining Chat ID sini yuboring (masalan: <code>-1001234567890</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(WalletStates.waiting_report_group_id, F.chat.type == "private")
async def process_report_group_id(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    raw = (message.text or "").strip()
    try:
        chat_id = int(raw)
    except ValueError:
        await message.answer("⚠️ Noto'g'ri ID! Raqam kiriting (masalan: -1001234567890):")
        return
    title = f"Guruh ({chat_id})"
    try:
        chat = await message.bot.get_chat(chat_id)
        if chat.title:
            title = chat.title
    except Exception:
        pass
    async with async_session_maker() as db:
        await set_group_config(db, "report", chat_id, title)
    await state.clear()
    await message.answer(
        f"✅ Hisobot guruhi ulandi: <b>{html.escape(title)}</b> (<code>{chat_id}</code>)",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(F.data == "repgrp:ping")
async def cb_report_group_ping(cb: CallbackQuery) -> None:
    async with async_session_maker() as db:
        cfg = await get_group_config(db, "report")
    if not cfg:
        await cb.answer("Hisobot guruhi ulanmagan!", show_alert=True)
        return
    try:
        await cb.bot.send_message(
            cfg.chat_id,
            "✅ Test xabar: Ushbu guruh <b>Norin AI Hisobot</b> rahbariyat guruhi sifatida ulangan.",
            parse_mode="HTML",
        )
        await cb.answer("✅ Test xabar yuborildi!", show_alert=True)
    except Exception as exc:
        await cb.answer(f"❌ Xatolik: {exc}", show_alert=True)


# ---------------------------------------------------------------------------
# Products Catalog & Cost Management
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "set:products")
async def cb_products_menu(cb: CallbackQuery) -> None:
    async with async_session_maker() as db:
        products = await list_products(db, active_only=True)
    await cb.message.edit_text(
        "🥩 <b>Mahsulotlar Katalogi (Tannarx & Standart Sotuv Narxi)</b>\n"
        "Tahrirlash uchun mahsulotni tanlang:",
        parse_mode="HTML",
        reply_markup=products_list_kb(products),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("prd:view:"))
async def cb_product_detail(cb: CallbackQuery) -> None:
    pid = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        prod = await get_product(db, pid)
    if not prod or not prod.is_active:
        await cb.answer("Mahsulot topilmadi", show_alert=True)
        return
    margin = prod.default_sell_price - prod.cost_price
    await cb.message.edit_text(
        f"🥩 <b>{html.escape(prod.name)}</b>\n"
        "===============================\n"
        f"📉 Tannarx (1 kg): <b>{format_uzs(prod.cost_price)} so'm</b>\n"
        f"💰 Standart sotuv narxi (1 kg): <b>{format_uzs(prod.default_sell_price)} so'm</b>\n"
        f"📈 Standart foyda (1 kg): <b>{format_uzs(margin)} so'm</b>\n"
        f"🔗 Sinonimlar (AI uchun):\n<code>{html.escape(prod.aliases or '-')}</code>",
        parse_mode="HTML",
        reply_markup=product_detail_kb(prod.id),
    )
    await cb.answer()


@router.callback_query(F.data == "prd:add")
async def cb_product_add_start(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProductStates.waiting_product_name)
    await cb.message.answer(
        "🥩 Yangi mahsulot nomini kiriting (masalan: <code>Qazi (Tayyor)</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(ProductStates.waiting_product_name, F.chat.type == "private")
async def process_product_name(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    name = (message.text or "").strip()
    if not name:
        await message.answer("⚠️ Nom kiriting:")
        return
    await state.update_data(prod_name=name)
    await state.set_state(ProductStates.waiting_product_cost)
    await message.answer(
        f"📉 <b>{html.escape(name)}</b> ning 1 kg TANNARXINI kiriting (masalan: <code>90 000</code>):",
        parse_mode="HTML",
    )


@router.message(ProductStates.waiting_product_cost, F.chat.type == "private")
async def process_product_cost(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    amt = parse_uzbek_amount(message.text or "")
    if amt is None or amt < 0:
        await message.answer("⚠️ To'g'ri tannarx kiriting (masalan: 90 000):")
        return
    await state.update_data(prod_cost=amt)
    await state.set_state(ProductStates.waiting_product_sell)
    await message.answer(
        "💰 1 kg STANDART SOTUV NARXINI kiriting (masalan: <code>115 000</code>):",
        parse_mode="HTML",
    )


@router.message(ProductStates.waiting_product_sell, F.chat.type == "private")
async def process_product_sell(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    amt = parse_uzbek_amount(message.text or "")
    if amt is None or amt <= 0:
        await message.answer("⚠️ To'g'ri sotuv narxi kiriting:")
        return
    data = await state.get_data()
    async with async_session_maker() as db:
        prod = await create_product(
            db,
            name=data["prod_name"],
            cost_price=data["prod_cost"],
            default_sell_price=amt,
        )
        products = await list_products(db, active_only=True)
    await state.clear()
    await message.answer(
        f"✅ Mahsulot qo'shildi: <b>{html.escape(prod.name)}</b>\n"
        f"📉 Tannarx: {format_uzs(prod.cost_price)} | 💰 Sotuv: {format_uzs(prod.default_sell_price)}",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    await message.answer("🥩 Mahsulotlar:", reply_markup=products_list_kb(products))


@router.callback_query(F.data.startswith("prd:edit_cost:"))
async def cb_product_edit_cost_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    pid = int(cb.data.split(":")[-1])
    await state.set_state(ProductStates.waiting_edit_product_cost)
    await state.update_data(product_id=pid)
    await cb.message.answer(
        "📉 Yangi 1 kg TANNARXNI kiriting (masalan: <code>92 000</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(ProductStates.waiting_edit_product_cost, F.chat.type == "private")
async def process_product_edit_cost(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    amt = parse_uzbek_amount(message.text or "")
    if amt is None or amt < 0:
        await message.answer("⚠️ Summa noto'g'ri. Qayta kiriting:")
        return
    pid = (await state.get_data())["product_id"]
    async with async_session_maker() as db:
        prod = await update_product(db, pid, cost_price=amt)
    await state.clear()
    if prod:
        await message.answer(
            f"✅ <b>{html.escape(prod.name)}</b> tannarxi yangilandi: <b>{format_uzs(prod.cost_price)} so'm/kg</b>",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        await message.answer("Mahsulot kartasi:", reply_markup=product_detail_kb(prod.id))


@router.callback_query(F.data.startswith("prd:edit_sell:"))
async def cb_product_edit_sell_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    pid = int(cb.data.split(":")[-1])
    await state.set_state(ProductStates.waiting_edit_product_sell)
    await state.update_data(product_id=pid)
    await cb.message.answer(
        "💰 Yangi 1 kg STANDART SOTUV NARXINI kiriting (masalan: <code>118 000</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(ProductStates.waiting_edit_product_sell, F.chat.type == "private")
async def process_product_edit_sell(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    amt = parse_uzbek_amount(message.text or "")
    if amt is None or amt <= 0:
        await message.answer("⚠️ Summa noto'g'ri. Qayta kiriting:")
        return
    pid = (await state.get_data())["product_id"]
    async with async_session_maker() as db:
        prod = await update_product(db, pid, default_sell_price=amt)
    await state.clear()
    if prod:
        await message.answer(
            f"✅ <b>{html.escape(prod.name)}</b> standart sotuv narxi: <b>{format_uzs(prod.default_sell_price)} so'm/kg</b>",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        await message.answer("Mahsulot kartasi:", reply_markup=product_detail_kb(prod.id))


@router.callback_query(F.data.startswith("prd:alias:"))
async def cb_product_alias_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    pid = int(cb.data.split(":")[-1])
    await state.set_state(ProductStates.waiting_product_alias)
    await state.update_data(product_id=pid)
    await cb.message.answer(
        "🔗 Mahsulot uchun yangi sinonim so'z yozing (masalan: <code>КОНИНА</code> yoki <code>OTLI NORIN</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(ProductStates.waiting_product_alias, F.chat.type == "private")
async def process_product_alias(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    alias = (message.text or "").strip()
    if not alias:
        await message.answer("⚠️ Sinonim kiriting:")
        return
    pid = (await state.get_data())["product_id"]
    async with async_session_maker() as db:
        prod = await append_product_alias(db, pid, alias)
    await state.clear()
    if prod:
        await message.answer(
            f"✅ Sinonim qo'shildi! <b>{html.escape(prod.name)}</b> → <code>{html.escape(prod.aliases)}</code>",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )


@router.callback_query(F.data.startswith("prd:del:"))
async def cb_product_delete(cb: CallbackQuery) -> None:
    pid = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        await delete_product(db, pid)
        products = await list_products(db, active_only=True)
    await cb.message.edit_text(
        "🥩 <b>Mahsulotlar katalogi:</b>",
        parse_mode="HTML",
        reply_markup=products_list_kb(products),
    )
    await cb.answer("🗑 O'chirildi")


# ---------------------------------------------------------------------------
# Clients, Custom Per-Client Pricing & Debt Ledger
# ---------------------------------------------------------------------------


async def _render_client_card_text(client_id: int) -> tuple[str, Optional[object]]:
    async with async_session_maker() as db:
        cli = await get_client(db, client_id)
        if not cli or not cli.is_active:
            return "", None
        products = await list_products(db, active_only=True)
        custom_map = await get_client_prices_map(db, client_id)
        debt = await compute_client_debt(db, client_id, history_limit=5)

    grp_str = (
        f"🔗 <b>{html.escape(cli.group_title)}</b> (<code>{cli.group_chat_id}</code>)"
        if cli.group_chat_id
        else "⚠️ <i>Guruh ulanmagan</i>"
    )
    price_lines = []
    for p in products:
        if p.id in custom_map:
            price_lines.append(f"  • {html.escape(p.name)}: <b>{format_uzs(custom_map[p.id])} so'm/kg</b> (Maxsus)")
        else:
            price_lines.append(f"  • {html.escape(p.name)}: {format_uzs(p.default_sell_price)} so'm/kg (Standart)")

    text = (
        f"🏪 <b>Mijoz: {html.escape(cli.name)}</b>\n"
        "===============================\n"
        f"📞 Telefon: <code>{html.escape(cli.phone or '-')}</code>\n"
        f"💬 Guruh: {grp_str}\n"
        f"💳 Hozirgi qarz: <b>{format_uzs(debt.current_debt)} so'm</b>\n"
        f"🔗 Sinonimlar: <code>{html.escape(cli.aliases or '-')}</code>\n\n"
        "💰 <b>Sotuv narxlari:</b>\n" + "\n".join(price_lines)
    )
    return text, cli


@router.callback_query(F.data == "set:clients")
async def cb_clients_menu(cb: CallbackQuery) -> None:
    async with async_session_maker() as db:
        clients = await list_clients(db, active_only=True)
    await cb.message.edit_text(
        "🏪 <b>Mijozlar Ro'yxati (Individual Narx & Guruhlar)</b>\n"
        "Sozlash uchun mijozni tanlang yoki yangi mijoz qo'shing:",
        parse_mode="HTML",
        reply_markup=clients_list_kb(clients),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("cli:view:"))
async def cb_client_detail(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":")[-1])
    text, cli = await _render_client_card_text(cid)
    if not cli:
        await cb.answer("Mijoz topilmadi", show_alert=True)
        return
    uname = await get_bot_username(cb.bot)
    await cb.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=client_detail_kb(cli, uname),
    )
    if cb.from_user and cb.message.chat.type == "private":
        _last_client_card[cb.from_user.id] = (
            cb.message.chat.id,
            cb.message.message_id,
            cli.id,
        )
    await cb.answer()


@router.callback_query(F.data == "cli:add")
async def cb_client_add_start(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ClientStates.waiting_client_name)
    await cb.message.answer(
        "🏪 Yangi mijoz (do'kon/xaridor) nomini kiriting (masalan: <code>Iftiqor 80</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(ClientStates.waiting_client_name, F.chat.type == "private")
async def process_client_name(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    name = (message.text or "").strip()
    if not name:
        await message.answer("⚠️ Mijoz nomini kiriting:")
        return
    await state.update_data(cli_name=name)
    await state.set_state(ClientStates.waiting_client_phone)
    await message.answer(
        "📞 Telefon raqamini kiriting (yoki o'tkazib yuborish uchun <code>-</code> yozing):",
        parse_mode="HTML",
    )


@router.message(ClientStates.waiting_client_phone, F.chat.type == "private")
async def process_client_phone(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    phone = (message.text or "").strip()
    if phone == "-":
        phone = ""
    await state.update_data(cli_phone=phone)
    await state.set_state(ClientStates.waiting_client_opening_debt)
    await message.answer(
        "💳 Mijozning hozirgi eski qarzi bormi? Summani kiriting (yo'q bo'lsa <code>0</code>):",
        parse_mode="HTML",
    )


@router.message(ClientStates.waiting_client_opening_debt, F.chat.type == "private")
async def process_client_opening_debt(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    raw = (message.text or "").strip()
    if raw == "0":
        debt_amt = 0.0
    else:
        parsed = parse_uzbek_amount(raw)
        if parsed is None or parsed < 0:
            await message.answer("⚠️ Summa noto'g'ri. Raqam kiriting (masalan: <code>0</code> yoki <code>1 500 000</code>):", parse_mode="HTML")
            return
        debt_amt = parsed

    data = await state.get_data()
    async with async_session_maker() as db:
        cli = await create_client(
            db,
            name=data["cli_name"],
            phone=data.get("cli_phone", ""),
            opening_debt=debt_amt,
        )
    await state.clear()
    text, loaded_cli = await _render_client_card_text(cli.id)
    uname = await get_bot_username(message.bot)
    await message.answer(
        f"✅ Yangi mijoz qo'shildi: <b>{html.escape(cli.name)}</b>!",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    if loaded_cli:
        sent = await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=client_detail_kb(loaded_cli, uname),
        )
        if message.from_user:
            _last_client_card[message.from_user.id] = (
                sent.chat.id,
                sent.message_id,
                loaded_cli.id,
            )


@router.callback_query(F.data.startswith("cli:prices:"))
async def cb_client_prices_menu(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        cli = await get_client(db, cid)
        products = await list_products(db, active_only=True)
        custom_map = await get_client_prices_map(db, cid)
    if not cli:
        await cb.answer("Mijoz topilmadi", show_alert=True)
        return
    await cb.message.edit_text(
        f"💰 <b>{html.escape(cli.name)} — Individual KG Narxlari</b>\n"
        "Narxni o'zgartirmoqchi bo'lgan mahsulotni tanlang:",
        parse_mode="HTML",
        reply_markup=client_prices_kb(cid, products, custom_map),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("cli:setprice:"))
async def cb_client_set_price_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    parts = cb.data.split(":")
    cid = int(parts[2])
    pid = int(parts[3])
    async with async_session_maker() as db:
        cli = await get_client(db, cid)
        prod = await get_product(db, pid)
    if not cli or not prod:
        await cb.answer("Topilmadi", show_alert=True)
        return
    await state.set_state(ClientStates.waiting_client_custom_price)
    await state.update_data(client_id=cid, product_id=pid)
    await cb.message.answer(
        f"💰 <b>{html.escape(cli.name)}</b> uchun <b>{html.escape(prod.name)}</b> ning 1 kg narxini yozing\n"
        f"(Standart narx: {format_uzs(prod.default_sell_price)} | Standartga qaytarish uchun <code>0</code> yozing):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(ClientStates.waiting_client_custom_price, F.chat.type == "private")
async def process_client_custom_price(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    raw = (message.text or "").strip()
    if raw == "0":
        price: Optional[float] = 0.0
    else:
        price = parse_uzbek_amount(raw)
        if price is None or price < 0:
            await message.answer("⚠️ To'g'ri narx kiriting (masalan: <code>112 000</code>):", parse_mode="HTML")
            return
    data = await state.get_data()
    cid = data["client_id"]
    pid = data["product_id"]
    async with async_session_maker() as db:
        await set_client_product_price(db, cid, pid, price if price and price > 0 else None)
        cli = await get_client(db, cid)
        products = await list_products(db, active_only=True)
        custom_map = await get_client_prices_map(db, cid)
    await state.clear()
    await message.answer(
        "✅ Mijoz narxi saqlandi!",
        reply_markup=main_menu_keyboard(),
    )
    if cli:
        await message.answer(
            f"💰 <b>{html.escape(cli.name)} — Individual KG Narxlari</b>",
            parse_mode="HTML",
            reply_markup=client_prices_kb(cid, products, custom_map),
        )


@router.callback_query(F.data.startswith("cli:set_gid:"))
async def cb_client_group_id_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    cid = int(cb.data.split(":")[-1])
    await state.set_state(ClientStates.waiting_client_group_id)
    await state.update_data(client_id=cid)
    await cb.message.answer(
        "🆔 Mijozning Telegram guruh ID sini kiriting (masalan: <code>-1001234567890</code>):\n"
        "<i>Maslahat: Guruh ichida /bind_group deb yozsangiz ID kiritish shart emas!</i>",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(ClientStates.waiting_client_group_id, F.chat.type == "private")
async def process_client_group_id(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    try:
        chat_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("⚠️ Noto'g'ri ID. Raqam kiriting (masalan: -1001234567890):")
        return
    cid = (await state.get_data())["client_id"]
    title = f"Guruh ({chat_id})"
    try:
        chat = await message.bot.get_chat(chat_id)
        if chat.title:
            title = chat.title
    except Exception:
        pass
    async with async_session_maker() as db:
        cli = await bind_client_group(db, cid, chat_id, title)
    await state.clear()
    uid = message.from_user.id if message.from_user else None
    await _refresh_open_client_card(message.bot, uid, cid)
    await message.answer(
        f"✅ Guruh biriktirildi: <b>{html.escape(cli.name if cli else '')}</b> → <code>{chat_id}</code>",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    card_text, loaded_cli = await _render_client_card_text(cid)
    if loaded_cli:
        uname = await get_bot_username(message.bot)
        sent = await message.answer(
            card_text,
            parse_mode="HTML",
            reply_markup=client_detail_kb(loaded_cli, uname),
        )
        if uid:
            _last_client_card[uid] = (sent.chat.id, sent.message_id, cid)


@router.callback_query(F.data.startswith("cli:grp_ping:"))
async def cb_client_group_ping(cb: CallbackQuery) -> None:
    """Confirm bound group status and bot presence when clicking the bound group button."""
    cid = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        cli = await get_client(db, cid)
    if not cli or not cli.group_chat_id:
        await cb.answer("Guruh ulanmagan", show_alert=True)
        return
    try:
        chat = await cb.bot.get_chat(cli.group_chat_id)
        title = chat.title or cli.group_title or str(cli.group_chat_id)
        await cb.answer(
            f"✅ Ulangan: {title}\n🆔 ID: {cli.group_chat_id}",
            show_alert=True,
        )
    except Exception as exc:
        await cb.answer(f"⚠️ Guruh tekshiruv xatosi: {exc}", show_alert=True)


@router.callback_query(F.data.startswith("cli:alias:"))
async def cb_client_alias_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    cid = int(cb.data.split(":")[-1])
    await state.set_state(ClientStates.waiting_client_alias)
    await state.update_data(client_id=cid)
    await cb.message.answer(
        "🔗 Mijoz uchun qo'shimcha sinonim nom kiriting (masalan: <code>IFTIQOR</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(ClientStates.waiting_client_alias, F.chat.type == "private")
async def process_client_alias(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    alias = (message.text or "").strip().upper()
    if not alias:
        await message.answer("⚠️ Sinonim kiriting:")
        return
    cid = (await state.get_data())["client_id"]
    async with async_session_maker() as db:
        cli = await get_client(db, cid)
        if cli:
            parts = [p.strip() for p in cli.aliases.split(",") if p.strip()]
            if alias not in [p.upper() for p in parts]:
                parts.append(alias)
            await update_client(db, cid, aliases=",".join(parts))
    await state.clear()
    await message.answer("✅ Sinonim qo'shildi!", reply_markup=main_menu_keyboard())


@router.callback_query(F.data.startswith("cli:unbind:"))
async def cb_client_unbind_group(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        await unbind_client_group(db, cid)
    text, cli = await _render_client_card_text(cid)
    if cli:
        uname = await get_bot_username(cb.bot)
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=client_detail_kb(cli, uname))
    await cb.answer("🔓 Guruh uzildi")


@router.callback_query(F.data.startswith("cli:del:"))
async def cb_client_delete(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        await delete_client(db, cid)
        clients = await list_clients(db, active_only=True)
    await cb.message.edit_text(
        "🏪 <b>Mijozlar Ro'yxati:</b>",
        parse_mode="HTML",
        reply_markup=clients_list_kb(clients),
    )
    await cb.answer("🗑 O'chirildi")


@router.callback_query(F.data.startswith("cli:send_sverka:"))
async def cb_client_send_sverka_to_group(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        debt = await compute_client_debt(db, cid)
    if not debt.client.group_chat_id:
        await cb.answer("Bu mijozga guruh biriktirilmagan!", show_alert=True)
        return
    sverka_text = render_client_sverka_text(debt, for_group=True)
    try:
        await cb.bot.send_message(
            chat_id=debt.client.group_chat_id,
            text=sverka_text,
            parse_mode="HTML",
        )
        await cb.answer("✅ Akt Sverka mijoz guruhiga yuborildi!", show_alert=True)
    except Exception as exc:
        await cb.answer(f"❌ Guruhga yuborib bo'lmadi: {exc}", show_alert=True)


# ---------------------------------------------------------------------------
# Debts Menu (💳 Qarzlar)
# ---------------------------------------------------------------------------


@router.message(F.text == BTN_DEBTS, F.chat.type == "private")
async def handle_debts_btn(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    await state.clear()
    async with async_session_maker() as db:
        debts = await list_all_client_debts(db)
    await message.answer(
        render_debts_overview_text(debts),
        parse_mode="HTML",
        reply_markup=debts_list_kb(debts),
    )


@router.callback_query(F.data == "debt:list")
async def cb_debts_list(cb: CallbackQuery) -> None:
    async with async_session_maker() as db:
        debts = await list_all_client_debts(db)
    await cb.message.edit_text(
        render_debts_overview_text(debts),
        parse_mode="HTML",
        reply_markup=debts_list_kb(debts),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("debt:view:"))
async def cb_debt_client_detail(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        debt = await compute_client_debt(db, cid, history_limit=10)
    await cb.message.edit_text(
        render_client_sverka_text(debt, for_group=False),
        parse_mode="HTML",
        reply_markup=client_debt_detail_kb(cid, has_group=bool(debt.client.group_chat_id)),
    )
    await cb.answer()

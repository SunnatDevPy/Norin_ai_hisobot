"""Start, Group Setup hub, Telegram Group auto-binding, and Read-only Debts / Akt Sverka."""

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
    BTN_GROUPS,
    BTN_SETTINGS,
    MAIN_MENU_BUTTONS,
    bind_group_clients_kb,
    cancel_reply_keyboard,
    client_debt_readonly_kb,
    client_detail_kb,
    clients_list_kb,
    debts_list_kb,
    main_menu_keyboard,
    report_group_config_kb,
    settings_menu_kb,
)
from bot.states import ClientStates, WalletStates
from bot.ui_helpers import fast_edit, mark_reply_kb_sent, send_inline_panel
from database.crud import (
    CURRENT_USER_AUTHORIZED,
    ClientDebtSummary,
    bind_client_group,
    compute_client_debt,
    evaluate_subscription_status,
    format_local_dt,
    get_client,
    get_client_by_group,
    get_client_prices_map,
    get_group_config,
    is_user_authorized,
    list_all_client_debts,
    list_clients,
    list_products,
    set_group_config,
    unbind_client_group,
)
from database.session import async_session_maker
from services.gemini_ai import format_kg, format_uzs


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


def set_cached_bot_username(username: Optional[str]) -> None:
    """Pre-populate the cached bot @username during startup."""
    global _BOT_USERNAME
    if username:
        _BOT_USERNAME = username.lstrip("@")


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
    """Check if Telegram user is authorized, reusing middleware auth ContextVar with 0 extra DB queries."""
    cached = CURRENT_USER_AUTHORIZED.get()
    if cached is not None:
        if cached or not allow_group_anon:
            return cached
    async with async_session_maker() as db:
        return await is_user_authorized(db, user_id, allow_group_anon=allow_group_anon)


def render_debts_overview_text(debts: list[ClientDebtSummary]) -> str:
    """Format overview of all clients' debt balances."""
    if not debts:
        return (
            "💳 <b>Mijozlar Qarz Daftari</b>\n\n"
            "<i>Hozircha mijozlar qo'shilmagan. Mijozlarni Norin AI Android ilovasida qo'shing.</i>"
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
    lines.append("\n<i>Batafsil Akt Sverka yoki Excel olish uchun mijozni tanlang:</i>")
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
    ]
    if debt.total_returns > 0:
        lines.append(
            f"↩️ Jami vozvrat ({format_kg(debt.total_return_kg)} kg): <b>-{format_uzs(debt.total_returns)} so'm</b>"
        )
    lines.extend(
        [
            f"💵 Jami to'langan: <b>{format_uzs(debt.total_paid)} so'm</b>",
            f"💳 <b>Hozirgi qarz qoldig'i: {format_uzs(debt.current_debt)} so'm</b>",
        ]
    )
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
    """Handle /start in private chat with focused 4-section navigation."""
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
        warn_line = "\n\n🔒 <b>Obuna muddati tugagan.</b> Davom ettirish uchun 💎 Obuna va Status bo'limiga kiring."

    await message.answer(
        "👋 <b>Assalomu alaykum! Norin AI Hisobot botiga xush kelibsiz.</b>\n"
        f"🏢 Filial: <b>{html.escape(sub_status.state.tenant_name)}</b> (<code>#{sub_status.state.id}</code>)\n\n"
        "Botda faqat quyidagi asosiy boshqaruv bo'limlari qoldirilgan:\n"
        "• 📱 <b>Mobil ilova (APK)</b> — ilovani yuklab olish, 1-bosishda ulanish va kirish kodi\n"
        "• 📊 <b>Dashboardlar</b> — kunlik, 7/30 kunlik va oylik hisobotlar, qarzlar, Excel\n"
        "• 🔗 <b>Guruh sozlash</b> — rahbariyat hisobot guruhi va mijoz guruhlarini ulash\n"
        "• 💎 <b>Obuna va Status</b> — tarif muddati, AI kvota va faol qurilmalar\n\n"
        "<i>🥩 Savdo, chek rasmi, to'lov, vozvrat va xarajatlar Norin AI Android APK ilovasida bajariladi.</i>"
        f"{warn_line}\n\n"
        f"🆔 Sizning ID: <code>{uid or 0}</code>",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    mark_reply_kb_sent(message.chat.id)


@router.message(Command("cancel"), F.chat.type == "private")
@router.message(F.text == "❌ Bekor qilish", F.chat.type == "private")
async def cancel_any_state(message: Message, state: FSMContext) -> None:
    """Cancel current FSM operation and return to main menu."""
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    await state.clear()
    await message.answer("❌ Amal bekor qilindi.", reply_markup=main_menu_keyboard())
    mark_reply_kb_sent(message.chat.id)


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
            "Endi Norin AI ilovasida tasdiqlangan sotuv va to'lov cheklari avtomatik shu guruhga yuboriladi.",
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
# Group Setup Hub (🔗 Guruh sozlash / /groups)
# ---------------------------------------------------------------------------


async def _render_groups_hub_text() -> str:
    async with async_session_maker() as db:
        clients = await list_clients(db, active_only=True)
        rep_cfg = await get_group_config(db, "report")
    bound_cnt = sum(1 for c in clients if c.group_chat_id)
    rep_line = (
        f"✅ <b>{html.escape(rep_cfg.title)}</b> (<code>{rep_cfg.chat_id}</code>)"
        if rep_cfg
        else "⚠️ <i>Hali ulanmagan</i>"
    )
    return (
        "🔗 <b>Telegram Guruhlarni Sozlash</b>\n"
        "===============================\n"
        f"📊 <b>Rahbariyat hisobot guruhi:</b> {rep_line}\n"
        f"🏪 <b>Mijoz guruhlari:</b> <b>{bound_cnt} / {len(clients)} ta</b> ulangan\n\n"
        "<i>Guruh ulashning 2 ta oson usuli:</i>\n"
        "1️⃣ Quyidan mijoz yoki hisobot guruhini tanlab <b>1-bosishda ulash</b> tugmasini bosing;\n"
        "2️⃣ Yoki botni kerakli guruhga qo'shib ichida <code>/bind_group</code> yozing."
    )


@router.message(Command("groups"), F.chat.type == "private")
@router.message(F.text.in_({BTN_GROUPS, BTN_SETTINGS}), F.chat.type == "private")
async def open_settings_menu(message: Message, state: FSMContext) -> None:
    uid = message.from_user.id if message.from_user else None
    if not await is_authorized_async(uid):
        return
    await state.clear()
    text = await _render_groups_hub_text()
    await send_inline_panel(
        message,
        text,
        reply_markup=settings_menu_kb(is_super_admin=is_super_admin(uid)),
        delete_prev=True,
    )


@router.callback_query(F.data == "set:back")
async def cb_settings_back(cb: CallbackQuery, state: FSMContext) -> None:
    uid = cb.from_user.id if cb.from_user else None
    await state.clear()
    text = await _render_groups_hub_text()
    await fast_edit(
        cb,
        text,
        reply_markup=settings_menu_kb(is_super_admin=is_super_admin(uid)),
    )


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
    await fast_edit(
        cb,
        text,
        reply_markup=report_group_config_kb(username, group_title=cfg.title if cfg else None),
    )


@router.callback_query(F.data == "repgrp:set_id")
async def cb_report_group_id_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(WalletStates.waiting_report_group_id)
    await cb.message.answer(
        "🆔 Rahbariyat hisobot guruhining Chat ID sini yuboring (masalan: <code>-1001234567890</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(
    WalletStates.waiting_report_group_id,
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
    F.text != "❌ Bekor qilish",
)
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
# Client Group Binding Directory (Group Setup Only)
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
    if not clients:
        await cb.answer(
            "Hozircha mijozlar yo'q. Mijozni Norin AI APK ilovasida qo'shing.",
            show_alert=True,
        )
        return
    await fast_edit(
        cb,
        "🏪 <b>Mijoz Guruhlarini Sozlash</b>\n"
        "Guruhini ulash yoki tekshirish uchun mijozni tanlang:",
        reply_markup=clients_list_kb(clients, page=0),
    )


@router.callback_query(F.data.startswith("set:clients:p:"))
async def cb_clients_page(cb: CallbackQuery) -> None:
    page = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        clients = await list_clients(db, active_only=True)
    await asyncio.gather(
        cb.message.edit_reply_markup(reply_markup=clients_list_kb(clients, page=page)),
        cb.answer(),
        return_exceptions=True,
    )


@router.callback_query(F.data.startswith("cli:view:"))
async def cb_client_detail(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":")[-1])
    text, cli = await _render_client_card_text(cid)
    if not cli:
        await cb.answer("Mijoz topilmadi", show_alert=True)
        return
    uname = await get_bot_username(cb.bot)
    await fast_edit(
        cb,
        text,
        reply_markup=client_detail_kb(cli, uname),
    )
    if cb.from_user and cb.message.chat.type == "private":
        _last_client_card[cb.from_user.id] = (
            cb.message.chat.id,
            cb.message.message_id,
            cli.id,
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


@router.message(
    ClientStates.waiting_client_group_id,
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
    F.text != "❌ Bekor qilish",
)
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
# Read-only Debts & Akt Sverka (Accessible from Dashboards)
# ---------------------------------------------------------------------------


@router.message(F.text == BTN_DEBTS, F.chat.type == "private")
async def handle_debts_btn(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    await state.clear()
    async with async_session_maker() as db:
        debts = await list_all_client_debts(db)
    await send_inline_panel(
        message,
        render_debts_overview_text(debts),
        reply_markup=debts_list_kb(debts),
        delete_prev=False,
    )


@router.callback_query(F.data == "debt:list")
async def cb_debts_list(cb: CallbackQuery) -> None:
    async with async_session_maker() as db:
        debts = await list_all_client_debts(db)
    await fast_edit(
        cb,
        render_debts_overview_text(debts),
        reply_markup=debts_list_kb(debts, page=0),
    )


@router.callback_query(F.data.startswith("debt:list:p:"))
async def cb_debts_list_page(cb: CallbackQuery) -> None:
    page = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        debts = await list_all_client_debts(db)
    await asyncio.gather(
        cb.message.edit_reply_markup(reply_markup=debts_list_kb(debts, page=page)),
        cb.answer(),
        return_exceptions=True,
    )


@router.callback_query(F.data.startswith("debt:view:"))
async def cb_debt_client_detail(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        debt = await compute_client_debt(db, cid, history_limit=10)
    await fast_edit(
        cb,
        render_client_sverka_text(debt, for_group=False),
        reply_markup=client_debt_readonly_kb(cid, has_group=bool(debt.client.group_chat_id)),
    )


# ---------------------------------------------------------------------------
# Legacy Catalog / Prefs Callbacks -> Polite APK Redirect
# ---------------------------------------------------------------------------


@router.callback_query(
    F.data.in_({"set:products", "set:ai_prefs"})
    | F.data.startswith("prd:")
    | F.data.startswith("pref:")
    | F.data.startswith("cli:add")
    | F.data.startswith("cli:edit")
    | F.data.startswith("cli:prices:")
    | F.data.startswith("cli:setprice:")
    | F.data.startswith("cli:alias:")
    | F.data.startswith("cli:del")
)
async def redirect_legacy_catalog_callbacks(cb: CallbackQuery) -> None:
    await cb.answer(
        "📱 Mahsulot, mijoz va narx sozlamalari endi Norin AI APK ilovasida bajariladi.",
        show_alert=True,
    )

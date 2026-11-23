"""Client-safe receipt formatters, navigation home/dismiss callbacks, and polite APK redirects."""

from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import re
from typing import Optional

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.handlers.clients_products import is_authorized_async
from bot.keyboards import (
    BTN_ADD_SALE,
    BTN_CLIENT_PAY,
    BTN_EDIT,
    MAIN_MENU_BUTTONS,
    main_menu_keyboard,
)
from bot.ui_helpers import clear_active_panel, mark_reply_kb_sent
from database.crud import format_local_dt
from database.models import ClientPayment, ProductReturn, Sale
from services.gemini_ai import format_kg, format_uzs, parse_weight_kg


router = Router(name="sales_norin")
logger = logging.getLogger("norin_bot.sales")


# ---------------------------------------------------------------------------
# Caption & Message Renderers (STRICT CLIENT PRIVACY ON GROUP CAPTIONS)
# ---------------------------------------------------------------------------


def render_sale_group_caption(
    sale: Sale, current_debt: float, tag: str = ""
) -> str:
    """
    Build caption/message posted to a client's Telegram group.

    STRICT SAFETY RULE: Never include cost_price, unit_cost, total_cost, profit, or margin!
    Only displays kg weights, client sell price, total amount, and client's current debt.
    """
    client_name = sale.client.name if sale.client else "Mijoz"
    prefix = f"{tag}\n" if tag else ""
    if sale.status == "deleted":
        return (
            f"❌ <b>[BEKOR QILINDI / O'CHIRILDI]</b>\n"
            f"🥩 Hisob #{sale.id} — <s>{html.escape(client_name)}</s>\n"
            f"⚖️ <s>{format_kg(sale.total_weight_kg)} kg</s> | <s>{format_uzs(sale.total_amount)} so'm</s>\n"
            f"💳 Hozirgi qarz qoldig'i: <b>{format_uzs(current_debt)} so'm</b>"
        )

    ts = format_local_dt(sale.created_at, "%d.%m.%Y %H:%M")
    lines = [
        f"{prefix}🥩 <b>Norin Hisob #{sale.id}</b>",
        f"🏪 Mijoz: <b>{html.escape(client_name)}</b>",
        f"📅 Sana: {ts}",
        "-------------------------------",
    ]
    for item in sale.items:
        bd = f" ({html.escape(item.weights_detail)})" if item.weights_detail else ""
        lines.append(
            f"• {html.escape(item.product_name)}: <b>{format_kg(item.weight_kg)} kg</b>{bd} × {format_uzs(item.unit_sell_price)} = <b>{format_uzs(item.line_total)} so'm</b>"
        )
    lines.extend(
        [
            "-------------------------------",
            f"⚖️ Jami vazn: <b>{format_kg(sale.total_weight_kg)} kg</b>",
            f"💰 <b>Jami summa: {format_uzs(sale.total_amount)} so'm</b>",
            f"💳 Hozirgi qarz qoldig'i: <b>{format_uzs(current_debt)} so'm</b>",
        ]
    )
    return "\n".join(lines)


def render_sale_admin_summary(
    sale: Sale, current_debt: Optional[float] = None
) -> str:
    """Build detailed internal summary for admin private DM (includes cost & profit)."""
    client_name = sale.client.name if sale.client else "Tanlanmagan ⚠️"
    lines = [
        f"🧾 <b>Sotuv #{sale.id}</b> — 🏪 <b>{html.escape(client_name)}</b>",
    ]
    for item in sale.items:
        bd = f" ({html.escape(item.weights_detail)})" if item.weights_detail else ""
        lines.append(
            f"• {html.escape(item.product_name)}: <b>{format_kg(item.weight_kg)} kg</b>{bd} × {format_uzs(item.unit_sell_price)} = <b>{format_uzs(item.line_total)}</b>"
        )
    lines.extend(
        [
            f"⚖️ Jami vazn: <b>{format_kg(sale.total_weight_kg)} kg</b>",
            f"💰 Jami sotuv: <b>{format_uzs(sale.total_amount)} so'm</b>",
            f"📉 Tannarx: {format_uzs(sale.total_cost)} so'm",
            f"📈 <b>Sof foyda: {format_uzs(sale.total_profit)} so'm</b>",
        ]
    )
    if current_debt is not None and sale.client_id is not None:
        lines.append(f"💳 Mijoz qarzi: <b>{format_uzs(current_debt)} so'm</b>")
    return "\n".join(lines)


def render_payment_group_receipt(
    payment: ClientPayment, current_debt: float, tag: str = ""
) -> str:
    """Client-safe payment receipt posted to client group."""
    m_labels = {"cash": "Naqd", "card": "Karta / Click", "transfer": "Perechesleniye"}
    cname = payment.client.name if payment.client else "Mijoz"
    dt = format_local_dt(payment.created_at, "%d.%m.%Y %H:%M")
    if payment.is_deleted:
        return (
            f"❌ <b>[TO'LOV BEKOR QILINDI]</b>\n"
            f"💵 To'lov #{payment.id} — <s>{html.escape(cname)}</s>\n"
            f"💰 Summa: <s>+{format_uzs(payment.amount)} so'm</s>\n"
            f"💳 Yangilangan qarz qoldig'i: <b>{format_uzs(current_debt)} so'm</b>"
        )
    prefix = f"{tag}\n" if tag else ""
    return (
        f"{prefix}💵 <b>TO'LOV QABUL QILINDI</b>\n"
        f"🏪 Mijoz: <b>{html.escape(cname)}</b>\n"
        f"💰 Summa: <b>+{format_uzs(payment.amount)} so'm</b> ({m_labels.get(payment.payment_method, payment.payment_method)})\n"
        f"📅 Vaqt: {dt}\n"
        f"💳 Qolgan qarz qoldig'i: <b>{format_uzs(current_debt)} so'm</b>"
    )


def render_sale_edit_group_notice(
    sale: Sale, current_debt: float, change_line: str, is_deleted: bool = False
) -> str:
    """
    Client-safe visible reply notification sent to client group when a sale is edited or deleted.

    STRICT SAFETY RULE: Never include cost_price, unit_cost, total_cost, profit, or margin!
    """
    cname = sale.client.name if sale.client else "Mijoz"
    header = (
        f"❌ <b>HISOB #{sale.id} BEKOR QILINDI</b>"
        if is_deleted
        else f"✏️ <b>HISOB #{sale.id} TAHRIRLANDI</b>"
    )
    return (
        f"{header}\n"
        f"🏪 Mijoz: <b>{html.escape(cname)}</b>\n"
        f"{change_line}\n"
        f"💳 Yangilangan qarz qoldig'i: <b>{format_uzs(current_debt)} so'm</b>"
    )


def render_payment_edit_group_notice(
    payment: ClientPayment,
    current_debt: float,
    old_amount: Optional[float] = None,
    is_deleted: bool = False,
) -> str:
    """Client-safe visible notification sent to client group when a debt payment is edited or deleted."""
    cname = payment.client.name if payment.client else "Mijoz"
    if is_deleted:
        return (
            f"❌ <b>TO'LOV #{payment.id} BEKOR QILINDI</b>\n"
            f"🏪 Mijoz: <b>{html.escape(cname)}</b>\n"
            f"💰 Summa: <s>+{format_uzs(payment.amount)} so'm</s>\n"
            f"💳 Yangilangan qarz qoldig'i: <b>{format_uzs(current_debt)} so'm</b>"
        )
    amt_line = (
        f"💰 Summa: <s>+{format_uzs(old_amount)}</s> → <b>+{format_uzs(payment.amount)} so'm</b>"
        if old_amount is not None
        else f"💰 Yangi summa: <b>+{format_uzs(payment.amount)} so'm</b>"
    )
    return (
        f"✏️ <b>TO'LOV #{payment.id} TAHRIRLANDI</b>\n"
        f"🏪 Mijoz: <b>{html.escape(cname)}</b>\n"
        f"{amt_line}\n"
        f"💳 Yangilangan qarz qoldig'i: <b>{format_uzs(current_debt)} so'm</b>"
    )


def render_return_group_caption(ret: ProductReturn, current_debt: float) -> str:
    """
    Client-safe Vozvrat receipt posted to a client's Telegram group.

    STRICT SAFETY RULE: Never include unit_cost, total_cost, profit, or margin!
    """
    cname = ret.client.name if ret.client else f"Mijoz #{ret.client_id}"
    dt = format_local_dt(ret.created_at, "%d.%m.%Y %H:%M") if ret.created_at else ret.report_date
    reason_line = f"\n📝 Sabab: <i>{html.escape(ret.reason)}</i>" if ret.reason else ""
    return (
        f"↩️ <b>VOZVRAT QABUL QILINDI (#{ret.id})</b>\n"
        f"🏪 Mijoz: <b>{html.escape(cname)}</b>\n"
        f"🥩 Mahsulot: <b>{html.escape(ret.product_name)}</b>\n"
        f"⚖️ Vazn: <b>-{format_kg(ret.weight_kg)} kg</b> × {format_uzs(ret.unit_sell_price)}\n"
        f"💰 Qarzdan ayirildi: <b>-{format_uzs(ret.total_amount)} so'm</b>"
        f"{reason_line}\n"
        f"📅 Vaqt: {dt}\n"
        f"💳 Yangilangan qarz qoldig'i: <b>{format_uzs(current_debt)} so'm</b>"
    )


def render_return_delete_group_notice(ret: ProductReturn, current_debt: float) -> str:
    """Client-safe visible notice sent to group when a Vozvrat entry is deleted."""
    cname = ret.client.name if ret.client else f"Mijoz #{ret.client_id}"
    return (
        f"❌ <b>VOZVRAT #{ret.id} BEKOR QILINDI</b>\n"
        f"🏪 Mijoz: <b>{html.escape(cname)}</b>\n"
        f"🥩 {html.escape(ret.product_name)}: <s>-{format_kg(ret.weight_kg)} kg</s> (<s>-{format_uzs(ret.total_amount)} so'm</s>)\n"
        f"💳 Yangilangan qarz qoldig'i: <b>{format_uzs(current_debt)} so'm</b>"
    )


def _parse_return_weight_and_reason(raw_text: str) -> tuple[Optional[float], str]:
    """Extract leading kg/sum weight expression and optional reason text with 0 AI tokens."""
    txt = (raw_text or "").strip()
    if not txt:
        return None, ""
    m = re.match(
        r"^\s*((?:\d+(?:[.,]\d+)?\s+yarim|yarim|\d+(?:[.,]\d+)?(?:\s*\+\s*\d+(?:[.,]\d+)?)*)(?:\s*(?:kg|кг))?)(?:\s+(.*))?$",
        txt,
        flags=re.IGNORECASE,
    )
    if m:
        w = parse_weight_kg(m.group(1))
        reason = (m.group(2) or "").strip()
        if w and w > 0:
            return w, reason
    w = parse_weight_kg(txt)
    if w and w > 0:
        return w, ""
    return None, ""


# ---------------------------------------------------------------------------
# Home / Dismiss Menu Callbacks
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "menu:home")
async def cb_menu_home(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    chat_id = cb.message.chat.id if cb.message else None
    clear_active_panel(chat_id)
    with contextlib.suppress(Exception):
        await cb.message.edit_reply_markup(reply_markup=None)
    await asyncio.gather(
        cb.answer(),
        cb.message.answer(
            "🏠 <b>Asosiy menyu</b> — pastdagi tugmalardan tanlang:",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        ),
        return_exceptions=True,
    )
    mark_reply_kb_sent(chat_id)


@router.callback_query(F.data == "menu:dismiss")
async def cb_menu_dismiss(cb: CallbackQuery) -> None:
    clear_active_panel(cb.message.chat.id if cb.message else None)
    await asyncio.gather(
        cb.message.delete(),
        cb.answer(),
        return_exceptions=True,
    )


# ---------------------------------------------------------------------------
# Polite APK Redirects for Legacy Sales / Payments / Voice / Photo Input
# ---------------------------------------------------------------------------


def _apk_only_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 Mobil ilova (APK)", callback_data="apk:home")],
            [
                InlineKeyboardButton(text="📊 Dashboardlar", callback_data="rep:today"),
                InlineKeyboardButton(text="🔗 Guruh sozlash", callback_data="set:back"),
            ],
        ]
    )


@router.callback_query(
    F.data.startswith("sale:")
    | F.data.startswith("sale_view:")
    | F.data.startswith("pay:")
    | F.data.startswith("pay_view:")
    | F.data.startswith("ret:")
    | F.data.startswith("ret_view:")
    | F.data.startswith("edit_menu:")
    | F.data.startswith("ctx_")
)
async def redirect_legacy_sale_callbacks(cb: CallbackQuery) -> None:
    await cb.answer(
        "📱 Sotuv, chek o'qish, to'lov, vozvrat va tahrirlash endi Norin AI APK ilovasida bajariladi.",
        show_alert=True,
    )


@router.message(
    F.text.in_({BTN_ADD_SALE, BTN_CLIENT_PAY, BTN_EDIT}),
    F.chat.type == "private",
)
async def redirect_legacy_sale_buttons(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    await state.clear()
    await message.answer(
        "📱 <b>Sotuv, chek rasmi, to'lov va tahrirlash amallari Norin AI Android APK ilovasiga ko'chirilgan.</b>\n\n"
        "Botda faqat <b>APK yuklash</b>, <b>Status</b>, <b>Dashboardlar</b> va <b>Guruh sozlash</b> ishlaydi.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    mark_reply_kb_sent(message.chat.id)
    await message.answer("👇 Kerakli bo'limni tanlang:", reply_markup=_apk_only_kb())


@router.message(
    StateFilter(None),
    F.chat.type == "private",
    F.photo | F.voice | F.audio | (F.text & ~F.text.startswith("/") & ~F.text.in_(MAIN_MENU_BUTTONS)),
)
async def redirect_private_fallback_to_apk(message: Message) -> None:
    """In private chat, gently guide authorized users to the APK app instead of processing sales here."""
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    await message.answer(
        "📱 <b>Chek rasmi, ovozli va matnli sotuvlar endi Norin AI Android ilovasida qabul qilinadi!</b>\n\n"
        "Bu botda esa ilovani yuklab olish (<code>/apk</code>), obuna va status (<code>/status</code>), "
        "hisobot dashboardlari (<code>/dashboard</code>) hamda Telegram guruhlarni ulash (<code>/groups</code>) mavjud.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    mark_reply_kb_sent(message.chat.id)
    await message.answer("📲 Tezkor kirish:", reply_markup=_apk_only_kb())

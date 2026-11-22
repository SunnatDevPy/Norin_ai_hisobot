"""AI Norin receipt/voice/text sales, client payments, group auto-calculation, and live editing."""

from __future__ import annotations

import asyncio
import contextlib
import html
import io
import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.handlers.clients_products import (
    is_authorized_async,
    render_debts_overview_text,
)
from bot.handlers.wallet_reports import render_daily_report_text
from bot.keyboards import (
    BTN_ADD_SALE,
    BTN_CLIENT_PAY,
    BTN_EDIT,
    MAIN_MENU_BUTTONS,
    auto_confirmed_sale_kb,
    cancel_reply_keyboard,
    cash_tx_edit_kb,
    confirm_delete_kb,
    confirmed_sale_edit_kb,
    daily_report_kb,
    debts_list_kb,
    edit_items_list_kb,
    main_menu_keyboard,
    payment_after_record_kb,
    payment_edit_kb,
    payment_method_kb,
    pick_client_for_payment_kb,
    pick_client_for_return_kb,
    pick_client_for_sale_kb,
    pick_product_for_item_kb,
    pick_product_for_return_kb,
    quick_sale_payment_kb,
    return_after_record_kb,
    return_edit_kb,
    sale_confirm_kb,
)
from bot.states import SaleStates, WalletStates
from bot.ui_helpers import clear_active_panel, fast_edit, mark_reply_kb_sent, send_inline_panel
from config import get_settings
from database.crud import (
    add_cash_transaction,
    add_client_payment,
    add_product_return,
    compute_client_debt,
    compute_session_summary,
    confirm_sale,
    create_client,
    create_pending_sale,
    delete_cash_transaction,
    delete_client_payment,
    delete_product_return,
    delete_sale,
    find_duplicate_confirmed_sale,
    format_local_dt,
    get_app_setting,
    get_cash_transaction,
    get_client,
    get_client_by_group,
    get_client_payment,
    get_client_prices_map,
    get_open_session,
    get_product,
    get_product_return,
    get_sale,
    list_all_client_debts,
    list_authorized_users,
    list_clients,
    list_products,
    match_client,
    match_product,
    round_amount,
    set_client_payment_group_message,
    set_product_return_group_message,
    set_sale_group_message,
    today_iso,
    update_cash_transaction,
    update_client_payment,
    update_sale_client,
    update_sale_item,
)
from database.models import (
    CashTransaction,
    ClientPayment,
    Product,
    ProductReturn,
    Sale,
    SaleItem,
)
from database.session import async_session_maker
from services.gemini_ai import (
    _heuristic_parse_norin_text,
    extract_amount_from_audio,
    extract_caption_client_override,
    extract_norin_from_image,
    format_kg,
    format_uzs,
    parse_norin_voice_or_text,
    parse_uzbek_amount,
    parse_weight_kg,
)


router = Router(name="sales_norin")
logger = logging.getLogger("norin_bot.sales")
_PENDING_SALE_SUGGESTED_CLIENT: dict[int, str] = {}


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


async def _download_voice_bytes(message: Message) -> tuple[bytes, str]:
    file_obj = message.voice or message.audio
    mime = "audio/ogg" if message.voice else (file_obj.mime_type or "audio/mpeg")
    buf = io.BytesIO()
    await message.bot.download(file_obj, destination=buf)
    return buf.getvalue(), mime


async def _post_sale_to_client_group(
    bot,
    sale: Sale,
    current_debt: float,
    reply_to_message: Optional[Message] = None,
) -> tuple[bool, str]:
    """Post confirmed sale photo or reply caption to the client's bound Telegram group."""
    if not sale.client or not sale.client.group_chat_id:
        return False, "<i>(Mijoz guruhi ulanmagan — faqat bazaga saqlandi)</i>"

    caption = render_sale_group_caption(sale, current_debt)
    target_chat_id = sale.client.group_chat_id
    try:
        if reply_to_message is not None:
            sent = await reply_to_message.reply(caption, parse_mode="HTML")
        elif sale.photo_file_id:
            sent = await bot.send_photo(
                chat_id=target_chat_id,
                photo=sale.photo_file_id,
                caption=caption,
                parse_mode="HTML",
            )
        else:
            sent = await bot.send_message(
                chat_id=target_chat_id,
                text=caption,
                parse_mode="HTML",
            )
        async with async_session_maker() as db:
            await set_sale_group_message(db, sale.id, target_chat_id, sent.message_id)
        return True, f"📤 <b>{html.escape(sale.client.group_title or sale.client.name)}</b> guruhiga yuborildi!"
    except Exception as exc:
        return False, f"⚠️ Guruhga yuborib bo'lmadi: {html.escape(str(exc))}"


async def _sync_sale_group_message(
    bot,
    sale: Sale,
    current_debt: float,
    tag: str = "✏️ [TAHRIRLANDI]",
    change_line: Optional[str] = None,
) -> tuple[bool, str]:
    """Update original group message AND send a visible change alert to the client's group."""
    target_chat_id = sale.group_chat_id or (sale.client.group_chat_id if sale.client else None)
    if not target_chat_id:
        return False, "<i>(Mijoz guruhi ulanmagan)</i>"

    edited_ok = False
    if sale.group_chat_id and sale.group_message_id:
        new_caption = render_sale_group_caption(sale, current_debt, tag=tag)
        try:
            if sale.photo_file_id and sale.source_channel == "dm":
                try:
                    await bot.edit_message_caption(
                        chat_id=sale.group_chat_id,
                        message_id=sale.group_message_id,
                        caption=new_caption,
                        parse_mode="HTML",
                    )
                except Exception as cap_exc:
                    if "no caption" in str(cap_exc).lower() or "text" in str(cap_exc).lower():
                        await bot.edit_message_text(
                            chat_id=sale.group_chat_id,
                            message_id=sale.group_message_id,
                            text=new_caption,
                            parse_mode="HTML",
                        )
                    else:
                        raise
            else:
                await bot.edit_message_text(
                    chat_id=sale.group_chat_id,
                    message_id=sale.group_message_id,
                    text=new_caption,
                    parse_mode="HTML",
                )
            edited_ok = True
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                edited_ok = True
            else:
                logger.warning("Failed to edit group message for sale_id=%s: %s", sale.id, exc)

    alert_ok = False
    if change_line or sale.status == "deleted":
        notice_text = render_sale_edit_group_notice(
            sale,
            current_debt,
            change_line or f"⚖️ {format_kg(sale.total_weight_kg)} kg — {format_uzs(sale.total_amount)} so'm",
            is_deleted=(sale.status == "deleted"),
        )
        reply_id = sale.group_message_id if sale.group_chat_id == target_chat_id else None
        try:
            await bot.send_message(
                chat_id=target_chat_id,
                text=notice_text,
                parse_mode="HTML",
                reply_to_message_id=reply_id,
            )
            alert_ok = True
        except Exception:
            if reply_id:
                try:
                    await bot.send_message(
                        chat_id=target_chat_id,
                        text=notice_text,
                        parse_mode="HTML",
                    )
                    alert_ok = True
                except Exception as exc2:
                    logger.warning("Failed to send group edit alert for sale_id=%s: %s", sale.id, exc2)

    if alert_ok and edited_ok:
        return True, "📤 <b>Mijoz guruhidagi xabar yangilandi va o'zgarish haqida xabar yuborildi!</b>"
    if alert_ok:
        return True, "📤 <b>Mijoz guruhiga o'zgarish haqida xabar yuborildi!</b>"
    if edited_ok:
        return True, "📤 <b>Mijoz guruhidagi xabar ham yangilandi!</b>"
    return False, "⚠️ Guruhga xabar yuborib bo'lmadi."


async def _sync_payment_group_message(
    bot,
    payment: ClientPayment,
    current_debt: float,
    old_amount: Optional[float] = None,
    is_deleted: bool = False,
) -> tuple[bool, str]:
    """Update original group payment receipt (if posted) AND send visible edit/delete alert to client group."""
    target_chat_id = payment.group_chat_id or (
        payment.client.group_chat_id if payment.client else None
    )
    if not target_chat_id:
        return False, "<i>(Mijoz guruhi ulanmagan)</i>"

    edited_ok = False
    if payment.group_chat_id and payment.group_message_id:
        tag = "❌ [BEKOR QILINDI]" if is_deleted else "✏️ [TAHRIRLANDI]"
        new_text = render_payment_group_receipt(payment, current_debt, tag=tag)
        try:
            await bot.edit_message_text(
                chat_id=payment.group_chat_id,
                message_id=payment.group_message_id,
                text=new_text,
                parse_mode="HTML",
            )
            edited_ok = True
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                edited_ok = True
            else:
                logger.warning("Failed to edit payment group message pay_id=%s: %s", payment.id, exc)

    alert_ok = False
    notice_text = render_payment_edit_group_notice(
        payment, current_debt, old_amount=old_amount, is_deleted=is_deleted
    )
    reply_id = payment.group_message_id if payment.group_chat_id == target_chat_id else None
    try:
        await bot.send_message(
            chat_id=target_chat_id,
            text=notice_text,
            parse_mode="HTML",
            reply_to_message_id=reply_id,
        )
        alert_ok = True
    except Exception:
        if reply_id:
            try:
                await bot.send_message(
                    chat_id=target_chat_id,
                    text=notice_text,
                    parse_mode="HTML",
                )
                alert_ok = True
            except Exception as exc2:
                logger.warning("Failed to send payment alert pay_id=%s: %s", payment.id, exc2)

    if alert_ok:
        return True, "📤 <b>Mijoz guruhiga to'lov o'zgarishi haqida xabar yuborildi!</b>"
    if edited_ok:
        return True, "📤 <b>Mijoz guruhidagi kvitansiya yangilandi!</b>"
    return False, "⚠️ Guruhga xabar yuborib bo'lmadi."


def _build_items_spec(
    raw_items: Sequence[Dict[str, Any]],
    products: Sequence[Product],
) -> List[Dict[str, Any]]:
    """Map AI-extracted product hints to active Product records and aggregate identical products."""
    if not products:
        return []
    merged: Dict[int, Dict[str, Any]] = {}
    for entry in raw_items:
        w = float(entry.get("weight_kg") or 0.0)
        if w <= 0:
            continue
        prod = match_product(entry.get("product_hint"), products) or products[0]
        bd = entry.get("weights_breakdown") or []
        bd_parts = [format_kg(x) for x in bd if isinstance(x, (int, float)) and x > 0]
        bd_str = " + ".join(bd_parts) if len(bd_parts) > 1 else ""

        if prod.id in merged:
            prev = merged[prod.id]
            prev["weight_kg"] = round(prev["weight_kg"] + w, 3)
            if bd_str or prev["weights_detail"]:
                left = prev["weights_detail"] or format_kg(prev["weight_kg"] - w)
                right = bd_str or format_kg(w)
                prev["weights_detail"] = f"{left} + {right}"
        else:
            merged[prod.id] = {
                "product": prod,
                "weight_kg": round(w, 3),
                "weights_detail": bd_str,
            }
    return list(merged.values())


async def _process_ready_sale(
    message: Message,
    state: FSMContext,
    client_id: Optional[int],
    items_spec: List[Dict[str, Any]],
    photo_file_id: Optional[str],
    note: str,
    is_confident: bool,
    prefix_html: str = "",
    suggested_client_name: Optional[str] = None,
) -> None:
    """Create pending Sale, check duplicates/client match, and auto-post or ask confirmation."""
    was_in_fsm = (await state.get_state()) is not None
    async with async_session_maker() as db:
        auto_confirm = (await get_app_setting(db, "auto_confirm", "on")) == "on"
        round_mode = await get_app_setting(db, "round_mode", "none")

        # Optional total rounding on unit price/line if configured
        if round_mode != "none":
            for spec in items_spec:
                prod = spec["product"]
                # Keep custom price resolution intact; round only if user explicitly enabled rounding
                from database.crud import resolve_sell_price
                unit_p = await resolve_sell_price(db, client_id, prod)
                line_t = round_amount(spec["weight_kg"] * unit_p, round_mode)
                if spec["weight_kg"] > 0 and line_t > 0:
                    spec["unit_sell_price"] = round(line_t / spec["weight_kg"], 2)

        sale = await create_pending_sale(
            db,
            client_id=client_id,
            items_spec=items_spec,
            photo_file_id=photo_file_id,
            note=note,
            source_channel="dm",
        )
        dup = await find_duplicate_confirmed_sale(
            db, sale.session_id, client_id, sale.total_weight_kg, exclude_id=sale.id
        )
        clients = await list_clients(db, active_only=True)

        # If client is missing, do not auto-confirm — ask user to pick client!
        if client_id is None:
            await state.clear()
            clean_suggested = (suggested_client_name or "").strip() or None
            if clean_suggested:
                _PENDING_SALE_SUGGESTED_CLIENT[sale.id] = clean_suggested
                pick_prompt = (
                    f"🏷 Rasm tagidagi nom: <b>{html.escape(clean_suggested)}</b> (bazada topilmadi)\n"
                    "🏪 Uni yangi mijoz qilib qo'shing yoki mavjud mijozni tanlang:"
                )
            else:
                pick_prompt = "🏪 <b>Bu chek qaysi mijozga (do'konga) tegishli?</b> Tanlang:"
            if was_in_fsm:
                await message.answer("🔍 Hisob tayyor!", reply_markup=main_menu_keyboard())
            await message.answer(
                f"{prefix_html}"
                f"{render_sale_admin_summary(sale)}\n\n"
                f"{pick_prompt}",
                parse_mode="HTML",
                reply_markup=pick_client_for_sale_kb(
                    sale.id,
                    clients,
                    prefix="sale:setcli",
                    suggested_name=clean_suggested,
                ),
            )
            return

        if auto_confirm and is_confident and dup is None:
            sale = await confirm_sale(db, sale.id)  # type: ignore[assignment]
            debt = await compute_client_debt(db, client_id, history_limit=1)
        else:
            debt = None

    await state.clear()

    if auto_confirm and is_confident and dup is None and debt is not None:
        posted, group_notice = await _post_sale_to_client_group(
            message.bot, sale, debt.current_debt
        )
        if was_in_fsm:
            await message.answer("⚡ Avto-tasdiqlandi!", reply_markup=main_menu_keyboard())
        await message.answer(
            f"{prefix_html}"
            f"⚡ <b>Avto-tasdiqlandi!</b>\n"
            f"{render_sale_admin_summary(sale, debt.current_debt)}\n"
            f"{group_notice}",
            parse_mode="HTML",
            reply_markup=auto_confirmed_sale_kb(sale, sent_to_group=posted),
        )
        return

    dup_warn = ""
    if dup is not None:
        dup_warn = (
            f"\n\n⚠️ <b>DIQQAT (Dublikat ehtimoli):</b> Bugun <b>{html.escape(sale.client.name if sale.client else '')}</b> "
            f"uchun <b>{format_kg(dup.total_weight_kg)} kg</b> allaqachon tasdiqlangan!"
        )
    if was_in_fsm:
        await message.answer("🔍 Tekshirib tasdiqlang:", reply_markup=main_menu_keyboard())
    await message.answer(
        f"{prefix_html}"
        f"{render_sale_admin_summary(sale)}{dup_warn}\n\n"
        "Hammasi to'g'rimi?",
        parse_mode="HTML",
        reply_markup=sale_confirm_kb(sale),
    )


# ---------------------------------------------------------------------------
# Menu Button: 🥩 Sotuv qo'shish & Photo Processing
# ---------------------------------------------------------------------------


@router.message(F.text == BTN_ADD_SALE, F.chat.type == "private")
async def handle_add_sale_btn(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    await state.clear()
    warn_prev = ""
    async with async_session_maker() as db:
        open_sess = await get_open_session(db)
        if open_sess and open_sess.report_date != today_iso():
            warn_prev = (
                f"\n\n⚠️ <i>Eslatma: <code>{open_sess.report_date}</code> smenasi hali yopilmagan "
                "(avval «🏁 Kunni yakunlash» ni bosishingiz mumkin).</i>"
            )
    await state.set_state(SaleStates.waiting_sale_input)
    await message.answer(
        "🥩 <b>Yangi Norin Sotuvi</b>\n\n"
        "Quyidagilardan birini yuboring:\n"
        "• 📸 <b>Tarozi / do'kon cheki rasmi</b> (AI faqat KG ni o'qiydi, chekdagi do'kon narxiga qaramaydi!)\n"
        "• 🎤 <b>Ovozli xabar</b>: <i>«Iftiqor 80 notin ot 25 kg»</i>\n"
        "• ✍️ <b>Matn</b>: <i>«Iftiqor ot 12.5 kg mol 8 kg»</i>"
        f"{warn_prev}",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await message.answer(
        "Yoki qaytarilgan mahsulot (Vozvrat) kiritish:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="↩️ Vozvrat qayd etish", callback_data="ret:pick_cli")]
            ]
        ),
    )


async def _process_dm_photo(message: Message, state: FSMContext) -> None:
    """Process a scale receipt photo sent in private chat."""
    wait_msg = await message.answer("🔍 Chekdagi KG miqdori va go'sht turi o'qilmoqda...")
    photo = message.photo[-1]
    buf = io.BytesIO()
    await message.bot.download(photo, destination=buf)

    async with async_session_maker() as db:
        products = await list_products(db, active_only=True)
        clients = await list_clients(db, active_only=True)

    cap_cli, cap_hint = extract_caption_client_override(message.caption, products, clients)

    extracted = await extract_norin_from_image(
        image_bytes=buf.getvalue(),
        products=products,
        clients=clients,
        mime_type="image/jpeg",
        caption=message.caption,
    )
    try:
        await wait_msg.delete()
    except Exception:
        pass

    items_spec = _build_items_spec(extracted.get("items") or [], products)
    if cap_cli is not None:
        client_obj = cap_cli
        suggested_name: Optional[str] = None
        caption_prefix = (
            f"🏷 <i>Rasm tagidagi nom olindi:</i> <b>{html.escape(cap_cli.name)}</b>\n\n"
        )
    elif cap_hint:
        client_obj = None
        suggested_name = cap_hint
        caption_prefix = ""
    else:
        client_obj = match_client(extracted.get("client_hint"), clients)
        suggested_name = None
        caption_prefix = ""

    is_clear = bool(extracted.get("is_clear")) and len(items_spec) > 0

    if items_spec:
        await _process_ready_sale(
            message=message,
            state=state,
            client_id=client_obj.id if client_obj else None,
            items_spec=items_spec,
            photo_file_id=photo.file_id,
            note=extracted.get("notes") or "",
            is_confident=is_clear,
            prefix_html=caption_prefix,
            suggested_client_name=suggested_name,
        )
        return

    # Could not read any kg from photo -> ask clarification
    await state.set_state(SaleStates.waiting_sale_clarify)
    await state.update_data(
        clarify_photo_id=photo.file_id,
        clarify_client_id=client_obj.id if client_obj else None,
        clarify_client_hint=suggested_name,
    )
    await message.answer(
        "🤔 Rasmdan KG miqdori aniq o'qilmadi.\n"
        "🎤 Iltimos, ovozda yoki matnda yozing (masalan: <i>«Iftiqor ot 25 kg»</i>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )


@router.message(
    SaleStates.waiting_sale_clarify,
    F.chat.type == "private",
    (~F.text) | (~F.text.startswith("/") & ~F.text.in_(MAIN_MENU_BUTTONS) & (F.text != "❌ Bekor qilish")),
)
async def process_sale_clarify(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    data = await state.get_data()
    photo_id = data.get("clarify_photo_id")
    preset_client_id = data.get("clarify_client_id")
    preset_client_hint = data.get("clarify_client_hint")

    async with async_session_maker() as db:
        products = await list_products(db, active_only=True)
        clients = await list_clients(db, active_only=True)

    if message.voice or message.audio:
        file_obj = message.voice or message.audio
        if (getattr(file_obj, "duration", 0) or 0) > 90:
            await message.answer("⚠️ Ovozli xabar 90 soniyadan oshmasligi kerak (qisqaroq ayting).")
            return
        audio_bytes, mime = await _download_voice_bytes(message)
        parsed = await parse_norin_voice_or_text(
            products, clients, audio_bytes=audio_bytes, mime_type=mime
        )
    elif message.text:
        parsed = await parse_norin_voice_or_text(products, clients, text=message.text)
    else:
        await message.answer("⚠️ Ovoz yoki matn yuboring (masalan: «Iftiqor ot 25 kg»):")
        return

    raw_items = parsed.get("items") or []
    if not raw_items and parsed.get("amount"):
        # User wrote just a number like "25"
        w = parse_weight_kg(str(parsed["amount"]))
        if w and w < 5000:
            raw_items = [{"product_hint": "norin", "weight_kg": w, "weights_breakdown": []}]

    items_spec = _build_items_spec(raw_items, products)
    if not items_spec:
        await message.answer("⚠️ KG miqdori topilmadi. Masalan: <code>Iftiqor ot 25 kg</code> deb yozing:", parse_mode="HTML")
        return

    cli = match_client(parsed.get("client_hint"), clients)
    cid = cli.id if cli else preset_client_id
    suggested_hint = None if cid else (parsed.get("client_hint") or preset_client_hint)
    await _process_ready_sale(
        message=message,
        state=state,
        client_id=cid,
        items_spec=items_spec,
        photo_file_id=photo_id,
        note=parsed.get("transcript") or "",
        is_confident=False,
        suggested_client_name=suggested_hint,
    )


# ---------------------------------------------------------------------------
# Sale Confirmation, Client Binding, Group Posting, Edit & Delete
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("sale:pick_cli:"))
async def cb_sale_pick_client(cb: CallbackQuery) -> None:
    sale_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        clients = await list_clients(db, active_only=True)
    await cb.message.edit_reply_markup(
        reply_markup=pick_client_for_sale_kb(
            sale_id,
            clients,
            prefix="sale:setcli",
            page=0,
            suggested_name=_PENDING_SALE_SUGGESTED_CLIENT.get(sale_id),
            back_cb=f"sale:back_card:{sale_id}",
        )
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sale:pcli:"))
async def cb_sale_pick_client_page(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    sale_id = int(parts[2])
    page = int(parts[3])
    async with async_session_maker() as db:
        sale = await get_sale(db, sale_id)
        clients = await list_clients(db, active_only=True)
    has_card = bool(sale and (sale.status == "confirmed" or sale.client_id is not None))
    await cb.message.edit_reply_markup(
        reply_markup=pick_client_for_sale_kb(
            sale_id,
            clients,
            prefix="sale:setcli",
            page=page,
            suggested_name=_PENDING_SALE_SUGGESTED_CLIENT.get(sale_id) if page == 0 else None,
            back_cb=f"sale:back_card:{sale_id}" if has_card else None,
        )
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sale:newcli_cap:"))
async def cb_sale_newcli_from_caption(cb: CallbackQuery) -> None:
    sale_id = int(cb.data.split(":")[-1])
    suggested_name = _PENDING_SALE_SUGGESTED_CLIENT.pop(sale_id, None)
    if not suggested_name:
        await cb.answer(
            "⚠️ Taklif qilingan nom topilmadi, «➕ Yangi mijoz qo'shish» ni bosing.",
            show_alert=True,
        )
        return

    async with async_session_maker() as db:
        before = await get_sale(db, sale_id)
        if not before or before.status == "deleted":
            await cb.answer("Sotuv topilmadi", show_alert=True)
            return
        existing_clients = await list_clients(db, active_only=True)
        exact = next(
            (c for c in existing_clients if c.name.strip().lower() == suggested_name.strip().lower()),
            None,
        )
        cli = exact if exact is not None else await create_client(db, name=suggested_name.strip())
        sale = await update_sale_client(db, sale_id, cli.id)
        if not sale:
            await cb.answer("Sotuv topilmadi", show_alert=True)
            return
        debt = await compute_client_debt(db, cli.id, history_limit=1)

    header = (
        f"✅ <b>«{html.escape(cli.name)}»</b> hisobga ulandi!\n\n"
        if exact is not None
        else f"🆕 <b>«{html.escape(cli.name)}»</b> yangi mijoz qilib yaratildi va hisobga ulandi!\n\n"
    )
    await cb.message.edit_text(
        f"{header}{render_sale_admin_summary(sale, debt.current_debt)}\n\nHammasi to'g'rimi?",
        parse_mode="HTML",
        reply_markup=sale_confirm_kb(sale),
    )
    await cb.answer(f"✅ «{cli.name}» saqlandi!")


@router.callback_query(F.data.startswith("sale:back_card:"))
async def cb_sale_back_card(cb: CallbackQuery) -> None:
    sale_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        sale = await get_sale(db, sale_id)
        if not sale or sale.status == "deleted":
            await cb.answer("Topilmadi", show_alert=True)
            return
        debt = (
            await compute_client_debt(db, sale.client_id, history_limit=1)
            if sale.client_id
            else None
        )
    if sale.status == "confirmed":
        await cb.message.edit_text(
            render_sale_admin_summary(sale, debt.current_debt if debt else None),
            parse_mode="HTML",
            reply_markup=confirmed_sale_edit_kb(sale),
        )
    else:
        await cb.message.edit_text(
            f"{render_sale_admin_summary(sale)}\n\nTasdiqlaysizmi?",
            parse_mode="HTML",
            reply_markup=sale_confirm_kb(sale),
        )
    await cb.answer()


@router.callback_query(F.data.startswith("sale:edit_prod:"))
async def cb_sale_edit_product_menu(cb: CallbackQuery) -> None:
    item_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        item = await db.get(SaleItem, item_id)
        sale = await get_sale(db, item.sale_id) if item else None
        if not item or not sale or sale.status == "deleted":
            await cb.answer("Topilmadi", show_alert=True)
            return
        products = await list_products(db, active_only=True)
    back_cb = f"sale_view:{sale.id}" if sale.status == "confirmed" else f"sale:back_card:{sale.id}"
    await cb.message.edit_text(
        f"🥩 <b>{html.escape(item.product_name)}</b> ({format_kg(item.weight_kg)} kg) o'rniga qaysi mahsulotni qo'yamiz?",
        parse_mode="HTML",
        reply_markup=pick_product_for_item_kb(item_id, products, back_cb=back_cb),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sale:set_prod:"))
async def cb_sale_set_product(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    item_id = int(parts[2])
    new_pid = int(parts[3])
    async with async_session_maker() as db:
        old_item = await db.get(SaleItem, item_id)
        old_sale = await get_sale(db, old_item.sale_id) if old_item else None
        if not old_item or not old_sale or old_sale.status == "deleted":
            await cb.answer("Topilmadi", show_alert=True)
            return
        old_name = old_item.product_name
        old_total = float(old_sale.total_amount)
        prod = await get_product(db, new_pid)
        if not prod:
            await cb.answer("Mahsulot topilmadi", show_alert=True)
            return
        sale = await update_sale_item(db, item_id, product_id=new_pid)
        if not sale:
            await cb.answer("Topilmadi", show_alert=True)
            return
        debt = (
            await compute_client_debt(db, sale.client_id, history_limit=1)
            if sale.client_id
            else None
        )
    if sale.status == "confirmed":
        change_line = (
            f"🥩 Mahsulot: <s>{html.escape(old_name)}</s> → <b>{html.escape(prod.name)}</b>\n"
            f"💰 Summa: <s>{format_uzs(old_total)}</s> → <b>{format_uzs(sale.total_amount)} so'm</b>"
        )
        _, sync_msg = await _sync_sale_group_message(
            cb.bot,
            sale,
            debt.current_debt if debt else 0.0,
            tag="✏️ [MAHSULOT O'ZGARDI]",
            change_line=change_line,
        )
        await cb.message.edit_text(
            f"✅ Mahsulot almashtirildi!\n{render_sale_admin_summary(sale, debt.current_debt if debt else None)}\n{sync_msg}",
            parse_mode="HTML",
            reply_markup=confirmed_sale_edit_kb(sale),
        )
    else:
        await cb.message.edit_text(
            f"✅ Mahsulot yangilandi!\n{render_sale_admin_summary(sale)}\n\nTasdiqlaysizmi?",
            parse_mode="HTML",
            reply_markup=sale_confirm_kb(sale),
        )
    await cb.answer("✅ Almashtirildi!")


@router.callback_query(F.data.startswith("sale:quick_pay:"))
async def cb_sale_quick_pay_menu(cb: CallbackQuery) -> None:
    sale_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        sale = await get_sale(db, sale_id)
        if not sale or not sale.client_id or sale.status == "deleted":
            await cb.answer("Avval mijozni tanlang!", show_alert=True)
            return
        debt = await compute_client_debt(db, sale.client_id, history_limit=1)
    await cb.message.edit_text(
        f"💵 <b>Tezkor To'lov — {html.escape(debt.client.name)}</b>\n"
        f"🧾 Sotuv #{sale.id}: <b>{format_uzs(sale.total_amount)} so'm</b>\n"
        f"💳 Hozirgi jami qarz: <b>{format_uzs(debt.current_debt)} so'm</b>\n\n"
        "To'lov usulini tanlang:",
        parse_mode="HTML",
        reply_markup=quick_sale_payment_kb(sale),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sale:qpay_do:"))
async def cb_sale_quick_pay_execute(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    sale_id = int(parts[2])
    method = parts[3]
    async with async_session_maker() as db:
        sale = await get_sale(db, sale_id)
        if not sale or not sale.client_id or sale.status == "deleted":
            await cb.answer("Topilmadi", show_alert=True)
            return
        pay = await add_client_payment(
            db,
            client_id=sale.client_id,
            amount=float(sale.total_amount),
            payment_method=method,
            note=f"Sotuv #{sale.id} to'lovi",
        )
        debt = await compute_client_debt(db, sale.client_id, history_limit=1)
    await cb.message.edit_text(
        f"✅ <b>To'lov qabul qilindi!</b>\n"
        f"{render_payment_group_receipt(pay, debt.current_debt)}",
        parse_mode="HTML",
        reply_markup=payment_after_record_kb(pay.id, has_group=bool(debt.client.group_chat_id)),
    )
    await cb.answer("✅ Saqlandi!")


@router.callback_query(F.data.startswith("sale:setcli:"))
async def cb_sale_set_client(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    sale_id = int(parts[2])
    client_id = int(parts[3])
    async with async_session_maker() as db:
        before = await get_sale(db, sale_id)
        if not before or before.status == "deleted":
            await cb.answer("Sotuv topilmadi", show_alert=True)
            return
        old_client_id = before.client_id
        old_group_chat_id = before.group_chat_id
        old_group_message_id = before.group_message_id
        old_total = before.total_amount
        old_weight = before.total_weight_kg
        old_client_name = before.client.name if before.client else "Oldingi mijoz"

        sale = await update_sale_client(db, sale_id, client_id)
        if not sale:
            await cb.answer("Sotuv topilmadi", show_alert=True)
            return
        debt = await compute_client_debt(db, client_id, history_limit=1)
        old_debt = (
            await compute_client_debt(db, old_client_id, history_limit=1)
            if old_client_id and old_client_id != client_id
            else None
        )

    if sale.status == "confirmed":
        sync_note = ""
        if old_client_id and old_client_id != client_id:
            if old_group_chat_id and old_group_message_id:
                try:
                    await cb.bot.edit_message_caption(
                        chat_id=old_group_chat_id,
                        message_id=old_group_message_id,
                        caption=(
                            f"❌ <b>[BOSHQA MIJOZGA O'TKAZILDI]</b>\n"
                            f"🥩 Hisob #{sale.id} — <s>{html.escape(old_client_name)}</s>\n"
                            f"⚖️ <s>{format_kg(old_weight)} kg</s> | <s>{format_uzs(old_total)} so'm</s>\n"
                            f"💳 Yangilangan qarz qoldig'i: <b>{format_uzs(old_debt.current_debt if old_debt else 0)} so'm</b>"
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    try:
                        await cb.bot.edit_message_text(
                            chat_id=old_group_chat_id,
                            message_id=old_group_message_id,
                            text=(
                                f"❌ <b>[BOSHQA MIJOZGA O'TKAZILDI]</b>\n"
                                f"🥩 Hisob #{sale.id} — <s>{html.escape(old_client_name)}</s>\n"
                                f"💳 Yangilangan qarz qoldig'i: <b>{format_uzs(old_debt.current_debt if old_debt else 0)} so'm</b>"
                            ),
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
            if old_group_chat_id:
                try:
                    await cb.bot.send_message(
                        chat_id=old_group_chat_id,
                        text=(
                            f"🔄 <b>HISOB #{sale.id} BOSHQA MIJOZGA O'TKAZILDI</b>\n"
                            f"💳 Yangilangan qarz qoldig'i: <b>{format_uzs(old_debt.current_debt if old_debt else 0)} so'm</b>"
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
            async with async_session_maker() as db:
                sale = await set_sale_group_message(db, sale.id, None, None)  # type: ignore[assignment]
            _, sync_note = await _post_sale_to_client_group(cb.bot, sale, debt.current_debt)
        else:
            change_line = f"🏪 Mijoz: <b>{html.escape(sale.client.name if sale.client else '')}</b>\n💰 Summa: <b>{format_uzs(sale.total_amount)} so'm</b>"
            _, sync_note = await _sync_sale_group_message(
                cb.bot, sale, debt.current_debt, tag="✏️ [MIJOZ YANGILANDI]", change_line=change_line
            )

        await cb.message.edit_text(
            f"{render_sale_admin_summary(sale, debt.current_debt)}\n{sync_note}",
            parse_mode="HTML",
            reply_markup=confirmed_sale_edit_kb(sale),
        )
    else:
        await cb.message.edit_text(
            f"{render_sale_admin_summary(sale)}\n\nMijoz narxi bo'yicha hisoblandi. Tasdiqlaysizmi?",
            parse_mode="HTML",
            reply_markup=sale_confirm_kb(sale),
        )
    await cb.answer("✅ Mijoz tanlandi!")


@router.callback_query(F.data.startswith("sale:confirm:"))
async def cb_sale_confirm(cb: CallbackQuery) -> None:
    sale_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        sale = await confirm_sale(db, sale_id)
        if not sale:
            await cb.answer("Topilmadi", show_alert=True)
            return
        debt = (
            await compute_client_debt(db, sale.client_id, history_limit=1)
            if sale.client_id
            else None
        )

    posted, grp_msg = await _post_sale_to_client_group(
        cb.bot, sale, debt.current_debt if debt else 0.0
    )
    await cb.message.edit_text(
        f"✅ <b>Tasdiqlandi!</b>\n"
        f"{render_sale_admin_summary(sale, debt.current_debt if debt else None)}\n"
        f"{grp_msg}",
        parse_mode="HTML",
        reply_markup=auto_confirmed_sale_kb(sale, sent_to_group=posted),
    )
    await cb.answer("✅ Tasdiqlandi!")


@router.callback_query(F.data.startswith("sale:save_only:"))
async def cb_sale_save_only(cb: CallbackQuery) -> None:
    sale_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        sale = await confirm_sale(db, sale_id)
        if not sale:
            await cb.answer("Topilmadi", show_alert=True)
            return
        debt = (
            await compute_client_debt(db, sale.client_id, history_limit=1)
            if sale.client_id
            else None
        )
    await cb.message.edit_text(
        f"⏭ <b>Faqat bazaga saqlandi!</b>\n"
        f"{render_sale_admin_summary(sale, debt.current_debt if debt else None)}",
        parse_mode="HTML",
        reply_markup=auto_confirmed_sale_kb(sale, sent_to_group=False),
    )
    await cb.answer("✅ Bazaga saqlandi")


@router.callback_query(F.data.startswith("sale:repost_group:"))
async def cb_sale_repost_group(cb: CallbackQuery) -> None:
    sale_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        sale = await get_sale(db, sale_id)
        if not sale or sale.status != "confirmed":
            await cb.answer("Topilmadi", show_alert=True)
            return
        debt = (
            await compute_client_debt(db, sale.client_id, history_limit=1)
            if sale.client_id
            else None
        )
    posted, grp_msg = await _post_sale_to_client_group(
        cb.bot, sale, debt.current_debt if debt else 0.0
    )
    await cb.message.edit_text(
        f"{render_sale_admin_summary(sale, debt.current_debt if debt else None)}\n{grp_msg}",
        parse_mode="HTML",
        reply_markup=auto_confirmed_sale_kb(sale, sent_to_group=posted),
    )
    await cb.answer("📤 Yuborildi!")


@router.callback_query(F.data.startswith("sale:unpost_group:"))
async def cb_sale_unpost_group(cb: CallbackQuery) -> None:
    sale_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        sale = await get_sale(db, sale_id)
        if not sale or sale.status == "deleted":
            await cb.answer("Topilmadi", show_alert=True)
            return
        old_chat = sale.group_chat_id
        old_msg = sale.group_message_id
        sale = await set_sale_group_message(db, sale.id, None, None)  # type: ignore[assignment]
        debt = (
            await compute_client_debt(db, sale.client_id, history_limit=1)
            if sale.client_id
            else None
        )
    if old_chat and old_msg:
        try:
            await cb.bot.delete_message(chat_id=old_chat, message_id=old_msg)
        except Exception:
            pass
    await cb.message.edit_text(
        f"{render_sale_admin_summary(sale, debt.current_debt if debt else None)}\n"
        "🙈 <i>(Guruhdan olib tashlandi — bazada saqlangan)</i>",
        parse_mode="HTML",
        reply_markup=auto_confirmed_sale_kb(sale, sent_to_group=False),
    )
    await cb.answer("Guruhdan olindi")


@router.callback_query(F.data.startswith("sale:done:"))
async def cb_sale_done(cb: CallbackQuery) -> None:
    sale_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        sale = await get_sale(db, sale_id)
        if not sale:
            await cb.answer("Topilmadi", show_alert=True)
            return
        debt = (
            await compute_client_debt(db, sale.client_id, history_limit=1)
            if sale.client_id
            else None
        )
    where = "📤 Mijoz guruhiga yuborilgan" if sale.group_message_id else "💾 Faqat bazada"
    await cb.message.edit_text(
        f"✅ <b>Saqlandi!</b> ({where})\n"
        f"{render_sale_admin_summary(sale, debt.current_debt if debt else None)}",
        parse_mode="HTML",
        reply_markup=None,
    )
    await cb.answer("✅ Tayyor!")


@router.callback_query(F.data.startswith("sale:cancel:"))
async def cb_sale_cancel(cb: CallbackQuery) -> None:
    sale_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        sale = await get_sale(db, sale_id)
        if not sale or sale.status == "deleted":
            await cb.answer("Sotuv topilmadi", show_alert=True)
            return
        if sale.status == "confirmed":
            await cb.message.edit_text(
                f"⚠️ <b>Sotuv #{sale.id}</b> ({format_kg(sale.total_weight_kg)} kg — {format_uzs(sale.total_amount)} so'm) "
                "allaqachon tasdiqlangan!\nRostdan ham o'chirasizmi?",
                parse_mode="HTML",
                reply_markup=confirm_delete_kb(f"sale:delete_ok:{sale_id}", f"sale_view:{sale_id}"),
            )
            await cb.answer()
            return
        await delete_sale(db, sale_id)
    await cb.message.edit_text("❌ Sotuv bekor qilindi (hisobga olinmadi).", reply_markup=None)
    await cb.answer("Bekor qilindi")


@router.callback_query(F.data.startswith("sale:delete_conf:"))
async def cb_sale_delete_prompt(cb: CallbackQuery) -> None:
    sale_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        sale = await get_sale(db, sale_id)
    if not sale or sale.status == "deleted":
        await cb.answer("Topilmadi", show_alert=True)
        return
    await cb.message.edit_text(
        f"⚠️ <b>Sotuv #{sale.id}</b> ({format_kg(sale.total_weight_kg)} kg — {format_uzs(sale.total_amount)} so'm) "
        "rostdan ham o'chirasizmi?",
        parse_mode="HTML",
        reply_markup=confirm_delete_kb(f"sale:delete_ok:{sale_id}", f"sale_view:{sale_id}"),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sale:delete_ok:"))
async def cb_sale_delete_confirmed(cb: CallbackQuery) -> None:
    sale_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        sale = await delete_sale(db, sale_id)
        if not sale:
            await cb.answer("Topilmadi", show_alert=True)
            return
        debt = (
            await compute_client_debt(db, sale.client_id, history_limit=1)
            if sale.client_id
            else None
        )
    change_line = (
        f"⚖️ <s>{format_kg(sale.total_weight_kg)} kg</s> | "
        f"💰 <s>{format_uzs(sale.total_amount)} so'm</s> bekor qilindi"
    )
    _, sync_msg = await _sync_sale_group_message(
        cb.bot, sale, debt.current_debt if debt else 0.0, change_line=change_line
    )
    await cb.message.edit_text(
        f"🗑 Sotuv #{sale.id} ({format_kg(sale.total_weight_kg)} kg — {format_uzs(sale.total_amount)} so'm) o'chirildi!\n{sync_msg}",
        parse_mode="HTML",
    )
    await cb.answer("🗑 O'chirildi!")


@router.callback_query(F.data.startswith("sale:edit_w:"))
async def cb_sale_edit_weight_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    item_id = int(cb.data.split(":")[-1])
    await state.set_state(SaleStates.waiting_edit_item_weight)
    await state.update_data(item_id=item_id)
    await cb.message.answer(
        "⚖️ Yangi KG miqdorini kiriting (masalan: <code>24.5</code> yoki <code>8.25 + 9.1 + 7.65</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(
    SaleStates.waiting_edit_item_weight,
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
    F.text != "❌ Bekor qilish",
)
async def process_sale_edit_weight(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    txt = (message.text or "").strip()
    new_w = parse_weight_kg(txt)
    if not new_w or new_w <= 0:
        await message.answer("⚠️ To'g'ri kg kiriting (masalan: <code>25</code> yoki <code>12.5</code>):", parse_mode="HTML")
        return
    item_id = (await state.get_data())["item_id"]
    bd_detail = txt if "+" in txt else ""
    async with async_session_maker() as db:
        old_item = await db.get(SaleItem, item_id)
        old_sale = await get_sale(db, old_item.sale_id) if old_item else None
        old_kg = float(old_item.weight_kg) if old_item else 0.0
        old_total = float(old_sale.total_amount) if old_sale else 0.0
        prod_name = old_item.product_name if old_item else "Norin"

        sale = await update_sale_item(
            db, item_id, weight_kg=new_w, weights_detail=bd_detail
        )
        if not sale:
            await state.clear()
            await message.answer("⚠️ Topilmadi.", reply_markup=main_menu_keyboard())
            return
        debt = (
            await compute_client_debt(db, sale.client_id, history_limit=1)
            if sale.client_id
            else None
        )
    await state.clear()
    if sale.status == "confirmed":
        change_line = (
            f"⚖️ {html.escape(prod_name)}: <s>{format_kg(old_kg)} kg</s> → <b>{format_kg(new_w)} kg</b>\n"
            f"💰 Summa: <s>{format_uzs(old_total)}</s> → <b>{format_uzs(sale.total_amount)} so'm</b>"
        )
        _, sync_msg = await _sync_sale_group_message(
            message.bot,
            sale,
            debt.current_debt if debt else 0.0,
            tag="✏️ [KG TAHRIRLANDI]",
            change_line=change_line,
        )
        await message.answer("✅ Vazn yangilandi!", reply_markup=main_menu_keyboard())
        await message.answer(
            f"{render_sale_admin_summary(sale, debt.current_debt if debt else None)}\n{sync_msg}",
            parse_mode="HTML",
            reply_markup=confirmed_sale_edit_kb(sale),
        )
    else:
        await message.answer("✅ Vazn yangilandi!", reply_markup=main_menu_keyboard())
        await message.answer(
            f"{render_sale_admin_summary(sale)}\n\nTasdiqlaysizmi?",
            parse_mode="HTML",
            reply_markup=sale_confirm_kb(sale),
        )


@router.callback_query(F.data.startswith("sale:edit_p:"))
async def cb_sale_edit_price_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    item_id = int(cb.data.split(":")[-1])
    await state.set_state(SaleStates.waiting_edit_item_price)
    await state.update_data(item_id=item_id)
    await cb.message.answer(
        "💰 Ushbu sotuv uchun yangi 1 kg narxini kiriting (masalan: <code>112 000</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(
    SaleStates.waiting_edit_item_price,
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
    F.text != "❌ Bekor qilish",
)
async def process_sale_edit_price(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    new_p = parse_uzbek_amount(message.text or "")
    if not new_p or new_p <= 0:
        await message.answer("⚠️ To'g'ri narx kiriting:")
        return
    item_id = (await state.get_data())["item_id"]
    async with async_session_maker() as db:
        old_item = await db.get(SaleItem, item_id)
        old_sale = await get_sale(db, old_item.sale_id) if old_item else None
        old_price = float(old_item.unit_sell_price) if old_item else 0.0
        old_total = float(old_sale.total_amount) if old_sale else 0.0
        prod_name = old_item.product_name if old_item else "Norin"

        sale = await update_sale_item(db, item_id, unit_sell_price=new_p)
        if not sale:
            await state.clear()
            await message.answer("⚠️ Topilmadi.", reply_markup=main_menu_keyboard())
            return
        debt = (
            await compute_client_debt(db, sale.client_id, history_limit=1)
            if sale.client_id
            else None
        )
    await state.clear()
    if sale.status == "confirmed":
        change_line = (
            f"💵 Narx ({html.escape(prod_name)}): <s>{format_uzs(old_price)}</s> → <b>{format_uzs(new_p)} so'm/kg</b>\n"
            f"💰 Summa: <s>{format_uzs(old_total)}</s> → <b>{format_uzs(sale.total_amount)} so'm</b>"
        )
        _, sync_msg = await _sync_sale_group_message(
            message.bot,
            sale,
            debt.current_debt if debt else 0.0,
            tag="✏️ [NARX TAHRIRLANDI]",
            change_line=change_line,
        )
        await message.answer("✅ Narx yangilandi!", reply_markup=main_menu_keyboard())
        await message.answer(
            f"{render_sale_admin_summary(sale, debt.current_debt if debt else None)}\n{sync_msg}",
            parse_mode="HTML",
            reply_markup=confirmed_sale_edit_kb(sale),
        )
    else:
        await message.answer("✅ Narx yangilandi!", reply_markup=main_menu_keyboard())
        await message.answer(
            f"{render_sale_admin_summary(sale)}\n\nTasdiqlaysizmi?",
            parse_mode="HTML",
            reply_markup=sale_confirm_kb(sale),
        )


# ---------------------------------------------------------------------------
# Client Payments (💵 Pul oldim (Mijoz))
# ---------------------------------------------------------------------------


@router.message(F.text == BTN_CLIENT_PAY, F.chat.type == "private")
async def handle_client_pay_btn(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    await state.clear()
    async with async_session_maker() as db:
        clients = await list_clients(db, active_only=True)
    if not clients:
        await message.answer("ℹ️ Avval Sozlamalar → Mijozlar bo'limidan mijoz qo'shing.")
        return
    await send_inline_panel(
        message,
        "💵 <b>Qaysi mijozdan pul oldingiz?</b>\nMijozni tanlang (yoki ovoz/matnda <i>«Iftiqordan 2 mln karta oldim»</i> deb yuboring):",
        reply_markup=pick_client_for_payment_kb(clients, page=0),
        delete_prev=True,
    )


@router.callback_query(F.data == "pay:pick_list")
async def cb_pay_pick_list(cb: CallbackQuery) -> None:
    async with async_session_maker() as db:
        clients = await list_clients(db, active_only=True)
    await cb.message.edit_text(
        "💵 <b>Qaysi mijozdan pul oldingiz?</b>\nMijozni tanlang:",
        parse_mode="HTML",
        reply_markup=pick_client_for_payment_kb(clients, page=0),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("pay:list:p:"))
async def cb_pay_clients_page(cb: CallbackQuery) -> None:
    page = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        clients = await list_clients(db, active_only=True)
    await cb.message.edit_reply_markup(reply_markup=pick_client_for_payment_kb(clients, page=page))
    await cb.answer()


@router.callback_query(F.data.startswith("pay:cli:"))
async def cb_pay_pick_client(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        debt = await compute_client_debt(db, cid, history_limit=1)
    await cb.message.edit_text(
        f"🏪 Mijoz: <b>{html.escape(debt.client.name)}</b>\n"
        f"💳 Hozirgi qarz: <b>{format_uzs(debt.current_debt)} so'm</b>\n\n"
        "To'lov usulini tanlang:",
        parse_mode="HTML",
        reply_markup=payment_method_kb(cid, back_cb="pay:pick_list"),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("pay:meth:"))
async def cb_pay_pick_method(cb: CallbackQuery, state: FSMContext) -> None:
    parts = cb.data.split(":")
    cid = int(parts[2])
    method = parts[3]
    await state.set_state(SaleStates.waiting_client_payment_amount)
    await state.update_data(pay_client_id=cid, pay_method=method)
    await cb.message.answer(
        "💰 Qancha pul oldingiz? Summani yozing yoki ovozda ayting (masalan: <code>2 500 000</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(
    SaleStates.waiting_client_payment_amount,
    F.chat.type == "private",
    (~F.text) | (~F.text.startswith("/") & ~F.text.in_(MAIN_MENU_BUTTONS) & (F.text != "❌ Bekor qilish")),
)
async def process_client_payment_amount(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    amount: Optional[float] = None
    note = ""
    if message.voice or message.audio:
        file_obj = message.voice or message.audio
        if (getattr(file_obj, "duration", 0) or 0) > 90:
            await message.answer("⚠️ Ovozli xabar 90 soniyadan oshmasligi kerak (qisqaroq ayting).")
            return
        audio_bytes, mime = await _download_voice_bytes(message)
        amount, note = await extract_amount_from_audio(audio_bytes, mime_type=mime)
    elif message.text:
        amount = parse_uzbek_amount(message.text)
        note = message.text.strip()

    if not amount or amount <= 0:
        await message.answer("⚠️ Summa topilmadi. Raqam kiriting (masalan: <code>2 500 000</code>):", parse_mode="HTML")
        return

    data = await state.get_data()
    cid = data["pay_client_id"]
    method = data.get("pay_method", "cash")
    async with async_session_maker() as db:
        pay = await add_client_payment(db, client_id=cid, amount=amount, payment_method=method, note=note)
        debt = await compute_client_debt(db, cid, history_limit=1)

    await state.clear()
    await message.answer("✅ To'lov qabul qilindi!", reply_markup=main_menu_keyboard())
    await message.answer(
        render_payment_group_receipt(pay, debt.current_debt),
        parse_mode="HTML",
        reply_markup=payment_after_record_kb(pay.id, has_group=bool(debt.client.group_chat_id)),
    )


@router.callback_query(F.data.startswith("pay:post_grp:"))
async def cb_pay_post_group(cb: CallbackQuery) -> None:
    pay_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        pay = await get_client_payment(db, pay_id)
        if not pay or pay.is_deleted:
            await cb.answer("Topilmadi", show_alert=True)
            return
        debt = await compute_client_debt(db, pay.client_id, history_limit=1)
    if not debt.client.group_chat_id:
        await cb.answer("Mijoz guruhi ulanmagan", show_alert=True)
        return
    try:
        sent = await cb.bot.send_message(
            chat_id=debt.client.group_chat_id,
            text=render_payment_group_receipt(pay, debt.current_debt),
            parse_mode="HTML",
        )
        async with async_session_maker() as db:
            await set_client_payment_group_message(db, pay.id, debt.client.group_chat_id, sent.message_id)
        await cb.message.edit_text(
            f"✅ Kvitansiya <b>{html.escape(debt.client.name)}</b> guruhiga yuborildi!\n\n"
            f"{render_payment_group_receipt(pay, debt.current_debt)}",
            parse_mode="HTML",
        )
        await cb.answer("📤 Yuborildi!")
    except Exception as exc:
        await cb.answer(f"❌ Xatolik: {exc}", show_alert=True)


# ---------------------------------------------------------------------------
# Edit Confirmed Sales, Payments & Cash/Expenses (✏️ Tahrirlash)
# ---------------------------------------------------------------------------


@router.message(F.text == BTN_EDIT, F.chat.type == "private")
async def handle_edit_btn(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    await state.clear()
    async with async_session_maker() as db:
        summary = await compute_session_summary(db)
    if (
        not summary.confirmed_sales
        and not summary.client_payments
        and not summary.cash_transactions
        and not summary.returns
    ):
        await message.answer("ℹ️ Bugungi ochiq smenada hali tahrirlanadigan yozuvlar yo'q.")
        return
    await send_inline_panel(
        message,
        "✏️ <b>Bugungi Yozuvlarni Tahrirlash:</b>\n"
        "O'zgartirmoqchi bo'lgan sotuv, to'lov, vozvrat yoki xarajatni tanlang\n"
        "<i>(Sotuv/vozvrat o'zgarsa mijoz guruhidagi xabar ham yangilanadi)</i>:",
        reply_markup=edit_items_list_kb(
            summary.confirmed_sales,
            summary.client_payments,
            summary.cash_transactions,
            returns=summary.returns,
        ),
        delete_prev=True,
    )


@router.callback_query(F.data == "edit_menu:open")
async def cb_edit_menu_open(cb: CallbackQuery) -> None:
    async with async_session_maker() as db:
        summary = await compute_session_summary(db)
    if (
        not summary.confirmed_sales
        and not summary.client_payments
        and not summary.cash_transactions
        and not summary.returns
    ):
        await cb.answer("Bugungi smenada yozuvlar yo'q.", show_alert=True)
        return
    await fast_edit(
        cb,
        "✏️ <b>Bugungi Yozuvlarni Tahrirlash:</b>\nKerakli qatorni tanlang:",
        reply_markup=edit_items_list_kb(
            summary.confirmed_sales,
            summary.client_payments,
            summary.cash_transactions,
            returns=summary.returns,
        ),
    )


@router.callback_query(F.data.startswith("edit_menu:p:"))
async def cb_edit_menu_page(cb: CallbackQuery) -> None:
    page = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        summary = await compute_session_summary(db)
    await asyncio.gather(
        cb.message.edit_reply_markup(
            reply_markup=edit_items_list_kb(
                summary.confirmed_sales,
                summary.client_payments,
                summary.cash_transactions,
                page=page,
                returns=summary.returns,
            )
        ),
        cb.answer(),
        return_exceptions=True,
    )


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


@router.callback_query(F.data.startswith("sale_view:"))
async def cb_sale_edit_view(cb: CallbackQuery) -> None:
    sale_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        sale = await get_sale(db, sale_id)
        if not sale or sale.status == "deleted":
            await cb.answer("Topilmadi", show_alert=True)
            return
        debt = (
            await compute_client_debt(db, sale.client_id, history_limit=1)
            if sale.client_id
            else None
        )
    await cb.message.edit_text(
        render_sale_admin_summary(sale, debt.current_debt if debt else None),
        parse_mode="HTML",
        reply_markup=confirmed_sale_edit_kb(sale),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("pay_view:"))
async def cb_payment_edit_view(cb: CallbackQuery) -> None:
    pay_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        pay = await get_client_payment(db, pay_id)
    if not pay or pay.is_deleted:
        await cb.answer("Topilmadi", show_alert=True)
        return
    cname = pay.client.name if pay.client else f"Mijoz #{pay.client_id}"
    await cb.message.edit_text(
        f"💵 <b>Mijoz To'lovi #{pay.id}</b>\n"
        f"🏪 Mijoz: <b>{html.escape(cname)}</b>\n"
        f"💰 Summa: <b>{format_uzs(pay.amount)} so'm</b>\n"
        f"📝 Izoh: <i>{html.escape(pay.note or '-')}</i>",
        parse_mode="HTML",
        reply_markup=payment_edit_kb(pay.id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("pay:edit_amt:"))
async def cb_pay_edit_amt_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    pay_id = int(cb.data.split(":")[-1])
    await state.set_state(SaleStates.waiting_edit_payment_amount)
    await state.update_data(pay_id=pay_id)
    await cb.message.answer(
        "💰 To'lovning yangi summasini kiriting:",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(
    SaleStates.waiting_edit_payment_amount,
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
    F.text != "❌ Bekor qilish",
)
async def process_pay_edit_amt(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    amt = parse_uzbek_amount(message.text or "")
    if not amt or amt <= 0:
        await message.answer("⚠️ Summa noto'g'ri:")
        return
    pay_id = (await state.get_data())["pay_id"]
    async with async_session_maker() as db:
        old_pay = await get_client_payment(db, pay_id)
        old_amount = float(old_pay.amount) if old_pay else None
        pay = await update_client_payment(db, pay_id, new_amount=amt)
        if not pay:
            await state.clear()
            await message.answer("⚠️ Topilmadi.", reply_markup=main_menu_keyboard())
            return
        debt = await compute_client_debt(db, pay.client_id, history_limit=1)
    await state.clear()
    _, sync_msg = await _sync_payment_group_message(
        message.bot, pay, debt.current_debt, old_amount=old_amount, is_deleted=False
    )
    await message.answer(
        f"✅ To'lov yangilandi: <b>{format_uzs(pay.amount)} so'm</b>\n"
        f"💳 Yangi qarz qoldig'i: <b>{format_uzs(debt.current_debt)} so'm</b>\n"
        f"{sync_msg}",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(F.data.startswith("pay:delete:"))
async def cb_pay_delete_confirm(cb: CallbackQuery) -> None:
    pay_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        pay = await get_client_payment(db, pay_id)
    if not pay or pay.is_deleted:
        await cb.answer("Topilmadi", show_alert=True)
        return
    await cb.message.edit_text(
        f"⚠️ <b>To'lov #{pay.id}</b> ({format_uzs(pay.amount)} so'm) rostdan ham o'chirasizmi?",
        parse_mode="HTML",
        reply_markup=confirm_delete_kb(f"pay:delete_ok:{pay_id}", f"pay_view:{pay_id}"),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("pay:delete_ok:"))
async def cb_pay_delete(cb: CallbackQuery) -> None:
    pay_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        pay = await delete_client_payment(db, pay_id)
        if not pay:
            await cb.answer("Topilmadi", show_alert=True)
            return
        debt = await compute_client_debt(db, pay.client_id, history_limit=1)
    _, sync_msg = await _sync_payment_group_message(
        cb.bot, pay, debt.current_debt, is_deleted=True
    )
    await cb.message.edit_text(
        f"🗑 To'lov ({format_uzs(pay.amount)} so'm) o'chirildi!\n"
        f"💳 Yangilangan qarz: <b>{format_uzs(debt.current_debt)} so'm</b>\n"
        f"{sync_msg}",
        parse_mode="HTML",
    )
    await cb.answer("O'chirildi!")


@router.callback_query(F.data.startswith("cash_view:"))
async def cb_cash_tx_view(cb: CallbackQuery) -> None:
    tx_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        tx = await get_cash_transaction(db, tx_id)
    if not tx or tx.is_deleted:
        await cb.answer("Topilmadi", show_alert=True)
        return
    labels = {
        "main_in": "Asosiy kirim",
        "expense": "Sex xarajati",
        "kassa_debt": "Kassadan qarz",
        "kassa_repay": "Kassaga qaytarish",
    }
    cat_line = f"\n🏷 Kategoriya: <b>{html.escape(tx.category)}</b>" if tx.source_type == "expense" and tx.category else ""
    await cb.message.edit_text(
        f"💵 <b>{labels.get(tx.source_type, tx.source_type)}</b>{cat_line}\n"
        f"💰 Summa: <b>{format_uzs(tx.amount)} so'm</b>\n"
        f"📝 Izoh: <i>{html.escape(tx.note or '-')}</i>",
        parse_mode="HTML",
        reply_markup=cash_tx_edit_kb(tx.id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("cash:edit_amt:"))
async def cb_cash_edit_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    tx_id = int(cb.data.split(":")[-1])
    await state.set_state(WalletStates.waiting_edit_cash_amount)
    await state.update_data(tx_id=tx_id)
    await cb.message.answer("💰 Yangi summani kiriting:", reply_markup=cancel_reply_keyboard())
    await cb.answer()


@router.message(
    WalletStates.waiting_edit_cash_amount,
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
    F.text != "❌ Bekor qilish",
)
async def process_edit_cash_amount(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    amt = parse_uzbek_amount(message.text or "")
    if not amt or amt <= 0:
        await message.answer("⚠️ To'g'ri summa kiriting:")
        return
    tx_id = (await state.get_data())["tx_id"]
    async with async_session_maker() as db:
        tx = await update_cash_transaction(db, tx_id, new_amount=amt)
        if not tx:
            await state.clear()
            await message.answer("⚠️ Topilmadi.", reply_markup=main_menu_keyboard())
            return
        summary = await compute_session_summary(db, tx.session_id)
    await state.clear()
    await message.answer(
        f"✅ Summa yangilandi: <b>{format_uzs(tx.amount)} so'm</b>\n"
        f"💰 Qo'lda qolishi kerak: <b>{format_uzs(summary.expected_cash)} so'm</b>",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(F.data.startswith("cash:delete:"))
async def cb_cash_delete_confirm(cb: CallbackQuery) -> None:
    tx_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        tx = await get_cash_transaction(db, tx_id)
    if not tx or tx.is_deleted:
        await cb.answer("Topilmadi", show_alert=True)
        return
    await cb.message.edit_text(
        f"⚠️ Ushbu kassa/xarajat yozuvini (<b>{format_uzs(tx.amount)} so'm</b>) rostdan ham o'chirasizmi?",
        parse_mode="HTML",
        reply_markup=confirm_delete_kb(f"cash:delete_ok:{tx_id}", f"cash_view:{tx_id}"),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("cash:delete_ok:"))
async def cb_cash_delete(cb: CallbackQuery) -> None:
    tx_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        tx = await delete_cash_transaction(db, tx_id)
        if not tx:
            await cb.answer("Topilmadi", show_alert=True)
            return
        summary = await compute_session_summary(db, tx.session_id)
    await cb.message.edit_text(
        f"🗑 Yozuv ({format_uzs(tx.amount)} so'm) o'chirildi!\n"
        f"💰 Yangilangan kassa qoldig'i: <b>{format_uzs(summary.expected_cash)} so'm</b>",
        parse_mode="HTML",
    )
    await cb.answer("O'chirildi!")


# ---------------------------------------------------------------------------
# Product Returns (Vozvrat / Brak)
# ---------------------------------------------------------------------------


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


@router.callback_query(F.data == "ret:pick_cli")
async def cb_return_pick_client_list(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with async_session_maker() as db:
        clients = await list_clients(db, active_only=True)
    if not clients:
        await cb.answer("Avval mijoz qo'shing!", show_alert=True)
        return
    await fast_edit(
        cb,
        "↩️ <b>Qaytarilgan mahsulot (Vozvrat)</b>\nQaysi mijozdan mahsulot qaytdi?",
        reply_markup=pick_client_for_return_kb(clients, page=0),
    )


@router.callback_query(F.data.startswith("ret:list:p:"))
async def cb_return_clients_page(cb: CallbackQuery) -> None:
    page = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        clients = await list_clients(db, active_only=True)
    await asyncio.gather(
        cb.message.edit_reply_markup(reply_markup=pick_client_for_return_kb(clients, page=page)),
        cb.answer(),
        return_exceptions=True,
    )


@router.callback_query(F.data.startswith("ret:cli:"))
async def cb_return_pick_product(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        cli = await get_client(db, cid)
        if not cli:
            await cb.answer("Mijoz topilmadi", show_alert=True)
            return
        products = await list_products(db, active_only=True)
        custom_map = await get_client_prices_map(db, cid)
    await fast_edit(
        cb,
        f"↩️ <b>Vozvrat — {html.escape(cli.name)}</b>\nQaysi mahsulot qaytarildi?",
        reply_markup=pick_product_for_return_kb(cid, products, custom_map),
    )


@router.callback_query(F.data.startswith("ret:prod:"))
async def cb_return_weight_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    parts = cb.data.split(":")
    cid = int(parts[2])
    pid = int(parts[3])
    async with async_session_maker() as db:
        cli = await get_client(db, cid)
        prod = await get_product(db, pid)
    if not cli or not prod:
        await cb.answer("Topilmadi", show_alert=True)
        return
    await state.set_state(SaleStates.waiting_return_weight)
    await state.update_data(ret_client_id=cid, ret_product_id=pid)
    await cb.message.answer(
        f"↩️ <b>{html.escape(cli.name)}</b> ← <b>{html.escape(prod.name)}</b>\n\n"
        f"Necha <b>{html.escape(prod.unit)}</b> qaytdi? (ixtiyoriy sabab bilan yozing, masalan: <code>2.5</code> yoki <code>2.5 brak</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(
    SaleStates.waiting_return_weight,
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MAIN_MENU_BUTTONS),
    F.text != "❌ Bekor qilish",
)
async def process_return_weight(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    w, reason = _parse_return_weight_and_reason(message.text or "")
    if not w or w <= 0:
        await message.answer(
            "⚠️ To'g'ri miqdor kiriting (masalan: <code>2.5</code> yoki <code>2.5 brak</code>):",
            parse_mode="HTML",
        )
        return
    data = await state.get_data()
    cid = int(data["ret_client_id"])
    pid = int(data["ret_product_id"])
    async with async_session_maker() as db:
        ret = await add_product_return(db, client_id=cid, product_id=pid, weight_kg=w, reason=reason)
        debt = await compute_client_debt(db, cid, history_limit=1)
    await state.clear()
    await message.answer("✅ Vozvrat qayd etildi!", reply_markup=main_menu_keyboard())
    reason_line = f"\n📝 Sabab: <i>{html.escape(ret.reason)}</i>" if ret.reason else ""
    await message.answer(
        f"↩️ <b>Vozvrat #{ret.id}</b> — 🏪 <b>{html.escape(debt.client.name)}</b>\n"
        f"🥩 {html.escape(ret.product_name)}: <b>-{format_kg(ret.weight_kg)} kg</b> × {format_uzs(ret.unit_sell_price)}\n"
        f"💰 Qarzdan ayirildi: <b>-{format_uzs(ret.total_amount)} so'm</b>"
        f"{reason_line}\n"
        f"💳 Yangi qarz qoldig'i: <b>{format_uzs(debt.current_debt)} so'm</b>",
        parse_mode="HTML",
        reply_markup=return_after_record_kb(ret.id, has_group=bool(debt.client.group_chat_id)),
    )


@router.callback_query(F.data.startswith("ret:post_grp:"))
async def cb_return_post_group(cb: CallbackQuery) -> None:
    ret_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        ret = await get_product_return(db, ret_id)
        if not ret or ret.is_deleted:
            await cb.answer("Topilmadi", show_alert=True)
            return
        debt = await compute_client_debt(db, ret.client_id, history_limit=1)
    if not debt.client.group_chat_id:
        await cb.answer("Mijoz guruhi ulanmagan", show_alert=True)
        return
    caption = render_return_group_caption(ret, debt.current_debt)
    try:
        sent = await cb.bot.send_message(
            chat_id=debt.client.group_chat_id,
            text=caption,
            parse_mode="HTML",
        )
        async with async_session_maker() as db:
            await set_product_return_group_message(
                db, ret.id, debt.client.group_chat_id, sent.message_id
            )
        await cb.message.edit_text(
            f"✅ Vozvrat xabari <b>{html.escape(debt.client.name)}</b> guruhiga yuborildi!\n\n{caption}",
            parse_mode="HTML",
        )
        await cb.answer("📤 Yuborildi!")
    except Exception as exc:
        await cb.answer(f"❌ Xatolik: {exc}", show_alert=True)


@router.callback_query(F.data.startswith("ret_view:"))
async def cb_return_edit_view(cb: CallbackQuery) -> None:
    ret_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        ret = await get_product_return(db, ret_id)
    if not ret or ret.is_deleted:
        await cb.answer("Topilmadi", show_alert=True)
        return
    cname = ret.client.name if ret.client else f"Mijoz #{ret.client_id}"
    await cb.message.edit_text(
        f"↩️ <b>Vozvrat #{ret.id}</b>\n"
        f"🏪 Mijoz: <b>{html.escape(cname)}</b>\n"
        f"🥩 {html.escape(ret.product_name)}: <b>-{format_kg(ret.weight_kg)} kg</b> × {format_uzs(ret.unit_sell_price)}\n"
        f"💰 Summa: <b>-{format_uzs(ret.total_amount)} so'm</b>\n"
        f"📝 Sabab: <i>{html.escape(ret.reason or '-')}</i>",
        parse_mode="HTML",
        reply_markup=return_edit_kb(ret.id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("ret:delete:"))
async def cb_return_delete_confirm(cb: CallbackQuery) -> None:
    ret_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        ret = await get_product_return(db, ret_id)
    if not ret or ret.is_deleted:
        await cb.answer("Topilmadi", show_alert=True)
        return
    await cb.message.edit_text(
        f"⚠️ <b>Vozvrat #{ret.id}</b> (-{format_kg(ret.weight_kg)} kg / -{format_uzs(ret.total_amount)} so'm) rostdan ham o'chirasizmi?",
        parse_mode="HTML",
        reply_markup=confirm_delete_kb(f"ret:delete_ok:{ret_id}", f"ret_view:{ret_id}"),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("ret:delete_ok:"))
async def cb_return_delete(cb: CallbackQuery) -> None:
    ret_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        ret = await delete_product_return(db, ret_id)
        if not ret:
            await cb.answer("Topilmadi", show_alert=True)
            return
        debt = await compute_client_debt(db, ret.client_id, history_limit=1)
    notice_info = ""
    target_grp = ret.group_chat_id or (debt.client.group_chat_id if ret.client else None)
    if target_grp and ret.group_message_id:
        try:
            await cb.bot.send_message(
                chat_id=target_grp,
                text=render_return_delete_group_notice(ret, debt.current_debt),
                parse_mode="HTML",
            )
            notice_info = "\n📤 <i>Mijoz guruhiga bekor qilingani haqida xabar yuborildi.</i>"
        except Exception:
            pass
    await cb.message.edit_text(
        f"🗑 Vozvrat #{ret.id} ({format_kg(ret.weight_kg)} kg) o'chirildi!\n"
        f"💳 Yangilangan qarz: <b>{format_uzs(debt.current_debt)} so'm</b>"
        f"{notice_info}",
        parse_mode="HTML",
    )
    await cb.answer("O'chirildi!")


# ---------------------------------------------------------------------------
# Private Chat Smart Photo / Voice / Text Handlers
# ---------------------------------------------------------------------------


@router.message(F.chat.type == "private", F.photo)
async def handle_dm_photo(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    await _process_dm_photo(message, state)


async def _handle_parsed_dm_command(
    message: Message,
    state: FSMContext,
    parsed: Dict[str, Any],
    is_voice: bool = False,
) -> bool:
    """Execute a parsed Norin voice or text command in private chat."""
    intent = parsed.get("intent", "unknown")
    transcript = parsed.get("transcript") or ""
    voice_header = f"🎤 <i>«{html.escape(transcript)}»</i>\n\n" if is_voice and transcript else ""

    if intent == "status":
        await state.clear()
        async with async_session_maker() as db:
            summary = await compute_session_summary(db)
        await message.answer(
            voice_header + render_daily_report_text(summary),
            parse_mode="HTML",
            reply_markup=daily_report_kb(summary.session.id),
        )
        return True

    if intent == "debts":
        await state.clear()
        async with async_session_maker() as db:
            debts = await list_all_client_debts(db)
        await message.answer(
            voice_header + render_debts_overview_text(debts),
            parse_mode="HTML",
            reply_markup=debts_list_kb(debts),
        )
        return True

    amount = parsed.get("amount")
    if intent in ("cash_in", "expense", "kassa_debt", "kassa_repay") and amount and amount > 0:
        await state.clear()
        src_map = {
            "cash_in": "main_in",
            "expense": "expense",
            "kassa_debt": "kassa_debt",
            "kassa_repay": "kassa_repay",
        }
        lbl_map = {
            "cash_in": "Asosiy balansga qo'shildi",
            "expense": "Sex xarajati yozildi",
            "kassa_debt": "Kassadan qarzga olindi",
            "kassa_repay": "Kassaga qaytarildi",
        }
        async with async_session_maker() as db:
            await add_cash_transaction(
                db, amount=float(amount), source_type=src_map[intent], note=transcript
            )
            summary = await compute_session_summary(db)
        await message.answer(
            f"{voice_header}"
            f"✅ <b>{lbl_map[intent]}:</b> {format_uzs(amount)} so'm\n"
            f"💰 Qo'lda qolishi kerak: <b>{format_uzs(summary.expected_cash)} so'm</b>",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return True

    if intent == "client_payment" and amount and amount > 0:
        async with async_session_maker() as db:
            clients = await list_clients(db, active_only=True)
            cli = match_client(parsed.get("client_hint"), clients)
            if not cli:
                await message.answer(
                    f"{voice_header}💵 <b>{format_uzs(amount)} so'm</b> qaysi mijozdan olindi?",
                    parse_mode="HTML",
                    reply_markup=pick_client_for_payment_kb(clients),
                )
                return True
            method = parsed.get("payment_method") or "cash"
            pay = await add_client_payment(
                db, client_id=cli.id, amount=float(amount), payment_method=method, note=transcript
            )
            debt = await compute_client_debt(db, cli.id, history_limit=1)
        await state.clear()
        await message.answer(
            f"{voice_header}✅ <b>To'lov qabul qilindi!</b>\n"
            f"{render_payment_group_receipt(pay, debt.current_debt)}",
            parse_mode="HTML",
            reply_markup=payment_after_record_kb(pay.id, has_group=bool(debt.client.group_chat_id)),
        )
        return True

    if intent == "sale" and parsed.get("items"):
        async with async_session_maker() as db:
            products = await list_products(db, active_only=True)
            clients = await list_clients(db, active_only=True)
        items_spec = _build_items_spec(parsed["items"], products)
        cli = match_client(parsed.get("client_hint"), clients)
        if items_spec:
            await _process_ready_sale(
                message=message,
                state=state,
                client_id=cli.id if cli else None,
                items_spec=items_spec,
                photo_file_id=None,
                note=transcript,
                is_confident=bool(cli),
                prefix_html=voice_header,
            )
            return True

    return False


@router.message(F.chat.type == "private", F.voice | F.audio)
async def handle_dm_voice(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    file_obj = message.voice or message.audio
    if (getattr(file_obj, "duration", 0) or 0) > 90:
        await message.answer("⚠️ Ovozli xabar 90 soniyadan oshmasligi kerak (token tejash uchun qisqaroq ayting).")
        return
    wait_msg = await message.answer("🎤 Ovozli xabar eshitilmoqda...")
    try:
        audio_bytes, mime = await _download_voice_bytes(message)
        async with async_session_maker() as db:
            products = await list_products(db, active_only=True)
            clients = await list_clients(db, active_only=True)
        parsed = await parse_norin_voice_or_text(
            products, clients, audio_bytes=audio_bytes, mime_type=mime
        )
    finally:
        try:
            await wait_msg.delete()
        except Exception:
            pass

    if await _handle_parsed_dm_command(message, state, parsed, is_voice=True):
        return

    transcript = parsed.get("transcript") or "Tushunilmadi"
    await message.answer(
        f"🎤 Eshitildi: <i>«{html.escape(transcript)}»</i>\n"
        "Aniq amal topilmadi. Misol uchun:\n"
        "• <i>«Iftiqor 80 notin ot 25 kg»</i>\n"
        "• <i>«Iftiqordan 2 million karta oldim»</i>\n"
        "• <i>«Go'shtga 3 yarim million xarajat»</i>",
        parse_mode="HTML",
    )


@router.message(F.chat.type == "private", F.text)
async def handle_dm_text(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    txt = (message.text or "").strip()
    if not txt or txt.startswith("/"):
        return

    async with async_session_maker() as db:
        products = await list_products(db, active_only=True)
        clients = await list_clients(db, active_only=True)
    parsed = await parse_norin_voice_or_text(products, clients, text=txt)
    if await _handle_parsed_dm_command(message, state, parsed, is_voice=False):
        return

    await message.answer(
        "ℹ️ Tushunmadim. Quyidagi tugmalardan foydalaning yoki:\n"
        "• Tarozi/chek rasmini tashlang 📸\n"
        "• <code>Iftiqor ot 25 kg</code> deb yozing 🥩\n"
        "• <code>Iftiqordan 2 mln karta oldim</code> deb yozing 💵\n"
        "• <code>Go'shtga 3.5 mln xarajat</code> deb yozing ➖",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


# ---------------------------------------------------------------------------
# Client-Bound Group Auto-Calculation Handlers
# ---------------------------------------------------------------------------


async def _notify_admins_after_group_sale(
    bot,
    sender_id: Optional[int],
    sale: Sale,
    current_debt: float,
) -> None:
    """Send private profit & quick-edit card to the sender/admin after a group auto-calc."""
    settings = get_settings()
    targets: set[int] = set()
    tid = int(getattr(sale, "tenant_id", 1) or 1)
    if sender_id and sender_id != 1087968824:
        targets.add(sender_id)
    else:
        async with async_session_maker() as db:
            db_users = await list_authorized_users(db, active_only=True, tenant_id=tid)
        targets.update(u.telegram_id for u in db_users)
        if tid == 1:
            targets.update(settings.admin_id_list)
        if not targets:
            targets.update(settings.super_admin_id_list)

    text = (
        "🤖 <b>Guruhda avto-hisoblandi!</b>\n"
        f"{render_sale_admin_summary(sale, current_debt)}"
    )
    kb = auto_confirmed_sale_kb(sale, sent_to_group=True)
    for uid in targets:
        try:
            await bot.send_message(chat_id=uid, text=text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            pass


async def _finalize_group_sale(
    message: Message,
    client_id: int,
    items_spec: List[Dict[str, Any]],
    photo_file_id: Optional[str],
    note: str,
) -> None:
    """Create & confirm group sale, reply in group (NO cost/profit), and DM admin with profit."""
    async with async_session_maker() as db:
        sale = await create_pending_sale(
            db,
            client_id=client_id,
            items_spec=items_spec,
            photo_file_id=photo_file_id,
            note=note,
            source_channel="group",
        )
        sale = await confirm_sale(db, sale.id)  # type: ignore[assignment]
        debt = await compute_client_debt(db, client_id, history_limit=1)

    await _post_sale_to_client_group(
        message.bot, sale, debt.current_debt, reply_to_message=message
    )
    await _notify_admins_after_group_sale(
        message.bot,
        message.from_user.id if message.from_user else None,
        sale,
        debt.current_debt,
    )


@router.message(F.chat.type.in_({"group", "supergroup"}), F.photo)
async def handle_group_photo(message: Message) -> None:
    """Auto-read scale/receipt photo inside a client-bound Telegram group (caption 0-token first)."""
    uid = message.from_user.id if message.from_user else None
    if not await is_authorized_async(uid, allow_group_anon=True):
        return
    async with async_session_maker() as db:
        if (await get_app_setting(db, "group_auto_calc", "on")) != "on":
            return
        client = await get_client_by_group(db, message.chat.id)
        if not client:
            return
        products = await list_products(db, active_only=True)

    photo = message.photo[-1]
    if message.caption:
        cap_parsed = _heuristic_parse_norin_text(message.caption, products, [])
        if cap_parsed and cap_parsed.get("intent") == "sale" and cap_parsed.get("items"):
            cap_spec = _build_items_spec(cap_parsed["items"], products)
            if cap_spec:
                await _finalize_group_sale(
                    message=message,
                    client_id=client.id,
                    items_spec=cap_spec,
                    photo_file_id=photo.file_id,
                    note=message.caption.strip(),
                )
                return

    buf = io.BytesIO()
    await message.bot.download(photo, destination=buf)
    extracted = await extract_norin_from_image(
        image_bytes=buf.getvalue(),
        products=products,
        clients=(),
        mime_type="image/jpeg",
        caption=message.caption,
    )
    items_spec = _build_items_spec(extracted.get("items") or [], products)
    if not items_spec:
        return
    await _finalize_group_sale(
        message=message,
        client_id=client.id,
        items_spec=items_spec,
        photo_file_id=photo.file_id,
        note=extracted.get("notes") or "",
    )


@router.message(F.chat.type.in_({"group", "supergroup"}), F.voice | F.audio)
async def handle_group_voice(message: Message) -> None:
    """Auto-calculate Norin sale from voice message inside a client-bound group."""
    uid = message.from_user.id if message.from_user else None
    if not await is_authorized_async(uid, allow_group_anon=True):
        return
    file_obj = message.voice or message.audio
    if (getattr(file_obj, "duration", 0) or 0) > 90:
        return
    async with async_session_maker() as db:
        if (await get_app_setting(db, "group_auto_calc", "on")) != "on":
            return
        client = await get_client_by_group(db, message.chat.id)
        if not client:
            return
        products = await list_products(db, active_only=True)

    audio_bytes, mime = await _download_voice_bytes(message)
    parsed = await parse_norin_voice_or_text(
        products, (), audio_bytes=audio_bytes, mime_type=mime
    )
    if parsed.get("intent") != "sale" or not parsed.get("items"):
        return
    items_spec = _build_items_spec(parsed["items"], products)
    if not items_spec:
        return
    await _finalize_group_sale(
        message=message,
        client_id=client.id,
        items_spec=items_spec,
        photo_file_id=None,
        note=parsed.get("transcript") or "",
    )


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def handle_group_text(message: Message) -> None:
    """Auto-calculate Norin text orders like 'norin ot 25 kg' inside a client-bound group."""
    txt = (message.text or "").strip()
    if not txt or txt.startswith("/"):
        return
    uid = message.from_user.id if message.from_user else None
    if not await is_authorized_async(uid, allow_group_anon=True):
        return

    async with async_session_maker() as db:
        if (await get_app_setting(db, "group_auto_calc", "on")) != "on":
            return
        client = await get_client_by_group(db, message.chat.id)
        if not client:
            return
        products = await list_products(db, active_only=True)
        clients = await list_clients(db, active_only=True)

    from services.gemini_ai import _heuristic_parse_norin_text

    parsed = _heuristic_parse_norin_text(txt, products, clients)
    if not parsed or parsed.get("intent") != "sale" or not parsed.get("items"):
        return

    items_spec = _build_items_spec(parsed["items"], products)
    if not items_spec:
        return
    await _finalize_group_sale(
        message=message,
        client_id=client.id,
        items_spec=items_spec,
        photo_file_id=None,
        note=txt,
    )

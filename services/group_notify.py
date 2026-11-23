"""Client-safe Telegram group notifications shared between the bot and norin-api."""

from __future__ import annotations

import html
import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import BufferedInputFile
from sqlalchemy.ext.asyncio import AsyncSession

from database.crud import (
    ClientDebtSummary,
    format_local_dt,
    set_client_payment_group_message,
    set_product_return_group_message,
    set_sale_group_message,
)
from database.models import ClientPayment, ProductReturn, Sale
from services.gemini_ai import format_kg, format_uzs


logger = logging.getLogger("norin_bot.group_notify")


def render_sale_group_caption(
    sale: Sale, current_debt: float, tag: str = ""
) -> str:
    """
    Build caption/message posted to a client's Telegram group.

    STRICT SAFETY RULE: Never include cost_price, unit_cost, total_cost, profit, or margin!
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


def render_sale_edit_group_notice(
    sale: Sale, current_debt: float, change_line: str, is_deleted: bool = False
) -> str:
    """Client-safe edit/delete notification for a client group (zero cost/profit)."""
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


def render_return_group_caption(ret: ProductReturn, current_debt: float) -> str:
    """Client-safe Vozvrat receipt posted to a client's group (zero cost/profit)."""
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
    """Client-safe notice sent to group when a Vozvrat entry is deleted."""
    cname = ret.client.name if ret.client else f"Mijoz #{ret.client_id}"
    return (
        f"❌ <b>VOZVRAT #{ret.id} BEKOR QILINDI</b>\n"
        f"🏪 Mijoz: <b>{html.escape(cname)}</b>\n"
        f"🥩 {html.escape(ret.product_name)}: <s>-{format_kg(ret.weight_kg)} kg</s> (<s>-{format_uzs(ret.total_amount)} so'm</s>)\n"
        f"💳 Yangilangan qarz qoldig'i: <b>{format_uzs(current_debt)} so'm</b>"
    )


def render_client_sverka_group_text(debt: ClientDebtSummary) -> str:
    """Client-safe Akt Sverka message for Telegram groups (never exposes cost/profit)."""
    cli = debt.client
    lines = [
        f"📋 <b>AKT SVERKA — {html.escape(cli.name)}</b>",
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
    return "\n".join(lines)


async def post_sale_to_group(
    bot: Optional[Bot],
    db: AsyncSession,
    sale: Sale,
    current_debt: float,
    photo_bytes: Optional[bytes] = None,
) -> tuple[bool, str]:
    """Post a confirmed sale (with optional photo or Telegram file_id) to the client's group."""
    if not sale.client or not sale.client.group_chat_id:
        return False, "Mijoz guruhi ulanmagan"
    if bot is None:
        return False, "Bot ulanmagan"
    chat_id = sale.client.group_chat_id
    caption = render_sale_group_caption(sale, current_debt)
    try:
        if photo_bytes:
            sent = await bot.send_photo(
                chat_id=chat_id,
                photo=BufferedInputFile(photo_bytes, filename=f"sale_{sale.id}.jpg"),
                caption=caption,
            )
            if sent.photo:
                sale.photo_file_id = sent.photo[-1].file_id
        elif sale.photo_file_id:
            sent = await bot.send_photo(
                chat_id=chat_id, photo=sale.photo_file_id, caption=caption
            )
        else:
            sent = await bot.send_message(chat_id=chat_id, text=caption)
        await set_sale_group_message(db, sale.id, chat_id, sent.message_id)
        return True, f"{sale.client.group_title or sale.client.name} guruhiga yuborildi"
    except Exception as exc:
        logger.warning("post_sale_to_group failed sale=%s: %s", sale.id, exc)
        return False, f"Guruhga yuborib bo'lmadi: {exc}"


async def sync_sale_group_edit(
    bot: Optional[Bot],
    sale: Sale,
    current_debt: float,
    tag: str = "✏️ [TAHRIRLANDI]",
    change_line: str = "",
    is_deleted: bool = False,
) -> tuple[bool, str]:
    """Update original group message if posted and send a visible edit/delete alert."""
    if bot is None:
        return False, "Bot ulanmagan"
    target_chat_id = sale.group_chat_id or (sale.client.group_chat_id if sale.client else None)
    if not target_chat_id:
        return False, "Mijoz guruhi ulanmagan"

    edited_ok = False
    if sale.group_chat_id and sale.group_message_id:
        new_caption = render_sale_group_caption(sale, current_debt, tag=tag)
        try:
            if sale.photo_file_id:
                try:
                    await bot.edit_message_caption(
                        chat_id=sale.group_chat_id,
                        message_id=sale.group_message_id,
                        caption=new_caption,
                    )
                except Exception:
                    await bot.edit_message_text(
                        chat_id=sale.group_chat_id,
                        message_id=sale.group_message_id,
                        text=new_caption,
                    )
            else:
                await bot.edit_message_text(
                    chat_id=sale.group_chat_id,
                    message_id=sale.group_message_id,
                    text=new_caption,
                )
            edited_ok = True
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                edited_ok = True

    alert_ok = False
    if change_line or is_deleted or sale.status == "deleted":
        notice = render_sale_edit_group_notice(
            sale,
            current_debt,
            change_line or f"⚖️ {format_kg(sale.total_weight_kg)} kg — {format_uzs(sale.total_amount)} so'm",
            is_deleted=is_deleted or (sale.status == "deleted"),
        )
        try:
            await bot.send_message(chat_id=target_chat_id, text=notice)
            alert_ok = True
        except Exception as exc:
            logger.warning("sync_sale_group_edit failed sale=%s: %s", sale.id, exc)
    return (edited_ok or alert_ok), "Guruh yangilandi" if (edited_ok or alert_ok) else "Guruhga yuborib bo'lmadi"


async def post_payment_to_group(
    bot: Optional[Bot],
    db: AsyncSession,
    payment: ClientPayment,
    current_debt: float,
) -> tuple[bool, str]:
    if not payment.client or not payment.client.group_chat_id:
        return False, "Mijoz guruhi ulanmagan"
    if bot is None:
        return False, "Bot ulanmagan"
    chat_id = payment.client.group_chat_id
    try:
        sent = await bot.send_message(
            chat_id=chat_id, text=render_payment_group_receipt(payment, current_debt)
        )
        await set_client_payment_group_message(db, payment.id, chat_id, sent.message_id)
        return True, "Kvitansiya guruhga yuborildi"
    except Exception as exc:
        return False, f"Guruhga yuborib bo'lmadi: {exc}"


async def post_return_to_group(
    bot: Optional[Bot],
    db: AsyncSession,
    ret: ProductReturn,
    current_debt: float,
) -> tuple[bool, str]:
    if not ret.client or not ret.client.group_chat_id:
        return False, "Mijoz guruhi ulanmagan"
    if bot is None:
        return False, "Bot ulanmagan"
    chat_id = ret.client.group_chat_id
    try:
        sent = await bot.send_message(
            chat_id=chat_id, text=render_return_group_caption(ret, current_debt)
        )
        await set_product_return_group_message(db, ret.id, chat_id, sent.message_id)
        return True, "Vozvrat guruhga yuborildi"
    except Exception as exc:
        return False, f"Guruhga yuborib bo'lmadi: {exc}"


async def post_sverka_to_group(
    bot: Optional[Bot], debt: ClientDebtSummary
) -> tuple[bool, str]:
    if not debt.client.group_chat_id:
        return False, "Bu mijozga guruh biriktirilmagan"
    if bot is None:
        return False, "Bot ulanmagan"
    try:
        await bot.send_message(
            chat_id=debt.client.group_chat_id,
            text=render_client_sverka_group_text(debt),
        )
        return True, "Akt Sverka mijoz guruhiga yuborildi"
    except Exception as exc:
        return False, f"Guruhga yuborib bo'lmadi: {exc}"

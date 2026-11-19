"""Daily Norin profit report, 30-day period analytics, expenses, kassa debt, day close, history & Excel."""

from __future__ import annotations

import html
import io
import logging
from typing import Optional

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.handlers.clients_products import is_authorized_async
from bot.keyboards import (
    BTN_CLOSE_DAY,
    BTN_DAILY_REPORT,
    BTN_EXPENSE_KASSA,
    cancel_reply_keyboard,
    close_day_confirm_kb,
    daily_report_kb,
    history_detail_kb,
    history_feed_kb,
    history_sessions_kb,
    main_menu_keyboard,
    period_report_kb,
    wallet_expense_kb,
)
from bot.states import WalletStates
from database.crud import (
    DailyReportSummary,
    PeriodReportSummary,
    add_cash_transaction,
    close_cash_session,
    compute_client_debt,
    compute_period_summary,
    compute_session_summary,
    format_local_dt,
    get_group_config,
    get_kassa_debt_stats,
    list_all_client_debts,
    list_all_sessions,
    list_closed_sessions,
    list_recent_client_payments,
    list_recent_sales,
    reopen_cash_session,
)
from database.session import async_session_maker
from services.excel_export import (
    build_client_statement_excel,
    build_daily_norin_excel,
    build_history_excel,
)
from services.gemini_ai import format_kg, format_uzs, parse_uzbek_amount, parse_norin_voice_or_text
from database.crud import list_clients, list_products


router = Router(name="wallet_reports")
logger = logging.getLogger("norin_bot.wallet")


def render_daily_report_text(summary: DailyReportSummary) -> str:
    """Format complete internal daily Norin sales, kg, cost, profit, cash, and client debt summary."""
    lines = [
        f"📊 <b>NORIN KUNLIK HISOBOT ({summary.session.report_date})</b>",
        "===============================",
        f"🥩 <b>Sotilgan mahsulotlar ({len(summary.confirmed_sales)} ta sotuv):</b>",
    ]
    if not summary.weight_by_product:
        lines.append("<i>Bugun hali tasdiqlangan sotuvlar yo'q</i>")
    else:
        for pname, kg in summary.weight_by_product.items():
            lines.append(f"  • {html.escape(pname)}: <b>{format_kg(kg)} kg</b>")
        lines.append(f"⚖️ Jami vazn: <b>{format_kg(summary.total_kg)} kg</b>")

    lines.extend(
        [
            "-------------------------------",
            f"💰 Jami sotuv (Tushum): <b>{format_uzs(summary.total_revenue)} so'm</b>",
            f"📉 Jami tannarx: <b>{format_uzs(summary.total_cost)} so'm</b>",
            f"📈 <b>Sof foyda: {format_uzs(summary.total_profit)} so'm ({summary.margin_pct:.1f}%)</b>",
            "===============================",
            "💵 <b>Kassa va To'lovlar:</b>",
            f"⏮ Kechadan naqd qoldiq: <b>{format_uzs(summary.opening_balance)}</b>",
            f"💵 Mijozlardan naqd: <b>+{format_uzs(summary.client_cash_in)}</b>",
        ]
    )
    if summary.client_card_in > 0:
        lines.append(f"💳 Mijozlardan karta/Click: <b>{format_uzs(summary.client_card_in)}</b> <i>(qarzdan ayirildi)</i>")
    if summary.client_transfer_in > 0:
        lines.append(f"🏦 Perechesleniye: <b>{format_uzs(summary.client_transfer_in)}</b> <i>(qarzdan ayirildi)</i>")
    if summary.main_cash_in > 0:
        lines.append(f"➕ Qo'shimcha kiritilgan pul: <b>+{format_uzs(summary.main_cash_in)}</b>")
    if summary.kassa_debt_today > 0:
        lines.append(f"🏦 Kassadan olingan qarz: <b>+{format_uzs(summary.kassa_debt_today)}</b>")
    if summary.kassa_repay_today > 0:
        lines.append(f"↩️ Kassaga qaytarilgan: <b>-{format_uzs(summary.kassa_repay_today)}</b>")

    lines.extend(
        [
            f"➖ Sex xarajatlari (rasxod): <b>-{format_uzs(summary.total_expenses)}</b>",
            f"💰 <b>Qo'lda qolishi kerak (Naqd): {format_uzs(summary.expected_cash)} so'm</b>",
            "===============================",
            f"💳 Barcha mijozlar qarzi: <b>{format_uzs(summary.total_all_clients_debt)} so'm</b>",
            f"🏦 Kassa qarzi qoldig'i: <b>{format_uzs(summary.total_kassa_debt_outstanding)} so'm</b>",
        ]
    )
    return "\n".join(lines)


def render_period_report_text(p: PeriodReportSummary) -> str:
    """Format 30-day aggregated Norin sales, profit, and cash flow report."""
    lines = [
        f"📆 <b>{p.days} KUNLIK YIG'MA HISOBOT</b>",
        f"🗓 Davr: <code>{p.start_date}</code> → <code>{p.end_date}</code>",
        "===============================",
        f"📦 Sotuvlar soni: <b>{p.sales_count} ta</b>",
        f"⚖️ Jami sotilgan vazn: <b>{format_kg(p.total_kg)} kg</b>",
    ]
    for pname, kg in p.weight_by_product.items():
        lines.append(f"  • {html.escape(pname)}: <b>{format_kg(kg)} kg</b>")
    lines.extend(
        [
            "-------------------------------",
            f"💰 Umumiy sotuv: <b>{format_uzs(p.total_revenue)} so'm</b>",
            f"📉 Umumiy tannarx: <b>{format_uzs(p.total_cost)} so'm</b>",
            f"📈 <b>Sof foyda: {format_uzs(p.total_profit)} so'm ({p.margin_pct:.1f}%)</b>",
            "-------------------------------",
            f"💵 Yig'ilgan naqd: <b>{format_uzs(p.total_cash_collected)}</b>",
            f"💳 Yig'ilgan karta: <b>{format_uzs(p.total_card_collected)}</b>",
            f"🏦 Perechesleniye: <b>{format_uzs(p.total_transfer_collected)}</b>",
            f"➖ Jami xarajatlar: <b>{format_uzs(p.total_expenses)}</b>",
            "-------------------------------",
            f"💳 Hozirgi jami mijoz qarzlari: <b>{format_uzs(p.total_all_clients_debt)} so'm</b>",
        ]
    )
    return "\n".join(lines)


async def _download_voice_bytes(message: Message) -> tuple[bytes, str]:
    file_obj = message.voice or message.audio
    mime = "audio/ogg" if message.voice else (file_obj.mime_type or "audio/mpeg")
    buf = io.BytesIO()
    await message.bot.download(file_obj, destination=buf)
    return buf.getvalue(), mime


async def _extract_amount_and_note(message: Message) -> tuple[Optional[float], str]:
    if message.voice or message.audio:
        audio_bytes, mime = await _download_voice_bytes(message)
        async with async_session_maker() as db:
            prods = await list_products(db)
            clis = await list_clients(db)
        parsed = await parse_norin_voice_or_text(
            prods, clis, audio_bytes=audio_bytes, mime_type=mime
        )
        return parsed.get("amount"), parsed.get("transcript", "")
    if message.text:
        return parse_uzbek_amount(message.text), message.text.strip()
    return None, ""


# ---------------------------------------------------------------------------
# Daily & Period Reports
# ---------------------------------------------------------------------------


@router.message(F.text == BTN_DAILY_REPORT, F.chat.type == "private")
async def handle_daily_report_btn(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    await state.clear()
    async with async_session_maker() as db:
        summary = await compute_session_summary(db)
    await message.answer(
        render_daily_report_text(summary),
        parse_mode="HTML",
        reply_markup=daily_report_kb(summary.session.id),
    )


@router.callback_query(F.data == "rep:today")
async def cb_report_today(cb: CallbackQuery) -> None:
    async with async_session_maker() as db:
        summary = await compute_session_summary(db)
    await cb.message.edit_text(
        render_daily_report_text(summary),
        parse_mode="HTML",
        reply_markup=daily_report_kb(summary.session.id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("rep:period:"))
async def cb_report_period(cb: CallbackQuery) -> None:
    days = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        period = await compute_period_summary(db, days=days)
    await cb.message.edit_text(
        render_period_report_text(period),
        parse_mode="HTML",
        reply_markup=period_report_kb(),
    )
    await cb.answer()


# ---------------------------------------------------------------------------
# Expenses, Owner Cash-In, and Kassa Debt
# ---------------------------------------------------------------------------


@router.message(F.text == BTN_EXPENSE_KASSA, F.chat.type == "private")
async def handle_expense_kassa_btn(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    await state.clear()
    async with async_session_maker() as db:
        summary = await compute_session_summary(db)
        kstats = await get_kassa_debt_stats(db, limit=5)

    lines = [
        "💵 <b>Xarajatlar, Qo'shimcha Kirim & Kassa Qarzi</b>",
        "===============================",
        f"➖ Bugungi xarajatlar: <b>{format_uzs(summary.total_expenses)} so'm</b>",
        f"➕ Qo'shimcha kirim: <b>{format_uzs(summary.main_cash_in)} so'm</b>",
        f"🏦 Bugun kassadan olingan: <b>{format_uzs(summary.kassa_debt_today)} so'm</b>",
        f"↩️ Bugun kassaga qaytarilgan: <b>{format_uzs(summary.kassa_repay_today)} so'm</b>",
        f"⚠️ <b>Jami kassa qarzi qoldig'i: {format_uzs(kstats['outstanding'])} so'm</b>",
        f"💰 Qo'ldagi naqd qolishi kerak: <b>{format_uzs(summary.expected_cash)} so'm</b>",
    ]
    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=wallet_expense_kb(),
    )


@router.callback_query(F.data == "wal:expense")
async def cb_wal_expense(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(WalletStates.waiting_expense_amount)
    await cb.message.answer(
        "➖ <b>Sex xarajatini yozing</b> (ovozda yoki matnda, masalan: <i>«Go'shtga 3.5 mln xarajat»</i> yoki <code>450 000 xamir</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(WalletStates.waiting_expense_amount, F.chat.type == "private")
async def process_expense_input(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    amount, note = await _extract_amount_and_note(message)
    if not amount or amount <= 0:
        await message.answer("⚠️ Summa tushunilmadi. Masalan: <code>500 000 go'sht</code>:", parse_mode="HTML")
        return
    async with async_session_maker() as db:
        await add_cash_transaction(db, amount=amount, source_type="expense", note=note)
        summary = await compute_session_summary(db)
    await state.clear()
    await message.answer(
        f"➖ Xarajat yozildi: <b>{format_uzs(amount)} so'm</b>\n"
        f"📝 Izoh: <i>{html.escape(note or '-')}</i>\n"
        f"💰 Qo'lda qolishi kerak: <b>{format_uzs(summary.expected_cash)} so'm</b>",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(F.data == "wal:cash_in")
async def cb_wal_cash_in(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(WalletStates.waiting_cash_in_amount)
    await cb.message.answer(
        "➕ <b>Qancha qo'shimcha pul kiritildi?</b> (masalan: <code>5 000 000</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(WalletStates.waiting_cash_in_amount, F.chat.type == "private")
async def process_wal_cash_in(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    amount, note = await _extract_amount_and_note(message)
    if not amount or amount <= 0:
        await message.answer("⚠️ Summa topilmadi. Raqam kiriting:")
        return
    async with async_session_maker() as db:
        await add_cash_transaction(db, amount=amount, source_type="main_in", note=note)
        summary = await compute_session_summary(db)
    await state.clear()
    await message.answer(
        f"✅ Asosiy balansga <b>+{format_uzs(amount)} so'm</b> qo'shildi!\n"
        f"💰 Qo'lda qolishi kerak: <b>{format_uzs(summary.expected_cash)} so'm</b>",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(F.data == "wal:kassa_borrow")
async def cb_wal_kassa_borrow(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(WalletStates.waiting_kassa_debt_amount)
    await cb.message.answer(
        "🏦 <b>Kassadan qancha pul oldingiz?</b> (masalan: <code>2 000 000</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(WalletStates.waiting_kassa_debt_amount, F.chat.type == "private")
async def process_wal_kassa_borrow(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    amount, note = await _extract_amount_and_note(message)
    if not amount or amount <= 0:
        await message.answer("⚠️ Summa topilmadi:")
        return
    async with async_session_maker() as db:
        await add_cash_transaction(db, amount=amount, source_type="kassa_debt", note=note)
        summary = await compute_session_summary(db)
    await state.clear()
    await message.answer(
        f"🏦 Kassadan qarz olindi: <b>+{format_uzs(amount)} so'm</b>\n"
        f"⚠️ Jami kassa qarzi: <b>{format_uzs(summary.total_kassa_debt_outstanding)} so'm</b>\n"
        f"💰 Qo'lda qolishi kerak: <b>{format_uzs(summary.expected_cash)} so'm</b>",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(F.data == "wal:kassa_repay")
async def cb_wal_kassa_repay(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(WalletStates.waiting_kassa_repay_amount)
    await cb.message.answer(
        "↩️ <b>Kassaga qancha qarz qaytardingiz?</b>:",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(WalletStates.waiting_kassa_repay_amount, F.chat.type == "private")
async def process_wal_kassa_repay(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    amount, note = await _extract_amount_and_note(message)
    if not amount or amount <= 0:
        await message.answer("⚠️ Summa topilmadi:")
        return
    async with async_session_maker() as db:
        await add_cash_transaction(db, amount=amount, source_type="kassa_repay", note=note)
        summary = await compute_session_summary(db)
    await state.clear()
    await message.answer(
        f"↩️ Kassaga qaytarildi: <b>{format_uzs(amount)} so'm</b>\n"
        f"⚠️ Qolgan kassa qarzi: <b>{format_uzs(summary.total_kassa_debt_outstanding)} so'm</b>\n"
        f"💰 Qo'lda qolishi kerak: <b>{format_uzs(summary.expected_cash)} so'm</b>",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


# ---------------------------------------------------------------------------
# Day Close (Sverka)
# ---------------------------------------------------------------------------


@router.message(F.text == BTN_CLOSE_DAY, F.chat.type == "private")
async def handle_close_day_start(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    async with async_session_maker() as db:
        summary = await compute_session_summary(db)
    await state.set_state(WalletStates.waiting_counted_cash)
    await state.update_data(session_id=summary.session.id)
    await message.answer(
        f"🏁 <b>KUNNI YAKUNLASH ({summary.session.report_date})</b>\n"
        "===============================\n"
        f"⚖️ Jami sotilgan: <b>{format_kg(summary.total_kg)} kg</b> ({format_uzs(summary.total_revenue)} so'm)\n"
        f"📈 Bugungi sof foyda: <b>{format_uzs(summary.total_profit)} so'm</b>\n"
        f"⏮ Kechadan qoldiq: <b>{format_uzs(summary.opening_balance)}</b>\n"
        f"💵 Mijoz naqd to'lovlari: <b>+{format_uzs(summary.client_cash_in)}</b>\n"
        f"➖ Xarajatlar: <b>-{format_uzs(summary.total_expenses)}</b>\n"
        f"💰 <b>Qo'lda qolishi kerak (Naqd): {format_uzs(summary.expected_cash)} so'm</b>\n"
        "===============================\n\n"
        "🖐 <b>Qo'lingizdagi naqd pulni sanab kiriting</b> (matn yoki ovozda, masalan: <code>1 500 000</code> yoki <code>0</code>):",
        parse_mode="HTML",
        reply_markup=cancel_reply_keyboard(),
    )


@router.callback_query(F.data == "close_day:recount")
async def cb_close_day_recount(cb: CallbackQuery, state: FSMContext) -> None:
    async with async_session_maker() as db:
        summary = await compute_session_summary(db)
    await state.set_state(WalletStates.waiting_counted_cash)
    await state.update_data(session_id=summary.session.id)
    await cb.message.answer(
        "🖐 Qo'lingizdagi naqd pulni qayta sanab kiriting:",
        reply_markup=cancel_reply_keyboard(),
    )
    await cb.answer()


@router.message(WalletStates.waiting_counted_cash, F.chat.type == "private")
async def process_counted_cash(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    counted: Optional[float] = None
    if message.voice or message.audio:
        counted, _ = await _extract_amount_and_note(message)
    elif message.text:
        txt = message.text.strip()
        counted = 0.0 if txt == "0" else parse_uzbek_amount(txt)

    if counted is None or counted < 0:
        await message.answer("⚠️ Summa tushunilmadi. Raqam kiriting (masalan: <code>1 500 000</code> yoki <code>0</code>):", parse_mode="HTML")
        return

    session_id = (await state.get_data()).get("session_id")
    async with async_session_maker() as db:
        summary = await compute_session_summary(db, session_id)

    diff = counted - summary.expected_cash
    if abs(diff) < 1:
        diff_msg = "✅ <b>Zo'r! Farq yo'q (0 so'm)</b>"
    elif diff < 0:
        diff_msg = f"⚠️ <b>Kamomad: {format_uzs(diff)} so'm</b>"
    else:
        diff_msg = f"➕ <b>Ortiqcha: +{format_uzs(diff)} so'm</b>"

    await state.clear()
    await message.answer(
        f"📊 <b>SVERKA NATIJASI ({summary.session.report_date})</b>\n"
        "===============================\n"
        f"💰 Qolishi kerak edi: <b>{format_uzs(summary.expected_cash)} so'm</b>\n"
        f"🖐 Siz sanadingiz: <b>{format_uzs(counted)} so'm</b>\n"
        f"⚖️ Farq: {diff_msg}\n"
        "===============================\n\n"
        "Hammasi to'g'ri bo'lsa kunni yoping:",
        parse_mode="HTML",
        reply_markup=close_day_confirm_kb(summary.session.id, counted),
    )
    await message.answer("👇 Qaroringizni tanlang:", reply_markup=main_menu_keyboard())


@router.callback_query(F.data.startswith("close_day:confirm:"))
async def cb_close_day_confirm(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    sess_id = int(parts[2])
    counted = float(parts[3])

    async with async_session_maker() as db:
        existing = await compute_session_summary(db, sess_id)
        if existing.session.status == "closed":
            await cb.answer("Bu kun allaqachon yopilgan!", show_alert=True)
            return
        closed = await close_cash_session(db, sess_id, counted)
        report_group = await get_group_config(db, "report")

    diff = closed.session.difference or 0
    diff_line = (
        "✅ Farq yo'q (0)"
        if abs(diff) < 1
        else (f"⚠️ Kamomad: {format_uzs(diff)}" if diff < 0 else f"➕ Ortiqcha: +{format_uzs(diff)}")
    )
    summary_msg = (
        f"🏁 <b>KUN YOPILDI — {closed.session.report_date}</b>\n"
        "===============================\n"
        f"⚖️ Jami sotilgan: <b>{format_kg(closed.total_kg)} kg</b>\n"
        f"💰 Jami savdo: <b>{format_uzs(closed.total_revenue)} so'm</b>\n"
        f"📉 Tannarx: {format_uzs(closed.total_cost)} so'm\n"
        f"📈 <b>Sof foyda: {format_uzs(closed.total_profit)} so'm ({closed.margin_pct:.1f}%)</b>\n"
        "-------------------------------\n"
        f"💵 Mijoz to'lovlari (Naqd/Karta/Bank): {format_uzs(closed.client_cash_in + closed.client_card_in + closed.client_transfer_in)}\n"
        f"➖ Xarajatlar: {format_uzs(closed.total_expenses)}\n"
        f"💰 Qolishi kerak edi (naqd): {format_uzs(closed.expected_cash)}\n"
        f"🖐 Sanalgan naqd: <b>{format_uzs(counted)} so'm</b>\n"
        f"⚖️ {diff_line}\n"
        f"💳 Barcha mijozlar qarzi: <b>{format_uzs(closed.total_all_clients_debt)} so'm</b>"
    )

    if report_group:
        try:
            await cb.bot.send_message(report_group.chat_id, summary_msg, parse_mode="HTML")
        except Exception:
            pass

    await cb.message.edit_text(
        f"{summary_msg}\n\n"
        f"💾 <b>Arxivga saqlandi!</b> Ertangi kunga <b>{format_uzs(counted)} so'm</b> qoldiq o'tdi.",
        parse_mode="HTML",
    )
    await cb.answer("✅ Kun yopildi!")


# ---------------------------------------------------------------------------
# History & Excel Export
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "set:history")
async def cb_history_list(cb: CallbackQuery) -> None:
    async with async_session_maker() as db:
        sessions = await list_all_sessions(db, limit=12)
    if not sessions:
        await cb.answer("Hozircha kunlik tarix yo'q.", show_alert=True)
        return
    await cb.message.edit_text(
        "📜 <b>Kunlik Hisobotlar va Savdo Tarixi (Arxiv):</b>",
        parse_mode="HTML",
        reply_markup=history_sessions_kb(sessions),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("hist:view:"))
async def cb_history_detail(cb: CallbackQuery) -> None:
    sess_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        summary = await compute_session_summary(db, sess_id)
    is_closed = summary.session.status == "closed"
    text = render_daily_report_text(summary)
    if is_closed:
        diff = summary.session.difference or 0
        text += (
            f"\n\n🖐 Sanalgan naqd: <b>{format_uzs(summary.session.actual_counted_cash or 0)}</b>"
            f"\n📊 Farq: <b>{format_uzs(diff)}</b>"
        )
    await cb.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=history_detail_kb(sess_id, is_closed=is_closed),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("hist:reopen:"))
async def cb_history_reopen(cb: CallbackQuery) -> None:
    sess_id = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        sess = await reopen_cash_session(db, sess_id)
    if not sess:
        await cb.answer("Topilmadi", show_alert=True)
        return
    await cb.message.edit_text(
        f"🔓 <b>{sess.report_date}</b> kuni qayta ochildi!\n"
        "Endi <b>✏️ Tahrirlash</b> orqali tuzatishingiz va qayta yopishingiz mumkin.",
        parse_mode="HTML",
    )
    await cb.answer("Qayta ochildi")


@router.callback_query(F.data.startswith("hist:all_sales:"))
async def cb_history_all_sales(cb: CallbackQuery) -> None:
    page = int(cb.data.split(":")[-1])
    page_size = 12
    async with async_session_maker() as db:
        items = await list_recent_sales(db, limit=page_size + 1, offset=page * page_size)
    has_next = len(items) > page_size
    items = items[:page_size]
    if not items and page == 0:
        await cb.answer("Hali tasdiqlangan sotuvlar yo'q.", show_alert=True)
        return
    lines = [f"🥩 <b>Sotuvlar Tarixi (Sahifa {page + 1})</b>\n"]
    for idx, s in enumerate(items, start=page * page_size + 1):
        dt = format_local_dt(s.created_at, "%d.%m %H:%M")
        cname = s.client.name if s.client else "Noma'lum"
        lines.append(
            f"{idx}) <code>{dt}</code> <b>{html.escape(cname)}</b> | {format_kg(s.total_weight_kg)} kg — {format_uzs(s.total_amount)} (foyda: {format_uzs(s.total_profit)})"
        )
    await cb.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=history_feed_kb("all_sales", page, has_next),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("hist:all_pays:"))
async def cb_history_all_pays(cb: CallbackQuery) -> None:
    page = int(cb.data.split(":")[-1])
    page_size = 15
    async with async_session_maker() as db:
        items = await list_recent_client_payments(db, limit=page_size + 1, offset=page * page_size)
    has_next = len(items) > page_size
    items = items[:page_size]
    if not items and page == 0:
        await cb.answer("Hali mijoz to'lovlari yo'q.", show_alert=True)
        return
    m_icons = {"cash": "💵", "card": "💳", "transfer": "🏦"}
    lines = [f"💵 <b>Mijoz To'lovlari Tarixi (Sahifa {page + 1})</b>\n"]
    for idx, p in enumerate(items, start=page * page_size + 1):
        dt = format_local_dt(p.created_at, "%d.%m %H:%M")
        cname = p.client.name if p.client else f"Mijoz #{p.client_id}"
        lines.append(
            f"{idx}) <code>{dt}</code> {m_icons.get(p.payment_method, '💵')} <b>{html.escape(cname)}</b> — +{format_uzs(p.amount)} so'm"
        )
    await cb.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=history_feed_kb("all_pays", page, has_next),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("export:"))
async def cb_export_excel(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    kind = parts[1]
    async with async_session_maker() as db:
        if kind == "daily":
            sess_id = int(parts[2])
            summary = await compute_session_summary(db, sess_id)
            debts = await list_all_client_debts(db)
            data = build_daily_norin_excel(summary, debts)
            filename = f"Norin_Hisobot_{summary.session.report_date}.xlsx"
        elif kind == "client":
            cid = int(parts[2])
            debt = await compute_client_debt(db, cid, history_limit=100)
            data = build_client_statement_excel(debt)
            safe_name = "".join(ch if ch.isalnum() else "_" for ch in debt.client.name).strip("_") or f"Mijoz_{cid}"
            filename = f"Sverka_{safe_name}.xlsx"
        elif kind == "history":
            sessions = await list_closed_sessions(db, limit=90)
            if not sessions:
                summary = await compute_session_summary(db)
                debts = await list_all_client_debts(db)
                data = build_daily_norin_excel(summary, debts)
                filename = f"Norin_Hisobot_{summary.session.report_date}.xlsx"
            else:
                data = build_history_excel(sessions)
                filename = "Norin_Kunlik_Tarix.xlsx"
        else:
            await cb.answer("Noma'lum eksport turi")
            return

    await cb.message.answer_document(
        BufferedInputFile(data, filename=filename),
        caption=f"📥 Tayyor Excel hisobot: <code>{filename}</code>",
        parse_mode="HTML",
    )
    await cb.answer("✅ Excel tayyor!")

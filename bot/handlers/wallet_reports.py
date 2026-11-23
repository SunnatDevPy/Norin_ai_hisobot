"""Read-only Daily & Period Dashboards, Debts Archive feeds, and Excel exports."""

from __future__ import annotations

import asyncio
import html
import logging
from datetime import date, timedelta
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.handlers.clients_products import is_authorized_async
from bot.keyboards import (
    BTN_CLOSE_DAY,
    BTN_DAILY_REPORT,
    BTN_DASHBOARDS,
    BTN_EXPENSE_KASSA,
    daily_report_kb,
    history_detail_kb,
    history_feed_kb,
    history_sessions_kb,
    main_menu_keyboard,
    period_report_kb,
)
from bot.ui_helpers import fast_edit, send_inline_panel
from database.crud import (
    DailyReportSummary,
    PeriodReportSummary,
    compute_client_debt,
    compute_period_summary,
    compute_session_summary,
    format_local_dt,
    get_period_excel_data,
    get_subscription_state,
    list_all_client_debts,
    list_all_sessions,
    list_closed_sessions,
    list_recent_client_payments,
    list_recent_sales,
    today_iso,
)
from database.session import async_session_maker
from services.excel_export import (
    build_client_statement_excel,
    build_daily_norin_excel,
    build_history_excel,
    build_period_excel,
)
from services.gemini_ai import format_kg, format_uzs


router = Router(name="wallet_reports")
logger = logging.getLogger("norin_bot.wallet")


def _apk_redirect_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 Mobil ilova (APK)", callback_data="apk:home")],
            [InlineKeyboardButton(text="📊 Dashboardlar", callback_data="rep:today")],
            [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="menu:home")],
        ]
    )


def _calendar_month_bounds(which: str) -> tuple[str, str, str]:
    """Return (start_iso, end_iso, title) for 'cur' or 'prev' calendar month."""
    today_d = date.fromisoformat(today_iso())
    if which == "cur":
        start_d = today_d.replace(day=1)
        end_d = today_d
        return start_d.isoformat(), end_d.isoformat(), f"SHU OY ({start_d.strftime('%Y-%m')})"
    first_cur = today_d.replace(day=1)
    end_d = first_cur - timedelta(days=1)
    start_d = end_d.replace(day=1)
    return start_d.isoformat(), end_d.isoformat(), f"O'TGAN OY ({start_d.strftime('%Y-%m')})"


def _safe_file_part(raw: str, fallback: str = "Filial") -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in (raw or "")).strip("_")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned[:32] or fallback


def render_daily_report_text(summary: DailyReportSummary) -> str:
    """Format complete internal daily Norin sales, kg, cost, profit, cash, and client debt summary."""
    lines = [
        f"📊 <b>NORIN KUNLIK HISOBOT ({summary.session.report_date})</b>",
        "===============================",
    ]
    if summary.session.status == "open" and summary.session.report_date != today_iso():
        lines.append(
            f"⚠️ <i>Diqqat: {summary.session.report_date} smenasi hali yopilmagan! Kunni yakunlang.</i>"
        )
    lines.append(f"🥩 <b>Sotilgan mahsulotlar ({len(summary.confirmed_sales)} ta sotuv):</b>")
    if not summary.weight_by_product:
        lines.append("<i>Bugun hali tasdiqlangan sotuvlar yo'q</i>")
    else:
        for pname, kg in summary.weight_by_product.items():
            lines.append(f"  • {html.escape(pname)}: <b>{format_kg(kg)} kg</b>")
        lines.append(f"⚖️ Jami vazn: <b>{format_kg(summary.total_kg)} kg</b>")
    if summary.total_return_amount > 0:
        lines.append(
            f"↩️ Vozvrat (qaytgan): <b>-{format_kg(summary.total_return_kg)} kg (-{format_uzs(summary.total_return_amount)} so'm)</b>"
        )

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


def render_period_report_text(p: PeriodReportSummary, title: Optional[str] = None) -> str:
    """Format period/monthly aggregated Norin sales, profit, and cash flow report."""
    header = html.escape(title) if title else f"{p.days} KUNLIK YIG'MA HISOBOT"
    lines = [
        f"📆 <b>{header}</b>",
        f"🗓 Davr: <code>{p.start_date}</code> → <code>{p.end_date}</code>",
        "===============================",
        f"📦 Sotuvlar soni: <b>{p.sales_count} ta</b>",
        f"⚖️ Jami sotilgan vazn: <b>{format_kg(p.total_kg)} kg</b>",
    ]
    for pname, kg in p.weight_by_product.items():
        lines.append(f"  • {html.escape(pname)}: <b>{format_kg(kg)} kg</b>")
    if p.total_return_amount > 0:
        lines.append(
            f"↩️ Vozvrat ({p.returns_count} ta): <b>-{format_kg(p.total_return_kg)} kg (-{format_uzs(p.total_return_amount)} so'm)</b>"
        )
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


# ---------------------------------------------------------------------------
# Daily & Period Dashboards (Read-only)
# ---------------------------------------------------------------------------


@router.message(Command("dashboard"), F.chat.type == "private")
@router.message(F.text.in_({BTN_DASHBOARDS, BTN_DAILY_REPORT}), F.chat.type == "private")
async def handle_daily_report_btn(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    await state.clear()
    async with async_session_maker() as db:
        summary = await compute_session_summary(db)
    await send_inline_panel(
        message,
        render_daily_report_text(summary),
        reply_markup=daily_report_kb(summary.session.id),
        delete_prev=False,
    )


@router.callback_query(F.data == "rep:today")
async def cb_report_today(cb: CallbackQuery) -> None:
    async with async_session_maker() as db:
        summary = await compute_session_summary(db)
    await fast_edit(
        cb,
        render_daily_report_text(summary),
        reply_markup=daily_report_kb(summary.session.id),
    )


@router.callback_query(F.data.startswith("rep:period:"))
async def cb_report_period(cb: CallbackQuery) -> None:
    days = int(cb.data.split(":")[-1])
    async with async_session_maker() as db:
        period = await compute_period_summary(db, days=days)
    await fast_edit(
        cb,
        render_period_report_text(period),
        reply_markup=period_report_kb(days=days),
    )


@router.callback_query(F.data.startswith("rep:month:"))
async def cb_report_month(cb: CallbackQuery) -> None:
    which = cb.data.split(":")[-1]
    if which not in ("cur", "prev"):
        await cb.answer("Noto'g'ri davr")
        return
    start_iso, end_iso, title = _calendar_month_bounds(which)
    async with async_session_maker() as db:
        period = await compute_period_summary(db, start_iso=start_iso, end_iso=end_iso)
    await fast_edit(
        cb,
        render_period_report_text(period, title=title),
        reply_markup=period_report_kb(period_key=which),
    )


# ---------------------------------------------------------------------------
# Archive / History Feeds (Read-only) & Excel Exports
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "set:history")
async def cb_history_list(cb: CallbackQuery) -> None:
    async with async_session_maker() as db:
        sessions = await list_all_sessions(db, limit=12)
    if not sessions:
        await cb.answer("Hozircha kunlik tarix yo'q.", show_alert=True)
        return
    await fast_edit(
        cb,
        "📜 <b>Kunlik Hisobotlar va Savdo Tarixi (Arxiv):</b>",
        reply_markup=history_sessions_kb(sessions),
    )


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
    await fast_edit(
        cb,
        text,
        reply_markup=history_detail_kb(sess_id, is_closed=is_closed),
    )


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
    await fast_edit(
        cb,
        "\n".join(lines),
        reply_markup=history_feed_kb("all_sales", page, has_next),
    )


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
    await fast_edit(
        cb,
        "\n".join(lines),
        reply_markup=history_feed_kb("all_pays", page, has_next),
    )


@router.callback_query(F.data.startswith("export:"))
async def cb_export_excel(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    kind = parts[1]
    if kind not in ("daily", "client", "period", "month", "history"):
        await cb.answer("Noma'lum eksport turi")
        return
    if kind == "month" and (parts[2] if len(parts) > 2 else "cur") not in ("cur", "prev"):
        await cb.answer("Noma'lum oy")
        return

    await cb.answer("⏳ Excel tayyorlanmoqda...")

    async with async_session_maker() as db:
        sub = await get_subscription_state(db)
        tenant_name = sub.tenant_name or "Norin Sexi"
        t_slug = _safe_file_part(tenant_name, "Filial")
        if kind == "daily":
            sess_id = int(parts[2])
            summary = await compute_session_summary(db, sess_id)
            debts = await list_all_client_debts(db)
            data = await asyncio.to_thread(
                build_daily_norin_excel, summary, debts, tenant_name=tenant_name
            )
            filename = f"{t_slug}_Hisobot_{summary.session.report_date}.xlsx"
        elif kind == "client":
            cid = int(parts[2])
            debt = await compute_client_debt(db, cid, history_limit=None)
            data = await asyncio.to_thread(
                build_client_statement_excel, debt, tenant_name=tenant_name
            )
            c_slug = _safe_file_part(debt.client.name, f"Mijoz_{cid}")
            filename = f"{t_slug}_Sverka_{c_slug}.xlsx"
        elif kind == "period":
            days = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 30
            pdata = await get_period_excel_data(db, days=days)
            data = await asyncio.to_thread(build_period_excel, pdata)
            filename = f"{t_slug}_{days}kunlik_{pdata['period'].start_date}_{pdata['period'].end_date}.xlsx"
        elif kind == "month":
            which = parts[2] if len(parts) > 2 else "cur"
            start_iso, end_iso, _ = _calendar_month_bounds(which)
            pdata = await get_period_excel_data(db, start_iso=start_iso, end_iso=end_iso)
            data = await asyncio.to_thread(build_period_excel, pdata)
            filename = f"{t_slug}_Oylik_{start_iso[:7]}.xlsx"
        else:
            sessions = await list_closed_sessions(db, limit=90)
            if not sessions:
                summary = await compute_session_summary(db)
                debts = await list_all_client_debts(db)
                data = await asyncio.to_thread(
                    build_daily_norin_excel, summary, debts, tenant_name=tenant_name
                )
                filename = f"{t_slug}_Hisobot_{summary.session.report_date}.xlsx"
            else:
                data = await asyncio.to_thread(
                    build_history_excel, sessions, tenant_name=tenant_name
                )
                filename = f"{t_slug}_Kunlik_Tarix.xlsx"

    await cb.message.answer_document(
        BufferedInputFile(data, filename=filename),
        caption=f"📥 Tayyor Excel hisobot: <code>{html.escape(filename)}</code>",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Legacy Expense / Close Day Buttons -> Redirect to Norin AI APK
# ---------------------------------------------------------------------------


@router.message(F.text.in_({BTN_EXPENSE_KASSA, BTN_CLOSE_DAY}), F.chat.type == "private")
async def redirect_legacy_kassa_to_apk(message: Message, state: FSMContext) -> None:
    if not await is_authorized_async(message.from_user.id if message.from_user else None):
        return
    await state.clear()
    await message.answer(
        "📱 <b>Kassa, xarajat va kunni yopish amallari Norin AI Android ilovasiga ko'chirildi.</b>\n\n"
        "Ilovada tez, qulay va jonli hisob bilan bajarishingiz mumkin.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    await message.answer(
        "📲 Ilovani yuklab olish yoki 1-bosishda ulanish uchun:",
        reply_markup=_apk_redirect_kb(),
    )


@router.callback_query(
    F.data.startswith("wal:") | F.data.startswith("close_day:") | F.data.startswith("hist:reopen:")
)
async def redirect_legacy_kassa_callbacks(cb: CallbackQuery) -> None:
    await cb.answer(
        "📱 Xarajat, kassa va kun yopish endi Norin AI APK ilovasida bajariladi.",
        show_alert=True,
    )

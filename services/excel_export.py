"""OpenPyXL Excel report generator for Norin AI daily profits, sales, client debts, and cash."""

from __future__ import annotations

import io
from typing import Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from database.crud import ClientDebtSummary, DailyReportSummary, format_local_dt
from database.models import DailyCashSession


HEADER_FILL = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
SUBHEADER_FILL = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
BOLD_FONT = Font(bold=True, size=11)
MONEY_FORMAT = "#,##0"
KG_FORMAT = "#,##0.###"


def _style_header_row(ws, row_idx: int, headers: Sequence[str]) -> None:
    """Apply consistent blue header styling to a table row."""
    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row_idx, column=col_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")


def build_daily_norin_excel(
    summary: DailyReportSummary,
    client_debts: Sequence[ClientDebtSummary],
) -> bytes:
    """
    Export full internal Norin daily report into a 4-sheet XLSX workbook:
    1. Kunlik Hisobot (KPIs, kg by product, profit, margin, cash)
    2. Sotuvlar (Kg) (itemized sales with cost & profit)
    3. Mijozlar Qarzi (debt ledger for all clients)
    4. Pul Oldi-Berdi (client payments, expenses, cash-in, kassa)
    """
    wb = Workbook()

    # Sheet 1: Kunlik Hisobot
    ws1 = wb.active
    ws1.title = "Kunlik Hisobot"
    ws1["A1"] = f"NORIN AI — KUNLIK HISOBOT ({summary.session.report_date})"
    ws1["A1"].font = Font(bold=True, size=13)

    overview = [
        ("Holati:", "Yopilgan" if summary.session.status == "closed" else "Ochiq"),
        ("Jami sotilgan vazn (kg):", round(summary.total_kg, 3)),
        ("Jami sotuv summasi (so'm):", round(summary.total_revenue)),
        ("Jami tannarx (so'm):", round(summary.total_cost)),
        ("Sof foyda (so'm):", round(summary.total_profit)),
        ("Marja (%):", f"{summary.margin_pct:.1f}%"),
        ("Kechadan naqd qoldiq:", round(summary.opening_balance)),
        ("Mijozlardan naqd tushum:", round(summary.client_cash_in)),
        ("Mijozlardan karta/Click tushum:", round(summary.client_card_in)),
        ("Mijozlardan perechesleniye:", round(summary.client_transfer_in)),
        ("Qo'shimcha kiritilgan pul:", round(summary.main_cash_in)),
        ("Kassadan olingan qarz:", round(summary.kassa_debt_today)),
        ("Kassaga qaytarilgan:", round(summary.kassa_repay_today)),
        ("Sex xarajatlari (rasxod):", round(summary.total_expenses)),
        ("Qo'lda qolishi kerak (naqd):", round(summary.expected_cash)),
        ("Sanalgan naqd pul:", round(summary.session.actual_counted_cash or 0)),
        ("Sverka farqi:", round(summary.session.difference or 0)),
        ("Barcha mijozlarning jami qarzi:", round(summary.total_all_clients_debt)),
    ]
    for idx, (lbl, val) in enumerate(overview, start=3):
        ws1.cell(row=idx, column=1, value=lbl).font = BOLD_FONT
        c = ws1.cell(row=idx, column=2, value=val)
        if isinstance(val, (int, float)):
            c.number_format = KG_FORMAT if "kg" in lbl.lower() else MONEY_FORMAT

    prod_row = len(overview) + 5
    ws1.cell(row=prod_row - 1, column=1, value="Mahsulotlar kesimida sotuv:").font = BOLD_FONT
    _style_header_row(ws1, prod_row, ["Mahsulot", "Sotilgan vazn (kg)"])
    for i, (pname, kg) in enumerate(summary.weight_by_product.items(), start=1):
        ws1.cell(row=prod_row + i, column=1, value=pname)
        c = ws1.cell(row=prod_row + i, column=2, value=round(kg, 3))
        c.number_format = KG_FORMAT

    ws1.column_dimensions["A"].width = 34
    ws1.column_dimensions["B"].width = 24

    # Sheet 2: Sotuvlar (Kg)
    ws2 = wb.create_sheet("Sotuvlar (Kg)")
    sale_headers = [
        "Sotuv #",
        "Vaqt",
        "Mijoz",
        "Mahsulot",
        "Kg",
        "Tarozi qismlari",
        "Narx/kg",
        "Jami summa",
        "Tannarx/kg",
        "Jami tannarx",
        "Sof foyda",
    ]
    _style_header_row(ws2, 1, sale_headers)
    r_idx = 2
    for s in summary.confirmed_sales:
        c_name = s.client.name if s.client else "Noma'lum"
        tm = format_local_dt(s.created_at, "%d.%m %H:%M") if s.created_at else ""
        for item in s.items:
            ws2.cell(row=r_idx, column=1, value=s.id)
            ws2.cell(row=r_idx, column=2, value=tm)
            ws2.cell(row=r_idx, column=3, value=c_name)
            ws2.cell(row=r_idx, column=4, value=item.product_name)
            c_kg = ws2.cell(row=r_idx, column=5, value=round(item.weight_kg, 3))
            c_kg.number_format = KG_FORMAT
            ws2.cell(row=r_idx, column=6, value=item.weights_detail or "")
            for col_i, num_val in (
                (7, item.unit_sell_price),
                (8, item.line_total),
                (9, item.unit_cost),
                (10, item.line_cost),
                (11, item.line_profit),
            ):
                cell = ws2.cell(row=r_idx, column=col_i, value=round(num_val))
                cell.number_format = MONEY_FORMAT
            r_idx += 1

    for col_letter, width in (
        ("A", 10),
        ("B", 16),
        ("C", 22),
        ("D", 24),
        ("E", 10),
        ("F", 20),
        ("G", 14),
        ("H", 16),
        ("I", 14),
        ("J", 16),
        ("K", 16),
    ):
        ws2.column_dimensions[col_letter].width = width

    # Sheet 3: Mijozlar Qarzi
    ws3 = wb.create_sheet("Mijozlar Qarzi")
    _style_header_row(
        ws3,
        1,
        ["#", "Mijoz", "Boshlang'ich qarz", "Jami yuk (so'm)", "Jami to'lagan", "Hozirgi qarz", "Jami kg"],
    )
    for idx, d in enumerate(client_debts, start=1):
        row_i = idx + 1
        ws3.cell(row=row_i, column=1, value=idx)
        ws3.cell(row=row_i, column=2, value=d.client.name)
        for col_i, val in (
            (3, d.opening_debt),
            (4, d.total_sales),
            (5, d.total_paid),
            (6, d.current_debt),
        ):
            c = ws3.cell(row=row_i, column=col_i, value=round(val))
            c.number_format = MONEY_FORMAT
        ck = ws3.cell(row=row_i, column=7, value=round(d.total_kg, 3))
        ck.number_format = KG_FORMAT

    for col_letter, width in (("A", 6), ("B", 24), ("C", 18), ("D", 18), ("E", 18), ("F", 18), ("G", 12)):
        ws3.column_dimensions[col_letter].width = width

    # Sheet 4: Pul Oldi-Berdi
    ws4 = wb.create_sheet("Pul Oldi-Berdi")
    _style_header_row(ws4, 1, ["Vaqt", "Turkum", "Kontragent / Izoh", "Usul", "Summa"])
    p_row = 2
    method_labels = {"cash": "Naqd", "card": "Karta", "transfer": "Perechesleniye"}
    for pay in summary.client_payments:
        tm = format_local_dt(pay.created_at, "%d.%m %H:%M") if pay.created_at else ""
        cname = pay.client.name if pay.client else f"Mijoz #{pay.client_id}"
        ws4.cell(row=p_row, column=1, value=tm)
        ws4.cell(row=p_row, column=2, value="Mijozdan to'lov")
        ws4.cell(row=p_row, column=3, value=f"{cname} {pay.note}".strip())
        ws4.cell(row=p_row, column=4, value=method_labels.get(pay.payment_method, pay.payment_method))
        c = ws4.cell(row=p_row, column=5, value=round(pay.amount))
        c.number_format = MONEY_FORMAT
        p_row += 1

    tx_labels = {
        "main_in": "Asosiy kirim",
        "expense": "Sex xarajati",
        "kassa_debt": "Kassadan qarz",
        "kassa_repay": "Kassaga qaytarish",
    }
    for tx in summary.cash_transactions:
        tm = format_local_dt(tx.created_at, "%d.%m %H:%M") if tx.created_at else ""
        ws4.cell(row=p_row, column=1, value=tm)
        ws4.cell(row=p_row, column=2, value=tx_labels.get(tx.source_type, tx.source_type))
        ws4.cell(row=p_row, column=3, value=tx.note or "-")
        ws4.cell(row=p_row, column=4, value="Naqd")
        c = ws4.cell(row=p_row, column=5, value=round(tx.amount))
        c.number_format = MONEY_FORMAT
        p_row += 1

    for col_letter, width in (("A", 16), ("B", 22), ("C", 32), ("D", 16), ("E", 18)):
        ws4.column_dimensions[col_letter].width = width

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_client_statement_excel(debt_summary: ClientDebtSummary) -> bytes:
    """
    Export a client-facing Akt Sverka workbook.

    IMPORTANT: Strictly omits internal cost_price and profit columns so this file
    can be sent directly to the client without leaking margins.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Akt Sverka"
    cli = debt_summary.client

    ws["A1"] = f"AKT SVERKA — {cli.name}"
    ws["A1"].font = Font(bold=True, size=13)

    summary_rows = [
        ("Mijoz:", cli.name),
        ("Telefon:", cli.phone or "-"),
        ("Boshlang'ich qarz:", round(debt_summary.opening_debt)),
        ("Jami olgan mahsuloti (kg):", round(debt_summary.total_kg, 3)),
        ("Jami yuk summasi (so'm):", round(debt_summary.total_sales)),
        ("Jami to'lagan summasi (so'm):", round(debt_summary.total_paid)),
        ("Hozirgi qarz qoldig'i (so'm):", round(debt_summary.current_debt)),
    ]
    for idx, (lbl, val) in enumerate(summary_rows, start=3):
        ws.cell(row=idx, column=1, value=lbl).font = BOLD_FONT
        c = ws.cell(row=idx, column=2, value=val)
        if isinstance(val, (int, float)):
            c.number_format = KG_FORMAT if "kg" in lbl.lower() else MONEY_FORMAT

    start_row = 12
    _style_header_row(
        ws,
        start_row,
        ["Sana / Vaqt", "Chek #", "Mahsulot", "Kg", "Tarozi qismlari", "Narx/kg", "Jami summa"],
    )
    r_idx = start_row + 1
    for sale in debt_summary.recent_sales:
        tm = format_local_dt(sale.created_at, "%d.%m.%Y %H:%M") if sale.created_at else sale.report_date
        for item in sale.items:
            ws.cell(row=r_idx, column=1, value=tm)
            ws.cell(row=r_idx, column=2, value=sale.id)
            ws.cell(row=r_idx, column=3, value=item.product_name)
            ck = ws.cell(row=r_idx, column=4, value=round(item.weight_kg, 3))
            ck.number_format = KG_FORMAT
            ws.cell(row=r_idx, column=5, value=item.weights_detail or "")
            cp = ws.cell(row=r_idx, column=6, value=round(item.unit_sell_price))
            cp.number_format = MONEY_FORMAT
            ct = ws.cell(row=r_idx, column=7, value=round(item.line_total))
            ct.number_format = MONEY_FORMAT
            r_idx += 1

    for col_letter, width in (("A", 18), ("B", 10), ("C", 24), ("D", 10), ("E", 20), ("F", 15), ("G", 18)):
        ws.column_dimensions[col_letter].width = width

    ws_pay = wb.create_sheet("To'lovlar")
    _style_header_row(ws_pay, 1, ["Sana / Vaqt", "Usul", "Summa", "Izoh"])
    method_labels = {"cash": "Naqd", "card": "Karta", "transfer": "Perechesleniye"}
    for idx, pay in enumerate(debt_summary.recent_payments, start=2):
        tm = format_local_dt(pay.created_at, "%d.%m.%Y %H:%M") if pay.created_at else ""
        ws_pay.cell(row=idx, column=1, value=tm)
        ws_pay.cell(row=idx, column=2, value=method_labels.get(pay.payment_method, pay.payment_method))
        ca = ws_pay.cell(row=idx, column=3, value=round(pay.amount))
        ca.number_format = MONEY_FORMAT
        ws_pay.cell(row=idx, column=4, value=pay.note or "")

    for col_letter, width in (("A", 18), ("B", 16), ("C", 18), ("D", 30)):
        ws_pay.column_dimensions[col_letter].width = width

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_history_excel(sessions: Sequence[DailyCashSession]) -> bytes:
    """Export closed daily session history list into XLSX bytes."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Kunlik Tarix"

    headers = [
        "ID",
        "Sana",
        "Boshlang'ich qoldiq",
        "Qolishi kerak edi",
        "Sanalgan pul",
        "Farq",
        "Yopilgan vaqt",
    ]
    _style_header_row(ws, 1, headers)

    for i, sess in enumerate(sessions, start=2):
        ws.cell(row=i, column=1, value=sess.id)
        ws.cell(row=i, column=2, value=sess.report_date)
        for col_i, val in (
            (3, sess.opening_balance),
            (4, sess.expected_cash),
            (5, sess.actual_counted_cash or 0),
            (6, sess.difference or 0),
        ):
            c = ws.cell(row=i, column=col_i, value=round(val))
            c.number_format = MONEY_FORMAT
        ws.cell(
            row=i,
            column=7,
            value=format_local_dt(sess.closed_at, "%Y-%m-%d %H:%M") if sess.closed_at else "",
        )

    for col_letter in ("A", "B", "C", "D", "E", "F", "G"):
        ws.column_dimensions[col_letter].width = 20

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

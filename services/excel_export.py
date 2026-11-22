"""OpenPyXL Excel report generator for Norin AI daily profits, period analytics, client statements, and cash history."""

from __future__ import annotations

import io
from typing import Any, Dict, List, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from database.crud import ClientDebtSummary, DailyReportSummary, format_local_dt, to_utc_dt
from database.models import DailyCashSession


HEADER_FILL = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
SUBHEADER_FILL = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
ZEBRA_FILL = PatternFill(start_color="F5F8FC", end_color="F5F8FC", fill_type="solid")
TOTAL_FILL = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")

HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
BOLD_FONT = Font(bold=True, size=11)
GREEN_FONT = Font(color="006100", bold=True, size=11)
RED_FONT = Font(color="9C0006", bold=True, size=11)

THIN_SIDE = Side(style="thin", color="D9D9D9")
TOTAL_TOP_SIDE = Side(style="medium", color="1F4E78")
TOTAL_BOTTOM_SIDE = Side(style="double", color="1F4E78")

THIN_BORDER = Border(left=THIN_SIDE, right=THIN_SIDE, top=THIN_SIDE, bottom=THIN_SIDE)
TOTAL_BORDER = Border(
    left=THIN_SIDE, right=THIN_SIDE, top=TOTAL_TOP_SIDE, bottom=TOTAL_BOTTOM_SIDE
)

MONEY_FORMAT = "#,##0"
KG_FORMAT = "#,##0.###"
PERCENT_FORMAT = "0.0%"


def _style_header_row(ws, row_idx: int, headers: Sequence[str]) -> None:
    """Apply consistent blue header styling to a table row."""
    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row_idx, column=col_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = THIN_BORDER
    ws.row_dimensions[row_idx].height = 22


def _style_data_row(ws, row_idx: int, max_col: int, zebra: bool = False) -> None:
    """Apply thin grid borders and optional zebra striping across a row."""
    for col_idx in range(1, max_col + 1):
        cell = ws.cell(row=row_idx, column=col_idx)
        cell.border = THIN_BORDER
        if zebra:
            cell.fill = ZEBRA_FILL


def _style_total_row(ws, row_idx: int, max_col: int) -> None:
    """Highlight bottom JAMI totals row with bold font and top/double-bottom borders."""
    for col_idx in range(1, max_col + 1):
        cell = ws.cell(row=row_idx, column=col_idx)
        cell.fill = TOTAL_FILL
        cell.border = TOTAL_BORDER
        cell.font = BOLD_FONT
    ws.row_dimensions[row_idx].height = 21


def _apply_print_and_grid(
    ws,
    freeze_cell: str = "A2",
    filter_ref: str | None = None,
    landscape: bool = True,
) -> None:
    """Configure freeze panes, auto-filter, and fit-to-1-page-wide A4 print layout."""
    if freeze_cell:
        ws.freeze_panes = freeze_cell
    if filter_ref:
        ws.auto_filter.ref = filter_ref
    ws.page_setup.orientation = (
        ws.ORIENTATION_LANDSCAPE if landscape else ws.ORIENTATION_PORTRAIT
    )
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0


def build_daily_norin_excel(
    summary: DailyReportSummary,
    client_debts: Sequence[ClientDebtSummary],
    tenant_name: str = "Norin Sexi",
) -> bytes:
    """
    Export full internal Norin daily report into a 4-sheet XLSX workbook:
    1. Kunlik Hisobot (KPIs, kg by product with =SUM, profit, margin, cash)
    2. Sotuvlar (Kg) (itemized sales with live Excel formulas & JAMI row)
    3. Mijozlar Qarzi (debt ledger with phone, last payment date & JAMI row)
    4. Pul Oldi-Berdi (split Kirim/Chiqim columns, categories & JAMI row)
    """
    wb = Workbook()
    clean_tenant = (tenant_name or "Norin Sexi").strip()

    # ------------------------------------------------------------------
    # Sheet 1: Kunlik Hisobot
    # ------------------------------------------------------------------
    ws1 = wb.active
    ws1.title = "Kunlik Hisobot"
    ws1["A1"] = f"{clean_tenant.upper()} — KUNLIK HISOBOT ({summary.session.report_date})"
    ws1["A1"].font = Font(bold=True, size=13, color="1F4E78")

    diff_val = round(summary.session.difference or 0)
    overview = [
        ("Holati:", "Yopilgan" if summary.session.status == "closed" else "Ochiq"),
        ("Jami sotilgan vazn (kg):", round(summary.total_kg, 3)),
        ("Jami sotuv summasi (so'm):", round(summary.total_revenue)),
        ("Jami tannarx (so'm):", round(summary.total_cost)),
        ("Sof foyda (so'm):", round(summary.total_profit)),
        ("Marja (%):", round(summary.margin_pct, 2) / 100.0),
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
        ("Sverka farqi:", diff_val),
        ("Barcha mijozlarning jami qarzi:", round(summary.total_all_clients_debt)),
    ]
    for idx, (lbl, val) in enumerate(overview, start=3):
        c_lbl = ws1.cell(row=idx, column=1, value=lbl)
        c_lbl.font = BOLD_FONT
        c = ws1.cell(row=idx, column=2, value=val)
        _style_data_row(ws1, idx, 2, zebra=(idx % 2 == 0))
        if isinstance(val, (int, float)):
            if "Marja" in lbl:
                c.number_format = PERCENT_FORMAT
            elif "kg" in lbl.lower():
                c.number_format = KG_FORMAT
            else:
                c.number_format = MONEY_FORMAT
        if lbl == "Sof foyda (so'm):":
            c.font = GREEN_FONT if summary.total_profit >= 0 else RED_FONT
        elif lbl == "Sverka farqi:" and diff_val != 0:
            c.font = GREEN_FONT if diff_val > 0 else RED_FONT

    prod_row = len(overview) + 5
    ws1.cell(row=prod_row - 1, column=1, value="Mahsulotlar kesimida sotuv:").font = BOLD_FONT
    _style_header_row(ws1, prod_row, ["Mahsulot", "Sotilgan vazn (kg)"])
    first_prod_r = prod_row + 1
    p_cur = first_prod_r
    for pname, kg in summary.weight_by_product.items():
        ws1.cell(row=p_cur, column=1, value=pname)
        c = ws1.cell(row=p_cur, column=2, value=round(kg, 3))
        c.number_format = KG_FORMAT
        _style_data_row(ws1, p_cur, 2, zebra=(p_cur % 2 == 0))
        p_cur += 1

    ws1.cell(row=p_cur, column=1, value="JAMI:")
    c_tot_kg = ws1.cell(
        row=p_cur,
        column=2,
        value=f"=SUM(B{first_prod_r}:B{p_cur - 1})" if p_cur > first_prod_r else 0,
    )
    c_tot_kg.number_format = KG_FORMAT
    _style_total_row(ws1, p_cur, 2)

    ws1.column_dimensions["A"].width = 36
    ws1.column_dimensions["B"].width = 24
    _apply_print_and_grid(ws1, freeze_cell="A3", landscape=False)

    # ------------------------------------------------------------------
    # Sheet 2: Sotuvlar (Kg)
    # ------------------------------------------------------------------
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
            c_sell = ws2.cell(row=r_idx, column=7, value=round(item.unit_sell_price))
            c_sell.number_format = MONEY_FORMAT
            c_tot = ws2.cell(row=r_idx, column=8, value=f"=ROUND(E{r_idx}*G{r_idx},0)")
            c_tot.number_format = MONEY_FORMAT
            c_uc = ws2.cell(row=r_idx, column=9, value=round(item.unit_cost))
            c_uc.number_format = MONEY_FORMAT
            c_cost = ws2.cell(row=r_idx, column=10, value=f"=ROUND(E{r_idx}*I{r_idx},0)")
            c_cost.number_format = MONEY_FORMAT
            c_prof = ws2.cell(row=r_idx, column=11, value=f"=H{r_idx}-J{r_idx}")
            c_prof.number_format = MONEY_FORMAT
            c_prof.font = GREEN_FONT if item.line_profit >= 0 else RED_FONT
            _style_data_row(ws2, r_idx, 11, zebra=(r_idx % 2 == 1))
            r_idx += 1

    last_sale_row = r_idx - 1
    ws2.cell(row=r_idx, column=1, value="JAMI:")
    if last_sale_row >= 2:
        ws2.cell(row=r_idx, column=5, value=f"=SUM(E2:E{last_sale_row})").number_format = KG_FORMAT
        ws2.cell(row=r_idx, column=8, value=f"=SUM(H2:H{last_sale_row})").number_format = MONEY_FORMAT
        ws2.cell(row=r_idx, column=10, value=f"=SUM(J2:J{last_sale_row})").number_format = MONEY_FORMAT
        ws2.cell(row=r_idx, column=11, value=f"=SUM(K2:K{last_sale_row})").number_format = MONEY_FORMAT
    else:
        for col_i, fmt in ((5, KG_FORMAT), (8, MONEY_FORMAT), (10, MONEY_FORMAT), (11, MONEY_FORMAT)):
            c = ws2.cell(row=r_idx, column=col_i, value=0)
            c.number_format = fmt
    _style_total_row(ws2, r_idx, 11)

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
    _apply_print_and_grid(ws2, freeze_cell="A2", filter_ref=f"A1:K{max(1, last_sale_row)}")

    # ------------------------------------------------------------------
    # Sheet 3: Mijozlar Qarzi
    # ------------------------------------------------------------------
    ws3 = wb.create_sheet("Mijozlar Qarzi")
    _style_header_row(
        ws3,
        1,
        [
            "#",
            "Mijoz",
            "Telefon",
            "Boshlang'ich qarz",
            "Jami yuk (so'm)",
            "Jami to'lagan",
            "Hozirgi qarz",
            "Jami kg",
            "Oxirgi to'lov",
        ],
    )
    d_row = 2
    for idx, d in enumerate(client_debts, start=1):
        ws3.cell(row=d_row, column=1, value=idx)
        ws3.cell(row=d_row, column=2, value=d.client.name)
        ws3.cell(row=d_row, column=3, value=d.client.phone or "-")
        for col_i, val in (
            (4, d.opening_debt),
            (5, d.total_sales),
            (6, d.total_paid),
            (7, d.current_debt),
        ):
            c = ws3.cell(row=d_row, column=col_i, value=round(val))
            c.number_format = MONEY_FORMAT
            if col_i == 7 and val > 0:
                c.font = RED_FONT
        ck = ws3.cell(row=d_row, column=8, value=round(d.total_kg, 3))
        ck.number_format = KG_FORMAT
        last_dt = d.last_payment_at or (
            d.recent_payments[0].created_at if d.recent_payments else None
        )
        last_pay_str = format_local_dt(last_dt, "%d.%m.%Y") if last_dt else "-"
        ws3.cell(row=d_row, column=9, value=last_pay_str)
        _style_data_row(ws3, d_row, 9, zebra=(d_row % 2 == 1))
        d_row += 1

    last_debt_row = d_row - 1
    ws3.cell(row=d_row, column=2, value="JAMI:")
    for col_i, col_ltr, fmt in (
        (4, "D", MONEY_FORMAT),
        (5, "E", MONEY_FORMAT),
        (6, "F", MONEY_FORMAT),
        (7, "G", MONEY_FORMAT),
        (8, "H", KG_FORMAT),
    ):
        c = ws3.cell(
            row=d_row,
            column=col_i,
            value=f"=SUM({col_ltr}2:{col_ltr}{last_debt_row})" if last_debt_row >= 2 else 0,
        )
        c.number_format = fmt
    _style_total_row(ws3, d_row, 9)

    for col_letter, width in (
        ("A", 6),
        ("B", 24),
        ("C", 16),
        ("D", 18),
        ("E", 18),
        ("F", 18),
        ("G", 18),
        ("H", 12),
        ("I", 15),
    ):
        ws3.column_dimensions[col_letter].width = width
    _apply_print_and_grid(ws3, freeze_cell="A2", filter_ref=f"A1:I{max(1, last_debt_row)}")

    # ------------------------------------------------------------------
    # Sheet 4: Pul Oldi-Berdi
    # ------------------------------------------------------------------
    ws4 = wb.create_sheet("Pul Oldi-Berdi")
    _style_header_row(
        ws4,
        1,
        ["Vaqt", "Turkum", "Kategoriya", "Kontragent / Izoh", "Usul", "Kirim (+)", "Chiqim (-)"],
    )
    p_row = 2
    method_labels = {"cash": "Naqd", "card": "Karta", "transfer": "Perechesleniye"}
    for pay in summary.client_payments:
        tm = format_local_dt(pay.created_at, "%d.%m %H:%M") if pay.created_at else ""
        cname = pay.client.name if pay.client else f"Mijoz #{pay.client_id}"
        ws4.cell(row=p_row, column=1, value=tm)
        ws4.cell(row=p_row, column=2, value="Mijozdan to'lov")
        ws4.cell(row=p_row, column=3, value="Savdo tushumi")
        ws4.cell(row=p_row, column=4, value=f"{cname} {pay.note}".strip())
        ws4.cell(row=p_row, column=5, value=method_labels.get(pay.payment_method, pay.payment_method))
        cin = ws4.cell(row=p_row, column=6, value=round(pay.amount))
        cin.number_format = MONEY_FORMAT
        cin.font = GREEN_FONT
        cout = ws4.cell(row=p_row, column=7, value=0)
        cout.number_format = MONEY_FORMAT
        _style_data_row(ws4, p_row, 7, zebra=(p_row % 2 == 1))
        p_row += 1

    tx_labels = {
        "main_in": "Asosiy kirim",
        "expense": "Sex xarajati",
        "kassa_debt": "Kassadan qarz",
        "kassa_repay": "Kassaga qaytarish",
    }
    for tx in summary.cash_transactions:
        tm = format_local_dt(tx.created_at, "%d.%m %H:%M") if tx.created_at else ""
        is_out = tx.source_type in ("expense", "kassa_repay")
        ws4.cell(row=p_row, column=1, value=tm)
        ws4.cell(row=p_row, column=2, value=tx_labels.get(tx.source_type, tx.source_type))
        ws4.cell(row=p_row, column=3, value=(tx.category or "Boshqa") if tx.source_type == "expense" else "-")
        ws4.cell(row=p_row, column=4, value=tx.note or "-")
        ws4.cell(row=p_row, column=5, value="Naqd")
        cin = ws4.cell(row=p_row, column=6, value=0 if is_out else round(tx.amount))
        cin.number_format = MONEY_FORMAT
        cout = ws4.cell(row=p_row, column=7, value=round(tx.amount) if is_out else 0)
        cout.number_format = MONEY_FORMAT
        if is_out:
            cout.font = RED_FONT
        else:
            cin.font = GREEN_FONT
        _style_data_row(ws4, p_row, 7, zebra=(p_row % 2 == 1))
        p_row += 1

    last_pay_row = p_row - 1
    ws4.cell(row=p_row, column=1, value="JAMI:")
    ws4.cell(
        row=p_row,
        column=6,
        value=f"=SUM(F2:F{last_pay_row})" if last_pay_row >= 2 else 0,
    ).number_format = MONEY_FORMAT
    ws4.cell(
        row=p_row,
        column=7,
        value=f"=SUM(G2:G{last_pay_row})" if last_pay_row >= 2 else 0,
    ).number_format = MONEY_FORMAT
    _style_total_row(ws4, p_row, 7)

    for col_letter, width in (
        ("A", 16),
        ("B", 20),
        ("C", 16),
        ("D", 32),
        ("E", 16),
        ("F", 16),
        ("G", 16),
    ):
        ws4.column_dimensions[col_letter].width = width
    _apply_print_and_grid(ws4, freeze_cell="A2", filter_ref=f"A1:G{max(1, last_pay_row)}")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_client_statement_excel(
    debt_summary: ClientDebtSummary,
    tenant_name: str = "Norin Sexi",
) -> bytes:
    """
    Export a client-facing Akt Sverka workbook with chronological running balance.

    IMPORTANT: Strictly omits internal cost_price and profit columns so this file
    can be sent directly to the client without leaking margins.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Akt Sverka"
    cli = debt_summary.client
    clean_tenant = (tenant_name or "Norin Sexi").strip()

    ws["A1"] = f"AKT SVERKA — {cli.name} ({clean_tenant})"
    ws["A1"].font = Font(bold=True, size=13, color="1F4E78")

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
        _style_data_row(ws, idx, 2, zebra=(idx % 2 == 0))
        if isinstance(val, (int, float)):
            c.number_format = KG_FORMAT if "kg" in lbl.lower() else MONEY_FORMAT
        if lbl == "Hozirgi qarz qoldig'i (so'm):" and debt_summary.current_debt > 0:
            c.font = RED_FONT

    start_row = 12
    _style_header_row(
        ws,
        start_row,
        [
            "Sana / Vaqt",
            "Hujjat",
            "Tafsilot / Mahsulot",
            "Kg",
            "Narx/kg",
            "Debet (Yuk +)",
            "Kredit (To'lov -)",
            "Qoldiq qarz",
        ],
    )

    # Row 13: Boshlang'ich qoldiq anchor for live running-balance formulas
    init_row = start_row + 1
    ws.cell(row=init_row, column=1, value="-")
    ws.cell(row=init_row, column=2, value="Saldo")
    ws.cell(row=init_row, column=3, value="Boshlang'ich qarz qoldig'i")
    c_init = ws.cell(row=init_row, column=8, value=round(debt_summary.opening_debt))
    c_init.number_format = MONEY_FORMAT
    c_init.font = BOLD_FONT
    _style_data_row(ws, init_row, 8, zebra=False)

    method_labels = {"cash": "Naqd", "card": "Karta", "transfer": "Perechesleniye"}
    events: List[tuple] = []
    for sale in debt_summary.recent_sales:
        dt_sort = to_utc_dt(sale.created_at)
        tm = format_local_dt(sale.created_at, "%d.%m.%Y %H:%M") if sale.created_at else sale.report_date
        for item in sale.items:
            bd = f" ({item.weights_detail})" if item.weights_detail else ""
            events.append(
                (
                    dt_sort,
                    0,
                    sale.id,
                    tm,
                    f"Yuk #{sale.id}",
                    f"{item.product_name}{bd}",
                    round(item.weight_kg, 3),
                    round(item.unit_sell_price),
                    round(item.line_total),
                    0,
                )
            )
    for pay in debt_summary.recent_payments:
        dt_sort = to_utc_dt(pay.created_at)
        tm = format_local_dt(pay.created_at, "%d.%m.%Y %H:%M") if pay.created_at else ""
        mlbl = method_labels.get(pay.payment_method, pay.payment_method)
        note_str = f" — {pay.note}" if pay.note else ""
        events.append(
            (
                dt_sort,
                1,
                pay.id,
                tm,
                f"To'lov #{pay.id}",
                f"To'lov ({mlbl}){note_str}",
                None,
                None,
                0,
                round(pay.amount),
            )
        )

    events.sort(key=lambda e: (e[0], e[1], e[2]))

    r_idx = init_row + 1
    for _, _, _, tm, doc_ref, detail, kg_val, price_val, debet_val, kredit_val in events:
        ws.cell(row=r_idx, column=1, value=tm)
        ws.cell(row=r_idx, column=2, value=doc_ref)
        ws.cell(row=r_idx, column=3, value=detail)
        if kg_val is not None:
            ck = ws.cell(row=r_idx, column=4, value=kg_val)
            ck.number_format = KG_FORMAT
        if price_val is not None:
            cp = ws.cell(row=r_idx, column=5, value=price_val)
            cp.number_format = MONEY_FORMAT
        cd = ws.cell(row=r_idx, column=6, value=debet_val)
        cd.number_format = MONEY_FORMAT
        ckr = ws.cell(row=r_idx, column=7, value=kredit_val)
        ckr.number_format = MONEY_FORMAT
        if kredit_val > 0:
            ckr.font = GREEN_FONT
        cbal = ws.cell(row=r_idx, column=8, value=f"=H{r_idx - 1}+F{r_idx}-G{r_idx}")
        cbal.number_format = MONEY_FORMAT
        _style_data_row(ws, r_idx, 8, zebra=(r_idx % 2 == 1))
        r_idx += 1

    last_ev_row = r_idx - 1
    first_ev_row = init_row + 1
    ws.cell(row=r_idx, column=3, value="JAMI:")
    if last_ev_row >= first_ev_row:
        ws.cell(row=r_idx, column=4, value=f"=SUM(D{first_ev_row}:D{last_ev_row})").number_format = KG_FORMAT
        ws.cell(row=r_idx, column=6, value=f"=SUM(F{first_ev_row}:F{last_ev_row})").number_format = MONEY_FORMAT
        ws.cell(row=r_idx, column=7, value=f"=SUM(G{first_ev_row}:G{last_ev_row})").number_format = MONEY_FORMAT
        c_end = ws.cell(row=r_idx, column=8, value=f"=H{last_ev_row}")
    else:
        ws.cell(row=r_idx, column=4, value=0).number_format = KG_FORMAT
        ws.cell(row=r_idx, column=6, value=0).number_format = MONEY_FORMAT
        ws.cell(row=r_idx, column=7, value=0).number_format = MONEY_FORMAT
        c_end = ws.cell(row=r_idx, column=8, value=f"=H{init_row}")
    c_end.number_format = MONEY_FORMAT
    _style_total_row(ws, r_idx, 8)

    for col_letter, width in (
        ("A", 18),
        ("B", 13),
        ("C", 32),
        ("D", 10),
        ("E", 14),
        ("F", 16),
        ("G", 16),
        ("H", 18),
    ):
        ws.column_dimensions[col_letter].width = width
    _apply_print_and_grid(ws, freeze_cell="A13", filter_ref=f"A12:H{max(13, last_ev_row)}")

    # Sheet 2: To'lovlar
    ws_pay = wb.create_sheet("To'lovlar")
    _style_header_row(ws_pay, 1, ["Sana / Vaqt", "Usul", "Summa", "Izoh"])
    pr = 2
    for pay in debt_summary.recent_payments:
        tm = format_local_dt(pay.created_at, "%d.%m.%Y %H:%M") if pay.created_at else ""
        ws_pay.cell(row=pr, column=1, value=tm)
        ws_pay.cell(row=pr, column=2, value=method_labels.get(pay.payment_method, pay.payment_method))
        ca = ws_pay.cell(row=pr, column=3, value=round(pay.amount))
        ca.number_format = MONEY_FORMAT
        ws_pay.cell(row=pr, column=4, value=pay.note or "")
        _style_data_row(ws_pay, pr, 4, zebra=(pr % 2 == 1))
        pr += 1

    last_pr = pr - 1
    ws_pay.cell(row=pr, column=1, value="JAMI:")
    ws_pay.cell(
        row=pr,
        column=3,
        value=f"=SUM(C2:C{last_pr})" if last_pr >= 2 else 0,
    ).number_format = MONEY_FORMAT
    _style_total_row(ws_pay, pr, 4)

    for col_letter, width in (("A", 18), ("B", 16), ("C", 18), ("D", 32)):
        ws_pay.column_dimensions[col_letter].width = width
    _apply_print_and_grid(ws_pay, freeze_cell="A2", filter_ref=f"A1:D{max(1, last_pr)}")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_period_excel(period_data: Dict[str, Any]) -> bytes:
    """
    Export multi-day/monthly analytics workbook with 4 sheets:
    1. Davriy Hisobot (KPIs & product breakdown)
    2. Kunma-kun Dinamika (date-by-date kg, revenue, cost, profit, expenses)
    3. Mijozlar Reytingi (client ranking by revenue & profit)
    4. Xarajatlar (categorized expenses)
    """
    wb = Workbook()
    p = period_data["period"]
    clean_tenant = (period_data.get("tenant_name") or "Norin Sexi").strip()
    daily_rows = period_data.get("daily_rows") or []
    client_stats = period_data.get("client_stats") or []
    expenses = period_data.get("expenses") or []

    # Sheet 1: Davriy Hisobot
    ws1 = wb.active
    ws1.title = "Davriy Hisobot"
    ws1["A1"] = f"{clean_tenant.upper()} — DAVRIY HISOBOT ({p.start_date} .. {p.end_date})"
    ws1["A1"].font = Font(bold=True, size=13, color="1F4E78")

    kpis = [
        ("Davr (kunlar):", p.days),
        ("Tasdiqlangan sotuvlar soni:", p.sales_count),
        ("Jami sotilgan vazn (kg):", round(p.total_kg, 3)),
        ("Umumiy tushum (so'm):", round(p.total_revenue)),
        ("Umumiy tannarx (so'm):", round(p.total_cost)),
        ("Sof foyda (so'm):", round(p.total_profit)),
        ("Marja (%):", round(p.margin_pct, 2) / 100.0),
        ("Yig'ilgan naqd pul:", round(p.total_cash_collected)),
        ("Yig'ilgan karta/Click:", round(p.total_card_collected)),
        ("Perechesleniye:", round(p.total_transfer_collected)),
        ("Jami xarajatlar:", round(p.total_expenses)),
        ("Hozirgi jami mijoz qarzlari:", round(p.total_all_clients_debt)),
    ]
    for idx, (lbl, val) in enumerate(kpis, start=3):
        ws1.cell(row=idx, column=1, value=lbl).font = BOLD_FONT
        c = ws1.cell(row=idx, column=2, value=val)
        _style_data_row(ws1, idx, 2, zebra=(idx % 2 == 0))
        if isinstance(val, (int, float)):
            if "Marja" in lbl:
                c.number_format = PERCENT_FORMAT
            elif "kg" in lbl.lower():
                c.number_format = KG_FORMAT
            else:
                c.number_format = MONEY_FORMAT
        if lbl == "Sof foyda (so'm):":
            c.font = GREEN_FONT if p.total_profit >= 0 else RED_FONT

    pr_hdr = len(kpis) + 5
    ws1.cell(row=pr_hdr - 1, column=1, value="Mahsulotlar kesimida sotuv:").font = BOLD_FONT
    _style_header_row(ws1, pr_hdr, ["Mahsulot", "Jami kg"])
    r_p = pr_hdr + 1
    for pname, kg in p.weight_by_product.items():
        ws1.cell(row=r_p, column=1, value=pname)
        c = ws1.cell(row=r_p, column=2, value=round(kg, 3))
        c.number_format = KG_FORMAT
        _style_data_row(ws1, r_p, 2, zebra=(r_p % 2 == 1))
        r_p += 1
    ws1.cell(row=r_p, column=1, value="JAMI:")
    ws1.cell(
        row=r_p,
        column=2,
        value=f"=SUM(B{pr_hdr + 1}:B{r_p - 1})" if r_p > pr_hdr + 1 else 0,
    ).number_format = KG_FORMAT
    _style_total_row(ws1, r_p, 2)
    ws1.column_dimensions["A"].width = 36
    ws1.column_dimensions["B"].width = 24
    _apply_print_and_grid(ws1, freeze_cell="A3", landscape=False)

    # Sheet 2: Kunma-kun Dinamika
    ws2 = wb.create_sheet("Kunma-kun Dinamika")
    _style_header_row(
        ws2,
        1,
        ["Sana", "Holat", "Sotuvlar", "Kg", "Tushum", "Tannarx", "Sof foyda", "Marja", "Yig'ilgan pul", "Xarajatlar"],
    )
    dr = 2
    for row in daily_rows:
        ws2.cell(row=dr, column=1, value=row["report_date"])
        ws2.cell(row=dr, column=2, value=row["status"])
        ws2.cell(row=dr, column=3, value=row["sales_count"]).number_format = MONEY_FORMAT
        ws2.cell(row=dr, column=4, value=round(row["total_kg"], 3)).number_format = KG_FORMAT
        ws2.cell(row=dr, column=5, value=round(row["total_revenue"])).number_format = MONEY_FORMAT
        ws2.cell(row=dr, column=6, value=round(row["total_cost"])).number_format = MONEY_FORMAT
        cf = ws2.cell(row=dr, column=7, value=f"=E{dr}-F{dr}")
        cf.number_format = MONEY_FORMAT
        cf.font = GREEN_FONT if row["total_profit"] >= 0 else RED_FONT
        cm = ws2.cell(row=dr, column=8, value=f"=IF(E{dr}>0,G{dr}/E{dr},0)")
        cm.number_format = PERCENT_FORMAT
        ws2.cell(row=dr, column=9, value=round(row["cash_collected"])).number_format = MONEY_FORMAT
        ws2.cell(row=dr, column=10, value=round(row["expenses"])).number_format = MONEY_FORMAT
        _style_data_row(ws2, dr, 10, zebra=(dr % 2 == 1))
        dr += 1

    last_dr = dr - 1
    ws2.cell(row=dr, column=1, value="JAMI:")
    for col_i, ltr, fmt in (
        (3, "C", MONEY_FORMAT),
        (4, "D", KG_FORMAT),
        (5, "E", MONEY_FORMAT),
        (6, "F", MONEY_FORMAT),
        (7, "G", MONEY_FORMAT),
        (9, "I", MONEY_FORMAT),
        (10, "J", MONEY_FORMAT),
    ):
        ws2.cell(
            row=dr,
            column=col_i,
            value=f"=SUM({ltr}2:{ltr}{last_dr})" if last_dr >= 2 else 0,
        ).number_format = fmt
    ws2.cell(row=dr, column=8, value=f"=IF(E{dr}>0,G{dr}/E{dr},0)").number_format = PERCENT_FORMAT
    _style_total_row(ws2, dr, 10)
    for col_letter, width in (
        ("A", 14),
        ("B", 11),
        ("C", 11),
        ("D", 11),
        ("E", 16),
        ("F", 16),
        ("G", 16),
        ("H", 11),
        ("I", 16),
        ("J", 16),
    ):
        ws2.column_dimensions[col_letter].width = width
    _apply_print_and_grid(ws2, freeze_cell="A2", filter_ref=f"A1:J{max(1, last_dr)}")

    # Sheet 3: Mijozlar Reytingi
    ws3 = wb.create_sheet("Mijozlar Reytingi")
    _style_header_row(
        ws3,
        1,
        ["#", "Mijoz", "Telefon", "Sotuvlar", "Jami kg", "Jami tushum", "Sof foyda", "Hozirgi qarz"],
    )
    cr = 2
    for idx, cstat in enumerate(client_stats, start=1):
        ws3.cell(row=cr, column=1, value=idx)
        ws3.cell(row=cr, column=2, value=cstat["name"])
        ws3.cell(row=cr, column=3, value=cstat["phone"] or "-")
        ws3.cell(row=cr, column=4, value=cstat["sales_count"]).number_format = MONEY_FORMAT
        ws3.cell(row=cr, column=5, value=round(cstat["total_kg"], 3)).number_format = KG_FORMAT
        ws3.cell(row=cr, column=6, value=round(cstat["total_revenue"])).number_format = MONEY_FORMAT
        cp = ws3.cell(row=cr, column=7, value=round(cstat["total_profit"]))
        cp.number_format = MONEY_FORMAT
        cp.font = GREEN_FONT if cstat["total_profit"] >= 0 else RED_FONT
        cd = ws3.cell(row=cr, column=8, value=round(cstat["current_debt"]))
        cd.number_format = MONEY_FORMAT
        if cstat["current_debt"] > 0:
            cd.font = RED_FONT
        _style_data_row(ws3, cr, 8, zebra=(cr % 2 == 1))
        cr += 1

    last_cr = cr - 1
    ws3.cell(row=cr, column=2, value="JAMI:")
    for col_i, ltr, fmt in (
        (4, "D", MONEY_FORMAT),
        (5, "E", KG_FORMAT),
        (6, "F", MONEY_FORMAT),
        (7, "G", MONEY_FORMAT),
        (8, "H", MONEY_FORMAT),
    ):
        ws3.cell(
            row=cr,
            column=col_i,
            value=f"=SUM({ltr}2:{ltr}{last_cr})" if last_cr >= 2 else 0,
        ).number_format = fmt
    _style_total_row(ws3, cr, 8)
    for col_letter, width in (
        ("A", 6),
        ("B", 24),
        ("C", 16),
        ("D", 11),
        ("E", 12),
        ("F", 18),
        ("G", 18),
        ("H", 18),
    ):
        ws3.column_dimensions[col_letter].width = width
    _apply_print_and_grid(ws3, freeze_cell="A2", filter_ref=f"A1:H{max(1, last_cr)}")

    # Sheet 4: Xarajatlar
    ws4 = wb.create_sheet("Xarajatlar")
    _style_header_row(ws4, 1, ["Vaqt", "Kategoriya", "Izoh", "Summa"])
    er = 2
    for tx in expenses:
        tm = format_local_dt(tx.created_at, "%d.%m.%Y %H:%M") if tx.created_at else ""
        ws4.cell(row=er, column=1, value=tm)
        ws4.cell(row=er, column=2, value=tx.category or "Boshqa")
        ws4.cell(row=er, column=3, value=tx.note or "-")
        ca = ws4.cell(row=er, column=4, value=round(tx.amount))
        ca.number_format = MONEY_FORMAT
        ca.font = RED_FONT
        _style_data_row(ws4, er, 4, zebra=(er % 2 == 1))
        er += 1
    last_er = er - 1
    ws4.cell(row=er, column=1, value="JAMI:")
    ws4.cell(
        row=er,
        column=4,
        value=f"=SUM(D2:D{last_er})" if last_er >= 2 else 0,
    ).number_format = MONEY_FORMAT
    _style_total_row(ws4, er, 4)
    for col_letter, width in (("A", 18), ("B", 16), ("C", 36), ("D", 18)):
        ws4.column_dimensions[col_letter].width = width
    _apply_print_and_grid(ws4, freeze_cell="A2", filter_ref=f"A1:D{max(1, last_er)}")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_history_excel(
    sessions: Sequence[DailyCashSession],
    tenant_name: str = "Norin Sexi",
) -> bytes:
    """Export closed/open daily session history list into styled XLSX bytes with totals."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Kunlik Tarix"
    clean_tenant = (tenant_name or "Norin Sexi").strip()
    ws["A1"] = f"{clean_tenant.upper()} — KUNLIK KASSA TARIXI"
    ws["A1"].font = Font(bold=True, size=13, color="1F4E78")

    headers = [
        "ID",
        "Sana",
        "Holat",
        "Boshlang'ich qoldiq",
        "Qolishi kerak edi",
        "Sanalgan pul",
        "Farq",
        "Yopilgan vaqt",
    ]
    _style_header_row(ws, 3, headers)

    r_idx = 4
    for sess in sessions:
        ws.cell(row=r_idx, column=1, value=sess.id)
        ws.cell(row=r_idx, column=2, value=sess.report_date)
        ws.cell(row=r_idx, column=3, value="Yopilgan" if sess.status == "closed" else "Ochiq")
        diff = sess.difference or 0
        for col_i, val in (
            (4, sess.opening_balance),
            (5, sess.expected_cash),
            (6, sess.actual_counted_cash or 0),
            (7, diff),
        ):
            c = ws.cell(row=r_idx, column=col_i, value=round(val))
            c.number_format = MONEY_FORMAT
            if col_i == 7 and abs(diff) >= 1:
                c.font = GREEN_FONT if diff > 0 else RED_FONT
        ws.cell(
            row=r_idx,
            column=8,
            value=format_local_dt(sess.closed_at, "%Y-%m-%d %H:%M") if sess.closed_at else "",
        )
        _style_data_row(ws, r_idx, 8, zebra=(r_idx % 2 == 1))
        r_idx += 1

    last_r = r_idx - 1
    ws.cell(row=r_idx, column=2, value="JAMI:")
    for col_i, ltr in ((4, "D"), (5, "E"), (6, "F"), (7, "G")):
        ws.cell(
            row=r_idx,
            column=col_i,
            value=f"=SUM({ltr}4:{ltr}{last_r})" if last_r >= 4 else 0,
        ).number_format = MONEY_FORMAT
    _style_total_row(ws, r_idx, 8)

    for col_idx, width in enumerate((8, 14, 12, 20, 20, 18, 16, 20), start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    _apply_print_and_grid(ws, freeze_cell="A4", filter_ref=f"A3:H{max(3, last_r)}")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

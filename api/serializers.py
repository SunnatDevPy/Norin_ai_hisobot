"""ORM -> JSON serializers for norin-api responses (owner view: includes cost & profit)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import inspect as sa_inspect

from database.crud import (
    ClientDebtSummary,
    DailyReportSummary,
    PeriodReportSummary,
    to_utc_dt,
)
from database.models import (
    CashTransaction,
    Client,
    ClientPayment,
    DailyCashSession,
    Product,
    ProductReturn,
    Sale,
)


def iso(dt) -> Optional[str]:
    return to_utc_dt(dt).isoformat() if dt else None


def r2(v: Any) -> float:
    return round(float(v or 0.0), 2)


def _loaded_client_name(obj: Any) -> Optional[str]:
    """Return related client name only if it was eagerly loaded (async-safe)."""
    if "client" in sa_inspect(obj).unloaded:
        return None
    cli = obj.client
    return cli.name if cli is not None else None


def product_out(p: Product) -> Dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "unit": p.unit,
        "aliases": p.aliases,
        "cost_price": r2(p.cost_price),
        "default_sell_price": r2(p.default_sell_price),
        "is_active": bool(p.is_active),
        "order_num": p.order_num,
    }


def client_out(c: Client, debt: Optional[ClientDebtSummary] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "id": c.id,
        "name": c.name,
        "phone": c.phone,
        "aliases": c.aliases,
        "group_chat_id": c.group_chat_id,
        "group_title": c.group_title,
        "opening_debt": r2(c.opening_debt),
        "is_active": bool(c.is_active),
    }
    if debt is not None:
        out.update(
            {
                "current_debt": r2(debt.current_debt),
                "total_sales": r2(debt.total_sales),
                "total_paid": r2(debt.total_paid),
                "total_kg": round(float(debt.total_kg), 3),
                "total_returns": r2(debt.total_returns),
                "total_return_kg": round(float(debt.total_return_kg), 3),
                "last_payment_at": iso(debt.last_payment_at),
            }
        )
    return out


def sale_out(s: Sale, client_name: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": s.id,
        "client_id": s.client_id,
        "client_name": client_name or _loaded_client_name(s),
        "report_date": s.report_date,
        "status": s.status,
        "source_channel": s.source_channel,
        "note": s.note or "",
        "total_weight_kg": round(float(s.total_weight_kg), 3),
        "total_amount": r2(s.total_amount),
        "total_cost": r2(s.total_cost),
        "total_profit": r2(s.total_profit),
        "posted_to_group": bool(s.group_message_id),
        "has_photo": bool(s.photo_file_id),
        "created_at": iso(s.created_at),
        "items": [
            {
                "id": i.id,
                "product_id": i.product_id,
                "product_name": i.product_name,
                "weight_kg": round(float(i.weight_kg), 3),
                "weights_detail": i.weights_detail,
                "unit_cost": r2(i.unit_cost),
                "unit_sell_price": r2(i.unit_sell_price),
                "line_total": r2(i.line_total),
                "line_cost": r2(i.line_cost),
                "line_profit": r2(i.line_profit),
            }
            for i in s.items
        ],
    }


def payment_out(p: ClientPayment, client_name: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": p.id,
        "client_id": p.client_id,
        "client_name": client_name or _loaded_client_name(p),
        "amount": r2(p.amount),
        "payment_method": p.payment_method,
        "note": p.note,
        "posted_to_group": bool(p.group_message_id),
        "created_at": iso(p.created_at),
    }


def return_out(r: ProductReturn, client_name: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": r.id,
        "client_id": r.client_id,
        "client_name": client_name or _loaded_client_name(r),
        "product_id": r.product_id,
        "product_name": r.product_name,
        "weight_kg": round(float(r.weight_kg), 3),
        "unit_sell_price": r2(r.unit_sell_price),
        "total_amount": r2(r.total_amount),
        "total_cost": r2(r.total_cost),
        "reason": r.reason,
        "posted_to_group": bool(r.group_message_id),
        "report_date": r.report_date,
        "created_at": iso(r.created_at),
    }


def cash_tx_out(t: CashTransaction) -> Dict[str, Any]:
    return {
        "id": t.id,
        "amount": r2(t.amount),
        "source_type": t.source_type,
        "category": t.category,
        "note": t.note,
        "created_at": iso(t.created_at),
    }


def session_out(s: DailyCashSession) -> Dict[str, Any]:
    return {
        "id": s.id,
        "report_date": s.report_date,
        "status": s.status,
        "opening_balance": r2(s.opening_balance),
        "expected_cash": r2(s.expected_cash),
        "actual_counted_cash": None if s.actual_counted_cash is None else r2(s.actual_counted_cash),
        "difference": None if s.difference is None else r2(s.difference),
        "closed_at": iso(s.closed_at),
    }


def summary_out(sm: DailyReportSummary, detail: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "session": session_out(sm.session),
        "kpis": {
            "sales_count": len(sm.confirmed_sales),
            "total_kg": round(float(sm.total_kg), 3),
            "revenue": r2(sm.total_revenue),
            "cost": r2(sm.total_cost),
            "profit": r2(sm.total_profit),
            "margin_pct": round(float(sm.margin_pct), 2),
            "returns_kg": round(float(sm.total_return_kg), 3),
            "returns_amount": r2(sm.total_return_amount),
            "expenses": r2(sm.total_expenses),
        },
        "cash": {
            "opening_balance": r2(sm.opening_balance),
            "client_cash_in": r2(sm.client_cash_in),
            "client_card_in": r2(sm.client_card_in),
            "client_transfer_in": r2(sm.client_transfer_in),
            "main_cash_in": r2(sm.main_cash_in),
            "kassa_debt_today": r2(sm.kassa_debt_today),
            "kassa_repay_today": r2(sm.kassa_repay_today),
            "total_expenses": r2(sm.total_expenses),
            "expected_cash": r2(sm.expected_cash),
            "kassa_debt_outstanding": r2(sm.total_kassa_debt_outstanding),
        },
        "weight_by_product": {k: round(float(v), 3) for k, v in sm.weight_by_product.items()},
        "total_clients_debt": r2(sm.total_all_clients_debt),
    }
    if detail:
        out["sales"] = [sale_out(s) for s in sm.confirmed_sales]
        out["payments"] = [payment_out(p) for p in sm.client_payments]
        out["returns"] = [return_out(r) for r in sm.returns]
        out["cash_transactions"] = [cash_tx_out(t) for t in sm.cash_transactions]
    return out


def period_out(p: PeriodReportSummary) -> Dict[str, Any]:
    return {
        "period": {"start": p.start_date, "end": p.end_date, "days": p.days},
        "kpis": {
            "sales_count": p.sales_count,
            "total_kg": round(float(p.total_kg), 3),
            "revenue": r2(p.total_revenue),
            "cost": r2(p.total_cost),
            "profit": r2(p.total_profit),
            "margin_pct": round(float(p.margin_pct), 2),
            "returns_kg": round(float(p.total_return_kg), 3),
            "returns_amount": r2(p.total_return_amount),
            "expenses": r2(p.total_expenses),
        },
        "collected": {
            "cash": r2(p.total_cash_collected),
            "card": r2(p.total_card_collected),
            "transfer": r2(p.total_transfer_collected),
        },
        "weight_by_product": {k: round(float(v), 3) for k, v in p.weight_by_product.items()},
        "total_clients_debt": r2(p.total_all_clients_debt),
    }


def statement_events(debt: ClientDebtSummary) -> List[Dict[str, Any]]:
    """Chronological Akt Sverka rows with running balance (client-safe: no cost/profit)."""
    events: List[tuple] = []
    for s in debt.recent_sales:
        for i in s.items:
            events.append(
                (to_utc_dt(s.created_at), 0, s.id, "sale", f"Yuk #{s.id}", i.product_name,
                 float(i.weight_kg), float(i.unit_sell_price), float(i.line_total), 0.0)
            )
    for p in debt.recent_payments:
        events.append(
            (to_utc_dt(p.created_at), 1, p.id, "payment", f"To'lov #{p.id}",
             f"To'lov ({p.payment_method})", None, None, 0.0, float(p.amount))
        )
    for r in debt.recent_returns:
        events.append(
            (to_utc_dt(r.created_at), 2, r.id, "return", f"Vozvrat #{r.id}",
             r.product_name, -float(r.weight_kg), float(r.unit_sell_price), 0.0, float(r.total_amount))
        )
    events.sort(key=lambda e: (e[0], e[1], e[2]))
    balance = float(debt.opening_debt)
    rows: List[Dict[str, Any]] = []
    for dt, _, _, kind, doc, detail, kg, price, debit, credit in events:
        balance = round(balance + debit - credit, 2)
        rows.append(
            {
                "at": dt.isoformat(),
                "kind": kind,
                "doc": doc,
                "detail": detail,
                "kg": None if kg is None else round(kg, 3),
                "price": None if price is None else r2(price),
                "debit": r2(debit),
                "credit": r2(credit),
                "balance": balance,
            }
        )
    return rows

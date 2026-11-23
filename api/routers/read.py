"""Read endpoints: dashboard, catalog (products/clients/debts), today, history, export, settings."""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from api import serializers as ser
from api.deps import Principal, get_db, get_principal, tenant_ctx
from database.crud import (
    check_tenant_ai_quota,
    compute_client_debt,
    compute_period_summary,
    compute_session_summary,
    evaluate_subscription_status,
    format_local_dt,
    get_app_setting,
    get_client,
    get_client_prices_map,
    get_group_config,
    get_kassa_debt_stats,
    get_open_session,
    get_period_excel_data,
    get_subscription_state,
    list_all_client_debts,
    list_all_sessions,
    list_closed_sessions,
    list_products,
    list_recent_client_payments,
    list_recent_sales,
    today_iso,
)
from services.excel_export import (
    build_client_statement_excel,
    build_daily_norin_excel,
    build_history_excel,
    build_period_excel,
)


router = APIRouter(tags=["read"], dependencies=[Depends(get_principal)])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PERIODS = ("today", "7", "30", "cur", "prev")


def period_bounds(period: str) -> tuple[Optional[str], Optional[str], int]:
    """Map a period key to (start_iso, end_iso, days). today => (None, None, 1)."""
    if period not in PERIODS:
        raise HTTPException(status_code=422, detail="Noto'g'ri davr (today|7|30|cur|prev)")
    if period == "today":
        return None, None, 1
    if period in ("7", "30"):
        return None, None, int(period)
    today_d = date.fromisoformat(today_iso())
    if period == "cur":
        return today_d.replace(day=1).isoformat(), today_d.isoformat(), 0
    first_cur = today_d.replace(day=1)
    end_d = first_cur - timedelta(days=1)
    return end_d.replace(day=1).isoformat(), end_d.isoformat(), 0


def _slug(raw: str, fallback: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", raw or "").strip("_")
    return s[:32] or fallback


def _xlsx(data: bytes, filename: str) -> Response:
    return Response(
        content=data,
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------- dashboard


@router.get("/dashboard/summary")
async def dashboard_summary(
    period: str = Query("today"),
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    start, end, days = period_bounds(period)
    open_sess = await get_open_session(db)
    stale = bool(open_sess and open_sess.report_date != today_iso())
    kassa = await get_kassa_debt_stats(db, limit=0)
    if period == "today":
        sm = await compute_session_summary(db)
        data = ser.summary_out(sm)
        data["period"] = {"key": "today", "start": sm.session.report_date, "end": sm.session.report_date, "days": 1}
    else:
        p = await compute_period_summary(db, days=days or 30, start_iso=start, end_iso=end)
        data = ser.period_out(p)
        data["period"]["key"] = period
        data["total_clients_debt"] = ser.r2(p.total_all_clients_debt)
    data["kassa_debt_outstanding"] = ser.r2(kassa["outstanding"])
    data["stale_open_session"] = (
        {"id": open_sess.id, "report_date": open_sess.report_date} if stale else None
    )
    return data


@router.get("/dashboard/charts")
async def dashboard_charts(
    period: str = Query("30"),
    top: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    start, end, days = period_bounds(period)
    pdata = await get_period_excel_data(db, days=days or 1, start_iso=start, end_iso=end)
    series = [
        {
            "date": r["report_date"],
            "sales_count": r["sales_count"],
            "kg": round(r["total_kg"], 3),
            "revenue": ser.r2(r["total_revenue"]),
            "cost": ser.r2(r["total_cost"]),
            "profit": ser.r2(r["total_profit"]),
            "expenses": ser.r2(r["expenses"]),
            "collected": ser.r2(r["cash_collected"]),
        }
        for r in pdata["daily_rows"]
    ]
    by_cat: dict[str, float] = defaultdict(float)
    for tx in pdata["expenses"]:
        by_cat[tx.category or "Boshqa"] += float(tx.amount)
    expenses = sorted(
        ({"category": k, "amount": ser.r2(v)} for k, v in by_cat.items()),
        key=lambda x: -x["amount"],
    )
    top_clients = [
        {
            "name": c["name"],
            "sales_count": c["sales_count"],
            "kg": round(c["total_kg"], 3),
            "revenue": ser.r2(c["total_revenue"]),
            "profit": ser.r2(c["total_profit"]),
            "current_debt": ser.r2(c["current_debt"]),
        }
        for c in pdata["client_stats"][:top]
    ]
    p = pdata["period"]
    return {
        "period": {"key": period, "start": p.start_date, "end": p.end_date},
        "daily_series": series,
        "expense_breakdown": expenses,
        "top_clients": top_clients,
    }


# ------------------------------------------------------------------ catalog


@router.get("/products")
async def products(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> list:
    rows = await list_products(db, active_only=not include_inactive)
    return [ser.product_out(p) for p in rows]


@router.get("/clients")
async def clients(
    q: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> list:
    debts = await list_all_client_debts(db)
    items = [ser.client_out(d.client, d) for d in debts]
    if q:
        ql = q.strip().lower()
        items = [c for c in items if ql in c["name"].lower() or ql in (c["aliases"] or "").lower()]
    return items


@router.get("/clients/{client_id}")
async def client_card(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    if await get_client(db, client_id) is None:
        raise HTTPException(status_code=404, detail="Mijoz topilmadi")
    debt = await compute_client_debt(db, client_id, history_limit=10)
    prices = await get_client_prices_map(db, client_id)
    out = ser.client_out(debt.client, debt)
    out["custom_prices"] = {str(pid): ser.r2(v) for pid, v in prices.items()}
    out["recent_sales"] = [ser.sale_out(s, debt.client.name) for s in debt.recent_sales]
    out["recent_payments"] = [ser.payment_out(p, debt.client.name) for p in debt.recent_payments]
    out["recent_returns"] = [ser.return_out(r, debt.client.name) for r in debt.recent_returns]
    return out


@router.get("/clients/{client_id}/statement")
async def client_statement(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    if await get_client(db, client_id) is None:
        raise HTTPException(status_code=404, detail="Mijoz topilmadi")
    debt = await compute_client_debt(db, client_id, history_limit=None)
    return {
        "client": ser.client_out(debt.client, debt),
        "opening_debt": ser.r2(debt.opening_debt),
        "events": ser.statement_events(debt),
    }


@router.get("/debts")
async def debts(
    db: AsyncSession = Depends(get_db), _tid: int = Depends(tenant_ctx)
) -> dict:
    rows = await list_all_client_debts(db)
    return {
        "total": ser.r2(sum(d.current_debt for d in rows)),
        "count": len(rows),
        "items": [ser.client_out(d.client, d) for d in rows],
    }


# ------------------------------------------------------------ today/history


@router.get("/today")
async def today(
    db: AsyncSession = Depends(get_db), _tid: int = Depends(tenant_ctx)
) -> dict:
    sm = await compute_session_summary(db)
    return ser.summary_out(sm, detail=True)


@router.get("/history/sessions")
async def history_sessions(
    limit: int = Query(30, ge=1, le=120),
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> list:
    return [ser.session_out(s) for s in await list_all_sessions(db, limit=limit)]


@router.get("/history/sessions/{session_id}")
async def history_session_detail(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    try:
        sm = await compute_session_summary(db, session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Kun topilmadi")
    return ser.summary_out(sm, detail=True)


@router.get("/history/sales")
async def history_sales(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    client_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    rows = await list_recent_sales(db, limit=limit + 1, offset=offset, client_id=client_id)
    return {"items": [ser.sale_out(s) for s in rows[:limit]], "has_more": len(rows) > limit}


@router.get("/history/payments")
async def history_payments(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    client_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    rows = await list_recent_client_payments(db, limit=limit + 1, offset=offset, client_id=client_id)
    return {"items": [ser.payment_out(p) for p in rows[:limit]], "has_more": len(rows) > limit}


# ------------------------------------------------------------------- export


@router.get("/export/daily/{session_id}")
async def export_daily(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> Response:
    sub = await get_subscription_state(db)
    try:
        sm = await compute_session_summary(db, session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Kun topilmadi")
    debts_ = await list_all_client_debts(db)
    data = await asyncio.to_thread(build_daily_norin_excel, sm, debts_, tenant_name=sub.tenant_name)
    return _xlsx(data, f"{_slug(sub.tenant_name, 'Filial')}_Hisobot_{sm.session.report_date}.xlsx")


@router.get("/export/period")
async def export_period(
    period: str = Query("30"),
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> Response:
    start, end, days = period_bounds(period)
    if period == "today":
        raise HTTPException(status_code=422, detail="Kunlik uchun /export/daily dan foydalaning")
    sub = await get_subscription_state(db)
    pdata = await get_period_excel_data(db, days=days or 30, start_iso=start, end_iso=end)
    data = await asyncio.to_thread(build_period_excel, pdata)
    p = pdata["period"]
    return _xlsx(data, f"{_slug(sub.tenant_name, 'Filial')}_Davriy_{p.start_date}_{p.end_date}.xlsx")


@router.get("/export/client/{client_id}")
async def export_client(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> Response:
    if await get_client(db, client_id) is None:
        raise HTTPException(status_code=404, detail="Mijoz topilmadi")
    sub = await get_subscription_state(db)
    debt = await compute_client_debt(db, client_id, history_limit=None)
    data = await asyncio.to_thread(build_client_statement_excel, debt, tenant_name=sub.tenant_name)
    return _xlsx(
        data,
        f"{_slug(sub.tenant_name, 'Filial')}_Sverka_{_slug(debt.client.name, f'Mijoz_{client_id}')}.xlsx",
    )


@router.get("/export/history")
async def export_history(
    db: AsyncSession = Depends(get_db), _tid: int = Depends(tenant_ctx)
) -> Response:
    sub = await get_subscription_state(db)
    sessions = await list_closed_sessions(db, limit=90)
    if not sessions:
        raise HTTPException(status_code=404, detail="Yopilgan kunlar hali yo'q")
    data = await asyncio.to_thread(build_history_excel, sessions, tenant_name=sub.tenant_name)
    return _xlsx(data, f"{_slug(sub.tenant_name, 'Filial')}_Kunlik_Tarix.xlsx")


# ----------------------------------------------------------------- settings


@router.get("/settings")
async def get_settings_view(
    p: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
    tid: int = Depends(tenant_ctx),
) -> dict:
    st = await evaluate_subscription_status(db, tenant_id=tid)
    allowed, used, limit = await check_tenant_ai_quota(db, tenant_id=tid)
    rep = await get_group_config(db, "report")
    return {
        "tenant": {"id": st.state.id, "name": st.state.tenant_name},
        "subscription": {
            "plan": st.state.plan_name,
            "monthly_price": ser.r2(st.state.monthly_price),
            "status": st.status,
            "days_left": st.days_left,
            "expires_at": ser.iso(st.state.expires_at),
        },
        "auto_confirm": (await get_app_setting(db, "auto_confirm", "on")) == "on",
        "group_auto_calc": (await get_app_setting(db, "group_auto_calc", "on")) == "on",
        "round_mode": await get_app_setting(db, "round_mode", "none"),
        "ai": {"daily_limit": limit, "used_today": used, "allowed": allowed},
        "report_group": (
            {"chat_id": rep.chat_id, "title": rep.title} if rep else None
        ),
    }

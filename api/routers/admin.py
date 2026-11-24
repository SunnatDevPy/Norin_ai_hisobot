"""Super Admin endpoints (strictly SUPER_ADMIN_IDS): SaaS MRR analytics, tenants, users, broadcast & audit."""

from __future__ import annotations

import asyncio
import html
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api import serializers as ser
from api.deps import Principal, client_ip, get_db, require_super_admin
from database.crud import (
    add_authorized_user,
    check_tenant_ai_quota,
    create_tenant,
    delete_tenant,
    evaluate_subscription_status,
    extend_subscription,
    get_ai_usage_summary,
    get_app_setting,
    get_authorized_user,
    get_global_saas_analytics,
    get_tenant_overview_stats,
    list_all_broadcast_recipients,
    list_authorized_users,
    list_subscription_payments,
    list_tenants,
    reassign_authorized_user,
    remove_authorized_user,
    reset_full_database,
    reset_test_transactions,
    set_app_setting,
    update_subscription_settings,
)
from database.models import ApiSession, AuditLog, SubscriptionState


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_super_admin)],
)


def _audit(db: AsyncSession, p: Principal, request: Request, action: str, detail: str = "") -> None:
    db.add(
        AuditLog(
            actor_id=p.telegram_id,
            action=action,
            detail=detail[:500],
            ip=client_ip(request),
        )
    )


class TenantCreateIn(BaseModel):
    tenant_name: str = Field(min_length=1, max_length=255)
    monthly_price: Optional[float] = Field(default=None, ge=0)
    trial_days: Optional[int] = Field(default=None, ge=1, le=3650)
    owner_contact: Optional[str] = None


class TenantPatchIn(BaseModel):
    tenant_name: Optional[str] = None
    plan_name: Optional[str] = None
    monthly_price: Optional[float] = Field(default=None, ge=0)
    grace_days: Optional[int] = Field(default=None, ge=0, le=60)
    owner_contact: Optional[str] = None
    auto_confirm: Optional[bool] = None
    group_auto_calc: Optional[bool] = None
    round_mode: Optional[str] = None
    ai_daily_limit: Optional[int] = Field(default=None, ge=0, le=10000)


class ExtendIn(BaseModel):
    days: int = Field(gt=0, le=3650)
    amount: Optional[float] = Field(default=None, ge=0)
    note: str = ""


class SuspendIn(BaseModel):
    is_suspended: bool


class ClearIn(BaseModel):
    mode: str = "tx"  # tx | full


class UserCreateIn(BaseModel):
    telegram_id: int
    full_name: str = ""
    role: str = "staff"
    tenant_id: int = 1
    create_new_tenant: bool = False
    new_tenant_name: Optional[str] = None


class UserPatchIn(BaseModel):
    tenant_id: Optional[int] = None
    role: Optional[str] = None


class BroadcastIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.get("/analytics")
async def admin_analytics(db: AsyncSession = Depends(get_db)) -> dict:
    return await get_global_saas_analytics(db, days=30)


async def _serialize_admin_tenant(db: AsyncSession, t: SubscriptionState) -> dict:
    st = await evaluate_subscription_status(db, tenant_id=t.id)
    stats = await get_tenant_overview_stats(db, t.id)
    ai_30 = await get_ai_usage_summary(db, days=30, tenant_id=t.id)
    _, ai_used_today, ai_limit = await check_tenant_ai_quota(db, tenant_id=t.id)
    return {
        "id": t.id,
        "tenant_name": t.tenant_name,
        "plan_name": t.plan_name,
        "monthly_price": ser.r2(t.monthly_price),
        "grace_days": t.grace_days,
        "owner_contact": t.owner_contact,
        "is_suspended": bool(t.is_suspended),
        "status": st.status,
        "days_left": st.days_left,
        "grace_days_left": st.grace_days_left,
        "expires_at": ser.iso(t.expires_at),
        "stats": stats,
        "users_count": stats.get("users", 0),
        "ai_30d": ai_30,
        "ai_used_today": ai_used_today,
        "ai_daily_limit": ai_limit,
        "auto_confirm": (await get_app_setting(db, "auto_confirm", "on", tenant_id=t.id)) == "on",
        "group_auto_calc": (await get_app_setting(db, "group_auto_calc", "on", tenant_id=t.id)) == "on",
        "round_mode": await get_app_setting(db, "round_mode", "none", tenant_id=t.id),
    }


@router.get("/tenants")
async def admin_tenants(db: AsyncSession = Depends(get_db)) -> List[dict]:
    tenants = await list_tenants(db)
    return [await _serialize_admin_tenant(db, t) for t in tenants]


@router.post("/tenants")
async def admin_create_tenant(
    body: TenantCreateIn,
    request: Request,
    p: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sub = await create_tenant(
        db,
        tenant_name=body.tenant_name,
        trial_days=body.trial_days,
        monthly_price=body.monthly_price,
        owner_contact=body.owner_contact,
    )
    _audit(db, p, request, "create_tenant", f"#{sub.id} {sub.tenant_name}")
    await db.commit()
    return {"id": sub.id, "tenant_name": sub.tenant_name}


@router.patch("/tenants/{tenant_id}")
async def admin_patch_tenant(
    tenant_id: int,
    body: TenantPatchIn,
    request: Request,
    p: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if await db.get(SubscriptionState, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Filial topilmadi")
    await update_subscription_settings(
        db,
        monthly_price=body.monthly_price,
        owner_contact=body.owner_contact,
        tenant_name=body.tenant_name,
        plan_name=body.plan_name,
        grace_days=body.grace_days,
        tenant_id=tenant_id,
    )
    if body.auto_confirm is not None:
        await set_app_setting(db, "auto_confirm", "on" if body.auto_confirm else "off", tenant_id=tenant_id)
    if body.group_auto_calc is not None:
        await set_app_setting(db, "group_auto_calc", "on" if body.group_auto_calc else "off", tenant_id=tenant_id)
    if body.round_mode is not None:
        if body.round_mode not in ("none", "nearest_1000", "floor_1000"):
            raise HTTPException(status_code=422, detail="round_mode noto'g'ri")
        await set_app_setting(db, "round_mode", body.round_mode, tenant_id=tenant_id)
    if body.ai_daily_limit is not None:
        await set_app_setting(db, "ai_daily_limit", str(body.ai_daily_limit), tenant_id=tenant_id)
    _audit(db, p, request, "patch_tenant", f"#{tenant_id}")
    await db.commit()
    sub_obj = await db.get(SubscriptionState, tenant_id)
    return {"ok": True, **(await _serialize_admin_tenant(db, sub_obj))}


@router.post("/tenants/{tenant_id}/extend")
async def admin_extend_tenant(
    tenant_id: int,
    body: ExtendIn,
    request: Request,
    p: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sub_obj = await db.get(SubscriptionState, tenant_id)
    if sub_obj is None:
        raise HTTPException(status_code=404, detail="Do'kon topilmadi")
    amt = (
        body.amount
        if body.amount is not None
        else round((float(sub_obj.monthly_price) / 30.0) * body.days)
    )
    updated = await extend_subscription(
        db,
        days=body.days,
        amount=amt,
        recorded_by=p.telegram_id,
        note=body.note or f"APK Admin +{body.days} kun",
        tenant_id=tenant_id,
    )
    _audit(db, p, request, "extend_tenant", f"#{tenant_id} +{body.days}d ({amt})")
    await db.commit()
    return await _serialize_admin_tenant(db, updated)


@router.post("/tenants/{tenant_id}/suspend")
async def admin_suspend_tenant(
    tenant_id: int,
    body: SuspendIn,
    request: Request,
    p: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if await db.get(SubscriptionState, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Do'kon topilmadi")
    await update_subscription_settings(db, is_suspended=body.is_suspended, tenant_id=tenant_id)
    _audit(db, p, request, "suspend_tenant", f"#{tenant_id} -> {body.is_suspended}")
    await db.commit()
    sub_obj = await db.get(SubscriptionState, tenant_id)
    return {"ok": True, **(await _serialize_admin_tenant(db, sub_obj))}


@router.delete("/tenants/{tenant_id}")
async def admin_delete_tenant(
    tenant_id: int,
    request: Request,
    p: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if tenant_id <= 1:
        raise HTTPException(status_code=400, detail="#1 Asosiy filialni o'chirib bo'lmaydi")
    if not await delete_tenant(db, tenant_id):
        raise HTTPException(status_code=404, detail="Filial topilmadi")
    _audit(db, p, request, "delete_tenant", f"#{tenant_id}")
    await db.commit()
    return {"ok": True}


@router.post("/tenants/{tenant_id}/clear")
async def admin_clear_tenant(
    tenant_id: int,
    body: ClearIn,
    request: Request,
    p: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if await db.get(SubscriptionState, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Do'kon topilmadi")
    mode = "tx" if body.mode in ("tx", "tx_only") else body.mode
    if mode == "full":
        stats = await reset_full_database(db, tenant_id=tenant_id)
    elif mode == "tx":
        stats = await reset_test_transactions(db, tenant_id=tenant_id)
    else:
        raise HTTPException(status_code=422, detail="mode: tx yoki full")
    _audit(db, p, request, "clear_tenant", f"#{tenant_id} mode={mode}")
    await db.commit()
    return {"ok": True, "stats": stats}


@router.get("/tenants/{tenant_id}/payments")
async def admin_tenant_payments(
    tenant_id: int, db: AsyncSession = Depends(get_db)
) -> list:
    rows = await list_subscription_payments(db, limit=30, tenant_id=tenant_id)
    return [
        {
            "id": r.id,
            "amount": ser.r2(r.amount),
            "days_added": r.days_added,
            "plan_name": r.plan_name,
            "note": r.note,
            "paid_at": ser.iso(r.paid_at),
        }
        for r in rows
    ]


@router.get("/tenants/{tenant_id}/users")
async def admin_tenant_users(
    tenant_id: int, db: AsyncSession = Depends(get_db)
) -> list:
    rows = await list_authorized_users(db, active_only=True, tenant_id=tenant_id)
    return [
        {
            "id": u.id,
            "telegram_id": u.telegram_id,
            "full_name": u.full_name,
            "role": u.role,
            "tenant_id": u.tenant_id,
        }
        for u in rows
    ]


@router.post("/users")
async def admin_add_user(
    body: UserCreateIn,
    request: Request,
    p: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    role = "staff" if body.role == "worker" else body.role
    if role not in ("owner", "staff"):
        raise HTTPException(status_code=422, detail="role: owner yoki staff")
    u = await add_authorized_user(
        db,
        telegram_id=body.telegram_id,
        full_name=body.full_name,
        role=role,
        tenant_id=body.tenant_id,
        create_new_tenant=body.create_new_tenant,
        new_tenant_name=body.new_tenant_name,
    )
    _audit(db, p, request, "add_user", f"tg={u.telegram_id} tid={u.tenant_id} role={u.role}")
    await db.commit()
    return {
        "telegram_id": u.telegram_id,
        "full_name": u.full_name,
        "role": u.role,
        "tenant_id": u.tenant_id,
    }


@router.patch("/users/{telegram_id}")
async def admin_patch_user(
    telegram_id: int,
    body: UserPatchIn,
    request: Request,
    p: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    existing = await get_authorized_user(db, telegram_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
    new_tid = body.tenant_id if body.tenant_id is not None else existing.tenant_id
    role = "staff" if body.role == "worker" else body.role
    if role is not None and role not in ("owner", "staff"):
        raise HTTPException(status_code=422, detail="role: owner yoki staff")
    updated = await reassign_authorized_user(db, telegram_id, new_tid, role=role)
    if updated is None:
        raise HTTPException(status_code=404, detail="Do'kon topilmadi")
    _audit(db, p, request, "patch_user", f"tg={telegram_id} tid={new_tid}")
    await db.commit()
    return {
        "telegram_id": updated.telegram_id,
        "full_name": updated.full_name,
        "role": updated.role,
        "tenant_id": updated.tenant_id,
    }


@router.delete("/users/{telegram_id}")
async def admin_delete_user(
    telegram_id: int,
    request: Request,
    p: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not await remove_authorized_user(db, telegram_id):
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
    await db.execute(
        update(ApiSession)
        .where(ApiSession.telegram_id == telegram_id)
        .values(is_revoked=True)
    )
    _audit(db, p, request, "delete_user", f"tg={telegram_id}")
    await db.commit()
    return {"ok": True}


@router.post("/broadcast")
async def admin_broadcast(
    body: BroadcastIn,
    request: Request,
    p: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    recipients = await list_all_broadcast_recipients(db)
    sender = request.app.state.send_telegram
    sent = 0
    for uid in recipients:
        try:
            await sender(uid, f"📢 <b>Tizim e'loni:</b>\n\n{html.escape(body.text)}")
            sent += 1
            await asyncio.sleep(0.03)
        except Exception:
            pass
    _audit(db, p, request, "broadcast", f"sent={sent}/{len(recipients)}")
    await db.commit()
    return {"sent": sent, "total": len(recipients)}


@router.get("/audit")
async def admin_audit(db: AsyncSession = Depends(get_db)) -> list:
    rows = (
        await db.scalars(select(AuditLog).order_by(desc(AuditLog.id)).limit(50))
    ).all()
    return [
        {
            "id": r.id,
            "actor_id": r.actor_id,
            "action": r.action,
            "detail": r.detail,
            "ip": r.ip,
            "created_at": ser.iso(r.created_at),
        }
        for r in rows
    ]

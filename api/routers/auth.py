"""Authentication endpoints: Telegram OTP login, token refresh, devices."""

from __future__ import annotations

from datetime import timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import Principal, client_ip, get_db, get_principal
from api.security import (
    create_access_token,
    hash_secret,
    make_otp,
    make_refresh_token,
    rate_limiter,
    verify_hash,
)
from config import get_settings
from database.crud import now_utc, to_utc_dt
from database.models import ApiLoginCode, ApiSession, AuditLog


router = APIRouter(prefix="/auth", tags=["auth"])

MAX_CODE_ATTEMPTS = 5


class RequestCodeIn(BaseModel):
    telegram_id: int


class VerifyCodeIn(BaseModel):
    telegram_id: int
    code: str = Field(min_length=6, max_length=6)
    device_name: str = Field(default="", max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    role: str
    tenant_id: int


def _audit(db: AsyncSession, actor: int, action: str, detail: str, ip: str) -> None:
    db.add(AuditLog(actor_id=actor, action=action, detail=detail[:500], ip=ip))


@router.post("/request-code")
async def request_code(
    body: RequestCodeIn, request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    """Send a 6-digit login code to the Super Admin's Telegram (same reply for any ID)."""
    ip = client_ip(request)
    if not rate_limiter.check(f"rc-ip:{ip}", 10, 600) or not rate_limiter.check(
        f"rc-id:{body.telegram_id}", 3, 600
    ):
        raise HTTPException(status_code=429, detail="Juda ko'p urinish. Keyinroq qayta urinib ko'ring.")

    reply = {"ok": True, "detail": "Agar ID ruxsat etilgan bo'lsa, kod Telegramga yuborildi."}
    if body.telegram_id not in get_settings().super_admin_id_list:
        return reply

    code = make_otp()
    db.add(
        ApiLoginCode(
            telegram_id=body.telegram_id,
            code_hash=hash_secret(code),
            expires_at=now_utc() + timedelta(minutes=max(1, get_settings().API_OTP_TTL_MIN)),
        )
    )
    _audit(db, body.telegram_id, "otp_requested", "", ip)
    await db.commit()
    ttl = get_settings().API_OTP_TTL_MIN
    text = (
        "🔐 <b>Norin AI — kirish kodi</b>\n\n"
        f"Kod: <code>{code}</code>\n"
        f"⏳ {ttl} daqiqa amal qiladi. Hech kimga bermang!"
    )
    sender = request.app.state.send_telegram
    try:
        await sender(body.telegram_id, text)
    except Exception:
        raise HTTPException(status_code=502, detail="Telegramga kod yuborib bo'lmadi")
    return reply


async def _issue_tokens(
    db: AsyncSession, telegram_id: int, role: str, tenant_id: int, device: str
) -> TokenOut:
    refresh = make_refresh_token()
    sess = ApiSession(
        telegram_id=telegram_id,
        role=role,
        tenant_id=tenant_id,
        device_name=device or "Noma'lum qurilma",
        refresh_hash=hash_secret(refresh),
        expires_at=now_utc() + timedelta(days=max(1, get_settings().API_REFRESH_TTL_DAYS)),
        last_used_at=now_utc(),
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    access, ttl = create_access_token(telegram_id, role, tenant_id, sess.id)
    return TokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=ttl,
        role=role,
        tenant_id=tenant_id,
    )


@router.post("/verify-code", response_model=TokenOut)
async def verify_code(
    body: VerifyCodeIn, request: Request, db: AsyncSession = Depends(get_db)
) -> TokenOut:
    ip = client_ip(request)
    if not rate_limiter.check(f"vc-ip:{ip}", 15, 600):
        raise HTTPException(status_code=429, detail="Juda ko'p urinish. Keyinroq qayta urinib ko'ring.")

    bad = HTTPException(status_code=400, detail="Kod noto'g'ri yoki eskirgan")
    if body.telegram_id not in get_settings().super_admin_id_list:
        raise bad
    row = await db.scalar(
        select(ApiLoginCode)
        .where(ApiLoginCode.telegram_id == body.telegram_id, ApiLoginCode.used.is_(False))
        .order_by(desc(ApiLoginCode.id))
        .limit(1)
    )
    if row is None or to_utc_dt(row.expires_at) < now_utc():
        raise bad
    row.attempts += 1
    if row.attempts > MAX_CODE_ATTEMPTS:
        row.used = True
        await db.commit()
        raise bad
    if not verify_hash(body.code.strip(), row.code_hash):
        await db.commit()
        raise bad
    row.used = True
    _audit(db, body.telegram_id, "login", body.device_name, ip)
    await db.commit()
    return await _issue_tokens(db, body.telegram_id, "super_admin", 1, body.device_name)


@router.post("/refresh", response_model=TokenOut)
async def refresh(body: RefreshIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    sess = await db.scalar(
        select(ApiSession).where(ApiSession.refresh_hash == hash_secret(body.refresh_token))
    )
    if sess is None or sess.is_revoked or to_utc_dt(sess.expires_at) < now_utc():
        raise HTTPException(status_code=401, detail="Sessiya tugagan, qaytadan kiring")
    new_refresh = make_refresh_token()
    sess.refresh_hash = hash_secret(new_refresh)
    sess.last_used_at = now_utc()
    await db.commit()
    access, ttl = create_access_token(sess.telegram_id, sess.role, sess.tenant_id, sess.id)
    return TokenOut(
        access_token=access,
        refresh_token=new_refresh,
        expires_in=ttl,
        role=sess.role,
        tenant_id=sess.tenant_id,
    )


@router.get("/me")
async def me(p: Principal = Depends(get_principal)) -> dict:
    return {"telegram_id": p.telegram_id, "role": p.role, "tenant_id": p.tenant_id}


@router.post("/logout")
async def logout(p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    sess = await db.get(ApiSession, p.session_id)
    if sess is not None:
        sess.is_revoked = True
        await db.commit()
    return {"ok": True}


@router.get("/devices")
async def devices(
    p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)
) -> List[dict]:
    rows = (
        await db.scalars(
            select(ApiSession)
            .where(ApiSession.telegram_id == p.telegram_id, ApiSession.is_revoked.is_(False))
            .order_by(desc(ApiSession.id))
        )
    ).all()
    return [
        {
            "id": r.id,
            "device_name": r.device_name,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
            "current": r.id == p.session_id,
        }
        for r in rows
    ]


@router.delete("/devices/{session_id}")
async def revoke_device(
    session_id: int,
    p: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sess = await db.get(ApiSession, session_id)
    if sess is None or int(sess.telegram_id) != p.telegram_id:
        raise HTTPException(status_code=404, detail="Qurilma topilmadi")
    sess.is_revoked = True
    await db.commit()
    return {"ok": True}

"""Authentication endpoints: Telegram OTP login, token refresh, devices."""

from __future__ import annotations

from datetime import timedelta
import secrets
from typing import List, Optional, Tuple

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
from database.crud import evaluate_subscription_status, now_utc, to_utc_dt
from database.models import ApiLoginCode, ApiSession, AuditLog, AuthorizedUser


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


class CodeOnlyLoginIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)
    device_name: str = Field(default="", max_length=128)


class TicketCreateIn(BaseModel):
    device_name: str = Field(default="", max_length=128)


class TicketPollIn(BaseModel):
    ticket: str = Field(min_length=8, max_length=64)
    device_name: str = Field(default="", max_length=128)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    role: str
    tenant_id: int


_CACHED_BOT_USERNAME: Optional[str] = None


async def _get_bot_username(request: Request) -> str:
    global _CACHED_BOT_USERNAME
    if _CACHED_BOT_USERNAME:
        return _CACHED_BOT_USERNAME
    bot = getattr(request.app.state, "bot", None)
    if bot is not None:
        try:
            me = await bot.get_me()
            if me and me.username:
                _CACHED_BOT_USERNAME = me.username.lstrip("@")
                return _CACHED_BOT_USERNAME
        except Exception:
            pass
    return "norin_ai_hisobot"


async def resolve_apk_user(db: AsyncSession, telegram_id: int) -> Optional[Tuple[str, int]]:
    """Resolve (role, tenant_id) for an APK user or return None / raise 403 if expired."""
    settings = get_settings()
    tid = int(telegram_id)
    if tid in settings.super_admin_id_list:
        return ("super_admin", 1)

    au = await db.scalar(
        select(AuthorizedUser).where(
            AuthorizedUser.telegram_id == tid,
            AuthorizedUser.is_active.is_(True),
        )
    )
    if au is not None:
        sub = await evaluate_subscription_status(db, tenant_id=int(au.tenant_id))
        if not sub.is_allowed:
            raise HTTPException(
                status_code=403,
                detail="Obuna muddati tugagan yoki do'kon vaqtincha to'xtatilgan",
            )
        return (au.role or "owner", int(au.tenant_id))

    if tid in settings.admin_id_list:
        sub = await evaluate_subscription_status(db, tenant_id=1)
        if not sub.is_allowed:
            raise HTTPException(
                status_code=403,
                detail="Obuna muddati tugagan yoki do'kon vaqtincha to'xtatilgan",
            )
        return ("owner", 1)

    return None


def _audit(db: AsyncSession, actor: int, action: str, detail: str, ip: str) -> None:
    db.add(AuditLog(actor_id=actor, action=action, detail=detail[:500], ip=ip))


@router.post("/request-code")
async def request_code(
    body: RequestCodeIn, request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    """Send a 6-digit login code to any authorized APK user's Telegram (same reply for any ID)."""
    ip = client_ip(request)
    if not rate_limiter.check(f"rc-ip:{ip}", 10, 600) or not rate_limiter.check(
        f"rc-id:{body.telegram_id}", 3, 600
    ):
        raise HTTPException(status_code=429, detail="Juda ko'p urinish. Keyinroq qayta urinib ko'ring.")

    reply = {"ok": True, "detail": "Agar ID ruxsat etilgan bo'lsa, kod Telegramga yuborildi."}
    try:
        resolved = await resolve_apk_user(db, body.telegram_id)
    except HTTPException:
        resolved = None
    if resolved is None:
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
        "🔐 <b>Sotuv AI — kirish kodi</b>\n\n"
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
    resolved = await resolve_apk_user(db, body.telegram_id)
    if resolved is None:
        raise bad
    role, tid = resolved
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
    return await _issue_tokens(db, body.telegram_id, role, tid, body.device_name)


@router.post("/login-code", response_model=TokenOut)
async def login_with_code_only(
    body: CodeOnlyLoginIn, request: Request, db: AsyncSession = Depends(get_db)
) -> TokenOut:
    """Authenticate using only a 6-digit Telegram OTP code (without typing Telegram ID)."""
    ip = client_ip(request)
    if not rate_limiter.check(f"vc-ip:{ip}", 10, 600):
        raise HTTPException(status_code=429, detail="Juda ko'p urinish. Keyinroq qayta urinib ko'ring.")

    code = body.code.strip()
    bad = HTTPException(status_code=400, detail="Kod noto'g'ri yoki muddati tugagan")
    if not code.isdigit() or len(code) != 6:
        raise bad

    row = await db.scalar(
        select(ApiLoginCode)
        .where(
            ApiLoginCode.code_hash == hash_secret(code),
            ApiLoginCode.telegram_id > 0,
            ApiLoginCode.used.is_(False),
        )
        .order_by(desc(ApiLoginCode.id))
        .limit(1)
    )
    if row is None or to_utc_dt(row.expires_at) < now_utc():
        raise bad

    resolved = await resolve_apk_user(db, int(row.telegram_id))
    if resolved is None:
        raise bad
    role, tid = resolved
    row.used = True
    _audit(db, int(row.telegram_id), "login_code", body.device_name, ip)
    await db.commit()
    return await _issue_tokens(db, int(row.telegram_id), role, tid, body.device_name)


@router.post("/telegram-ticket")
async def create_telegram_ticket(
    body: TicketCreateIn, request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    """Issue a short-lived deep-link login ticket so users can approve login in Telegram with 1 tap."""
    ip = client_ip(request)
    if not rate_limiter.check(f"tkt-ip:{ip}", 15, 600):
        raise HTTPException(status_code=429, detail="Juda ko'p urinish. Keyinroq qayta urinib ko'ring.")

    ticket = secrets.token_urlsafe(12)
    ttl_sec = max(60, get_settings().API_OTP_TTL_MIN * 60)
    db.add(
        ApiLoginCode(
            telegram_id=0,
            code_hash=hash_secret(f"tkt:{ticket}"),
            expires_at=now_utc() + timedelta(seconds=ttl_sec),
        )
    )
    await db.commit()
    bot_user = await _get_bot_username(request)
    return {
        "ticket": ticket,
        "bot_url": f"https://t.me/{bot_user}?start=apk_{ticket}",
        "tg_uri": f"tg://resolve?domain={bot_user}&start=apk_{ticket}",
        "expires_in": ttl_sec,
    }


@router.post("/telegram-poll")
async def poll_telegram_ticket(
    body: TicketPollIn, request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    """Poll whether the deep-link ticket has been approved by the user in Telegram bot."""
    ip = client_ip(request)
    row = await db.scalar(
        select(ApiLoginCode)
        .where(ApiLoginCode.code_hash == hash_secret(f"tkt:{body.ticket.strip()}"))
        .order_by(desc(ApiLoginCode.id))
        .limit(1)
    )
    if row is None or row.used or to_utc_dt(row.expires_at) < now_utc():
        return {"status": "expired"}
    if int(row.telegram_id) <= 0:
        return {"status": "pending"}

    resolved = await resolve_apk_user(db, int(row.telegram_id))
    if resolved is None:
        row.used = True
        await db.commit()
        return {"status": "expired"}

    role, tid = resolved
    row.used = True
    _audit(db, int(row.telegram_id), "login_telegram_1tap", body.device_name, ip)
    await db.commit()
    tokens = await _issue_tokens(db, int(row.telegram_id), role, tid, body.device_name)
    return {"status": "approved", **tokens.model_dump()}


@router.post("/refresh", response_model=TokenOut)
async def refresh(body: RefreshIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    sess = await db.scalar(
        select(ApiSession).where(ApiSession.refresh_hash == hash_secret(body.refresh_token))
    )
    if sess is None or sess.is_revoked or to_utc_dt(sess.expires_at) < now_utc():
        raise HTTPException(status_code=401, detail="Sessiya tugagan, qaytadan kiring")
    resolved = await resolve_apk_user(db, int(sess.telegram_id))
    if resolved is None:
        sess.is_revoked = True
        await db.commit()
        raise HTTPException(status_code=401, detail="Ruxsat bekor qilingan")
    sess.role, sess.tenant_id = resolved
    new_refresh = make_refresh_token()
    sess.refresh_hash = hash_secret(new_refresh)
    sess.expires_at = now_utc() + timedelta(days=max(1, get_settings().API_REFRESH_TTL_DAYS))
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

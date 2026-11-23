"""Shared FastAPI dependencies: DB session, authenticated principal, tenant scope."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import AsyncIterator, Optional

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.security import decode_access_token
from config import get_settings
from database import session as db_session
from database.crud import now_utc, tenant_scope, to_utc_dt
from database.models import ApiSession, SubscriptionState


@dataclass
class Principal:
    telegram_id: int
    role: str
    tenant_id: int
    session_id: int

    @property
    def is_super_admin(self) -> bool:
        return self.role == "super_admin"


async def get_db() -> AsyncIterator[AsyncSession]:
    async with db_session.async_session_maker() as db:
        yield db


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]


async def get_principal(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Avtorizatsiya talab qilinadi")
    claims = decode_access_token(authorization.split(" ", 1)[1].strip())
    if not claims:
        raise HTTPException(status_code=401, detail="Token yaroqsiz yoki eskirgan")
    try:
        tg_id = int(claims["sub"])
        sid = int(claims["sid"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Token yaroqsiz")

    sess = await db.get(ApiSession, sid)
    if (
        sess is None
        or sess.is_revoked
        or int(sess.telegram_id) != tg_id
        or to_utc_dt(sess.expires_at) < now_utc()
    ):
        raise HTTPException(status_code=401, detail="Sessiya tugagan, qaytadan kiring")
    if sess.role == "super_admin" and tg_id not in get_settings().super_admin_id_list:
        raise HTTPException(status_code=403, detail="Ruxsat bekor qilingan")

    last = sess.last_used_at
    if last is None or now_utc() - to_utc_dt(last) > timedelta(seconds=60):
        sess.last_used_at = now_utc()
        await db.commit()
    return Principal(
        telegram_id=tg_id, role=sess.role, tenant_id=int(sess.tenant_id), session_id=sid
    )


async def require_super_admin(p: Principal = Depends(get_principal)) -> Principal:
    if not p.is_super_admin:
        raise HTTPException(status_code=403, detail="Faqat Super Admin uchun")
    return p


async def tenant_ctx(
    p: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: Optional[int] = Header(default=None),
) -> AsyncIterator[int]:
    """Scope CRUD calls to the principal's tenant (Super Admin may pick via X-Tenant-Id)."""
    tid = p.tenant_id
    if x_tenant_id is not None and p.is_super_admin:
        if await db.get(SubscriptionState, int(x_tenant_id)) is None:
            raise HTTPException(status_code=404, detail="Filial topilmadi")
        tid = int(x_tenant_id)
    with tenant_scope(tid):
        yield tid

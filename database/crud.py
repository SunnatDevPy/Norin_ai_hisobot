"""Async CRUD operations for Norin products, clients, sales, debt ledger, cash sessions, and SaaS subscriptions."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import delete, desc, func as sa_func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import get_settings
from database.models import (
    AIUsageLog,
    AppSetting,
    AuthorizedUser,
    CashTransaction,
    Client,
    ClientPayment,
    ClientProductPrice,
    DailyCashSession,
    GroupConfig,
    Product,
    ProductReturn,
    Sale,
    SaleItem,
    SubscriptionPayment,
    SubscriptionState,
)


import asyncio
from contextlib import contextmanager
from contextvars import ContextVar

ANONYMOUS_ADMIN_BOT_ID = 1087968824
CURRENT_TENANT_ID: ContextVar[int] = ContextVar("norin_current_tenant_id", default=1)
CURRENT_USER_AUTHORIZED: ContextVar[Optional[bool]] = ContextVar(
    "norin_current_user_authorized", default=None
)
_ADD_USER_LOCK = asyncio.Lock()
_AUTH_CACHE_EPOCH = 0


def get_auth_cache_epoch() -> int:
    """Return monotonic epoch incremented whenever auth, group, or subscription state changes."""
    return _AUTH_CACHE_EPOCH


def bump_auth_cache_epoch() -> int:
    """Invalidate short-lived middleware subscription/auth caches immediately."""
    global _AUTH_CACHE_EPOCH
    _AUTH_CACHE_EPOCH += 1
    return _AUTH_CACHE_EPOCH


def get_current_tenant_id(tenant_id: Optional[int] = None) -> int:
    """Return explicit tenant_id or the active tenant_id from ContextVar (defaults to 1)."""
    if tenant_id is not None:
        return int(tenant_id)
    return int(CURRENT_TENANT_ID.get() or 1)


def set_current_tenant_id(tenant_id: int):
    """Set the active tenant_id in ContextVar and return reset token."""
    return CURRENT_TENANT_ID.set(int(tenant_id or 1))


def reset_current_tenant_id(token) -> None:
    """Restore previous tenant_id ContextVar token."""
    CURRENT_TENANT_ID.reset(token)


@contextmanager
def tenant_scope(tenant_id: int):
    """Context manager scoping CRUD operations cleanly to a specific tenant_id."""
    token = set_current_tenant_id(tenant_id)
    try:
        yield int(tenant_id or 1)
    finally:
        reset_current_tenant_id(token)


# ---------------------------------------------------------------------------
# Timezone & Datetime Helpers
# ---------------------------------------------------------------------------


def now_utc() -> datetime:
    """Return current UTC aware datetime."""
    return datetime.now(timezone.utc)


def now_local() -> datetime:
    """Return current datetime in configured local timezone."""
    tz = ZoneInfo(get_settings().TIMEZONE)
    return datetime.now(tz)


def to_utc_dt(dt: Optional[datetime]) -> datetime:
    """Normalize any naive/aware datetime into UTC-aware datetime (handles SQLite stripping tzinfo)."""
    if dt is None:
        return now_utc()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_local_dt(dt: Optional[datetime]) -> datetime:
    """Convert any UTC/naive/aware datetime into configured local timezone."""
    tz = ZoneInfo(get_settings().TIMEZONE)
    return to_utc_dt(dt).astimezone(tz)


def format_local_dt(dt: Optional[datetime], fmt: str = "%d.%m.%Y %H:%M") -> str:
    """Format a datetime in local timezone."""
    return to_local_dt(dt).strftime(fmt)


def today_iso() -> str:
    """Return today's date as YYYY-MM-DD in local timezone."""
    return now_local().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Dataclasses for Computed Summaries
# ---------------------------------------------------------------------------


@dataclass
class ClientDebtSummary:
    """Full debt ledger and history summary for a single client."""

    client: Client
    opening_debt: float
    total_sales: float
    total_paid: float
    current_debt: float
    total_kg: float
    recent_sales: List[Sale]
    recent_payments: List[ClientPayment]
    last_payment_at: Optional[datetime] = None
    total_returns: float = 0.0
    total_return_kg: float = 0.0
    recent_returns: List[ProductReturn] = field(default_factory=list)


@dataclass
class DailyReportSummary:
    """Calculated daily cash, sales kg, production cost, profit, and client debts."""

    session: DailyCashSession
    opening_balance: float
    main_cash_in: float
    client_cash_in: float
    client_card_in: float
    client_transfer_in: float
    kassa_debt_today: float
    kassa_repay_today: float
    total_expenses: float
    total_available_cash: float
    expected_cash: float
    total_kassa_debt_outstanding: float
    confirmed_sales: List[Sale]
    weight_by_product: Dict[str, float]
    total_kg: float
    total_revenue: float
    total_cost: float
    total_profit: float
    margin_pct: float
    total_all_clients_debt: float
    client_payments: List[ClientPayment]
    cash_transactions: List[CashTransaction]
    returns: List[ProductReturn] = field(default_factory=list)
    total_return_kg: float = 0.0
    total_return_amount: float = 0.0
    total_return_cost: float = 0.0


@dataclass
class PeriodReportSummary:
    """Aggregated sales, cost, profit, collections, and expenses over N days."""

    days: int
    start_date: str
    end_date: str
    sales_count: int
    total_kg: float
    weight_by_product: Dict[str, float]
    total_revenue: float
    total_cost: float
    total_profit: float
    margin_pct: float
    total_cash_collected: float
    total_card_collected: float
    total_transfer_collected: float
    total_expenses: float
    total_all_clients_debt: float
    returns_count: int = 0
    total_return_kg: float = 0.0
    total_return_amount: float = 0.0


@dataclass
class SubscriptionStatus:
    """Evaluated SaaS subscription state and access permission."""

    state: SubscriptionState
    status: str  # "active" | "expiring" | "grace" | "expired" | "suspended"
    days_left: int
    grace_days_left: int
    is_allowed: bool


# ---------------------------------------------------------------------------
# Products Catalog
# ---------------------------------------------------------------------------


async def list_products(
    db: AsyncSession, active_only: bool = True, tenant_id: Optional[int] = None
) -> List[Product]:
    """List products for the active tenant, auto-seeding defaults if empty."""
    tid = get_current_tenant_id(tenant_id)
    any_prod = await db.scalar(select(Product.id).where(Product.tenant_id == tid).limit(1))
    if any_prod is None:
        from database.session import seed_default_products

        await seed_default_products(db, tenant_id=tid)

    stmt = select(Product).where(Product.tenant_id == tid)
    if active_only:
        stmt = stmt.where(Product.is_active.is_(True))
    stmt = stmt.order_by(Product.order_num, Product.id)
    return list((await db.scalars(stmt)).all())


async def get_product(
    db: AsyncSession, product_id: int, tenant_id: Optional[int] = None
) -> Optional[Product]:
    """Fetch a product by id within the active tenant."""
    tid = get_current_tenant_id(tenant_id)
    prod = await db.get(Product, product_id)
    if prod is None or prod.tenant_id != tid:
        return None
    return prod


async def create_product(
    db: AsyncSession,
    name: str,
    cost_price: float,
    default_sell_price: float,
    aliases: str = "",
    unit: str = "kg",
    order_num: Optional[int] = None,
    tenant_id: Optional[int] = None,
) -> Product:
    """Create a new product or reactivate/update an existing one with the same name in this tenant."""
    tid = get_current_tenant_id(tenant_id)
    clean_name = name.strip()
    existing = await db.scalar(
        select(Product).where(Product.tenant_id == tid, Product.name == clean_name)
    )
    if existing is not None:
        existing.cost_price = float(cost_price)
        existing.default_sell_price = float(default_sell_price)
        if aliases.strip():
            existing.aliases = aliases.strip().upper()
        existing.unit = unit.strip() or "kg"
        existing.is_active = True
        await db.commit()
        await db.refresh(existing)
        return existing

    if order_num is None:
        current = await list_products(db, active_only=False, tenant_id=tid)
        order_num = max((p.order_num for p in current), default=0) + 1

    alias_str = aliases.strip().upper() or clean_name.upper()
    prod = Product(
        tenant_id=tid,
        order_num=order_num,
        name=clean_name,
        aliases=alias_str,
        unit=unit.strip() or "kg",
        cost_price=float(cost_price),
        default_sell_price=float(default_sell_price),
        is_active=True,
    )
    db.add(prod)
    await db.commit()
    await db.refresh(prod)
    return prod


async def update_product(
    db: AsyncSession,
    product_id: int,
    name: Optional[str] = None,
    cost_price: Optional[float] = None,
    default_sell_price: Optional[float] = None,
    aliases: Optional[str] = None,
    unit: Optional[str] = None,
    tenant_id: Optional[int] = None,
) -> Optional[Product]:
    """Update product fields within the active tenant."""
    prod = await get_product(db, product_id, tenant_id=tenant_id)
    if prod is None:
        return None
    if name is not None and name.strip():
        prod.name = name.strip()
    if cost_price is not None:
        prod.cost_price = float(cost_price)
    if default_sell_price is not None:
        prod.default_sell_price = float(default_sell_price)
    if aliases is not None:
        prod.aliases = aliases.strip().upper()
    if unit is not None and unit.strip():
        prod.unit = unit.strip()[:16]
    await db.commit()
    await db.refresh(prod)
    return prod


async def append_product_alias(
    db: AsyncSession, product_id: int, new_alias: str, tenant_id: Optional[int] = None
) -> Optional[Product]:
    """Append an uppercase synonym/alias to a product within the active tenant."""
    prod = await get_product(db, product_id, tenant_id=tenant_id)
    if prod is None:
        return None
    alias_clean = new_alias.strip().upper()
    if not alias_clean:
        return prod
    parts = [p.strip() for p in prod.aliases.split(",") if p.strip()]
    if alias_clean not in [p.upper() for p in parts]:
        parts.append(alias_clean)
    prod.aliases = ",".join(parts)
    await db.commit()
    await db.refresh(prod)
    return prod


async def delete_product(
    db: AsyncSession, product_id: int, tenant_id: Optional[int] = None
) -> bool:
    """Soft-deactivate a product so historical SaleItems keep their reference."""
    prod = await get_product(db, product_id, tenant_id=tenant_id)
    if prod is None:
        return False
    prod.is_active = False
    await db.commit()
    return True


_UZ_QUOTE_TRANS = str.maketrans(
    {
        '"': "'",
        "‘": "'",
        "’": "'",
        "ʻ": "'",
        "ʼ": "'",
        "`": "'",
    }
)


def _norm_uz(text: str) -> str:
    """Normalize Uzbek apostrophe/quote variants, case, and whitespace."""
    return " ".join(text.translate(_UZ_QUOTE_TRANS).strip().lower().split())


def match_product(hint: Optional[str], products: Sequence[Product]) -> Optional[Product]:
    """Match a text/OCR product hint against product names and comma-separated aliases."""
    if not hint or not products:
        return None
    norm_hint = _norm_uz(hint)
    if not norm_hint:
        return None

    # 1. Exact name or exact alias match
    for prod in products:
        if _norm_uz(prod.name) == norm_hint:
            return prod
        aliases = [_norm_uz(a) for a in prod.aliases.split(",") if a.strip()]
        if norm_hint in aliases:
            return prod

    # 2. Best token/substring score (longest matching alias wins)
    best_prod: Optional[Product] = None
    best_score = 0
    hint_tokens = set(norm_hint.replace("(", " ").replace(")", " ").split())
    for prod in products:
        candidates = [_norm_uz(prod.name)]
        candidates.extend(_norm_uz(a) for a in prod.aliases.split(",") if a.strip())
        for cand in candidates:
            if not cand:
                continue
            if cand in norm_hint or norm_hint in cand:
                score = len(cand) + (20 if cand in hint_tokens else 0)
                if score > best_score:
                    best_score = score
                    best_prod = prod
    return best_prod


# ---------------------------------------------------------------------------
# Clients, Custom Pricing & Group Binding
# ---------------------------------------------------------------------------


async def list_clients(
    db: AsyncSession, active_only: bool = True, tenant_id: Optional[int] = None
) -> List[Client]:
    """List clients ordered alphabetically by name for the active tenant."""
    tid = get_current_tenant_id(tenant_id)
    stmt = select(Client).where(Client.tenant_id == tid)
    if active_only:
        stmt = stmt.where(Client.is_active.is_(True))
    stmt = stmt.order_by(Client.name, Client.id)
    return list((await db.scalars(stmt)).all())


async def get_client(
    db: AsyncSession, client_id: int, tenant_id: Optional[int] = None
) -> Optional[Client]:
    """Fetch a client by id within the active tenant."""
    tid = get_current_tenant_id(tenant_id)
    cli = await db.get(Client, client_id)
    if cli is None or cli.tenant_id != tid:
        return None
    return cli


async def get_client_by_group(
    db: AsyncSession, chat_id: int, tenant_id: Optional[int] = None
) -> Optional[Client]:
    """Find an active client bound to a Telegram group chat_id within the active tenant."""
    tid = get_current_tenant_id(tenant_id)
    stmt = (
        select(Client)
        .where(
            Client.tenant_id == tid,
            Client.group_chat_id == chat_id,
            Client.is_active.is_(True),
        )
        .limit(1)
    )
    return await db.scalar(stmt)


async def create_client(
    db: AsyncSession,
    name: str,
    phone: str = "",
    opening_debt: float = 0.0,
    aliases: str = "",
    tenant_id: Optional[int] = None,
) -> Client:
    """Create a new client or reactivate an existing inactive one with the same name in this tenant."""
    tid = get_current_tenant_id(tenant_id)
    clean_name = name.strip()
    existing = await db.scalar(
        select(Client).where(Client.tenant_id == tid, Client.name == clean_name)
    )
    if existing is not None:
        if phone.strip():
            existing.phone = phone.strip()
        if opening_debt:
            existing.opening_debt = float(opening_debt)
        if aliases.strip():
            existing.aliases = aliases.strip().upper()
        existing.is_active = True
        await db.commit()
        await db.refresh(existing)
        return existing

    client = Client(
        tenant_id=tid,
        name=clean_name,
        aliases=(aliases.strip() or clean_name).upper(),
        phone=phone.strip(),
        opening_debt=float(opening_debt),
        is_active=True,
    )
    db.add(client)
    await db.commit()
    await db.refresh(client)
    return client


async def update_client(
    db: AsyncSession,
    client_id: int,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    opening_debt: Optional[float] = None,
    aliases: Optional[str] = None,
    tenant_id: Optional[int] = None,
) -> Optional[Client]:
    """Update client profile fields within the active tenant."""
    client = await get_client(db, client_id, tenant_id=tenant_id)
    if client is None:
        return None
    if name is not None and name.strip():
        client.name = name.strip()
    if phone is not None:
        client.phone = phone.strip()
    if opening_debt is not None:
        client.opening_debt = float(opening_debt)
    if aliases is not None:
        client.aliases = aliases.strip().upper()
    await db.commit()
    await db.refresh(client)
    return client


async def bind_client_group(
    db: AsyncSession,
    client_id: int,
    chat_id: int,
    title: str = "",
    tenant_id: Optional[int] = None,
) -> Optional[Client]:
    """Bind a Telegram group chat_id to a client (detaching any other client from the same group)."""
    client = await get_client(db, client_id, tenant_id=tenant_id)
    if client is None:
        return None

    # Ensure 1-to-1 group chat -> client mapping across all tenants
    others = (
        await db.scalars(
            select(Client).where(Client.group_chat_id == chat_id, Client.id != client_id)
        )
    ).all()
    for other in others:
        other.group_chat_id = None
        other.group_title = ""

    client.group_chat_id = int(chat_id)
    client.group_title = title.strip() or f"Guruh ({chat_id})"
    await db.commit()
    await db.refresh(client)
    bump_auth_cache_epoch()
    return client


async def unbind_client_group(
    db: AsyncSession, client_id: int, tenant_id: Optional[int] = None
) -> Optional[Client]:
    """Detach Telegram group from a client within the active tenant."""
    client = await get_client(db, client_id, tenant_id=tenant_id)
    if client is None:
        return None
    client.group_chat_id = None
    client.group_title = ""
    await db.commit()
    await db.refresh(client)
    bump_auth_cache_epoch()
    return client


async def delete_client(
    db: AsyncSession, client_id: int, tenant_id: Optional[int] = None
) -> bool:
    """Soft-deactivate a client and unbind its Telegram group within the active tenant."""
    client = await get_client(db, client_id, tenant_id=tenant_id)
    if client is None:
        return False
    client.is_active = False
    client.group_chat_id = None
    client.group_title = ""
    await db.commit()
    return True


def match_client(hint: Optional[str], clients: Sequence[Client]) -> Optional[Client]:
    """Match a text/voice/caption client hint against active clients and aliases."""
    if not hint or not clients:
        return None
    norm_hint = _norm_uz(hint)
    if not norm_hint:
        return None

    for cli in clients:
        if _norm_uz(cli.name) == norm_hint:
            return cli
        aliases = [_norm_uz(a) for a in cli.aliases.split(",") if a.strip()]
        if norm_hint in aliases:
            return cli

    best_cli: Optional[Client] = None
    best_score = 0
    for cli in clients:
        candidates = [_norm_uz(cli.name)]
        candidates.extend(_norm_uz(a) for a in cli.aliases.split(",") if a.strip())
        for cand in candidates:
            if not cand or len(cand) < 2:
                continue
            if cand in norm_hint or norm_hint in cand:
                score = len(cand)
                if score > best_score:
                    best_score = score
                    best_cli = cli
    return best_cli


async def set_client_product_price(
    db: AsyncSession,
    client_id: int,
    product_id: int,
    sell_price: Optional[float],
    tenant_id: Optional[int] = None,
) -> Optional[ClientProductPrice]:
    """Set or clear (when sell_price is None or <=0) a client-specific product price."""
    tid = get_current_tenant_id(tenant_id)
    cli = await get_client(db, client_id, tenant_id=tid)
    prod = await get_product(db, product_id, tenant_id=tid)
    if cli is None or prod is None:
        return None

    stmt = select(ClientProductPrice).where(
        ClientProductPrice.client_id == client_id,
        ClientProductPrice.product_id == product_id,
    )
    existing = await db.scalar(stmt)
    if sell_price is None or sell_price <= 0:
        if existing is not None:
            await db.delete(existing)
            await db.commit()
        return None

    if existing is None:
        existing = ClientProductPrice(
            client_id=client_id,
            product_id=product_id,
            sell_price=float(sell_price),
        )
        db.add(existing)
    else:
        existing.sell_price = float(sell_price)
    await db.commit()
    await db.refresh(existing)
    return existing


async def get_client_prices_map(
    db: AsyncSession, client_id: int, tenant_id: Optional[int] = None
) -> Dict[int, float]:
    """Return {product_id: custom_sell_price} for a client within the active tenant."""
    cli = await get_client(db, client_id, tenant_id=tenant_id)
    if cli is None:
        return {}
    rows = (
        await db.scalars(
            select(ClientProductPrice).where(ClientProductPrice.client_id == client_id)
        )
    ).all()
    return {row.product_id: float(row.sell_price) for row in rows}


async def resolve_sell_price(
    db: AsyncSession, client_id: Optional[int], product: Product
) -> float:
    """Resolve client custom price for product, falling back to Product.default_sell_price."""
    if client_id is not None:
        custom = await db.scalar(
            select(ClientProductPrice).where(
                ClientProductPrice.client_id == client_id,
                ClientProductPrice.product_id == product.id,
            )
        )
        if custom is not None and custom.sell_price > 0:
            return float(custom.sell_price)
    return float(product.default_sell_price)


# ---------------------------------------------------------------------------
# Client Debt Ledger
# ---------------------------------------------------------------------------


async def compute_client_debt(
    db: AsyncSession,
    client_id: int,
    history_limit: Optional[int] = 15,
    tenant_id: Optional[int] = None,
) -> ClientDebtSummary:
    """Compute opening debt + confirmed sales - non-deleted payments for a client."""
    tid = get_current_tenant_id(tenant_id)
    client = await get_client(db, client_id, tenant_id=tid)
    if client is None:
        raise ValueError(f"Client {client_id} not found")

    opening = float(client.opening_debt or 0.0)
    if history_limit is None:
        sales = list(
            (
                await db.scalars(
                    select(Sale)
                    .options(selectinload(Sale.items))
                    .where(
                        Sale.tenant_id == tid,
                        Sale.client_id == client_id,
                        Sale.status == "confirmed",
                    )
                    .order_by(desc(Sale.id))
                )
            ).all()
        )
        payments = list(
            (
                await db.scalars(
                    select(ClientPayment)
                    .where(
                        ClientPayment.tenant_id == tid,
                        ClientPayment.client_id == client_id,
                        ClientPayment.is_deleted.is_(False),
                    )
                    .order_by(desc(ClientPayment.id))
                )
            ).all()
        )
        returns = list(
            (
                await db.scalars(
                    select(ProductReturn)
                    .where(
                        ProductReturn.tenant_id == tid,
                        ProductReturn.client_id == client_id,
                        ProductReturn.is_deleted.is_(False),
                    )
                    .order_by(desc(ProductReturn.id))
                )
            ).all()
        )
        total_sales = sum(float(s.total_amount) for s in sales)
        total_paid = sum(float(p.amount) for p in payments)
        total_returns = sum(float(r.total_amount) for r in returns)
        total_return_kg = round(sum(float(r.weight_kg) for r in returns), 3)
        total_kg = round(sum(float(s.total_weight_kg) for s in sales), 3)
        last_pay_at = payments[0].created_at if payments else None
        recent_sales = sales
        recent_payments = payments
        recent_returns = returns
    else:
        lim = max(0, int(history_limit))
        s_amt, s_kg = (
            await db.execute(
                select(
                    sa_func.coalesce(sa_func.sum(Sale.total_amount), 0.0),
                    sa_func.coalesce(sa_func.sum(Sale.total_weight_kg), 0.0),
                ).where(
                    Sale.tenant_id == tid,
                    Sale.client_id == client_id,
                    Sale.status == "confirmed",
                )
            )
        ).one()
        p_amt, last_pay_at = (
            await db.execute(
                select(
                    sa_func.coalesce(sa_func.sum(ClientPayment.amount), 0.0),
                    sa_func.max(ClientPayment.created_at),
                ).where(
                    ClientPayment.tenant_id == tid,
                    ClientPayment.client_id == client_id,
                    ClientPayment.is_deleted.is_(False),
                )
            )
        ).one()
        r_amt, r_kg = (
            await db.execute(
                select(
                    sa_func.coalesce(sa_func.sum(ProductReturn.total_amount), 0.0),
                    sa_func.coalesce(sa_func.sum(ProductReturn.weight_kg), 0.0),
                ).where(
                    ProductReturn.tenant_id == tid,
                    ProductReturn.client_id == client_id,
                    ProductReturn.is_deleted.is_(False),
                )
            )
        ).one()
        total_sales = float(s_amt or 0.0)
        total_kg = round(float(s_kg or 0.0), 3)
        total_paid = float(p_amt or 0.0)
        total_returns = float(r_amt or 0.0)
        total_return_kg = round(float(r_kg or 0.0), 3)
        recent_sales = (
            list(
                (
                    await db.scalars(
                        select(Sale)
                        .options(selectinload(Sale.items))
                        .where(
                            Sale.tenant_id == tid,
                            Sale.client_id == client_id,
                            Sale.status == "confirmed",
                        )
                        .order_by(desc(Sale.id))
                        .limit(lim)
                    )
                ).all()
            )
            if lim > 0
            else []
        )
        recent_payments = (
            list(
                (
                    await db.scalars(
                        select(ClientPayment)
                        .where(
                            ClientPayment.tenant_id == tid,
                            ClientPayment.client_id == client_id,
                            ClientPayment.is_deleted.is_(False),
                        )
                        .order_by(desc(ClientPayment.id))
                        .limit(lim)
                    )
                ).all()
            )
            if lim > 0
            else []
        )
        recent_returns = (
            list(
                (
                    await db.scalars(
                        select(ProductReturn)
                        .where(
                            ProductReturn.tenant_id == tid,
                            ProductReturn.client_id == client_id,
                            ProductReturn.is_deleted.is_(False),
                        )
                        .order_by(desc(ProductReturn.id))
                        .limit(lim)
                    )
                ).all()
            )
            if lim > 0
            else []
        )

    current_debt = round(opening + total_sales - total_returns - total_paid, 2)
    return ClientDebtSummary(
        client=client,
        opening_debt=opening,
        total_sales=total_sales,
        total_paid=total_paid,
        current_debt=current_debt,
        total_kg=total_kg,
        recent_sales=recent_sales,
        recent_payments=recent_payments,
        last_payment_at=last_pay_at,
        total_returns=total_returns,
        total_return_kg=total_return_kg,
        recent_returns=recent_returns,
    )


async def list_all_client_debts(
    db: AsyncSession, tenant_id: Optional[int] = None
) -> List[ClientDebtSummary]:
    """Return ClientDebtSummary for all active clients of this tenant sorted by highest debt."""
    tid = get_current_tenant_id(tenant_id)
    clients = await list_clients(db, active_only=True, tenant_id=tid)
    if not clients:
        return []

    active_ids = [c.id for c in clients]
    sales_rows = (
        await db.execute(
            select(
                Sale.client_id,
                sa_func.coalesce(sa_func.sum(Sale.total_amount), 0.0),
                sa_func.coalesce(sa_func.sum(Sale.total_weight_kg), 0.0),
            )
            .where(
                Sale.tenant_id == tid,
                Sale.status == "confirmed",
                Sale.client_id.in_(active_ids),
            )
            .group_by(Sale.client_id)
        )
    ).all()
    pay_rows = (
        await db.execute(
            select(
                ClientPayment.client_id,
                sa_func.coalesce(sa_func.sum(ClientPayment.amount), 0.0),
                sa_func.max(ClientPayment.created_at),
            )
            .where(
                ClientPayment.tenant_id == tid,
                ClientPayment.is_deleted.is_(False),
                ClientPayment.client_id.in_(active_ids),
            )
            .group_by(ClientPayment.client_id)
        )
    ).all()
    ret_rows = (
        await db.execute(
            select(
                ProductReturn.client_id,
                sa_func.coalesce(sa_func.sum(ProductReturn.total_amount), 0.0),
                sa_func.coalesce(sa_func.sum(ProductReturn.weight_kg), 0.0),
            )
            .where(
                ProductReturn.tenant_id == tid,
                ProductReturn.is_deleted.is_(False),
                ProductReturn.client_id.in_(active_ids),
            )
            .group_by(ProductReturn.client_id)
        )
    ).all()

    sales_agg = {int(cid): (float(amt or 0.0), float(kg or 0.0)) for cid, amt, kg in sales_rows}
    pay_agg = {int(cid): (float(amt or 0.0), last_dt) for cid, amt, last_dt in pay_rows}
    ret_agg = {int(cid): (float(amt or 0.0), float(kg or 0.0)) for cid, amt, kg in ret_rows}

    summaries: List[ClientDebtSummary] = []
    for cli in clients:
        t_sales, raw_kg = sales_agg.get(cli.id, (0.0, 0.0))
        t_paid, last_dt = pay_agg.get(cli.id, (0.0, None))
        t_ret, raw_ret_kg = ret_agg.get(cli.id, (0.0, 0.0))
        opening = float(cli.opening_debt or 0.0)
        t_kg = round(raw_kg, 3)
        summaries.append(
            ClientDebtSummary(
                client=cli,
                opening_debt=opening,
                total_sales=t_sales,
                total_paid=t_paid,
                current_debt=round(opening + t_sales - t_ret - t_paid, 2),
                total_kg=t_kg,
                recent_sales=[],
                recent_payments=[],
                last_payment_at=last_dt,
                total_returns=t_ret,
                total_return_kg=round(raw_ret_kg, 3),
            )
        )

    summaries.sort(key=lambda d: (-d.current_debt, d.client.name.lower()))
    return summaries


# ---------------------------------------------------------------------------
# Sales CRUD & Snapshot Calculations
# ---------------------------------------------------------------------------


def _recalc_item(item: SaleItem) -> None:
    """Recompute line cost, line total, and line profit on a SaleItem."""
    w = float(item.weight_kg or 0.0)
    item.line_cost = round(w * float(item.unit_cost or 0.0), 2)
    item.line_total = round(w * float(item.unit_sell_price or 0.0), 2)
    item.line_profit = round(item.line_total - item.line_cost, 2)


def _recalc_sale_totals(sale: Sale) -> None:
    """Recompute Sale aggregates from its SaleItems."""
    for item in sale.items:
        _recalc_item(item)
    sale.total_weight_kg = round(sum(float(i.weight_kg or 0.0) for i in sale.items), 3)
    sale.total_cost = round(sum(float(i.line_cost or 0.0) for i in sale.items), 2)
    sale.total_amount = round(sum(float(i.line_total or 0.0) for i in sale.items), 2)
    sale.total_profit = round(sale.total_amount - sale.total_cost, 2)


async def create_pending_sale(
    db: AsyncSession,
    client_id: Optional[int],
    items_spec: Sequence[dict],
    photo_file_id: Optional[str] = None,
    note: Optional[str] = None,
    source_channel: str = "dm",
    session_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
) -> Sale:
    """
    Create a pending Sale with itemized Norin rows for the active tenant.

    Each entry in `items_spec` should provide:
        - product_id (int) OR product (Product)
        - weight_kg (float)
        - optional weights_detail (str)
        - optional unit_sell_price (float override)
    """
    tid = get_current_tenant_id(tenant_id)
    if session_id is None:
        sess = await get_or_create_open_session(db, tenant_id=tid)
        session_id = sess.id
    else:
        sess = await db.get(DailyCashSession, session_id)
        if sess is None or sess.tenant_id != tid:
            raise ValueError(f"Session {session_id} not found")

    if client_id is not None:
        cli = await get_client(db, client_id, tenant_id=tid)
        if cli is None:
            raise ValueError(f"Client {client_id} not found")
        custom_prices = await get_client_prices_map(db, client_id, tenant_id=tid)
    else:
        custom_prices = {}

    sale = Sale(
        tenant_id=tid,
        session_id=session_id,
        client_id=client_id,
        report_date=sess.report_date,
        photo_file_id=photo_file_id,
        note=note,
        status="pending",
        source_channel=source_channel,
    )

    sale_items: List[SaleItem] = []
    for spec in items_spec:
        prod: Optional[Product] = spec.get("product")
        if prod is not None and prod.tenant_id != tid:
            prod = None
        if prod is None and spec.get("product_id") is not None:
            prod = await get_product(db, int(spec["product_id"]), tenant_id=tid)
        if prod is None:
            raise ValueError("Mahsulot topilmadi")

        weight_kg = round(float(spec.get("weight_kg", 0.0)), 3)
        unit_cost = float(prod.cost_price)
        if spec.get("unit_sell_price") is not None:
            unit_sell = float(spec["unit_sell_price"])
        else:
            unit_sell = custom_prices.get(prod.id, float(prod.default_sell_price))

        item = SaleItem(
            product_id=prod.id,
            product_name=prod.name,
            weight_kg=weight_kg,
            weights_detail=str(spec.get("weights_detail") or "").strip(),
            unit_cost=unit_cost,
            unit_sell_price=unit_sell,
        )
        _recalc_item(item)
        sale_items.append(item)

    sale.items = sale_items
    _recalc_sale_totals(sale)
    db.add(sale)
    await db.commit()
    loaded = await get_sale(db, sale.id, tenant_id=tid)
    assert loaded is not None
    return loaded


async def get_sale(
    db: AsyncSession, sale_id: int, tenant_id: Optional[int] = None
) -> Optional[Sale]:
    """Fetch a Sale eager-loading its items and client within the active tenant."""
    tid = get_current_tenant_id(tenant_id)
    stmt = (
        select(Sale)
        .options(selectinload(Sale.items), selectinload(Sale.client))
        .where(Sale.id == sale_id, Sale.tenant_id == tid)
    )
    return await db.scalar(stmt)


async def confirm_sale(
    db: AsyncSession,
    sale_id: int,
    group_chat_id: Optional[int] = None,
    group_message_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
) -> Optional[Sale]:
    """Confirm a pending sale and attach optional group message metadata."""
    tid = get_current_tenant_id(tenant_id)
    sale = await get_sale(db, sale_id, tenant_id=tid)
    if sale is None or sale.status == "deleted":
        return None
    sale.status = "confirmed"
    if group_chat_id is not None:
        sale.group_chat_id = group_chat_id
    if group_message_id is not None:
        sale.group_message_id = group_message_id
    await db.commit()
    await compute_session_summary(db, sale.session_id, tenant_id=tid)
    return await get_sale(db, sale_id, tenant_id=tid)


async def set_sale_group_message(
    db: AsyncSession,
    sale_id: int,
    group_chat_id: Optional[int],
    group_message_id: Optional[int],
    tenant_id: Optional[int] = None,
) -> Optional[Sale]:
    """Store or clear Telegram group chat_id and message_id for a Sale."""
    tid = get_current_tenant_id(tenant_id)
    sale = await get_sale(db, sale_id, tenant_id=tid)
    if sale is None:
        return None
    sale.group_chat_id = group_chat_id
    sale.group_message_id = group_message_id
    await db.commit()
    return await get_sale(db, sale_id, tenant_id=tid)


async def update_sale_client(
    db: AsyncSession,
    sale_id: int,
    new_client_id: Optional[int],
    tenant_id: Optional[int] = None,
) -> Optional[Sale]:
    """Reassign a Sale's client and recalculate item sell prices using the new client's prices."""
    tid = get_current_tenant_id(tenant_id)
    sale = await get_sale(db, sale_id, tenant_id=tid)
    if sale is None or sale.status == "deleted":
        return None
    if new_client_id is not None and await get_client(db, new_client_id, tenant_id=tid) is None:
        return None
    sale.client_id = new_client_id
    custom_prices = (
        await get_client_prices_map(db, new_client_id, tenant_id=tid) if new_client_id else {}
    )

    for item in sale.items:
        if item.product_id is not None:
            prod = await get_product(db, item.product_id, tenant_id=tid)
            if prod is not None:
                item.unit_sell_price = custom_prices.get(prod.id, float(prod.default_sell_price))
    _recalc_sale_totals(sale)
    await db.commit()
    if sale.status == "confirmed":
        await compute_session_summary(db, sale.session_id, tenant_id=tid)
    return await get_sale(db, sale_id, tenant_id=tid)


async def update_sale_item(
    db: AsyncSession,
    item_id: int,
    weight_kg: Optional[float] = None,
    unit_sell_price: Optional[float] = None,
    product_id: Optional[int] = None,
    weights_detail: Optional[str] = None,
    tenant_id: Optional[int] = None,
) -> Optional[Sale]:
    """Update a SaleItem and recalculate its parent Sale totals and session summary."""
    tid = get_current_tenant_id(tenant_id)
    item = await db.get(SaleItem, item_id)
    if item is None:
        return None
    sale = await get_sale(db, item.sale_id, tenant_id=tid)
    if sale is None or sale.status == "deleted":
        return None

    target_item = next((i for i in sale.items if i.id == item_id), item)
    if product_id is not None:
        prod = await get_product(db, product_id, tenant_id=tid)
        if prod is not None:
            target_item.product_id = prod.id
            target_item.product_name = prod.name
            target_item.unit_cost = float(prod.cost_price)
            if unit_sell_price is None:
                target_item.unit_sell_price = await resolve_sell_price(db, sale.client_id, prod)
    if weight_kg is not None:
        target_item.weight_kg = round(float(weight_kg), 3)
        if weights_detail is None:
            target_item.weights_detail = ""
    if weights_detail is not None:
        target_item.weights_detail = weights_detail.strip()
    if unit_sell_price is not None:
        target_item.unit_sell_price = float(unit_sell_price)

    _recalc_sale_totals(sale)
    await db.commit()
    if sale.status == "confirmed":
        await compute_session_summary(db, sale.session_id, tenant_id=tid)
    return await get_sale(db, sale.id, tenant_id=tid)


async def delete_sale(
    db: AsyncSession, sale_id: int, tenant_id: Optional[int] = None
) -> Optional[Sale]:
    """Soft-delete a Sale and recalculate daily session summary."""
    tid = get_current_tenant_id(tenant_id)
    sale = await get_sale(db, sale_id, tenant_id=tid)
    if sale is None or sale.status == "deleted":
        return None
    was_confirmed = sale.status == "confirmed"
    sale.status = "deleted"
    await db.commit()
    if was_confirmed:
        await compute_session_summary(db, sale.session_id, tenant_id=tid)
    return await get_sale(db, sale_id, tenant_id=tid)


async def find_duplicate_confirmed_sale(
    db: AsyncSession,
    session_id: int,
    client_id: Optional[int],
    total_weight_kg: float,
    exclude_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
) -> Optional[Sale]:
    """Check if a confirmed sale with same client and weight already exists in this session."""
    if client_id is None:
        return None
    tid = get_current_tenant_id(tenant_id)
    stmt = (
        select(Sale)
        .options(selectinload(Sale.items), selectinload(Sale.client))
        .where(
            Sale.tenant_id == tid,
            Sale.session_id == session_id,
            Sale.client_id == client_id,
            Sale.status == "confirmed",
        )
    )
    rows = (await db.scalars(stmt)).all()
    for row in rows:
        if exclude_id is not None and row.id == exclude_id:
            continue
        if abs(float(row.total_weight_kg) - float(total_weight_kg)) < 0.005:
            return row
    return None


async def list_recent_sales(
    db: AsyncSession,
    limit: int = 30,
    offset: int = 0,
    client_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
) -> List[Sale]:
    """Return recent confirmed sales ordered newest first for this tenant."""
    tid = get_current_tenant_id(tenant_id)
    stmt = (
        select(Sale)
        .options(selectinload(Sale.items), selectinload(Sale.client))
        .where(Sale.tenant_id == tid, Sale.status == "confirmed")
    )
    if client_id is not None:
        stmt = stmt.where(Sale.client_id == client_id)
    stmt = stmt.order_by(desc(Sale.id)).offset(offset).limit(limit)
    return list((await db.scalars(stmt)).all())


# ---------------------------------------------------------------------------
# Client Payments CRUD
# ---------------------------------------------------------------------------


async def add_client_payment(
    db: AsyncSession,
    client_id: int,
    amount: float,
    payment_method: str = "cash",
    note: str = "",
    session_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
) -> ClientPayment:
    """Record a payment received from a client and update session expected cash."""
    tid = get_current_tenant_id(tenant_id)
    cli = await get_client(db, client_id, tenant_id=tid)
    if cli is None:
        raise ValueError(f"Client {client_id} not found")
    if session_id is None:
        sess = await get_or_create_open_session(db, tenant_id=tid)
        session_id = sess.id
    else:
        sess = await db.get(DailyCashSession, session_id)
        if sess is None or sess.tenant_id != tid:
            raise ValueError(f"Session {session_id} not found")

    method = payment_method if payment_method in ("cash", "card", "transfer") else "cash"
    pay = ClientPayment(
        tenant_id=tid,
        session_id=session_id,
        client_id=client_id,
        amount=float(amount),
        payment_method=method,
        note=note.strip(),
        is_deleted=False,
    )
    db.add(pay)
    await db.commit()
    await compute_session_summary(db, session_id, tenant_id=tid)
    loaded = await get_client_payment(db, pay.id, tenant_id=tid)
    assert loaded is not None
    return loaded


async def get_client_payment(
    db: AsyncSession, payment_id: int, tenant_id: Optional[int] = None
) -> Optional[ClientPayment]:
    """Fetch a ClientPayment eager-loading its client within the active tenant."""
    tid = get_current_tenant_id(tenant_id)
    stmt = (
        select(ClientPayment)
        .options(selectinload(ClientPayment.client))
        .where(ClientPayment.id == payment_id, ClientPayment.tenant_id == tid)
    )
    return await db.scalar(stmt)


async def set_client_payment_group_message(
    db: AsyncSession,
    payment_id: int,
    group_chat_id: Optional[int],
    group_message_id: Optional[int],
    tenant_id: Optional[int] = None,
) -> Optional[ClientPayment]:
    """Store group receipt message reference on ClientPayment."""
    tid = get_current_tenant_id(tenant_id)
    pay = await get_client_payment(db, payment_id, tenant_id=tid)
    if pay is None:
        return None
    pay.group_chat_id = group_chat_id
    pay.group_message_id = group_message_id
    await db.commit()
    return await get_client_payment(db, payment_id, tenant_id=tid)


async def update_client_payment(
    db: AsyncSession,
    payment_id: int,
    new_amount: Optional[float] = None,
    payment_method: Optional[str] = None,
    note: Optional[str] = None,
    tenant_id: Optional[int] = None,
) -> Optional[ClientPayment]:
    """Edit a ClientPayment and recalculate daily cash session."""
    tid = get_current_tenant_id(tenant_id)
    pay = await get_client_payment(db, payment_id, tenant_id=tid)
    if pay is None or pay.is_deleted:
        return None
    if new_amount is not None:
        pay.amount = float(new_amount)
    if payment_method in ("cash", "card", "transfer"):
        pay.payment_method = payment_method
    if note is not None:
        pay.note = note.strip()
    await db.commit()
    await compute_session_summary(db, pay.session_id, tenant_id=tid)
    return await get_client_payment(db, payment_id, tenant_id=tid)


async def delete_client_payment(
    db: AsyncSession, payment_id: int, tenant_id: Optional[int] = None
) -> Optional[ClientPayment]:
    """Soft-delete a ClientPayment and recalculate daily cash session."""
    tid = get_current_tenant_id(tenant_id)
    pay = await get_client_payment(db, payment_id, tenant_id=tid)
    if pay is None or pay.is_deleted:
        return None
    pay.is_deleted = True
    await db.commit()
    await compute_session_summary(db, pay.session_id, tenant_id=tid)
    return await get_client_payment(db, payment_id, tenant_id=tid)


async def list_recent_client_payments(
    db: AsyncSession,
    limit: int = 30,
    offset: int = 0,
    client_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
) -> List[ClientPayment]:
    """Return recent non-deleted client payments ordered newest first for this tenant."""
    tid = get_current_tenant_id(tenant_id)
    stmt = (
        select(ClientPayment)
        .options(selectinload(ClientPayment.client))
        .where(ClientPayment.tenant_id == tid, ClientPayment.is_deleted.is_(False))
    )
    if client_id is not None:
        stmt = stmt.where(ClientPayment.client_id == client_id)
    stmt = stmt.order_by(desc(ClientPayment.id)).offset(offset).limit(limit)
    return list((await db.scalars(stmt)).all())


# ---------------------------------------------------------------------------
# Daily Cash Wallet, Expenses, Kassa Debt & Profit Reports
# ---------------------------------------------------------------------------


async def get_open_session(
    db: AsyncSession, tenant_id: Optional[int] = None
) -> Optional[DailyCashSession]:
    """Fetch the most recent open DailyCashSession for this tenant."""
    tid = get_current_tenant_id(tenant_id)
    stmt = (
        select(DailyCashSession)
        .where(DailyCashSession.tenant_id == tid, DailyCashSession.status == "open")
        .order_by(desc(DailyCashSession.id))
        .limit(1)
    )
    return await db.scalar(stmt)


async def get_last_closed_session(
    db: AsyncSession, tenant_id: Optional[int] = None
) -> Optional[DailyCashSession]:
    """Fetch the most recent closed DailyCashSession for this tenant."""
    tid = get_current_tenant_id(tenant_id)
    stmt = (
        select(DailyCashSession)
        .where(DailyCashSession.tenant_id == tid, DailyCashSession.status == "closed")
        .order_by(desc(DailyCashSession.id))
        .limit(1)
    )
    return await db.scalar(stmt)


async def get_or_create_open_session(
    db: AsyncSession, report_date: Optional[str] = None, tenant_id: Optional[int] = None
) -> DailyCashSession:
    """Return active open session or create one carrying over last closed counted cash."""
    tid = get_current_tenant_id(tenant_id)
    open_sess = await get_open_session(db, tenant_id=tid)
    if open_sess is not None:
        return open_sess

    last_closed = await get_last_closed_session(db, tenant_id=tid)
    opening_balance = float(last_closed.actual_counted_cash or 0.0) if last_closed else 0.0

    new_sess = DailyCashSession(
        tenant_id=tid,
        report_date=report_date or today_iso(),
        status="open",
        opening_balance=opening_balance,
        expected_cash=opening_balance,
    )
    db.add(new_sess)
    await db.commit()
    await db.refresh(new_sess)
    return new_sess


async def get_outstanding_kassa_debt(
    db: AsyncSession, tenant_id: Optional[int] = None
) -> float:
    """Compute cumulative unpaid debt borrowed from Kassa for this tenant."""
    tid = get_current_tenant_id(tenant_id)
    rows = (
        await db.execute(
            select(
                CashTransaction.source_type,
                sa_func.coalesce(sa_func.sum(CashTransaction.amount), 0.0),
            )
            .where(
                CashTransaction.tenant_id == tid,
                CashTransaction.is_deleted.is_(False),
                CashTransaction.source_type.in_(["kassa_debt", "kassa_repay"]),
            )
            .group_by(CashTransaction.source_type)
        )
    ).all()
    sums = {str(src): float(amt or 0.0) for src, amt in rows}
    return sums.get("kassa_debt", 0.0) - sums.get("kassa_repay", 0.0)


async def get_kassa_debt_stats(
    db: AsyncSession, limit: int = 10, tenant_id: Optional[int] = None
) -> dict:
    """Return kassa debt totals and recent kassa debt/repay movements for this tenant."""
    tid = get_current_tenant_id(tenant_id)
    txs = list(
        (
            await db.scalars(
                select(CashTransaction)
                .where(
                    CashTransaction.tenant_id == tid,
                    CashTransaction.is_deleted.is_(False),
                    CashTransaction.source_type.in_(["kassa_debt", "kassa_repay"]),
                )
                .order_by(desc(CashTransaction.id))
            )
        ).all()
    )
    total_borrowed = sum(float(t.amount) for t in txs if t.source_type == "kassa_debt")
    total_repaid = sum(float(t.amount) for t in txs if t.source_type == "kassa_repay")
    return {
        "total_borrowed": total_borrowed,
        "total_repaid": total_repaid,
        "outstanding": total_borrowed - total_repaid,
        "recent_txs": txs[:limit],
    }


async def get_total_all_clients_debt(
    db: AsyncSession, tenant_id: Optional[int] = None
) -> float:
    """Quickly compute total unpaid debt across all active clients of this tenant via SQL SUM."""
    tid = get_current_tenant_id(tenant_id)
    active_ids_sub = select(Client.id).where(Client.tenant_id == tid, Client.is_active.is_(True))
    opening = float(
        await db.scalar(
            select(sa_func.coalesce(sa_func.sum(Client.opening_debt), 0.0)).where(
                Client.tenant_id == tid, Client.is_active.is_(True)
            )
        )
        or 0.0
    )
    total_sales = float(
        await db.scalar(
            select(sa_func.coalesce(sa_func.sum(Sale.total_amount), 0.0)).where(
                Sale.tenant_id == tid,
                Sale.status == "confirmed",
                Sale.client_id.in_(active_ids_sub),
            )
        )
        or 0.0
    )
    total_paid = float(
        await db.scalar(
            select(sa_func.coalesce(sa_func.sum(ClientPayment.amount), 0.0)).where(
                ClientPayment.tenant_id == tid,
                ClientPayment.is_deleted.is_(False),
                ClientPayment.client_id.in_(active_ids_sub),
            )
        )
        or 0.0
    )
    total_returns = float(
        await db.scalar(
            select(sa_func.coalesce(sa_func.sum(ProductReturn.total_amount), 0.0)).where(
                ProductReturn.tenant_id == tid,
                ProductReturn.is_deleted.is_(False),
                ProductReturn.client_id.in_(active_ids_sub),
            )
        )
        or 0.0
    )
    return round(opening + total_sales - total_returns - total_paid, 2)


# ---------------------------------------------------------------------------
# Product Returns (Vozvrat) CRUD
# ---------------------------------------------------------------------------


async def get_product_return(
    db: AsyncSession, return_id: int, tenant_id: Optional[int] = None
) -> Optional[ProductReturn]:
    """Fetch a ProductReturn eager-loading its client within the active tenant."""
    tid = get_current_tenant_id(tenant_id)
    stmt = (
        select(ProductReturn)
        .options(selectinload(ProductReturn.client))
        .where(ProductReturn.id == return_id, ProductReturn.tenant_id == tid)
    )
    return await db.scalar(stmt)


async def add_product_return(
    db: AsyncSession,
    client_id: int,
    product_id: int,
    weight_kg: float,
    reason: str = "",
    unit_sell_price: Optional[float] = None,
    session_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
) -> ProductReturn:
    """Record returned Norin (Vozvrat), reducing client debt & net session totals."""
    tid = get_current_tenant_id(tenant_id)
    cli = await get_client(db, client_id, tenant_id=tid)
    if cli is None:
        raise ValueError(f"Client {client_id} not found")
    prod = await get_product(db, product_id, tenant_id=tid)
    if prod is None:
        raise ValueError(f"Product {product_id} not found")

    if session_id is None:
        sess = await get_or_create_open_session(db, tenant_id=tid)
        session_id = sess.id
    else:
        sess = await db.get(DailyCashSession, session_id)
        if sess is None or sess.tenant_id != tid:
            raise ValueError(f"Session {session_id} not found")

    w = round(abs(float(weight_kg)), 3)
    unit_cost = float(prod.cost_price)
    unit_sell = (
        float(unit_sell_price)
        if unit_sell_price is not None
        else await resolve_sell_price(db, client_id, prod)
    )
    ret = ProductReturn(
        tenant_id=tid,
        session_id=session_id,
        client_id=client_id,
        product_id=prod.id,
        product_name=prod.name,
        weight_kg=w,
        unit_cost=unit_cost,
        unit_sell_price=unit_sell,
        total_cost=round(w * unit_cost, 2),
        total_amount=round(w * unit_sell, 2),
        reason=(reason or "").strip()[:255],
        is_deleted=False,
        report_date=sess.report_date,
    )
    db.add(ret)
    await db.commit()
    await compute_session_summary(db, session_id, tenant_id=tid)
    loaded = await get_product_return(db, ret.id, tenant_id=tid)
    assert loaded is not None
    return loaded


async def set_product_return_group_message(
    db: AsyncSession,
    return_id: int,
    group_chat_id: Optional[int],
    group_message_id: Optional[int],
    tenant_id: Optional[int] = None,
) -> Optional[ProductReturn]:
    """Store Telegram group chat_id and message_id for a posted ProductReturn."""
    tid = get_current_tenant_id(tenant_id)
    ret = await get_product_return(db, return_id, tenant_id=tid)
    if ret is None:
        return None
    ret.group_chat_id = group_chat_id
    ret.group_message_id = group_message_id
    await db.commit()
    return await get_product_return(db, return_id, tenant_id=tid)


async def delete_product_return(
    db: AsyncSession, return_id: int, tenant_id: Optional[int] = None
) -> Optional[ProductReturn]:
    """Soft-delete a ProductReturn and recalculate session summary."""
    tid = get_current_tenant_id(tenant_id)
    ret = await get_product_return(db, return_id, tenant_id=tid)
    if ret is None or ret.is_deleted:
        return None
    ret.is_deleted = True
    await db.commit()
    await compute_session_summary(db, ret.session_id, tenant_id=tid)
    return await get_product_return(db, return_id, tenant_id=tid)


async def compute_session_summary(
    db: AsyncSession, session_id: Optional[int] = None, tenant_id: Optional[int] = None
) -> DailyReportSummary:
    """Compute live cash balance, sales kg, cost, profit, and client payments for a session."""
    tid = get_current_tenant_id(tenant_id)
    if session_id is None:
        sess = await get_or_create_open_session(db, tenant_id=tid)
        session_id = sess.id
    else:
        sess = await db.get(DailyCashSession, session_id)
        if sess is None or sess.tenant_id != tid:
            raise ValueError(f"Session {session_id} not found")

    sales = list(
        (
            await db.scalars(
                select(Sale)
                .options(selectinload(Sale.items), selectinload(Sale.client))
                .where(
                    Sale.tenant_id == tid,
                    Sale.session_id == session_id,
                    Sale.status == "confirmed",
                )
                .order_by(Sale.id)
            )
        ).all()
    )
    payments = list(
        (
            await db.scalars(
                select(ClientPayment)
                .options(selectinload(ClientPayment.client))
                .where(
                    ClientPayment.tenant_id == tid,
                    ClientPayment.session_id == session_id,
                    ClientPayment.is_deleted.is_(False),
                )
                .order_by(ClientPayment.id)
            )
        ).all()
    )
    txs = list(
        (
            await db.scalars(
                select(CashTransaction)
                .where(
                    CashTransaction.tenant_id == tid,
                    CashTransaction.session_id == session_id,
                    CashTransaction.is_deleted.is_(False),
                )
                .order_by(CashTransaction.id)
            )
        ).all()
    )
    returns = list(
        (
            await db.scalars(
                select(ProductReturn)
                .options(selectinload(ProductReturn.client))
                .where(
                    ProductReturn.tenant_id == tid,
                    ProductReturn.session_id == session_id,
                    ProductReturn.is_deleted.is_(False),
                )
                .order_by(ProductReturn.id)
            )
        ).all()
    )

    opening = float(sess.opening_balance or 0.0)
    main_cash_in = sum(float(t.amount) for t in txs if t.source_type == "main_in")
    kassa_debt_today = sum(float(t.amount) for t in txs if t.source_type == "kassa_debt")
    kassa_repay_today = sum(float(t.amount) for t in txs if t.source_type == "kassa_repay")
    total_expenses = sum(float(t.amount) for t in txs if t.source_type == "expense")

    client_cash_in = sum(float(p.amount) for p in payments if p.payment_method == "cash")
    client_card_in = sum(float(p.amount) for p in payments if p.payment_method == "card")
    client_transfer_in = sum(float(p.amount) for p in payments if p.payment_method == "transfer")

    total_available_cash = (
        opening + main_cash_in + client_cash_in + kassa_debt_today - kassa_repay_today
    )
    expected_cash = total_available_cash - total_expenses

    if abs(float(sess.expected_cash) - expected_cash) > 0.001:
        sess.expected_cash = expected_cash
        if sess.actual_counted_cash is not None:
            sess.difference = float(sess.actual_counted_cash) - expected_cash
        await db.commit()
        await db.refresh(sess)

    weight_by_product: Dict[str, float] = {}
    for s in sales:
        for item in s.items:
            weight_by_product[item.product_name] = round(
                weight_by_product.get(item.product_name, 0.0) + float(item.weight_kg),
                3,
            )

    total_return_kg = round(sum(float(r.weight_kg) for r in returns), 3)
    total_return_amount = round(sum(float(r.total_amount) for r in returns), 2)
    total_return_cost = round(sum(float(r.total_cost) for r in returns), 2)

    total_kg = round(sum(float(s.total_weight_kg) for s in sales) - total_return_kg, 3)
    total_revenue = round(sum(float(s.total_amount) for s in sales) - total_return_amount, 2)
    total_cost = round(sum(float(s.total_cost) for s in sales) - total_return_cost, 2)
    total_profit = round(total_revenue - total_cost, 2)
    margin_pct = (total_profit / total_revenue * 100.0) if total_revenue > 0 else 0.0

    outstanding_kassa = await get_outstanding_kassa_debt(db, tenant_id=tid)
    total_clients_debt = await get_total_all_clients_debt(db, tenant_id=tid)

    return DailyReportSummary(
        session=sess,
        opening_balance=opening,
        main_cash_in=main_cash_in,
        client_cash_in=client_cash_in,
        client_card_in=client_card_in,
        client_transfer_in=client_transfer_in,
        kassa_debt_today=kassa_debt_today,
        kassa_repay_today=kassa_repay_today,
        total_expenses=total_expenses,
        total_available_cash=total_available_cash,
        expected_cash=expected_cash,
        total_kassa_debt_outstanding=outstanding_kassa,
        confirmed_sales=sales,
        weight_by_product=weight_by_product,
        total_kg=total_kg,
        total_revenue=total_revenue,
        total_cost=total_cost,
        total_profit=total_profit,
        margin_pct=margin_pct,
        total_all_clients_debt=total_clients_debt,
        client_payments=payments,
        cash_transactions=txs,
        returns=returns,
        total_return_kg=total_return_kg,
        total_return_amount=total_return_amount,
        total_return_cost=total_return_cost,
    )


EXPENSE_CATEGORIES = (
    "Go'sht",
    "Xamir",
    "Ziravor",
    "Ish haqi",
    "Transport",
    "Ijara",
    "Boshqa",
)


def infer_expense_category(note: str, explicit: Optional[str] = None) -> str:
    """Determine expense category explicitly or from Uzbek/Russian keywords in note."""
    if explicit and explicit.strip() in EXPENSE_CATEGORIES:
        return explicit.strip()
    if explicit and explicit.strip():
        return explicit.strip()[:32]
    low = (note or "").lower()
    if any(k in low for k in ("go'sht", "gosht", "mol", "ot ", "otga", "мяс", "qazi")):
        return "Go'sht"
    if any(k in low for k in ("xamir", "un", "nonga", "мук")):
        return "Xamir"
    if any(k in low for k in ("ziravor", "tuz", "piyoz", "yog'", "yog", "masalliq", "zira")):
        return "Ziravor"
    if any(k in low for k in ("ishchi", "oylik", "maosh", "ish haqi", "ustaga", "зарплат")):
        return "Ish haqi"
    if any(k in low for k in ("benzin", "taksi", "dostavka", "mashina", "transport", "yo'l", "yol")):
        return "Transport"
    if any(k in low for k in ("ijara", "arenda", "svet", "gaz", "suv", "kommunal")):
        return "Ijara"
    return "Boshqa"


def _resolve_period_bounds(
    days: int = 30,
    start_iso: Optional[str] = None,
    end_iso: Optional[str] = None,
) -> tuple[str, str, int]:
    """Return normalized (start_iso, end_iso, span_days) for a reporting period."""
    if start_iso and end_iso:
        s_dt = date.fromisoformat(start_iso)
        e_dt = date.fromisoformat(end_iso)
        span = max(1, (e_dt - s_dt).days + 1)
        return start_iso, end_iso, span
    end_dt = now_local().date()
    start_dt = end_dt - timedelta(days=max(0, days - 1))
    return start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"), days


async def compute_period_summary(
    db: AsyncSession,
    days: int = 30,
    start_iso: Optional[str] = None,
    end_iso: Optional[str] = None,
    tenant_id: Optional[int] = None,
) -> PeriodReportSummary:
    """Compute aggregated Norin sales, profit, collections, and expenses over a period."""
    tid = get_current_tenant_id(tenant_id)
    start_iso, end_iso, span_days = _resolve_period_bounds(
        days=days, start_iso=start_iso, end_iso=end_iso
    )

    sessions = list(
        (
            await db.scalars(
                select(DailyCashSession).where(
                    DailyCashSession.tenant_id == tid,
                    DailyCashSession.report_date >= start_iso,
                    DailyCashSession.report_date <= end_iso,
                )
            )
        ).all()
    )
    sess_ids = [s.id for s in sessions]

    sales: List[Sale] = []
    payments: List[ClientPayment] = []
    txs: List[CashTransaction] = []
    returns: List[ProductReturn] = []

    if sess_ids:
        sales = list(
            (
                await db.scalars(
                    select(Sale)
                    .options(selectinload(Sale.items))
                    .where(
                        Sale.tenant_id == tid,
                        Sale.session_id.in_(sess_ids),
                        Sale.status == "confirmed",
                    )
                )
            ).all()
        )
        payments = list(
            (
                await db.scalars(
                    select(ClientPayment).where(
                        ClientPayment.tenant_id == tid,
                        ClientPayment.session_id.in_(sess_ids),
                        ClientPayment.is_deleted.is_(False),
                    )
                )
            ).all()
        )
        txs = list(
            (
                await db.scalars(
                    select(CashTransaction).where(
                        CashTransaction.tenant_id == tid,
                        CashTransaction.session_id.in_(sess_ids),
                        CashTransaction.is_deleted.is_(False),
                    )
                )
            ).all()
        )
        returns = list(
            (
                await db.scalars(
                    select(ProductReturn).where(
                        ProductReturn.tenant_id == tid,
                        ProductReturn.session_id.in_(sess_ids),
                        ProductReturn.is_deleted.is_(False),
                    )
                )
            ).all()
        )

    weight_by_product: Dict[str, float] = {}
    for s in sales:
        for item in s.items:
            weight_by_product[item.product_name] = round(
                weight_by_product.get(item.product_name, 0.0) + float(item.weight_kg),
                3,
            )

    total_return_kg = round(sum(float(r.weight_kg) for r in returns), 3)
    total_return_amount = round(sum(float(r.total_amount) for r in returns), 2)
    total_return_cost = round(sum(float(r.total_cost) for r in returns), 2)

    total_kg = round(sum(float(s.total_weight_kg) for s in sales) - total_return_kg, 3)
    total_revenue = round(sum(float(s.total_amount) for s in sales) - total_return_amount, 2)
    total_cost = round(sum(float(s.total_cost) for s in sales) - total_return_cost, 2)
    total_profit = round(total_revenue - total_cost, 2)
    margin_pct = (total_profit / total_revenue * 100.0) if total_revenue > 0 else 0.0

    total_cash_collected = sum(float(p.amount) for p in payments if p.payment_method == "cash")
    total_card_collected = sum(float(p.amount) for p in payments if p.payment_method == "card")
    total_transfer_collected = sum(
        float(p.amount) for p in payments if p.payment_method == "transfer"
    )
    total_expenses = sum(float(t.amount) for t in txs if t.source_type == "expense")
    total_clients_debt = await get_total_all_clients_debt(db, tenant_id=tid)

    return PeriodReportSummary(
        days=span_days,
        start_date=start_iso,
        end_date=end_iso,
        sales_count=len(sales),
        total_kg=total_kg,
        weight_by_product=weight_by_product,
        total_revenue=total_revenue,
        total_cost=total_cost,
        total_profit=total_profit,
        margin_pct=margin_pct,
        total_cash_collected=total_cash_collected,
        total_card_collected=total_card_collected,
        total_transfer_collected=total_transfer_collected,
        total_expenses=total_expenses,
        total_all_clients_debt=total_clients_debt,
        returns_count=len(returns),
        total_return_kg=total_return_kg,
        total_return_amount=total_return_amount,
    )


async def get_period_excel_data(
    db: AsyncSession,
    days: int = 30,
    start_iso: Optional[str] = None,
    end_iso: Optional[str] = None,
    tenant_id: Optional[int] = None,
) -> dict:
    """Gather rich period analytics (KPIs, daily rows, client rankings, expenses) for Excel."""
    tid = get_current_tenant_id(tenant_id)
    start_iso, end_iso, span_days = _resolve_period_bounds(
        days=days, start_iso=start_iso, end_iso=end_iso
    )
    period = await compute_period_summary(
        db, days=span_days, start_iso=start_iso, end_iso=end_iso, tenant_id=tid
    )
    sub = await get_subscription_state(db, tenant_id=tid)

    sessions = list(
        (
            await db.scalars(
                select(DailyCashSession)
                .where(
                    DailyCashSession.tenant_id == tid,
                    DailyCashSession.report_date >= start_iso,
                    DailyCashSession.report_date <= end_iso,
                )
                .order_by(DailyCashSession.report_date, DailyCashSession.id)
            )
        ).all()
    )
    sess_ids = [s.id for s in sessions]

    sales: List[Sale] = []
    payments: List[ClientPayment] = []
    txs: List[CashTransaction] = []
    returns: List[ProductReturn] = []
    if sess_ids:
        sales = list(
            (
                await db.scalars(
                    select(Sale)
                    .options(selectinload(Sale.items), selectinload(Sale.client))
                    .where(
                        Sale.tenant_id == tid,
                        Sale.session_id.in_(sess_ids),
                        Sale.status == "confirmed",
                    )
                    .order_by(Sale.id)
                )
            ).all()
        )
        payments = list(
            (
                await db.scalars(
                    select(ClientPayment)
                    .where(
                        ClientPayment.tenant_id == tid,
                        ClientPayment.session_id.in_(sess_ids),
                        ClientPayment.is_deleted.is_(False),
                    )
                    .order_by(ClientPayment.id)
                )
            ).all()
        )
        txs = list(
            (
                await db.scalars(
                    select(CashTransaction)
                    .where(
                        CashTransaction.tenant_id == tid,
                        CashTransaction.session_id.in_(sess_ids),
                        CashTransaction.is_deleted.is_(False),
                    )
                    .order_by(CashTransaction.id)
                )
            ).all()
        )
        returns = list(
            (
                await db.scalars(
                    select(ProductReturn)
                    .options(selectinload(ProductReturn.client))
                    .where(
                        ProductReturn.tenant_id == tid,
                        ProductReturn.session_id.in_(sess_ids),
                        ProductReturn.is_deleted.is_(False),
                    )
                    .order_by(ProductReturn.id)
                )
            ).all()
        )

    sess_date_by_id = {s.id: s.report_date for s in sessions}
    daily_map: Dict[str, dict] = {}
    for s in sessions:
        row = daily_map.setdefault(
            s.report_date,
            {
                "report_date": s.report_date,
                "status": "Yopilgan" if s.status == "closed" else "Ochiq",
                "sales_count": 0,
                "total_kg": 0.0,
                "total_revenue": 0.0,
                "total_cost": 0.0,
                "total_profit": 0.0,
                "cash_collected": 0.0,
                "expenses": 0.0,
            },
        )
        if s.status == "open":
            row["status"] = "Ochiq"

    for sale in sales:
        rdate = sale.report_date or sess_date_by_id.get(sale.session_id, "")
        row = daily_map.setdefault(
            rdate,
            {
                "report_date": rdate,
                "status": "Ochiq",
                "sales_count": 0,
                "total_kg": 0.0,
                "total_revenue": 0.0,
                "total_cost": 0.0,
                "total_profit": 0.0,
                "cash_collected": 0.0,
                "expenses": 0.0,
            },
        )
        row["sales_count"] += 1
        row["total_kg"] = round(row["total_kg"] + float(sale.total_weight_kg), 3)
        row["total_revenue"] += float(sale.total_amount)
        row["total_cost"] += float(sale.total_cost)
        row["total_profit"] += float(sale.total_profit)

    for pay in payments:
        rdate = sess_date_by_id.get(pay.session_id, "")
        if rdate in daily_map:
            daily_map[rdate]["cash_collected"] += float(pay.amount)

    for tx in txs:
        rdate = sess_date_by_id.get(tx.session_id, "")
        if tx.source_type == "expense" and rdate in daily_map:
            daily_map[rdate]["expenses"] += float(tx.amount)

    for ret in returns:
        rdate = ret.report_date or sess_date_by_id.get(ret.session_id, "")
        if rdate in daily_map:
            daily_map[rdate]["total_kg"] = round(
                daily_map[rdate]["total_kg"] - float(ret.weight_kg), 3
            )
            daily_map[rdate]["total_revenue"] -= float(ret.total_amount)
            daily_map[rdate]["total_cost"] -= float(ret.total_cost)
            daily_map[rdate]["total_profit"] -= float(ret.total_amount) - float(ret.total_cost)

    daily_rows = sorted(daily_map.values(), key=lambda r: r["report_date"])
    for row in daily_rows:
        rev = row["total_revenue"]
        row["margin_pct"] = (row["total_profit"] / rev) if rev > 0 else 0.0

    debts = await list_all_client_debts(db, tenant_id=tid)
    debt_by_cid = {d.client.id: d for d in debts}
    cli_agg: Dict[int, dict] = {}
    for sale in sales:
        cid = int(sale.client_id or 0)
        d = debt_by_cid.get(cid)
        cname = sale.client.name if sale.client else "Noma'lum"
        entry = cli_agg.setdefault(
            cid,
            {
                "name": cname,
                "phone": d.client.phone if d else "",
                "sales_count": 0,
                "total_kg": 0.0,
                "total_revenue": 0.0,
                "total_profit": 0.0,
                "current_debt": d.current_debt if d else 0.0,
            },
        )
        entry["sales_count"] += 1
        entry["total_kg"] = round(entry["total_kg"] + float(sale.total_weight_kg), 3)
        entry["total_revenue"] += float(sale.total_amount)
        entry["total_profit"] += float(sale.total_profit)

    for ret in returns:
        cid = int(ret.client_id or 0)
        if cid in cli_agg:
            cli_agg[cid]["total_kg"] = round(
                cli_agg[cid]["total_kg"] - float(ret.weight_kg), 3
            )
            cli_agg[cid]["total_revenue"] -= float(ret.total_amount)
            cli_agg[cid]["total_profit"] -= float(ret.total_amount) - float(ret.total_cost)

    client_stats = sorted(
        cli_agg.values(), key=lambda c: (-c["total_revenue"], c["name"].lower())
    )
    expenses_list = [t for t in txs if t.source_type == "expense"]

    return {
        "tenant_name": sub.tenant_name,
        "period": period,
        "daily_rows": daily_rows,
        "client_stats": client_stats,
        "expenses": expenses_list,
    }


async def add_cash_transaction(
    db: AsyncSession,
    amount: float,
    source_type: str = "main_in",
    note: str = "",
    session_id: Optional[int] = None,
    category: Optional[str] = None,
    tenant_id: Optional[int] = None,
) -> CashTransaction:
    """Record a cash-in, expense, kassa debt, or kassa repayment transaction."""
    tid = get_current_tenant_id(tenant_id)
    if session_id is None:
        sess = await get_or_create_open_session(db, tenant_id=tid)
        session_id = sess.id
    else:
        sess = await db.get(DailyCashSession, session_id)
        if sess is None or sess.tenant_id != tid:
            raise ValueError(f"Session {session_id} not found")
    valid_type = (
        source_type
        if source_type in ("main_in", "expense", "kassa_debt", "kassa_repay")
        else "main_in"
    )
    cat = infer_expense_category(note, category) if valid_type == "expense" else ""
    tx = CashTransaction(
        tenant_id=tid,
        session_id=session_id,
        amount=float(amount),
        source_type=valid_type,
        category=cat,
        note=note.strip(),
        is_deleted=False,
    )
    db.add(tx)
    await db.commit()
    await db.refresh(tx)
    await compute_session_summary(db, session_id, tenant_id=tid)
    return tx


async def get_cash_transaction(
    db: AsyncSession, tx_id: int, tenant_id: Optional[int] = None
) -> Optional[CashTransaction]:
    """Fetch a CashTransaction enforcing active tenant_id isolation."""
    tid = get_current_tenant_id(tenant_id)
    tx = await db.get(CashTransaction, tx_id)
    if tx is None or tx.tenant_id != tid:
        return None
    return tx


async def update_cash_transaction(
    db: AsyncSession,
    tx_id: int,
    new_amount: Optional[float] = None,
    new_note: Optional[str] = None,
    tenant_id: Optional[int] = None,
) -> Optional[CashTransaction]:
    """Edit an existing cash/expense transaction and recalculate session balance."""
    tid = get_current_tenant_id(tenant_id)
    tx = await db.get(CashTransaction, tx_id)
    if tx is None or tx.is_deleted or tx.tenant_id != tid:
        return None
    if new_amount is not None:
        tx.amount = float(new_amount)
    if new_note is not None:
        tx.note = new_note.strip()
    await db.commit()
    await db.refresh(tx)
    await compute_session_summary(db, tx.session_id, tenant_id=tid)
    return tx


async def delete_cash_transaction(
    db: AsyncSession, tx_id: int, tenant_id: Optional[int] = None
) -> Optional[CashTransaction]:
    """Soft-delete a cash/expense transaction and recalculate session balance."""
    tid = get_current_tenant_id(tenant_id)
    tx = await db.get(CashTransaction, tx_id)
    if tx is None or tx.is_deleted or tx.tenant_id != tid:
        return None
    tx.is_deleted = True
    await db.commit()
    await db.refresh(tx)
    await compute_session_summary(db, tx.session_id, tenant_id=tid)
    return tx


async def close_cash_session(
    db: AsyncSession,
    session_id: int,
    actual_counted_cash: float,
    tenant_id: Optional[int] = None,
) -> DailyReportSummary:
    """Close a cash session with actual counted cash, recording discrepancy into history."""
    tid = get_current_tenant_id(tenant_id)
    summary = await compute_session_summary(db, session_id, tenant_id=tid)
    sess = summary.session
    sess.actual_counted_cash = float(actual_counted_cash)
    sess.expected_cash = summary.expected_cash
    sess.difference = float(actual_counted_cash) - summary.expected_cash
    sess.status = "closed"
    sess.closed_at = now_utc()
    await db.commit()
    await db.refresh(sess)
    return await compute_session_summary(db, session_id, tenant_id=tid)


async def reopen_cash_session(
    db: AsyncSession, session_id: int, tenant_id: Optional[int] = None
) -> Optional[DailyCashSession]:
    """Reopen a closed session if admin wants to correct entries."""
    tid = get_current_tenant_id(tenant_id)
    sess = await db.get(DailyCashSession, session_id)
    if sess is None or sess.tenant_id != tid:
        return None
    current_open = await get_open_session(db, tenant_id=tid)
    if current_open is not None and current_open.id != session_id:
        current_summary = await compute_session_summary(db, current_open.id, tenant_id=tid)
        if (
            not current_summary.confirmed_sales
            and not current_summary.client_payments
            and not current_summary.cash_transactions
        ):
            await db.delete(current_open)
            await db.commit()
    sess = await db.get(DailyCashSession, session_id)
    if sess is None or sess.tenant_id != tid:
        return None
    sess.status = "open"
    sess.closed_at = None
    await db.commit()
    await db.refresh(sess)
    return sess


async def list_closed_sessions(
    db: AsyncSession, limit: int = 10, tenant_id: Optional[int] = None
) -> List[DailyCashSession]:
    """Return recent closed sessions ordered newest first for this tenant."""
    tid = get_current_tenant_id(tenant_id)
    stmt = (
        select(DailyCashSession)
        .where(DailyCashSession.tenant_id == tid, DailyCashSession.status == "closed")
        .order_by(desc(DailyCashSession.id))
        .limit(limit)
    )
    return list((await db.scalars(stmt)).all())


async def list_all_sessions(
    db: AsyncSession, limit: int = 15, tenant_id: Optional[int] = None
) -> List[DailyCashSession]:
    """Return recent open and closed daily sessions ordered newest first for this tenant."""
    tid = get_current_tenant_id(tenant_id)
    stmt = (
        select(DailyCashSession)
        .where(DailyCashSession.tenant_id == tid)
        .order_by(desc(DailyCashSession.id))
        .limit(limit)
    )
    return list((await db.scalars(stmt)).all())


# ---------------------------------------------------------------------------
# Group Config, App Preferences & Rounding
# ---------------------------------------------------------------------------


async def set_group_config(
    db: AsyncSession,
    role: str,
    chat_id: int,
    title: str,
    tenant_id: Optional[int] = None,
) -> GroupConfig:
    """Bind or update a system Telegram group chat_id for a given role in this tenant."""
    tid = get_current_tenant_id(tenant_id)
    stmt = select(GroupConfig).where(GroupConfig.tenant_id == tid, GroupConfig.role == role)
    obj = await db.scalar(stmt)
    if obj is None:
        obj = GroupConfig(tenant_id=tid, role=role, chat_id=chat_id, title=title)
        db.add(obj)
    else:
        obj.chat_id = chat_id
        obj.title = title
    await db.commit()
    await db.refresh(obj)
    bump_auth_cache_epoch()
    return obj


async def get_group_config(
    db: AsyncSession, role: str, tenant_id: Optional[int] = None
) -> Optional[GroupConfig]:
    """Return configured system group for a role within the active tenant."""
    tid = get_current_tenant_id(tenant_id)
    return await db.scalar(
        select(GroupConfig).where(GroupConfig.tenant_id == tid, GroupConfig.role == role)
    )


async def get_all_group_configs(
    db: AsyncSession, tenant_id: Optional[int] = None
) -> Dict[str, GroupConfig]:
    """Return all configured system groups keyed by role for the active tenant."""
    tid = get_current_tenant_id(tenant_id)
    rows = (await db.scalars(select(GroupConfig).where(GroupConfig.tenant_id == tid))).all()
    return {row.role: row for row in rows}


def _scoped_setting_key(key: str, tenant_id: Optional[int] = None) -> str:
    """Namespace AppSetting keys cleanly per tenant while keeping Tenant #1 keys clean."""
    tid = get_current_tenant_id(tenant_id)
    return key if tid == 1 else f"t{tid}:{key}"


async def get_app_setting(
    db: AsyncSession, key: str, default: str = "", tenant_id: Optional[int] = None
) -> str:
    """Read a bot preference value from app_settings for the active tenant."""
    scoped_key = _scoped_setting_key(key, tenant_id=tenant_id)
    obj = await db.get(AppSetting, scoped_key)
    return obj.value if obj is not None else default


async def set_app_setting(
    db: AsyncSession, key: str, value: str, tenant_id: Optional[int] = None
) -> AppSetting:
    """Persist a bot preference value in app_settings for the active tenant."""
    scoped_key = _scoped_setting_key(key, tenant_id=tenant_id)
    obj = await db.get(AppSetting, scoped_key)
    if obj is None:
        obj = AppSetting(key=scoped_key, value=value)
        db.add(obj)
    else:
        obj.value = value
    await db.commit()
    await db.refresh(obj)
    bump_auth_cache_epoch()
    return obj


def round_amount(amount: float, mode: str = "nearest_1000") -> float:
    """
    Round calculated monetary amount according to user preference.

    Modes:
    - "nearest_1000": 2 875 400 -> 2 875 000
    - "floor_1000": 2 875 900 -> 2 875 000
    - "none": exact integer sum
    """
    val = float(amount)
    if val <= 0:
        return 0.0
    if mode == "floor_1000" and val >= 1000:
        return float((int(val) // 1000) * 1000)
    if mode == "nearest_1000" and val >= 1000:
        return float(round(val / 1000.0) * 1000)
    return float(round(val))


# ---------------------------------------------------------------------------
# SaaS Subscription & Access Control
# ---------------------------------------------------------------------------


async def get_subscription_state(
    db: AsyncSession, tenant_id: Optional[int] = None
) -> SubscriptionState:
    """Fetch SubscriptionState for the given tenant_id (creating Tenant #1 default if missing)."""
    tid = get_current_tenant_id(tenant_id)
    sub = await db.get(SubscriptionState, tid)
    if sub is not None:
        return sub

    sub_one = await db.get(SubscriptionState, 1)
    if tid != 1 and sub_one is not None:
        return sub_one
    if sub_one is not None:
        return sub_one

    settings = get_settings()
    trial_days = max(1, int(settings.DEFAULT_TRIAL_DAYS))
    sub = SubscriptionState(
        tenant_name="Test Filial (Asad)",
        plan_name="Pro Oylik",
        monthly_price=float(settings.DEFAULT_MONTHLY_PRICE),
        expires_at=now_utc() + timedelta(days=trial_days),
        grace_days=3,
        is_suspended=False,
        owner_contact=settings.OWNER_CONTACT,
        last_reminder_date="",
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


async def list_tenants(db: AsyncSession) -> List[SubscriptionState]:
    """List all SaaS tenants (ensuring Tenant #1 always exists)."""
    await get_subscription_state(db, tenant_id=1)
    return list((await db.scalars(select(SubscriptionState).order_by(SubscriptionState.id))).all())


async def create_tenant(
    db: AsyncSession,
    tenant_name: str,
    trial_days: Optional[int] = None,
    monthly_price: Optional[float] = None,
    owner_contact: Optional[str] = None,
) -> SubscriptionState:
    """Create a brand-new isolated SaaS tenant and seed its default products."""
    from database.session import seed_default_products

    await get_subscription_state(db, tenant_id=1)
    settings = get_settings()
    days = max(1, int(trial_days if trial_days is not None else settings.DEFAULT_TRIAL_DAYS))
    price = float(monthly_price if monthly_price is not None else settings.DEFAULT_MONTHLY_PRICE)
    contact = (owner_contact or settings.OWNER_CONTACT).strip()
    sub = SubscriptionState(
        tenant_name=tenant_name.strip() or "Yangi Filial",
        plan_name="Pro Oylik",
        monthly_price=price,
        expires_at=now_utc() + timedelta(days=days),
        grace_days=3,
        is_suspended=False,
        owner_contact=contact,
        last_reminder_date="",
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    await seed_default_products(db, tenant_id=sub.id)
    bump_auth_cache_epoch()
    return sub


async def evaluate_subscription_status(
    db: AsyncSession,
    current_time: Optional[datetime] = None,
    tenant_id: Optional[int] = None,
) -> SubscriptionStatus:
    """Evaluate active/expiring/grace/expired/suspended status safely with UTC normalization."""
    sub = await get_subscription_state(db, tenant_id=tenant_id)
    now = to_utc_dt(current_time) if current_time else now_utc()
    exp = to_utc_dt(sub.expires_at)

    if sub.is_suspended:
        return SubscriptionStatus(
            state=sub,
            status="suspended",
            days_left=0,
            grace_days_left=0,
            is_allowed=False,
        )

    seconds_left = (exp - now).total_seconds()
    if seconds_left >= 0:
        days_left = math.ceil(seconds_left / 86400.0) if seconds_left > 0 else 0
        status = "expiring" if days_left <= 3 else "active"
        return SubscriptionStatus(
            state=sub,
            status=status,
            days_left=days_left,
            grace_days_left=sub.grace_days,
            is_allowed=True,
        )

    grace_end = exp + timedelta(days=max(0, int(sub.grace_days)))
    grace_seconds_left = (grace_end - now).total_seconds()
    if grace_seconds_left > 0:
        grace_left = math.ceil(grace_seconds_left / 86400.0)
        return SubscriptionStatus(
            state=sub,
            status="grace",
            days_left=0,
            grace_days_left=grace_left,
            is_allowed=True,
        )

    return SubscriptionStatus(
        state=sub,
        status="expired",
        days_left=0,
        grace_days_left=0,
        is_allowed=False,
    )


async def extend_subscription(
    db: AsyncSession,
    days: int,
    amount: float,
    recorded_by: int,
    note: str = "",
    plan_name: Optional[str] = None,
    tenant_id: Optional[int] = None,
) -> SubscriptionState:
    """Extend subscription from current expiry (if active) or from now (if already expired)."""
    sub = await get_subscription_state(db, tenant_id=tenant_id)
    now = now_utc()
    current_exp = to_utc_dt(sub.expires_at)
    base_dt = current_exp if current_exp > now else now
    sub.expires_at = base_dt + timedelta(days=int(days))
    sub.is_suspended = False
    if plan_name:
        sub.plan_name = plan_name.strip()

    payment = SubscriptionPayment(
        tenant_id=sub.id,
        amount=float(amount),
        days_added=int(days),
        plan_name=sub.plan_name,
        note=note.strip(),
        recorded_by=int(recorded_by),
    )
    db.add(payment)
    await db.commit()
    await db.refresh(sub)
    bump_auth_cache_epoch()
    return sub


async def update_subscription_settings(
    db: AsyncSession,
    monthly_price: Optional[float] = None,
    owner_contact: Optional[str] = None,
    tenant_name: Optional[str] = None,
    plan_name: Optional[str] = None,
    is_suspended: Optional[bool] = None,
    grace_days: Optional[int] = None,
    tenant_id: Optional[int] = None,
) -> SubscriptionState:
    """Update subscription configuration fields for this tenant."""
    sub = await get_subscription_state(db, tenant_id=tenant_id)
    if monthly_price is not None:
        sub.monthly_price = float(monthly_price)
    if owner_contact is not None and owner_contact.strip():
        sub.owner_contact = owner_contact.strip()
    if tenant_name is not None and tenant_name.strip():
        sub.tenant_name = tenant_name.strip()
    if plan_name is not None and plan_name.strip():
        sub.plan_name = plan_name.strip()
    if is_suspended is not None:
        sub.is_suspended = bool(is_suspended)
    if grace_days is not None:
        sub.grace_days = max(0, int(grace_days))
    await db.commit()
    await db.refresh(sub)
    bump_auth_cache_epoch()
    return sub


async def mark_reminder_sent(
    db: AsyncSession, date_iso: str, tenant_id: Optional[int] = None
) -> None:
    """Record the local date when expiry reminder was sent for this tenant."""
    sub = await get_subscription_state(db, tenant_id=tenant_id)
    sub.last_reminder_date = date_iso
    await db.commit()


async def list_subscription_payments(
    db: AsyncSession, limit: int = 15, tenant_id: Optional[int] = None
) -> List[SubscriptionPayment]:
    """Return recent SaaS subscription payment entries for the target tenant."""
    tid = get_current_tenant_id(tenant_id)
    stmt = (
        select(SubscriptionPayment)
        .where(SubscriptionPayment.tenant_id == tid)
        .order_by(desc(SubscriptionPayment.id))
        .limit(limit)
    )
    return list((await db.scalars(stmt)).all())


async def list_authorized_users(
    db: AsyncSession, active_only: bool = True, tenant_id: Optional[int] = None
) -> List[AuthorizedUser]:
    """List dynamically added AuthorizedUsers belonging to the target tenant."""
    tid = get_current_tenant_id(tenant_id)
    stmt = select(AuthorizedUser).where(AuthorizedUser.tenant_id == tid)
    if active_only:
        stmt = stmt.where(AuthorizedUser.is_active.is_(True))
    stmt = stmt.order_by(AuthorizedUser.id)
    return list((await db.scalars(stmt)).all())


async def add_authorized_user(
    db: AsyncSession,
    telegram_id: int,
    full_name: str = "",
    role: str = "staff",
    tenant_id: Optional[int] = None,
    create_new_tenant: bool = False,
    new_tenant_name: Optional[str] = None,
) -> AuthorizedUser:
    """Add or reactivate an authorized Telegram user, optionally creating a dedicated new tenant."""
    async with _ADD_USER_LOCK:
        tid_int = int(telegram_id)
        existing = await db.scalar(
            select(AuthorizedUser).where(AuthorizedUser.telegram_id == tid_int)
        )

        if create_new_tenant:
            if existing is not None and existing.tenant_id != 1 and existing.is_active:
                target_tid = int(existing.tenant_id)
                if new_tenant_name and new_tenant_name.strip():
                    sub_existing = await db.get(SubscriptionState, target_tid)
                    if sub_existing is not None:
                        sub_existing.tenant_name = new_tenant_name.strip()
            else:
                label = (new_tenant_name or "").strip() or (
                    f"{full_name.strip()} Filiali" if full_name.strip() else f"Filial {tid_int}"
                )
                sub = await create_tenant(db, tenant_name=label)
                target_tid = sub.id
        else:
            target_tid = get_current_tenant_id(tenant_id)

        if existing is not None:
            existing.tenant_id = target_tid
            existing.is_active = True
            if full_name.strip():
                existing.full_name = full_name.strip()
            existing.role = role
            await db.commit()
            await db.refresh(existing)
            bump_auth_cache_epoch()
            return existing

        user = AuthorizedUser(
            tenant_id=target_tid,
            telegram_id=tid_int,
            full_name=full_name.strip() or f"User {tid_int}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        bump_auth_cache_epoch()
        return user


async def remove_authorized_user(
    db: AsyncSession, telegram_id: int, tenant_id: Optional[int] = None
) -> bool:
    """Deactivate/remove a dynamically added AuthorizedUser."""
    stmt = select(AuthorizedUser).where(AuthorizedUser.telegram_id == int(telegram_id))
    if tenant_id is not None:
        stmt = stmt.where(AuthorizedUser.tenant_id == int(tenant_id))
    existing = await db.scalar(stmt)
    if existing is None:
        return False
    await db.delete(existing)
    await db.commit()
    bump_auth_cache_epoch()
    return True


async def get_authorized_user(
    db: AsyncSession, telegram_id: int
) -> Optional[AuthorizedUser]:
    """Lookup an AuthorizedUser across all tenants by Telegram user ID."""
    return await db.scalar(
        select(AuthorizedUser).where(AuthorizedUser.telegram_id == int(telegram_id))
    )


async def reassign_authorized_user(
    db: AsyncSession,
    telegram_id: int,
    new_tenant_id: int,
    role: Optional[str] = None,
) -> Optional[AuthorizedUser]:
    """Move an AuthorizedUser to another tenant and/or update their role."""
    existing = await get_authorized_user(db, telegram_id)
    if existing is None:
        return None
    sub = await db.get(SubscriptionState, int(new_tenant_id))
    if sub is None:
        return None
    existing.tenant_id = int(new_tenant_id)
    existing.is_active = True
    if role is not None and role.strip():
        existing.role = role.strip()
    await db.commit()
    await db.refresh(existing)
    bump_auth_cache_epoch()
    return existing


async def get_tenant_overview_stats(db: AsyncSession, tenant_id: int) -> dict:
    """Return high-level counts of users, clients, groups, products, and confirmed sales in 1 query."""
    tid = int(tenant_id)
    stmt = select(
        select(sa_func.count(AuthorizedUser.id))
        .where(AuthorizedUser.tenant_id == tid, AuthorizedUser.is_active.is_(True))
        .scalar_subquery(),
        select(sa_func.count(Client.id))
        .where(Client.tenant_id == tid, Client.is_active.is_(True))
        .scalar_subquery(),
        select(sa_func.count(Client.id))
        .where(
            Client.tenant_id == tid,
            Client.is_active.is_(True),
            Client.group_chat_id.is_not(None),
        )
        .scalar_subquery(),
        select(sa_func.count(Product.id))
        .where(Product.tenant_id == tid, Product.is_active.is_(True))
        .scalar_subquery(),
        select(sa_func.count(Sale.id))
        .where(Sale.tenant_id == tid, Sale.status == "confirmed")
        .scalar_subquery(),
    )
    row = (await db.execute(stmt)).one()
    return {
        "users": int(row[0] or 0),
        "clients": int(row[1] or 0),
        "groups": int(row[2] or 0),
        "products": int(row[3] or 0),
        "sales": int(row[4] or 0),
    }


async def resolve_user_tenant_id(
    db: AsyncSession,
    user_id: Optional[int],
    chat_id: Optional[int] = None,
    chat_type: str = "private",
) -> int:
    """Resolve the SaaS tenant_id for an incoming Telegram event (by bound group first, then user)."""
    if chat_id is not None and chat_type in ("group", "supergroup"):
        client_tid = await db.scalar(
            select(Client.tenant_id)
            .where(Client.group_chat_id == int(chat_id), Client.is_active.is_(True))
            .limit(1)
        )
        if client_tid is not None:
            return int(client_tid)

        grp_tid = await db.scalar(
            select(GroupConfig.tenant_id)
            .where(GroupConfig.chat_id == int(chat_id))
            .limit(1)
        )
        if grp_tid is not None:
            return int(grp_tid)

    if user_id is None:
        return 1

    settings = get_settings()
    if int(user_id) in settings.super_admin_id_list:
        return 1

    db_tid = await db.scalar(
        select(AuthorizedUser.tenant_id).where(
            AuthorizedUser.telegram_id == int(user_id),
            AuthorizedUser.is_active.is_(True),
        )
    )
    if db_tid is not None:
        return int(db_tid)

    if int(user_id) in settings.admin_id_list:
        return 1

    return 1


async def is_user_authorized(
    db: AsyncSession,
    user_id: Optional[int],
    allow_group_anon: bool = False,
    tenant_id: Optional[int] = None,
) -> bool:
    """
    Check if a Telegram user is authorized to operate the bot within the active tenant.

    Super admins (SUPER_ADMIN_IDS) are always authorized.
    ADMIN_IDS apply to Tenant #1. AuthorizedUsers belong to their assigned tenant_id.
    """
    if user_id is None:
        return False
    settings = get_settings()
    if user_id in settings.super_admin_id_list:
        return True
    if allow_group_anon and user_id == ANONYMOUS_ADMIN_BOT_ID:
        return True

    tid = get_current_tenant_id(tenant_id)
    env_admins = settings.admin_id_list
    if tid == 1 and user_id in env_admins:
        return True

    active_db_user = await db.scalar(
        select(AuthorizedUser.id).where(
            AuthorizedUser.tenant_id == tid,
            AuthorizedUser.telegram_id == int(user_id),
            AuthorizedUser.is_active.is_(True),
        )
    )
    if active_db_user is not None:
        return True

    if tid == 1 and not env_admins:
        any_db_user = await db.scalar(
            select(sa_func.count(AuthorizedUser.id)).where(
                AuthorizedUser.tenant_id == 1,
                AuthorizedUser.is_active.is_(True),
            )
        )
        if not any_db_user:
            return True

    return False


# ---------------------------------------------------------------------------
# Database Reset Utilities (Super Admin /clear)
# ---------------------------------------------------------------------------


async def reset_test_transactions(
    db: AsyncSession, tenant_id: Optional[int] = None
) -> dict:
    """
    Clear all transactional test data (sales, payments, cash sessions, opening debts)
    for the target tenant while preserving its Products, Clients, Custom Prices, Bound Groups, and Subscriptions.
    """
    tid = get_current_tenant_id(tenant_id)
    sales_cnt = int(
        await db.scalar(select(sa_func.count(Sale.id)).where(Sale.tenant_id == tid)) or 0
    )
    pays_cnt = int(
        await db.scalar(
            select(sa_func.count(ClientPayment.id)).where(ClientPayment.tenant_id == tid)
        )
        or 0
    )
    txs_cnt = int(
        await db.scalar(
            select(sa_func.count(CashTransaction.id)).where(CashTransaction.tenant_id == tid)
        )
        or 0
    )
    sess_cnt = int(
        await db.scalar(
            select(sa_func.count(DailyCashSession.id)).where(DailyCashSession.tenant_id == tid)
        )
        or 0
    )

    sale_ids_sub = select(Sale.id).where(Sale.tenant_id == tid)
    await db.execute(delete(SaleItem).where(SaleItem.sale_id.in_(sale_ids_sub)))
    await db.execute(delete(Sale).where(Sale.tenant_id == tid))
    await db.execute(delete(ProductReturn).where(ProductReturn.tenant_id == tid))
    await db.execute(delete(ClientPayment).where(ClientPayment.tenant_id == tid))
    await db.execute(delete(CashTransaction).where(CashTransaction.tenant_id == tid))
    await db.execute(delete(DailyCashSession).where(DailyCashSession.tenant_id == tid))
    await db.execute(update(Client).where(Client.tenant_id == tid).values(opening_debt=0.0))
    await db.commit()

    return {
        "sales": sales_cnt,
        "payments": pays_cnt,
        "cash_txs": txs_cnt,
        "sessions": sess_cnt,
    }


async def reset_full_database(
    db: AsyncSession, tenant_id: Optional[int] = None
) -> dict:
    """
    Completely wipe operational data for the target tenant (sales, payments, cash, clients,
    groups, products, settings), re-seed its default Norin products, and strictly preserve
    SubscriptionState/Payments & AuthorizedUser.
    """
    from database.session import seed_default_products

    tid = get_current_tenant_id(tenant_id)
    sales_cnt = int(
        await db.scalar(select(sa_func.count(Sale.id)).where(Sale.tenant_id == tid)) or 0
    )
    pays_cnt = int(
        await db.scalar(
            select(sa_func.count(ClientPayment.id)).where(ClientPayment.tenant_id == tid)
        )
        or 0
    )
    txs_cnt = int(
        await db.scalar(
            select(sa_func.count(CashTransaction.id)).where(CashTransaction.tenant_id == tid)
        )
        or 0
    )
    sess_cnt = int(
        await db.scalar(
            select(sa_func.count(DailyCashSession.id)).where(DailyCashSession.tenant_id == tid)
        )
        or 0
    )
    clients_cnt = int(
        await db.scalar(select(sa_func.count(Client.id)).where(Client.tenant_id == tid)) or 0
    )

    sale_ids_sub = select(Sale.id).where(Sale.tenant_id == tid)
    client_ids_sub = select(Client.id).where(Client.tenant_id == tid)
    await db.execute(delete(SaleItem).where(SaleItem.sale_id.in_(sale_ids_sub)))
    await db.execute(delete(Sale).where(Sale.tenant_id == tid))
    await db.execute(delete(ProductReturn).where(ProductReturn.tenant_id == tid))
    await db.execute(delete(ClientPayment).where(ClientPayment.tenant_id == tid))
    await db.execute(delete(CashTransaction).where(CashTransaction.tenant_id == tid))
    await db.execute(delete(DailyCashSession).where(DailyCashSession.tenant_id == tid))
    await db.execute(
        delete(ClientProductPrice).where(ClientProductPrice.client_id.in_(client_ids_sub))
    )
    await db.execute(delete(Client).where(Client.tenant_id == tid))
    await db.execute(delete(GroupConfig).where(GroupConfig.tenant_id == tid))
    await db.execute(delete(Product).where(Product.tenant_id == tid))
    if tid == 1:
        await db.execute(delete(AppSetting).where(~AppSetting.key.contains(":")))
    else:
        await db.execute(delete(AppSetting).where(AppSetting.key.like(f"t{tid}:%")))
    await db.commit()

    await seed_default_products(db, tenant_id=tid)
    bump_auth_cache_epoch()

    return {
        "sales": sales_cnt,
        "payments": pays_cnt,
        "cash_txs": txs_cnt,
        "sessions": sess_cnt,
        "clients": clients_cnt,
    }


async def delete_tenant(db: AsyncSession, tenant_id: int) -> bool:
    """Permanently delete a client tenant (id >= 2) and all its isolated data."""
    tid = int(tenant_id)
    if tid <= 1:
        return False
    sub = await db.get(SubscriptionState, tid)
    if sub is None:
        return False

    sale_ids_sub = select(Sale.id).where(Sale.tenant_id == tid)
    client_ids_sub = select(Client.id).where(Client.tenant_id == tid)
    await db.execute(delete(SaleItem).where(SaleItem.sale_id.in_(sale_ids_sub)))
    await db.execute(delete(Sale).where(Sale.tenant_id == tid))
    await db.execute(delete(ProductReturn).where(ProductReturn.tenant_id == tid))
    await db.execute(delete(ClientPayment).where(ClientPayment.tenant_id == tid))
    await db.execute(delete(CashTransaction).where(CashTransaction.tenant_id == tid))
    await db.execute(delete(DailyCashSession).where(DailyCashSession.tenant_id == tid))
    await db.execute(
        delete(ClientProductPrice).where(ClientProductPrice.client_id.in_(client_ids_sub))
    )
    await db.execute(delete(Client).where(Client.tenant_id == tid))
    await db.execute(delete(GroupConfig).where(GroupConfig.tenant_id == tid))
    await db.execute(delete(Product).where(Product.tenant_id == tid))
    await db.execute(delete(SubscriptionPayment).where(SubscriptionPayment.tenant_id == tid))
    await db.execute(delete(AuthorizedUser).where(AuthorizedUser.tenant_id == tid))
    await db.execute(delete(AIUsageLog).where(AIUsageLog.tenant_id == tid))
    await db.execute(delete(AppSetting).where(AppSetting.key.like(f"t{tid}:%")))
    await db.execute(delete(SubscriptionState).where(SubscriptionState.id == tid))
    await db.commit()
    bump_auth_cache_epoch()
    return True


async def list_all_broadcast_recipients(db: AsyncSession) -> List[int]:
    """Return unique active Telegram IDs across all tenants (excluding Super Admins)."""
    settings = get_settings()
    super_ids = set(settings.super_admin_id_list)
    rows = (
        await db.scalars(
            select(AuthorizedUser.telegram_id).where(AuthorizedUser.is_active.is_(True))
        )
    ).all()
    recipients = {int(uid) for uid in rows} | set(settings.admin_id_list)
    recipients -= super_ids
    return sorted(recipients)


# ---------------------------------------------------------------------------
# AI Usage Tracking & Raw System Preferences
# ---------------------------------------------------------------------------


async def log_ai_usage(
    db: AsyncSession,
    kind: str,
    model_name: str,
    prompt_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    tenant_id: Optional[int] = None,
) -> AIUsageLog:
    """Record a single Gemini multimodal call (image or audio) for a tenant."""
    tid = get_current_tenant_id(tenant_id)
    entry = AIUsageLog(
        tenant_id=tid,
        kind="audio" if kind == "audio" else "image",
        model_name=(model_name or "")[:64],
        prompt_tokens=max(0, int(prompt_tokens or 0)),
        output_tokens=max(0, int(output_tokens or 0)),
        total_tokens=max(0, int(total_tokens or (prompt_tokens + output_tokens))),
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def get_ai_usage_summary(
    db: AsyncSession, days: int = 30, tenant_id: Optional[int] = None
) -> dict:
    """Return AI call counts and total tokens over the last N days (tenant_id=0 => all)."""
    since = now_utc() - timedelta(days=max(1, int(days)))
    stmt = select(AIUsageLog).where(AIUsageLog.created_at >= since)
    if tenant_id != 0:
        tid = get_current_tenant_id(tenant_id)
        stmt = stmt.where(AIUsageLog.tenant_id == tid)
    rows = (await db.scalars(stmt)).all()
    image_calls = sum(1 for r in rows if r.kind == "image")
    audio_calls = sum(1 for r in rows if r.kind == "audio")
    total_tokens = sum(int(r.total_tokens or 0) for r in rows)
    return {
        "image_calls": image_calls,
        "audio_calls": audio_calls,
        "total_calls": len(rows),
        "total_tokens": total_tokens,
    }


async def get_raw_app_setting(db: AsyncSession, key: str, default: str = "") -> str:
    """Read an un-namespaced global setting directly by primary key."""
    obj = await db.get(AppSetting, key)
    return obj.value if obj is not None else default


async def set_raw_app_setting(db: AsyncSession, key: str, value: str) -> AppSetting:
    """Persist an un-namespaced global setting directly by primary key."""
    obj = await db.get(AppSetting, key)
    if obj is None:
        obj = AppSetting(key=key, value=value)
        db.add(obj)
    else:
        obj.value = value
    await db.commit()
    await db.refresh(obj)
    bump_auth_cache_epoch()
    return obj


async def get_today_ai_usage_count(
    db: AsyncSession, tenant_id: Optional[int] = None
) -> int:
    """Return total AI calls (image + audio) recorded today (local midnight) for this tenant."""
    tid = get_current_tenant_id(tenant_id)
    local_midnight = now_local().replace(hour=0, minute=0, second=0, microsecond=0)
    since_utc = local_midnight.astimezone(timezone.utc)
    return int(
        await db.scalar(
            select(sa_func.count(AIUsageLog.id)).where(
                AIUsageLog.tenant_id == tid,
                AIUsageLog.created_at >= since_utc,
            )
        )
        or 0
    )


async def check_tenant_ai_quota(
    db: AsyncSession, tenant_id: Optional[int] = None
) -> tuple[bool, int, int]:
    """Return (is_allowed, used_today, daily_limit) for the active tenant (0 limit => unlimited)."""
    tid = get_current_tenant_id(tenant_id)
    raw = await get_app_setting(db, "ai_daily_limit", "0", tenant_id=tid)
    try:
        limit = max(0, int(str(raw).strip() or "0"))
    except ValueError:
        limit = 0
    used = await get_today_ai_usage_count(db, tenant_id=tid)
    return (limit == 0 or used < limit), used, limit


async def get_global_saas_analytics(db: AsyncSession, days: int = 30) -> dict:
    """Compute cross-tenant SaaS MRR, status counts, collected revenue, and global AI stats."""
    tenants = await list_tenants(db)
    now = now_utc()
    since = now - timedelta(days=max(1, int(days)))

    status_counts = {"active": 0, "expiring": 0, "grace": 0, "expired": 0, "suspended": 0}
    paying_mrr = 0.0
    total_mrr = 0.0

    user_rows = (
        await db.execute(
            select(AuthorizedUser.tenant_id, sa_func.count(AuthorizedUser.id))
            .where(AuthorizedUser.is_active.is_(True))
            .group_by(AuthorizedUser.tenant_id)
        )
    ).all()
    users_by_tid = {int(tid): int(cnt or 0) for tid, cnt in user_rows}

    tenants_breakdown: List[dict] = []
    for t in tenants:
        st = await evaluate_subscription_status(db, current_time=now, tenant_id=t.id)
        status_counts[st.status] = status_counts.get(st.status, 0) + 1
        price = float(t.monthly_price or 0.0)
        if st.is_allowed:
            total_mrr += price
            if t.id >= 2:
                paying_mrr += price
        tenants_breakdown.append(
            {
                "id": t.id,
                "name": t.tenant_name,
                "plan": t.plan_name,
                "price": price,
                "status": st.status,
                "days_left": st.days_left,
                "grace_days_left": st.grace_days_left,
                "users": users_by_tid.get(t.id, 0),
                "is_allowed": st.is_allowed,
            }
        )

    collected_30d = float(
        await db.scalar(
            select(sa_func.coalesce(sa_func.sum(SubscriptionPayment.amount), 0.0)).where(
                SubscriptionPayment.paid_at >= since
            )
        )
        or 0.0
    )
    collected_all = float(
        await db.scalar(
            select(sa_func.coalesce(sa_func.sum(SubscriptionPayment.amount), 0.0))
        )
        or 0.0
    )

    counts_row = (
        await db.execute(
            select(
                select(sa_func.count(AuthorizedUser.id))
                .where(AuthorizedUser.is_active.is_(True))
                .scalar_subquery(),
                select(sa_func.count(Client.id))
                .where(Client.is_active.is_(True))
                .scalar_subquery(),
                select(sa_func.count(Client.id))
                .where(Client.is_active.is_(True), Client.group_chat_id.is_not(None))
                .scalar_subquery(),
                select(sa_func.count(Sale.id))
                .where(Sale.status == "confirmed")
                .scalar_subquery(),
            )
        )
    ).one()

    ai_global = await get_ai_usage_summary(db, days=days, tenant_id=0)

    return {
        "total_tenants": len(tenants),
        "paying_tenants": sum(1 for x in tenants_breakdown if x["id"] >= 2 and x["is_allowed"]),
        "status_counts": status_counts,
        "paying_mrr": round(paying_mrr, 2),
        "total_mrr": round(total_mrr, 2),
        "collected_30d": round(collected_30d, 2),
        "collected_all": round(collected_all, 2),
        "total_users": int(counts_row[0] or 0),
        "total_clients": int(counts_row[1] or 0),
        "total_groups": int(counts_row[2] or 0),
        "total_sales": int(counts_row[3] or 0),
        "ai_global": ai_global,
        "tenants_breakdown": tenants_breakdown,
    }

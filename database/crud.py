"""Async CRUD operations for Norin products, clients, sales, debt ledger, cash sessions, and SaaS subscriptions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import delete, desc, func as sa_func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import get_settings
from database.models import (
    AppSetting,
    AuthorizedUser,
    CashTransaction,
    Client,
    ClientPayment,
    ClientProductPrice,
    DailyCashSession,
    GroupConfig,
    Product,
    Sale,
    SaleItem,
    SubscriptionPayment,
    SubscriptionState,
)


ANONYMOUS_ADMIN_BOT_ID = 1087968824


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


async def list_products(db: AsyncSession, active_only: bool = True) -> List[Product]:
    """List products ordered by order_num and id."""
    stmt = select(Product)
    if active_only:
        stmt = stmt.where(Product.is_active.is_(True))
    stmt = stmt.order_by(Product.order_num, Product.id)
    return list((await db.scalars(stmt)).all())


async def get_product(db: AsyncSession, product_id: int) -> Optional[Product]:
    """Fetch a product by id."""
    return await db.get(Product, product_id)


async def create_product(
    db: AsyncSession,
    name: str,
    cost_price: float,
    default_sell_price: float,
    aliases: str = "",
    unit: str = "kg",
    order_num: Optional[int] = None,
) -> Product:
    """Create a new product or reactivate/update an existing one with the same name."""
    clean_name = name.strip()
    existing = await db.scalar(select(Product).where(Product.name == clean_name))
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
        current = await list_products(db, active_only=False)
        order_num = max((p.order_num for p in current), default=0) + 1

    alias_str = aliases.strip().upper() or clean_name.upper()
    prod = Product(
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
) -> Optional[Product]:
    """Update product fields."""
    prod = await db.get(Product, product_id)
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
    await db.commit()
    await db.refresh(prod)
    return prod


async def append_product_alias(
    db: AsyncSession, product_id: int, new_alias: str
) -> Optional[Product]:
    """Append an uppercase synonym/alias to a product."""
    prod = await db.get(Product, product_id)
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


async def delete_product(db: AsyncSession, product_id: int) -> bool:
    """Soft-deactivate a product so historical SaleItems keep their reference."""
    prod = await db.get(Product, product_id)
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


async def list_clients(db: AsyncSession, active_only: bool = True) -> List[Client]:
    """List clients ordered alphabetically by name."""
    stmt = select(Client)
    if active_only:
        stmt = stmt.where(Client.is_active.is_(True))
    stmt = stmt.order_by(Client.name, Client.id)
    return list((await db.scalars(stmt)).all())


async def get_client(db: AsyncSession, client_id: int) -> Optional[Client]:
    """Fetch a client by id."""
    return await db.get(Client, client_id)


async def get_client_by_group(db: AsyncSession, chat_id: int) -> Optional[Client]:
    """Find an active client bound to a Telegram group chat_id."""
    stmt = (
        select(Client)
        .where(Client.group_chat_id == chat_id, Client.is_active.is_(True))
        .limit(1)
    )
    return await db.scalar(stmt)


async def create_client(
    db: AsyncSession,
    name: str,
    phone: str = "",
    opening_debt: float = 0.0,
    aliases: str = "",
) -> Client:
    """Create a new client or reactivate an existing inactive one with the same name."""
    clean_name = name.strip()
    existing = await db.scalar(select(Client).where(Client.name == clean_name))
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
) -> Optional[Client]:
    """Update client profile fields."""
    client = await db.get(Client, client_id)
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
    db: AsyncSession, client_id: int, chat_id: int, title: str = ""
) -> Optional[Client]:
    """Bind a Telegram group chat_id to a client (detaching any other client from the same group)."""
    client = await db.get(Client, client_id)
    if client is None:
        return None

    # Ensure 1-to-1 group chat -> client mapping
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
    return client


async def unbind_client_group(db: AsyncSession, client_id: int) -> Optional[Client]:
    """Detach Telegram group from a client."""
    client = await db.get(Client, client_id)
    if client is None:
        return None
    client.group_chat_id = None
    client.group_title = ""
    await db.commit()
    await db.refresh(client)
    return client


async def delete_client(db: AsyncSession, client_id: int) -> bool:
    """Soft-deactivate a client and unbind its Telegram group."""
    client = await db.get(Client, client_id)
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
    db: AsyncSession, client_id: int, product_id: int, sell_price: Optional[float]
) -> Optional[ClientProductPrice]:
    """Set or clear (when sell_price is None or <=0) a client-specific product price."""
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


async def get_client_prices_map(db: AsyncSession, client_id: int) -> Dict[int, float]:
    """Return {product_id: custom_sell_price} for a client."""
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
    db: AsyncSession, client_id: int, history_limit: int = 15
) -> ClientDebtSummary:
    """Compute opening debt + confirmed sales - non-deleted payments for a client."""
    client = await db.get(Client, client_id)
    if client is None:
        raise ValueError(f"Client {client_id} not found")

    sales = list(
        (
            await db.scalars(
                select(Sale)
                .options(selectinload(Sale.items))
                .where(Sale.client_id == client_id, Sale.status == "confirmed")
                .order_by(desc(Sale.id))
            )
        ).all()
    )
    payments = list(
        (
            await db.scalars(
                select(ClientPayment)
                .where(
                    ClientPayment.client_id == client_id,
                    ClientPayment.is_deleted.is_(False),
                )
                .order_by(desc(ClientPayment.id))
            )
        ).all()
    )

    opening = float(client.opening_debt or 0.0)
    total_sales = sum(float(s.total_amount) for s in sales)
    total_paid = sum(float(p.amount) for p in payments)
    total_kg = round(sum(float(s.total_weight_kg) for s in sales), 3)
    current_debt = round(opening + total_sales - total_paid, 2)

    return ClientDebtSummary(
        client=client,
        opening_debt=opening,
        total_sales=total_sales,
        total_paid=total_paid,
        current_debt=current_debt,
        total_kg=total_kg,
        recent_sales=sales[:history_limit],
        recent_payments=payments[:history_limit],
    )


async def list_all_client_debts(db: AsyncSession) -> List[ClientDebtSummary]:
    """Return ClientDebtSummary for all active clients sorted by highest debt first."""
    clients = await list_clients(db, active_only=True)
    if not clients:
        return []

    sales = list(
        (
            await db.scalars(
                select(Sale)
                .options(selectinload(Sale.items))
                .where(Sale.status == "confirmed", Sale.client_id.is_not(None))
                .order_by(desc(Sale.id))
            )
        ).all()
    )
    payments = list(
        (
            await db.scalars(
                select(ClientPayment)
                .where(ClientPayment.is_deleted.is_(False))
                .order_by(desc(ClientPayment.id))
            )
        ).all()
    )

    sales_by_cli: Dict[int, List[Sale]] = {}
    for s in sales:
        if s.client_id is not None:
            sales_by_cli.setdefault(s.client_id, []).append(s)

    pay_by_cli: Dict[int, List[ClientPayment]] = {}
    for p in payments:
        pay_by_cli.setdefault(p.client_id, []).append(p)

    summaries: List[ClientDebtSummary] = []
    for cli in clients:
        c_sales = sales_by_cli.get(cli.id, [])
        c_pays = pay_by_cli.get(cli.id, [])
        opening = float(cli.opening_debt or 0.0)
        t_sales = sum(float(s.total_amount) for s in c_sales)
        t_paid = sum(float(p.amount) for p in c_pays)
        t_kg = round(sum(float(s.total_weight_kg) for s in c_sales), 3)
        summaries.append(
            ClientDebtSummary(
                client=cli,
                opening_debt=opening,
                total_sales=t_sales,
                total_paid=t_paid,
                current_debt=round(opening + t_sales - t_paid, 2),
                total_kg=t_kg,
                recent_sales=c_sales[:10],
                recent_payments=c_pays[:10],
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
) -> Sale:
    """
    Create a pending Sale with itemized Norin rows.

    Each entry in `items_spec` should provide:
        - product_id (int) OR product (Product)
        - weight_kg (float)
        - optional weights_detail (str)
        - optional unit_sell_price (float override)
    """
    if session_id is None:
        sess = await get_or_create_open_session(db)
        session_id = sess.id
    else:
        sess = await db.get(DailyCashSession, session_id)
        if sess is None:
            raise ValueError(f"Session {session_id} not found")

    custom_prices = await get_client_prices_map(db, client_id) if client_id else {}

    sale = Sale(
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
        if prod is None and spec.get("product_id") is not None:
            prod = await db.get(Product, int(spec["product_id"]))
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
    loaded = await get_sale(db, sale.id)
    assert loaded is not None
    return loaded


async def get_sale(db: AsyncSession, sale_id: int) -> Optional[Sale]:
    """Fetch a Sale eager-loading its items and client."""
    stmt = (
        select(Sale)
        .options(selectinload(Sale.items), selectinload(Sale.client))
        .where(Sale.id == sale_id)
    )
    return await db.scalar(stmt)


async def confirm_sale(
    db: AsyncSession,
    sale_id: int,
    group_chat_id: Optional[int] = None,
    group_message_id: Optional[int] = None,
) -> Optional[Sale]:
    """Confirm a pending sale and attach optional group message metadata."""
    sale = await get_sale(db, sale_id)
    if sale is None or sale.status == "deleted":
        return None
    sale.status = "confirmed"
    if group_chat_id is not None:
        sale.group_chat_id = group_chat_id
    if group_message_id is not None:
        sale.group_message_id = group_message_id
    await db.commit()
    await compute_session_summary(db, sale.session_id)
    return await get_sale(db, sale_id)


async def set_sale_group_message(
    db: AsyncSession,
    sale_id: int,
    group_chat_id: Optional[int],
    group_message_id: Optional[int],
) -> Optional[Sale]:
    """Store or clear Telegram group chat_id and message_id for a Sale."""
    sale = await get_sale(db, sale_id)
    if sale is None:
        return None
    sale.group_chat_id = group_chat_id
    sale.group_message_id = group_message_id
    await db.commit()
    return await get_sale(db, sale_id)


async def update_sale_client(
    db: AsyncSession, sale_id: int, new_client_id: Optional[int]
) -> Optional[Sale]:
    """Reassign a Sale's client and recalculate item sell prices using the new client's prices."""
    sale = await get_sale(db, sale_id)
    if sale is None or sale.status == "deleted":
        return None
    sale.client_id = new_client_id
    custom_prices = await get_client_prices_map(db, new_client_id) if new_client_id else {}

    for item in sale.items:
        if item.product_id is not None:
            prod = await db.get(Product, item.product_id)
            if prod is not None:
                item.unit_sell_price = custom_prices.get(prod.id, float(prod.default_sell_price))
    _recalc_sale_totals(sale)
    await db.commit()
    if sale.status == "confirmed":
        await compute_session_summary(db, sale.session_id)
    return await get_sale(db, sale_id)


async def update_sale_item(
    db: AsyncSession,
    item_id: int,
    weight_kg: Optional[float] = None,
    unit_sell_price: Optional[float] = None,
    product_id: Optional[int] = None,
    weights_detail: Optional[str] = None,
) -> Optional[Sale]:
    """Update a SaleItem and recalculate its parent Sale totals and session summary."""
    item = await db.get(SaleItem, item_id)
    if item is None:
        return None
    sale = await get_sale(db, item.sale_id)
    if sale is None or sale.status == "deleted":
        return None

    target_item = next((i for i in sale.items if i.id == item_id), item)
    if product_id is not None:
        prod = await db.get(Product, product_id)
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
        await compute_session_summary(db, sale.session_id)
    return await get_sale(db, sale.id)


async def delete_sale(db: AsyncSession, sale_id: int) -> Optional[Sale]:
    """Soft-delete a Sale and recalculate daily session summary."""
    sale = await get_sale(db, sale_id)
    if sale is None or sale.status == "deleted":
        return None
    was_confirmed = sale.status == "confirmed"
    sale.status = "deleted"
    await db.commit()
    if was_confirmed:
        await compute_session_summary(db, sale.session_id)
    return await get_sale(db, sale_id)


async def find_duplicate_confirmed_sale(
    db: AsyncSession,
    session_id: int,
    client_id: Optional[int],
    total_weight_kg: float,
    exclude_id: Optional[int] = None,
) -> Optional[Sale]:
    """Check if a confirmed sale with same client and weight already exists in this session."""
    if client_id is None:
        return None
    stmt = (
        select(Sale)
        .options(selectinload(Sale.items), selectinload(Sale.client))
        .where(
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
) -> List[Sale]:
    """Return recent confirmed sales ordered newest first."""
    stmt = (
        select(Sale)
        .options(selectinload(Sale.items), selectinload(Sale.client))
        .where(Sale.status == "confirmed")
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
) -> ClientPayment:
    """Record a payment received from a client and update session expected cash."""
    if session_id is None:
        sess = await get_or_create_open_session(db)
        session_id = sess.id
    method = payment_method if payment_method in ("cash", "card", "transfer") else "cash"
    pay = ClientPayment(
        session_id=session_id,
        client_id=client_id,
        amount=float(amount),
        payment_method=method,
        note=note.strip(),
        is_deleted=False,
    )
    db.add(pay)
    await db.commit()
    await compute_session_summary(db, session_id)
    loaded = await get_client_payment(db, pay.id)
    assert loaded is not None
    return loaded


async def get_client_payment(db: AsyncSession, payment_id: int) -> Optional[ClientPayment]:
    """Fetch a ClientPayment eager-loading its client."""
    stmt = (
        select(ClientPayment)
        .options(selectinload(ClientPayment.client))
        .where(ClientPayment.id == payment_id)
    )
    return await db.scalar(stmt)


async def set_client_payment_group_message(
    db: AsyncSession,
    payment_id: int,
    group_chat_id: Optional[int],
    group_message_id: Optional[int],
) -> Optional[ClientPayment]:
    """Store group receipt message reference on ClientPayment."""
    pay = await db.get(ClientPayment, payment_id)
    if pay is None:
        return None
    pay.group_chat_id = group_chat_id
    pay.group_message_id = group_message_id
    await db.commit()
    return await get_client_payment(db, payment_id)


async def update_client_payment(
    db: AsyncSession,
    payment_id: int,
    new_amount: Optional[float] = None,
    payment_method: Optional[str] = None,
    note: Optional[str] = None,
) -> Optional[ClientPayment]:
    """Edit a ClientPayment and recalculate daily cash session."""
    pay = await db.get(ClientPayment, payment_id)
    if pay is None or pay.is_deleted:
        return None
    if new_amount is not None:
        pay.amount = float(new_amount)
    if payment_method in ("cash", "card", "transfer"):
        pay.payment_method = payment_method
    if note is not None:
        pay.note = note.strip()
    await db.commit()
    await compute_session_summary(db, pay.session_id)
    return await get_client_payment(db, payment_id)


async def delete_client_payment(db: AsyncSession, payment_id: int) -> Optional[ClientPayment]:
    """Soft-delete a ClientPayment and recalculate daily cash session."""
    pay = await db.get(ClientPayment, payment_id)
    if pay is None or pay.is_deleted:
        return None
    pay.is_deleted = True
    await db.commit()
    await compute_session_summary(db, pay.session_id)
    return await get_client_payment(db, payment_id)


async def list_recent_client_payments(
    db: AsyncSession,
    limit: int = 30,
    offset: int = 0,
    client_id: Optional[int] = None,
) -> List[ClientPayment]:
    """Return recent non-deleted client payments ordered newest first."""
    stmt = (
        select(ClientPayment)
        .options(selectinload(ClientPayment.client))
        .where(ClientPayment.is_deleted.is_(False))
    )
    if client_id is not None:
        stmt = stmt.where(ClientPayment.client_id == client_id)
    stmt = stmt.order_by(desc(ClientPayment.id)).offset(offset).limit(limit)
    return list((await db.scalars(stmt)).all())


# ---------------------------------------------------------------------------
# Daily Cash Wallet, Expenses, Kassa Debt & Profit Reports
# ---------------------------------------------------------------------------


async def get_open_session(db: AsyncSession) -> Optional[DailyCashSession]:
    """Fetch the most recent open DailyCashSession."""
    stmt = (
        select(DailyCashSession)
        .where(DailyCashSession.status == "open")
        .order_by(desc(DailyCashSession.id))
        .limit(1)
    )
    return await db.scalar(stmt)


async def get_last_closed_session(db: AsyncSession) -> Optional[DailyCashSession]:
    """Fetch the most recent closed DailyCashSession."""
    stmt = (
        select(DailyCashSession)
        .where(DailyCashSession.status == "closed")
        .order_by(desc(DailyCashSession.id))
        .limit(1)
    )
    return await db.scalar(stmt)


async def get_or_create_open_session(
    db: AsyncSession, report_date: Optional[str] = None
) -> DailyCashSession:
    """Return active open session or create one carrying over last closed counted cash."""
    open_sess = await get_open_session(db)
    if open_sess is not None:
        return open_sess

    last_closed = await get_last_closed_session(db)
    opening_balance = float(last_closed.actual_counted_cash or 0.0) if last_closed else 0.0

    new_sess = DailyCashSession(
        report_date=report_date or today_iso(),
        status="open",
        opening_balance=opening_balance,
        expected_cash=opening_balance,
    )
    db.add(new_sess)
    await db.commit()
    await db.refresh(new_sess)
    return new_sess


async def get_outstanding_kassa_debt(db: AsyncSession) -> float:
    """Compute cumulative unpaid debt borrowed from Kassa across all non-deleted records."""
    txs = (
        await db.scalars(
            select(CashTransaction).where(
                CashTransaction.is_deleted.is_(False),
                CashTransaction.source_type.in_(["kassa_debt", "kassa_repay"]),
            )
        )
    ).all()
    debt = sum(float(t.amount) for t in txs if t.source_type == "kassa_debt")
    repaid = sum(float(t.amount) for t in txs if t.source_type == "kassa_repay")
    return debt - repaid


async def get_kassa_debt_stats(db: AsyncSession, limit: int = 10) -> dict:
    """Return kassa debt totals and recent kassa debt/repay movements."""
    txs = list(
        (
            await db.scalars(
                select(CashTransaction)
                .where(
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


async def get_total_all_clients_debt(db: AsyncSession) -> float:
    """Quickly compute total unpaid debt across all active clients."""
    clients = await list_clients(db, active_only=True)
    if not clients:
        return 0.0
    opening = sum(float(c.opening_debt or 0.0) for c in clients)
    active_ids = {c.id for c in clients}

    sales_rows = (
        await db.scalars(
            select(Sale).where(Sale.status == "confirmed", Sale.client_id.in_(active_ids))
        )
    ).all()
    pay_rows = (
        await db.scalars(
            select(ClientPayment).where(
                ClientPayment.is_deleted.is_(False),
                ClientPayment.client_id.in_(active_ids),
            )
        )
    ).all()

    total_sales = sum(float(s.total_amount) for s in sales_rows)
    total_paid = sum(float(p.amount) for p in pay_rows)
    return round(opening + total_sales - total_paid, 2)


async def compute_session_summary(
    db: AsyncSession, session_id: Optional[int] = None
) -> DailyReportSummary:
    """Compute live cash balance, sales kg, cost, profit, and client payments for a session."""
    if session_id is None:
        sess = await get_or_create_open_session(db)
        session_id = sess.id
    else:
        sess = await db.get(DailyCashSession, session_id)
        if sess is None:
            raise ValueError(f"Session {session_id} not found")

    sales = list(
        (
            await db.scalars(
                select(Sale)
                .options(selectinload(Sale.items), selectinload(Sale.client))
                .where(Sale.session_id == session_id, Sale.status == "confirmed")
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
                    CashTransaction.session_id == session_id,
                    CashTransaction.is_deleted.is_(False),
                )
                .order_by(CashTransaction.id)
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

    total_kg = round(sum(float(s.total_weight_kg) for s in sales), 3)
    total_revenue = round(sum(float(s.total_amount) for s in sales), 2)
    total_cost = round(sum(float(s.total_cost) for s in sales), 2)
    total_profit = round(total_revenue - total_cost, 2)
    margin_pct = (total_profit / total_revenue * 100.0) if total_revenue > 0 else 0.0

    outstanding_kassa = await get_outstanding_kassa_debt(db)
    total_clients_debt = await get_total_all_clients_debt(db)

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
    )


async def compute_period_summary(db: AsyncSession, days: int = 30) -> PeriodReportSummary:
    """Compute aggregated Norin sales, profit, collections, and expenses over the last N days."""
    end_dt = now_local().date()
    start_dt = end_dt - timedelta(days=max(0, days - 1))
    start_iso = start_dt.strftime("%Y-%m-%d")
    end_iso = end_dt.strftime("%Y-%m-%d")

    sessions = list(
        (
            await db.scalars(
                select(DailyCashSession).where(
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

    if sess_ids:
        sales = list(
            (
                await db.scalars(
                    select(Sale)
                    .options(selectinload(Sale.items))
                    .where(Sale.session_id.in_(sess_ids), Sale.status == "confirmed")
                )
            ).all()
        )
        payments = list(
            (
                await db.scalars(
                    select(ClientPayment).where(
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
                        CashTransaction.session_id.in_(sess_ids),
                        CashTransaction.is_deleted.is_(False),
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

    total_kg = round(sum(float(s.total_weight_kg) for s in sales), 3)
    total_revenue = round(sum(float(s.total_amount) for s in sales), 2)
    total_cost = round(sum(float(s.total_cost) for s in sales), 2)
    total_profit = round(total_revenue - total_cost, 2)
    margin_pct = (total_profit / total_revenue * 100.0) if total_revenue > 0 else 0.0

    total_cash_collected = sum(float(p.amount) for p in payments if p.payment_method == "cash")
    total_card_collected = sum(float(p.amount) for p in payments if p.payment_method == "card")
    total_transfer_collected = sum(
        float(p.amount) for p in payments if p.payment_method == "transfer"
    )
    total_expenses = sum(float(t.amount) for t in txs if t.source_type == "expense")
    total_clients_debt = await get_total_all_clients_debt(db)

    return PeriodReportSummary(
        days=days,
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
    )


async def add_cash_transaction(
    db: AsyncSession,
    amount: float,
    source_type: str = "main_in",
    note: str = "",
    session_id: Optional[int] = None,
) -> CashTransaction:
    """Record a cash-in, expense, kassa debt, or kassa repayment transaction."""
    if session_id is None:
        sess = await get_or_create_open_session(db)
        session_id = sess.id
    valid_type = (
        source_type
        if source_type in ("main_in", "expense", "kassa_debt", "kassa_repay")
        else "main_in"
    )
    tx = CashTransaction(
        session_id=session_id,
        amount=float(amount),
        source_type=valid_type,
        note=note.strip(),
        is_deleted=False,
    )
    db.add(tx)
    await db.commit()
    await db.refresh(tx)
    await compute_session_summary(db, session_id)
    return tx


async def update_cash_transaction(
    db: AsyncSession,
    tx_id: int,
    new_amount: Optional[float] = None,
    new_note: Optional[str] = None,
) -> Optional[CashTransaction]:
    """Edit an existing cash/expense transaction and recalculate session balance."""
    tx = await db.get(CashTransaction, tx_id)
    if tx is None or tx.is_deleted:
        return None
    if new_amount is not None:
        tx.amount = float(new_amount)
    if new_note is not None:
        tx.note = new_note.strip()
    await db.commit()
    await db.refresh(tx)
    await compute_session_summary(db, tx.session_id)
    return tx


async def delete_cash_transaction(db: AsyncSession, tx_id: int) -> Optional[CashTransaction]:
    """Soft-delete a cash/expense transaction and recalculate session balance."""
    tx = await db.get(CashTransaction, tx_id)
    if tx is None or tx.is_deleted:
        return None
    tx.is_deleted = True
    await db.commit()
    await db.refresh(tx)
    await compute_session_summary(db, tx.session_id)
    return tx


async def close_cash_session(
    db: AsyncSession, session_id: int, actual_counted_cash: float
) -> DailyReportSummary:
    """Close a cash session with actual counted cash, recording discrepancy into history."""
    summary = await compute_session_summary(db, session_id)
    sess = summary.session
    sess.actual_counted_cash = float(actual_counted_cash)
    sess.expected_cash = summary.expected_cash
    sess.difference = float(actual_counted_cash) - summary.expected_cash
    sess.status = "closed"
    sess.closed_at = now_utc()
    await db.commit()
    await db.refresh(sess)
    return await compute_session_summary(db, session_id)


async def reopen_cash_session(
    db: AsyncSession, session_id: int
) -> Optional[DailyCashSession]:
    """Reopen a closed session if admin wants to correct entries."""
    current_open = await get_open_session(db)
    if current_open is not None and current_open.id != session_id:
        current_summary = await compute_session_summary(db, current_open.id)
        if (
            not current_summary.confirmed_sales
            and not current_summary.client_payments
            and not current_summary.cash_transactions
        ):
            await db.delete(current_open)
            await db.commit()
    sess = await db.get(DailyCashSession, session_id)
    if sess is None:
        return None
    sess.status = "open"
    sess.closed_at = None
    await db.commit()
    await db.refresh(sess)
    return sess


async def list_closed_sessions(
    db: AsyncSession, limit: int = 10
) -> List[DailyCashSession]:
    """Return recent closed sessions ordered newest first."""
    stmt = (
        select(DailyCashSession)
        .where(DailyCashSession.status == "closed")
        .order_by(desc(DailyCashSession.id))
        .limit(limit)
    )
    return list((await db.scalars(stmt)).all())


async def list_all_sessions(
    db: AsyncSession, limit: int = 15
) -> List[DailyCashSession]:
    """Return recent open and closed daily sessions ordered newest first."""
    stmt = select(DailyCashSession).order_by(desc(DailyCashSession.id)).limit(limit)
    return list((await db.scalars(stmt)).all())


# ---------------------------------------------------------------------------
# Group Config, App Preferences & Rounding
# ---------------------------------------------------------------------------


async def set_group_config(
    db: AsyncSession, role: str, chat_id: int, title: str
) -> GroupConfig:
    """Bind or update a system Telegram group chat_id for a given role."""
    stmt = select(GroupConfig).where(GroupConfig.role == role)
    obj = await db.scalar(stmt)
    if obj is None:
        obj = GroupConfig(role=role, chat_id=chat_id, title=title)
        db.add(obj)
    else:
        obj.chat_id = chat_id
        obj.title = title
    await db.commit()
    await db.refresh(obj)
    return obj


async def get_group_config(db: AsyncSession, role: str) -> Optional[GroupConfig]:
    """Return configured system group for a role."""
    return await db.scalar(select(GroupConfig).where(GroupConfig.role == role))


async def get_all_group_configs(db: AsyncSession) -> Dict[str, GroupConfig]:
    """Return all configured system groups keyed by role."""
    rows = (await db.scalars(select(GroupConfig))).all()
    return {row.role: row for row in rows}


async def get_app_setting(db: AsyncSession, key: str, default: str = "") -> str:
    """Read a bot preference value from app_settings."""
    obj = await db.get(AppSetting, key)
    return obj.value if obj is not None else default


async def set_app_setting(db: AsyncSession, key: str, value: str) -> AppSetting:
    """Persist a bot preference value in app_settings."""
    obj = await db.get(AppSetting, key)
    if obj is None:
        obj = AppSetting(key=key, value=value)
        db.add(obj)
    else:
        obj.value = value
    await db.commit()
    await db.refresh(obj)
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


async def get_subscription_state(db: AsyncSession) -> SubscriptionState:
    """Fetch singleton SubscriptionState (id=1), creating a default trial record if missing."""
    sub = await db.get(SubscriptionState, 1)
    if sub is None:
        settings = get_settings()
        trial_days = max(1, int(settings.DEFAULT_TRIAL_DAYS))
        sub = SubscriptionState(
            id=1,
            tenant_name="Norin Sexi",
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


async def evaluate_subscription_status(
    db: AsyncSession, current_time: Optional[datetime] = None
) -> SubscriptionStatus:
    """Evaluate active/expiring/grace/expired/suspended status safely with UTC normalization."""
    sub = await get_subscription_state(db)
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
) -> SubscriptionState:
    """Extend subscription from current expiry (if active) or from now (if already expired)."""
    sub = await get_subscription_state(db)
    now = now_utc()
    current_exp = to_utc_dt(sub.expires_at)
    base_dt = current_exp if current_exp > now else now
    sub.expires_at = base_dt + timedelta(days=int(days))
    sub.is_suspended = False
    if plan_name:
        sub.plan_name = plan_name.strip()

    payment = SubscriptionPayment(
        amount=float(amount),
        days_added=int(days),
        plan_name=sub.plan_name,
        note=note.strip(),
        recorded_by=int(recorded_by),
    )
    db.add(payment)
    await db.commit()
    await db.refresh(sub)
    return sub


async def update_subscription_settings(
    db: AsyncSession,
    monthly_price: Optional[float] = None,
    owner_contact: Optional[str] = None,
    tenant_name: Optional[str] = None,
    is_suspended: Optional[bool] = None,
    grace_days: Optional[int] = None,
) -> SubscriptionState:
    """Update subscription configuration fields."""
    sub = await get_subscription_state(db)
    if monthly_price is not None:
        sub.monthly_price = float(monthly_price)
    if owner_contact is not None and owner_contact.strip():
        sub.owner_contact = owner_contact.strip()
    if tenant_name is not None and tenant_name.strip():
        sub.tenant_name = tenant_name.strip()
    if is_suspended is not None:
        sub.is_suspended = bool(is_suspended)
    if grace_days is not None:
        sub.grace_days = max(0, int(grace_days))
    await db.commit()
    await db.refresh(sub)
    return sub


async def mark_reminder_sent(db: AsyncSession, date_iso: str) -> None:
    """Record the local date when expiry reminder was sent to avoid duplicate alerts."""
    sub = await get_subscription_state(db)
    sub.last_reminder_date = date_iso
    await db.commit()


async def list_subscription_payments(
    db: AsyncSession, limit: int = 15
) -> List[SubscriptionPayment]:
    """Return recent SaaS subscription payment entries."""
    stmt = (
        select(SubscriptionPayment)
        .order_by(desc(SubscriptionPayment.id))
        .limit(limit)
    )
    return list((await db.scalars(stmt)).all())


async def list_authorized_users(
    db: AsyncSession, active_only: bool = True
) -> List[AuthorizedUser]:
    """List dynamically added AuthorizedUsers."""
    stmt = select(AuthorizedUser)
    if active_only:
        stmt = stmt.where(AuthorizedUser.is_active.is_(True))
    stmt = stmt.order_by(AuthorizedUser.id)
    return list((await db.scalars(stmt)).all())


async def add_authorized_user(
    db: AsyncSession,
    telegram_id: int,
    full_name: str = "",
    role: str = "staff",
) -> AuthorizedUser:
    """Add or reactivate an authorized Telegram user."""
    existing = await db.scalar(
        select(AuthorizedUser).where(AuthorizedUser.telegram_id == int(telegram_id))
    )
    if existing is not None:
        existing.is_active = True
        if full_name.strip():
            existing.full_name = full_name.strip()
        existing.role = role
        await db.commit()
        await db.refresh(existing)
        return existing

    user = AuthorizedUser(
        telegram_id=int(telegram_id),
        full_name=full_name.strip() or f"User {telegram_id}",
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def remove_authorized_user(db: AsyncSession, telegram_id: int) -> bool:
    """Deactivate/remove a dynamically added AuthorizedUser."""
    existing = await db.scalar(
        select(AuthorizedUser).where(AuthorizedUser.telegram_id == int(telegram_id))
    )
    if existing is None:
        return False
    await db.delete(existing)
    await db.commit()
    return True


async def is_user_authorized(
    db: AsyncSession,
    user_id: Optional[int],
    allow_group_anon: bool = False,
) -> bool:
    """
    Check if a Telegram user is authorized to operate the bot.

    Super admins (SUPER_ADMIN_IDS) are always authorized.
    If both ADMIN_IDS (.env) and AuthorizedUser table are empty, private usage is open.
    Otherwise user_id must be in SUPER_ADMIN_IDS, ADMIN_IDS, or active AuthorizedUser rows.
    """
    if user_id is None:
        return False
    settings = get_settings()
    if user_id in settings.super_admin_id_list:
        return True
    if allow_group_anon and user_id == ANONYMOUS_ADMIN_BOT_ID:
        return True

    env_admins = settings.admin_id_list
    if user_id in env_admins:
        return True

    active_db_user = await db.scalar(
        select(AuthorizedUser.id).where(
            AuthorizedUser.telegram_id == int(user_id),
            AuthorizedUser.is_active.is_(True),
        )
    )
    if active_db_user is not None:
        return True

    if not env_admins:
        any_db_user = await db.scalar(
            select(sa_func.count(AuthorizedUser.id)).where(
                AuthorizedUser.is_active.is_(True)
            )
        )
        if not any_db_user:
            return True

    return False


# ---------------------------------------------------------------------------
# Database Reset Utilities (Super Admin /clear)
# ---------------------------------------------------------------------------


async def reset_test_transactions(db: AsyncSession) -> dict:
    """
    Clear all transactional test data (sales, payments, cash sessions, opening debts)
    while preserving Products, Clients, Custom Prices, Bound Groups, and Subscriptions.
    """
    sales_cnt = int(await db.scalar(select(sa_func.count(Sale.id))) or 0)
    pays_cnt = int(await db.scalar(select(sa_func.count(ClientPayment.id))) or 0)
    txs_cnt = int(await db.scalar(select(sa_func.count(CashTransaction.id))) or 0)
    sess_cnt = int(await db.scalar(select(sa_func.count(DailyCashSession.id))) or 0)

    await db.execute(delete(SaleItem))
    await db.execute(delete(Sale))
    await db.execute(delete(ClientPayment))
    await db.execute(delete(CashTransaction))
    await db.execute(delete(DailyCashSession))
    await db.execute(update(Client).values(opening_debt=0.0))
    await db.commit()

    return {
        "sales": sales_cnt,
        "payments": pays_cnt,
        "cash_txs": txs_cnt,
        "sessions": sess_cnt,
    }


async def reset_full_database(db: AsyncSession) -> dict:
    """
    Completely wipe operational data (sales, payments, cash, clients, groups, products, settings),
    re-seed default Norin products, and strictly preserve SubscriptionState/Payments & AuthorizedUser.
    """
    from database.session import seed_default_products

    sales_cnt = int(await db.scalar(select(sa_func.count(Sale.id))) or 0)
    pays_cnt = int(await db.scalar(select(sa_func.count(ClientPayment.id))) or 0)
    txs_cnt = int(await db.scalar(select(sa_func.count(CashTransaction.id))) or 0)
    sess_cnt = int(await db.scalar(select(sa_func.count(DailyCashSession.id))) or 0)
    clients_cnt = int(await db.scalar(select(sa_func.count(Client.id))) or 0)

    await db.execute(delete(SaleItem))
    await db.execute(delete(Sale))
    await db.execute(delete(ClientPayment))
    await db.execute(delete(CashTransaction))
    await db.execute(delete(DailyCashSession))
    await db.execute(delete(ClientProductPrice))
    await db.execute(delete(Client))
    await db.execute(delete(GroupConfig))
    await db.execute(delete(Product))
    await db.execute(delete(AppSetting))
    await db.commit()

    await seed_default_products(db)

    return {
        "sales": sales_cnt,
        "payments": pays_cnt,
        "cash_txs": txs_cnt,
        "sessions": sess_cnt,
        "clients": clients_cnt,
    }

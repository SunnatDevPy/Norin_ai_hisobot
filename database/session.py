"""Async SQLAlchemy engine, sessionmaker, and database initialization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import get_settings
from database.models import Base, Product, SubscriptionState


DEFAULT_PRODUCTS = [
    {
        "order_num": 1,
        "name": "Norin (Ot go'shtli)",
        "aliases": "OT,OT GO'SHTI,OTLI,NORIN OT,NOTIN OT,КОНИНА,ОТ,ОТ ГЎШТИ,НОРИН ОТ",
        "unit": "kg",
        "cost_price": 90000.0,
        "default_sell_price": 115000.0,
    },
    {
        "order_num": 2,
        "name": "Norin (Mol go'shtli)",
        "aliases": "MOL,MOL GO'SHTI,MOLLI,NORIN MOL,NOTIN MOL,ГОВЯДИНА,МОЛ,МОЛ ГЎШТИ,НОРИН МОЛ",
        "unit": "kg",
        "cost_price": 80000.0,
        "default_sell_price": 105000.0,
    },
]


def create_engine_and_session(
    database_url: str | None = None,
) -> Tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create an AsyncEngine and async_sessionmaker for the given URL."""
    url = database_url or get_settings().DATABASE_URL
    eng = create_async_engine(url, echo=False, future=True)
    maker = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)
    return eng, maker


engine, async_session_maker = create_engine_and_session()


async def seed_default_products(session: AsyncSession) -> None:
    """Populate initial Norin products if products table is empty."""
    existing = await session.scalar(select(Product.id).limit(1))
    if existing is not None:
        return
    for item in DEFAULT_PRODUCTS:
        session.add(Product(**item, is_active=True))
    await session.commit()


async def seed_default_subscription(session: AsyncSession) -> None:
    """Create initial singleton SubscriptionState (id=1) with trial period if missing."""
    existing = await session.get(SubscriptionState, 1)
    if existing is not None:
        return
    settings = get_settings()
    trial_days = max(1, int(settings.DEFAULT_TRIAL_DAYS))
    sub = SubscriptionState(
        id=1,
        tenant_name="Norin Sexi",
        plan_name="Pro Oylik",
        monthly_price=float(settings.DEFAULT_MONTHLY_PRICE),
        expires_at=datetime.now(timezone.utc) + timedelta(days=trial_days),
        grace_days=3,
        is_suspended=False,
        owner_contact=settings.OWNER_CONTACT,
        last_reminder_date="",
    )
    session.add(sub)
    await session.commit()


async def init_db(
    engine_override: AsyncEngine | None = None,
    session_maker_override: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Create all tables and seed initial products and subscription state."""
    target_engine = engine_override or engine
    target_maker = session_maker_override or async_session_maker
    async with target_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with target_maker() as session:
        await seed_default_products(session)
        await seed_default_subscription(session)

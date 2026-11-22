"""Async SQLAlchemy engine, sessionmaker, and database initialization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Tuple

from sqlalchemy import select, text
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
    eng_kwargs: dict = {"echo": False, "future": True}
    if url.startswith("postgresql"):
        eng_kwargs.update(
            {
                "pool_pre_ping": True,
                "pool_recycle": 300,
                "pool_size": 10,
                "max_overflow": 20,
            }
        )
    eng = create_async_engine(url, **eng_kwargs)
    maker = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)
    return eng, maker


engine, async_session_maker = create_engine_and_session()


async def seed_default_products(
    session: AsyncSession, tenant_id: int = 1, commit: bool = True
) -> None:
    """Populate initial Norin products if the tenant's products catalog is empty."""
    existing = await session.scalar(
        select(Product.id).where(Product.tenant_id == tenant_id).limit(1)
    )
    if existing is not None:
        return
    for item in DEFAULT_PRODUCTS:
        session.add(Product(**item, tenant_id=tenant_id, is_active=True))
    if commit:
        await session.commit()


async def seed_default_subscription(session: AsyncSession) -> None:
    """Create initial default tenant SubscriptionState (id=1) with trial period if missing."""
    existing = await session.get(SubscriptionState, 1)
    if existing is not None:
        return
    settings = get_settings()
    trial_days = max(1, int(settings.DEFAULT_TRIAL_DAYS))
    sub = SubscriptionState(
        tenant_name="Test Filial (Asad)",
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


def _upgrade_multitenant_schema(conn) -> None:
    """Idempotently migrate an existing PostgreSQL single-tenant database to multi-tenant."""
    if conn.dialect.name != "postgresql":
        return

    tenant_tables = (
        "products",
        "clients",
        "group_configs",
        "daily_cash_sessions",
        "sales",
        "client_payments",
        "cash_transactions",
        "subscription_payments",
        "authorized_users",
    )
    for tbl in tenant_tables:
        conn.execute(
            text(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1")
        )
        conn.execute(
            text(f"CREATE INDEX IF NOT EXISTS ix_{tbl}_tenant_id ON {tbl} (tenant_id)")
        )

    # Replace single-tenant unique constraints with per-tenant composite unique indexes
    for stmt in (
        "ALTER TABLE products DROP CONSTRAINT IF EXISTS products_name_key",
        "DROP INDEX IF EXISTS ix_products_name",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_products_tenant_name ON products (tenant_id, name)",
        "ALTER TABLE clients DROP CONSTRAINT IF EXISTS clients_name_key",
        "DROP INDEX IF EXISTS ix_clients_name",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_clients_tenant_name ON clients (tenant_id, name)",
        "ALTER TABLE group_configs DROP CONSTRAINT IF EXISTS group_configs_role_key",
        "DROP INDEX IF EXISTS ix_group_configs_role",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_group_configs_tenant_role ON group_configs (tenant_id, role)",
        "ALTER TABLE cash_transactions ADD COLUMN IF NOT EXISTS category VARCHAR(32) NOT NULL DEFAULT 'Boshqa'",
        "CREATE SEQUENCE IF NOT EXISTS subscription_states_id_seq OWNED BY subscription_states.id",
        "ALTER TABLE subscription_states ALTER COLUMN id SET DEFAULT nextval('subscription_states_id_seq')",
        """
        DO $$
        DECLARE max_id INTEGER;
        BEGIN
            SELECT MAX(id) INTO max_id FROM subscription_states;
            IF max_id IS NULL THEN
                PERFORM setval('subscription_states_id_seq', 1, false);
            ELSE
                PERFORM setval('subscription_states_id_seq', max_id, true);
            END IF;
        END $$;
        """,
    ):
        conn.execute(text(stmt))


async def init_db(
    engine_override: AsyncEngine | None = None,
    session_maker_override: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Create all tables, migrate schema if needed, and seed initial tenant data."""
    target_engine = engine_override or engine
    target_maker = session_maker_override or async_session_maker
    async with target_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_upgrade_multitenant_schema)
    async with target_maker() as session:
        await seed_default_products(session, tenant_id=1)
        await seed_default_subscription(session)
    from database.crud import bump_auth_cache_epoch

    bump_auth_cache_epoch()

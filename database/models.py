"""SQLAlchemy 2.0 ORM models for Norin AI Hisobot Bot."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base declarative class."""


class Product(Base):
    """Norin and meat products catalog with production cost and default sell price."""

    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_products_tenant_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    order_num: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="kg")
    cost_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    default_sell_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    client_prices: Mapped[List["ClientProductPrice"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class Client(Base):
    """Wholesale clients (stores/buyers) with bound Telegram group and opening debt."""

    __tablename__ = "clients"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_clients_tenant_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[str] = mapped_column(Text, nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    group_chat_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    group_title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    opening_debt: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    custom_prices: Mapped[List["ClientProductPrice"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )
    sales: Mapped[List["Sale"]] = relationship(back_populates="client")
    payments: Mapped[List["ClientPayment"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )


class ClientProductPrice(Base):
    """Per-client custom sell price override for a specific product."""

    __tablename__ = "client_product_prices"
    __table_args__ = (
        UniqueConstraint("client_id", "product_id", name="uq_client_product_price"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sell_price: Mapped[float] = mapped_column(Float, nullable=False)

    client: Mapped["Client"] = relationship(back_populates="custom_prices")
    product: Mapped["Product"] = relationship(back_populates="client_prices")


class GroupConfig(Base):
    """System Telegram group binding by role (e.g. 'report')."""

    __tablename__ = "group_configs"
    __table_args__ = (UniqueConstraint("tenant_id", "role", name="uq_group_configs_tenant_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DailyCashSession(Base):
    """Daily cash wallet session tracking opening balance, inflows, expenses, and reconciliation."""

    __tablename__ = "daily_cash_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    report_date: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", index=True)
    opening_balance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_counted_cash: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_cash: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    difference: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    sales: Mapped[List["Sale"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    client_payments: Mapped[List["ClientPayment"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    cash_transactions: Mapped[List["CashTransaction"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Sale(Base):
    """A Norin wholesale order/delivery to a client within a daily session."""

    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("daily_cash_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    report_date: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    photo_file_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_weight_kg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_profit: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    source_channel: Mapped[str] = mapped_column(String(16), nullable=False, default="dm")
    group_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    group_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    session: Mapped["DailyCashSession"] = relationship(back_populates="sales")
    client: Mapped[Optional["Client"]] = relationship(back_populates="sales")
    items: Mapped[List["SaleItem"]] = relationship(
        back_populates="sale", cascade="all, delete-orphan", order_by="SaleItem.id"
    )


class SaleItem(Base):
    """Individual meat/Norin product line item belonging to a Sale with price snapshots."""

    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sale_id: Mapped[int] = mapped_column(
        ForeignKey("sales.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    weights_detail: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    unit_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    unit_sell_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    line_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    line_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    line_profit: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    sale: Mapped["Sale"] = relationship(back_populates="items")


class ClientPayment(Base):
    """Payments received from clients (cash, card, or bank transfer)."""

    __tablename__ = "client_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("daily_cash_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(24), nullable=False, default="cash")
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    group_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    group_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped["DailyCashSession"] = relationship(back_populates="client_payments")
    client: Mapped["Client"] = relationship(back_populates="payments")


class CashTransaction(Base):
    """Owner cash-in, production expenses, kassa debt, and kassa repayment movements."""

    __tablename__ = "cash_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("daily_cash_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="main_in")
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped["DailyCashSession"] = relationship(back_populates="cash_transactions")


class SubscriptionState(Base):
    """Monthly SaaS subscription license state for the bot instance (singleton id=1)."""

    __tablename__ = "subscription_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_name: Mapped[str] = mapped_column(String(255), nullable=False, default="Norin Sexi")
    plan_name: Mapped[str] = mapped_column(String(64), nullable=False, default="Pro Oylik")
    monthly_price: Mapped[float] = mapped_column(Float, nullable=False, default=400000.0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    grace_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    is_suspended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    owner_contact: Mapped[str] = mapped_column(String(255), nullable=False, default="@SunnatDevPy")
    last_reminder_date: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SubscriptionPayment(Base):
    """Audit log of monthly subscription renewals recorded by Super Admin."""

    __tablename__ = "subscription_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    days_added: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    plan_name: Mapped[str] = mapped_column(String(64), nullable=False, default="Pro Oylik")
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    recorded_by: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuthorizedUser(Base):
    """Dynamically managed authorized bot users (client owner & staff) in addition to .env."""

    __tablename__ = "authorized_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="staff")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AppSetting(Base):
    """Key-value bot behavior settings (auto_confirm, group_auto_calc, round_mode, etc.)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False, default="")

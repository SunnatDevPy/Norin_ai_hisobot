"""Handlers router assembly for Norin AI Hisobot Bot."""

from aiogram import Router

from bot.handlers.clients_products import router as clients_products_router
from bot.handlers.sales_norin import router as sales_router
from bot.handlers.superadmin import router as superadmin_router
from bot.handlers.wallet_reports import router as wallet_reports_router


def get_main_router() -> Router:
    """Combine all feature routers in priority order."""
    root = Router()
    root.include_router(superadmin_router)
    root.include_router(clients_products_router)
    root.include_router(wallet_reports_router)
    # sales_router contains fallback photo/voice/text handlers, so include last
    root.include_router(sales_router)
    return root

"""norin-api entry point: `uvicorn api.main:app --host 0.0.0.0 --port 8000`."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from api import apk_meta
from api.routers import admin as admin_router
from api.routers import auth as auth_router
from api.routers import read as read_router
from api.routers import write as write_router
from config import get_settings
from database.session import init_db


logger = logging.getLogger("norin_api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    settings = get_settings()
    bot: Bot | None = None
    if settings.BOT_TOKEN and settings.BOT_TOKEN != "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        bot = Bot(
            token=settings.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    app.state.bot = bot

    async def send_telegram(chat_id: int, text: str) -> None:
        if bot is None:
            raise RuntimeError("BOT_TOKEN sozlanmagan")
        await bot.send_message(chat_id=chat_id, text=text)

    app.state.send_telegram = send_telegram
    logger.info("norin-api started")
    try:
        yield
    finally:
        if bot is not None:
            await bot.session.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Norin AI API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.bot = None

    @app.get("/health")
    async def health() -> dict:
        meta = apk_meta.get_apk_version_metadata()
        return {
            "status": "ok",
            "service": "norin-api",
            "apk_version": meta["version"],
            "apk_build": meta["build"],
        }

    @app.get("/apk/version")
    @app.get("/api/v1/apk/version")
    async def get_apk_version() -> JSONResponse:
        meta = apk_meta.get_apk_version_metadata()
        return JSONResponse(
            content={
                **meta,
                "download_path": "/download/norin_ai.apk",
                "api_download_path": "/api/v1/download/norin_ai.apk",
            },
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @app.get("/download/norin_ai.apk")
    @app.get("/api/v1/download/norin_ai.apk")
    async def download_apk_binary() -> FileResponse:
        if not apk_meta.APK_BINARY_PATH.is_file():
            raise HTTPException(
                status_code=404,
                detail="APK fayli serverda topilmadi (data/norin_ai.apk)",
            )
        meta = apk_meta.get_apk_version_metadata()
        return FileResponse(
            apk_meta.APK_BINARY_PATH,
            media_type="application/vnd.android.package-archive",
            filename=f"Norin_AI_v{meta['version']}.apk",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    prefix = "/api/v1"
    app.include_router(auth_router.router, prefix=prefix)
    app.include_router(read_router.router, prefix=prefix)
    app.include_router(write_router.router, prefix=prefix)
    app.include_router(admin_router.router, prefix=prefix)
    return app


app = create_app()

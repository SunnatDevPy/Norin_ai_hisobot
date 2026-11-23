"""norin-api entry point: `uvicorn api.main:app --host 0.0.0.0 --port 8000`."""

from __future__ import annotations

import html
import json
import logging
import re
from contextlib import asynccontextmanager
from typing import AsyncIterator

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

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

    @app.get("/app/open")
    async def open_mobile_app(ticket: str = "") -> HTMLResponse:
        safe_ticket = re.sub(r"[^A-Za-z0-9_-]", "", ticket or "")[:64]
        q = f"?ticket={safe_ticket}" if safe_ticket else ""
        scheme_url = f"sotuvai://auth-done{q}"
        intent_url = (
            f"intent://auth-done{q}"
            "#Intent;scheme=sotuvai;package=uz.norinai.norin_ai_app;end"
        )
        esc_intent = html.escape(intent_url, quote=True)
        esc_scheme = html.escape(scheme_url, quote=True)
        js_intent = json.dumps(intent_url)
        js_scheme = json.dumps(scheme_url)
        page = f"""<!doctype html>
<html lang="uz">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Sotuv AI</title>
  <style>
    body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
    background:radial-gradient(circle at top,#241242 0%,#0b0a0f 65%);color:#fff;
    font-family:system-ui,-apple-system,sans-serif;text-align:center;padding:24px}}
    .card{{max-width:340px;width:100%;padding:28px 22px;border-radius:24px;
    background:#14121e;border:1px solid rgba(168,85,247,.38);box-shadow:0 16px 40px rgba(0,0,0,.5)}}
    h2{{margin:0 0 8px;font-size:22px}}
    p{{margin:0 0 22px;color:#b8b4cc;font-size:14px;line-height:1.45}}
    .btn{{display:block;padding:14px 18px;border-radius:999px;text-decoration:none;
    font-weight:700;font-size:15px;color:#1a0b2e;
    background:linear-gradient(90deg,#e9d5ff,#a855f7);margin-bottom:10px}}
    .sub{{display:inline-block;color:#c084fc;font-size:13px;text-decoration:none;margin-top:6px}}
  </style>
</head>
<body>
  <div class="card">
    <h2>Sotuv AI</h2>
    <p>Kirish tasdiqlandi. Ilovaga qaytish uchun quyidagi tugmani bosing.</p>
    <a class="btn" id="openBtn" href="{esc_intent}">🚀 Sotuv AI ilovasini ochish</a>
    <a class="sub" href="{esc_scheme}">Ilova ochilmasa bosing</a>
  </div>
  <script>
    window.addEventListener('load', function(){{
      try {{ window.location.replace({js_intent}); }} catch(e) {{}}
      setTimeout(function(){{
        try {{ window.location.href = {js_scheme}; }} catch(e) {{}}
      }}, 350);
    }});
  </script>
</body>
</html>"""
        return HTMLResponse(content=page, headers={"Cache-Control": "no-store"})

    prefix = "/api/v1"
    app.include_router(auth_router.router, prefix=prefix)
    app.include_router(read_router.router, prefix=prefix)
    app.include_router(write_router.router, prefix=prefix)
    app.include_router(admin_router.router, prefix=prefix)
    return app


app = create_app()

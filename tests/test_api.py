"""Tests for the norin-api (FastAPI) backend used by the mobile app."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import httpx
import pytest

from api.main import create_app
from api.security import rate_limiter
from config import get_settings
from database import session as db_session
from database.session import create_engine_and_session, init_db


ADMIN_ID = 5649321700
PFX = "/api/v1"


async def _with_api(tmp_path: Path, monkeypatch, fn) -> None:
    """Run fn(client, sent_messages, maker) against an isolated SQLite DB and fresh app."""
    monkeypatch.setenv("SUPER_ADMIN_IDS", str(ADMIN_ID))
    monkeypatch.setenv("API_JWT_SECRET", "test-secret-key-for-norin-api-32bytes-ok")
    get_settings.cache_clear()
    rate_limiter.reset()
    eng, maker = create_engine_and_session(f"sqlite+aiosqlite:///{(tmp_path / 'api.db').as_posix()}")
    monkeypatch.setattr(db_session, "async_session_maker", maker)
    try:
        await init_db(engine_override=eng, session_maker_override=maker)
        app = create_app()
        sent: list[tuple[int, str]] = []

        async def fake_send(chat_id: int, text: str) -> None:
            sent.append((chat_id, text))

        app.state.send_telegram = fake_send
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await fn(client, sent, maker)
    finally:
        get_settings.cache_clear()
        await eng.dispose()


def _code_from(sent: list[tuple[int, str]]) -> str:
    m = re.search(r"<code>(\d{6})</code>", sent[-1][1])
    assert m, sent[-1][1]
    return m.group(1)


async def login(client, sent, device: str = "Test Phone") -> dict:
    r = await client.post(f"{PFX}/auth/request-code", json={"telegram_id": ADMIN_ID})
    assert r.status_code == 200
    r = await client.post(
        f"{PFX}/auth/verify-code",
        json={"telegram_id": ADMIN_ID, "code": _code_from(sent), "device_name": device},
    )
    assert r.status_code == 200, r.text
    return r.json()


def auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_auth_otp_flow_refresh_devices_and_logout(tmp_path: Path, monkeypatch):
    async def _logic(client, sent, maker):
        health = (await client.get("/health")).json()
        assert health["status"] == "ok" and health["service"] == "norin-api"

        # Non-admin ID: same reply, but NO code is sent
        r = await client.post(f"{PFX}/auth/request-code", json={"telegram_id": 111})
        assert r.status_code == 200 and sent == []
        r = await client.post(
            f"{PFX}/auth/verify-code", json={"telegram_id": 111, "code": "123456"}
        )
        assert r.status_code == 400

        # Super Admin OTP
        await client.post(f"{PFX}/auth/request-code", json={"telegram_id": ADMIN_ID})
        assert len(sent) == 1 and sent[0][0] == ADMIN_ID
        code = _code_from(sent)
        bad = await client.post(
            f"{PFX}/auth/verify-code",
            json={"telegram_id": ADMIN_ID, "code": "000000" if code != "000000" else "111111"},
        )
        assert bad.status_code == 400
        ok = await client.post(
            f"{PFX}/auth/verify-code",
            json={"telegram_id": ADMIN_ID, "code": code, "device_name": "Pixel"},
        )
        assert ok.status_code == 200
        tokens = ok.json()
        assert tokens["role"] == "super_admin" and tokens["tenant_id"] == 1

        # Code is single-use
        again = await client.post(
            f"{PFX}/auth/verify-code", json={"telegram_id": ADMIN_ID, "code": code}
        )
        assert again.status_code == 400

        # Protected endpoint
        assert (await client.get(f"{PFX}/auth/me")).status_code == 401
        me = await client.get(f"{PFX}/auth/me", headers=auth(tokens))
        assert me.status_code == 200 and me.json()["telegram_id"] == ADMIN_ID
        assert (
            await client.get(f"{PFX}/auth/me", headers={"Authorization": "Bearer junk"})
        ).status_code == 401

        # Refresh rotates refresh token
        rf = await client.post(
            f"{PFX}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert rf.status_code == 200
        new_tokens = rf.json()
        assert new_tokens["refresh_token"] != tokens["refresh_token"]
        old = await client.post(
            f"{PFX}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert old.status_code == 401

        # Devices & logout / revoke
        dev = await client.get(f"{PFX}/auth/devices", headers=auth(new_tokens))
        assert dev.status_code == 200 and dev.json()[0]["device_name"] == "Pixel"
        t2 = await login(client, sent, device="Second Phone")
        devs = (await client.get(f"{PFX}/auth/devices", headers=auth(t2))).json()
        assert len(devs) == 2
        first = next(d for d in devs if d["device_name"] == "Pixel")
        assert (
            await client.delete(f"{PFX}/auth/devices/{first['id']}", headers=auth(t2))
        ).status_code == 200
        assert (await client.get(f"{PFX}/auth/me", headers=auth(new_tokens))).status_code == 401

        assert (await client.post(f"{PFX}/auth/logout", headers=auth(t2))).status_code == 200
        assert (await client.get(f"{PFX}/auth/me", headers=auth(t2))).status_code == 401

    asyncio.run(_with_api(tmp_path, monkeypatch, _logic))


def test_read_api_dashboard_catalog_statement_and_exports(tmp_path: Path, monkeypatch):
    from database.crud import (
        add_cash_transaction,
        add_client_payment,
        add_product_return,
        bind_client_group,
        confirm_sale,
        create_client,
        create_pending_sale,
        list_products,
    )

    async def _logic(client, sent, maker):
        # 401 without token
        assert (await client.get(f"{PFX}/clients")).status_code == 401

        async with maker() as db:
            prods = await list_products(db)
            cli = await create_client(db, "Iftiqor API", phone="+998901112233", opening_debt=100_000)
            await bind_client_group(db, cli.id, -100999, "Iftiqor Guruh")
            sale = await create_pending_sale(
                db, client_id=cli.id, items_spec=[{"product_id": prods[0].id, "weight_kg": 10.0}]
            )
            await confirm_sale(db, sale.id)  # 10 * 115,000 = 1,150,000
            await add_client_payment(db, cli.id, 300_000, payment_method="cash")
            await add_product_return(db, cli.id, prods[0].id, 2.0, reason="brak")  # -230,000
            await add_cash_transaction(db, 50_000, source_type="expense", note="xamir", category="Xamir")

        tokens = await login(client, sent)
        h = auth(tokens)

        # Dashboard today: net of return (8 kg, 920,000), debt 100k+1.15M-230k-300k = 720k
        s = (await client.get(f"{PFX}/dashboard/summary?period=today", headers=h)).json()
        assert s["kpis"]["total_kg"] == 8.0 and s["kpis"]["revenue"] == 920_000
        assert s["kpis"]["returns_amount"] == 230_000 and s["kpis"]["expenses"] == 50_000
        assert s["total_clients_debt"] == 720_000
        assert s["cash"]["client_cash_in"] == 300_000

        for per in ("7", "30", "cur", "prev"):
            r = await client.get(f"{PFX}/dashboard/summary?period={per}", headers=h)
            assert r.status_code == 200, (per, r.text)
        assert (await client.get(f"{PFX}/dashboard/summary?period=zzz", headers=h)).status_code == 422

        ch = (await client.get(f"{PFX}/dashboard/charts?period=30", headers=h)).json()
        assert ch["daily_series"][0]["revenue"] == 920_000
        assert ch["expense_breakdown"][0] == {"category": "Xamir", "amount": 50_000}
        assert ch["top_clients"][0]["name"] == "Iftiqor API"

        # Catalog
        prods_json = (await client.get(f"{PFX}/products", headers=h)).json()
        assert len(prods_json) == 2 and "cost_price" in prods_json[0]
        cl = (await client.get(f"{PFX}/clients?q=iftiqor", headers=h)).json()
        assert cl[0]["current_debt"] == 720_000 and cl[0]["group_chat_id"] == -100999
        assert (await client.get(f"{PFX}/clients?q=nomavjud", headers=h)).json() == []
        card = (await client.get(f"{PFX}/clients/{cli.id}", headers=h)).json()
        assert card["total_returns"] == 230_000 and len(card["recent_sales"]) == 1
        assert (await client.get(f"{PFX}/clients/9999", headers=h)).status_code == 404
        dbt = (await client.get(f"{PFX}/debts", headers=h)).json()
        assert dbt["total"] == 720_000 and dbt["count"] == 1

        # Statement: running balance ends at current debt; NO cost/profit anywhere
        st = (await client.get(f"{PFX}/clients/{cli.id}/statement", headers=h)).json()
        assert st["events"][-1]["balance"] == 720_000
        assert {e["kind"] for e in st["events"]} == {"sale", "payment", "return"}
        blob = str(st).lower()
        assert "cost" not in blob and "profit" not in blob and "tannarx" not in blob

        # Today detail + history
        td = (await client.get(f"{PFX}/today", headers=h)).json()
        assert len(td["sales"]) == 1 and len(td["payments"]) == 1 and len(td["returns"]) == 1
        sessions = (await client.get(f"{PFX}/history/sessions", headers=h)).json()
        assert len(sessions) == 1
        det = await client.get(f"{PFX}/history/sessions/{sessions[0]['id']}", headers=h)
        assert det.status_code == 200
        assert (await client.get(f"{PFX}/history/sessions/9999", headers=h)).status_code == 404
        hs = (await client.get(f"{PFX}/history/sales", headers=h)).json()
        assert len(hs["items"]) == 1 and hs["has_more"] is False
        hp = (await client.get(f"{PFX}/history/payments?client_id={cli.id}", headers=h)).json()
        assert hp["items"][0]["amount"] == 300_000

        # Exports return real xlsx files
        for url in (
            f"/export/daily/{sessions[0]['id']}",
            "/export/period?period=30",
            f"/export/client/{cli.id}",
        ):
            r = await client.get(f"{PFX}{url}", headers=h)
            assert r.status_code == 200, (url, r.text)
            assert r.content[:2] == b"PK" and "spreadsheetml" in r.headers["content-type"]
        assert (await client.get(f"{PFX}/export/period?period=today", headers=h)).status_code == 422
        assert (await client.get(f"{PFX}/export/history", headers=h)).status_code == 404

        # Settings
        se = (await client.get(f"{PFX}/settings", headers=h)).json()
        assert se["tenant"]["id"] == 1 and se["auto_confirm"] is True
        assert se["ai"]["daily_limit"] == 0

        # Tenant switch via header (super admin) + unknown tenant
        assert (await client.get(f"{PFX}/clients", headers={**h, "X-Tenant-Id": "99"})).status_code == 404

    asyncio.run(_with_api(tmp_path, monkeypatch, _logic))


def test_write_api_full_operations_and_settings(tmp_path: Path, monkeypatch):
    """Verify full write API: products, clients, prices, manual & 0-token text sales, confirm, edit, payment, return, cash, close/reopen & settings."""
    async def _logic(client, sent, maker):
        h = auth(await login(client, sent))

        # 1. Product create / patch / delete
        pr = await client.post(
            f"{PFX}/products",
            headers=h,
            json={"name": "Qazi (API)", "cost_price": 120_000, "default_sell_price": 150_000, "unit": "kg"},
        )
        assert pr.status_code == 200
        pid = pr.json()["id"]
        pr_up = await client.patch(f"{PFX}/products/{pid}", headers=h, json={"unit": "dona", "default_sell_price": 160_000})
        assert pr_up.status_code == 200 and pr_up.json()["unit"] == "dona"
        assert (await client.delete(f"{PFX}/products/{pid}", headers=h)).status_code == 200

        # 2. Client create / patch / custom price / group bind & unbind
        prods = (await client.get(f"{PFX}/products", headers=h)).json()
        ot_id = prods[0]["id"]
        cr = await client.post(
            f"{PFX}/clients",
            headers=h,
            json={"name": "Sardor Bozor", "phone": "+998901234567", "opening_debt": 50_000},
        )
        assert cr.status_code == 200
        cid = cr.json()["id"]
        assert (
            await client.patch(
                f"{PFX}/clients/{cid}",
                headers=h,
                json={"group_chat_id": -100777, "group_title": "Sardor Grp"},
            )
        ).json()["group_chat_id"] == -100777
        cp = await client.put(
            f"{PFX}/clients/{cid}/prices/{ot_id}",
            headers=h,
            json={"sell_price": 112_000},
        )
        assert cp.json()["custom_prices"][str(ot_id)] == 112_000
        assert (await client.post(f"{PFX}/clients/{cid}/unbind-group", headers=h)).json()["group_chat_id"] is None

        # 3. Text sale (0-token) + edit item + confirm + delete
        ts = await client.post(f"{PFX}/sales/from-text", headers=h, json={"text": "Sardor Bozor ot 10 kg"})
        assert ts.status_code == 200 and ts.json()["intent"] == "sale"
        sale = ts.json()["sale"]
        assert sale["total_amount"] == 1_120_000  # 10 * custom 112,000
        item_id = sale["items"][0]["id"]

        ed = await client.patch(f"{PFX}/sales/items/{item_id}", headers=h, json={"weight_kg": 12.0})
        assert ed.status_code == 200 and ed.json()["sale"]["total_amount"] == 1_344_000

        cf = await client.post(
            f"{PFX}/sales/{sale['id']}/confirm", headers=h, json={"post_to_group": False}
        )
        assert cf.status_code == 200 and cf.json()["sale"]["status"] == "confirmed"
        assert cf.json()["client_debt"] == 1_394_000  # 50k opening + 1,344k

        # 4. Payment & Vozvrat
        pm = await client.post(
            f"{PFX}/payments",
            headers=h,
            json={"client_id": cid, "amount": 394_000, "payment_method": "card", "note": "Click"},
        )
        assert pm.status_code == 200 and pm.json()["client_debt"] == 1_000_000

        rt = await client.post(
            f"{PFX}/returns",
            headers=h,
            json={"client_id": cid, "product_id": ot_id, "weight_kg": 2.0, "reason": "brak"},
        )
        assert rt.status_code == 200 and rt.json()["client_debt"] == 776_000  # 1M - 2*112k

        # 5. Cash tx + Close & Reopen day
        tx = await client.post(
            f"{PFX}/cash/transactions",
            headers=h,
            json={"amount": 100_000, "source_type": "expense", "category": "Go'sht", "note": "ot go'shti"},
        )
        assert tx.status_code == 200 and tx.json()["transaction"]["category"] == "Go'sht"

        cl = await client.post(
            f"{PFX}/cash/close-day", headers=h, json={"counted_cash": 0, "notify_report_group": False}
        )
        assert cl.status_code == 200 and cl.json()["session"]["status"] == "closed"
        sess_id = cl.json()["session"]["id"]
        assert (await client.post(f"{PFX}/cash/reopen/{sess_id}", headers=h)).json()["session"]["status"] == "open"

        # 6. Settings patch
        sp = await client.patch(
            f"{PFX}/settings",
            headers=h,
            json={"auto_confirm": False, "round_mode": "nearest_1000"},
        )
        assert sp.status_code == 200
        sv = (await client.get(f"{PFX}/settings", headers=h)).json()
        assert sv["auto_confirm"] is False and sv["round_mode"] == "nearest_1000"

    asyncio.run(_with_api(tmp_path, monkeypatch, _logic))


def test_admin_api_tenants_users_analytics_broadcast_and_audit(tmp_path: Path, monkeypatch):
    """Verify Super Admin API endpoints: MRR analytics, tenant CRUD, extend, suspend, AI limit, users, broadcast & audit."""
    async def _logic(client, sent, maker):
        h = auth(await login(client, sent))

        # Create tenant #2
        ct = await client.post(
            f"{PFX}/admin/tenants",
            headers=h,
            json={"tenant_name": "Chorsu Sexi", "monthly_price": 500_000, "trial_days": 30},
        )
        assert ct.status_code == 200 and ct.json()["id"] == 2
        tid2 = ct.json()["id"]

        # Patch settings + AI daily limit
        pt = await client.patch(
            f"{PFX}/admin/tenants/{tid2}",
            headers=h,
            json={"plan_name": "VIP", "ai_daily_limit": 100, "round_mode": "floor_1000"},
        )
        assert pt.status_code == 200

        # Extend +30 days
        ex = await client.post(
            f"{PFX}/admin/tenants/{tid2}/extend", headers=h, json={"days": 30, "amount": 500_000}
        )
        assert ex.status_code == 200
        pays = (await client.get(f"{PFX}/admin/tenants/{tid2}/payments", headers=h)).json()
        assert len(pays) == 1 and pays[0]["amount"] == 500_000

        # Add user, reassign & remove
        au = await client.post(
            f"{PFX}/admin/users",
            headers=h,
            json={"telegram_id": 777000111, "full_name": "Sardor", "role": "owner", "tenant_id": tid2},
        )
        assert au.status_code == 200
        assert (await client.get(f"{PFX}/admin/tenants/{tid2}/users", headers=h)).json()[0]["telegram_id"] == 777000111

        # Broadcast uses fake_send
        bc = await client.post(f"{PFX}/admin/broadcast", headers=h, json={"text": "Yangi versiya!"})
        assert bc.status_code == 200 and bc.json()["sent"] >= 1
        assert any("Yangi versiya!" in txt for _, txt in sent)

        # Global MRR analytics
        an = (await client.get(f"{PFX}/admin/analytics", headers=h)).json()
        assert an["total_tenants"] == 2 and an["paying_mrr"] == 500_000

        # Suspend & resume return full serialized tenant objects
        s1 = await client.post(f"{PFX}/admin/tenants/{tid2}/suspend", headers=h, json={"is_suspended": True})
        assert s1.status_code == 200 and s1.json()["id"] == tid2 and s1.json()["is_suspended"] is True
        s2 = await client.post(f"{PFX}/admin/tenants/{tid2}/suspend", headers=h, json={"is_suspended": False})
        assert s2.status_code == 200 and s2.json()["id"] == tid2 and s2.json()["is_suspended"] is False

        # Patch tenant meta returns full object
        pm = await client.patch(f"{PFX}/admin/tenants/{tid2}", headers=h, json={"plan_name": "Pro"})
        assert pm.status_code == 200 and pm.json()["id"] == tid2 and pm.json()["plan_name"] == "Pro"

        # Staff & backward-compatible worker role + clear modes ('tx' and 'tx_only')
        au_staff = await client.post(
            f"{PFX}/admin/users",
            headers=h,
            json={"telegram_id": 777000222, "full_name": "Ishchi 1", "role": "worker", "tenant_id": tid2},
        )
        assert au_staff.status_code == 200 and au_staff.json()["role"] == "staff"
        assert (await client.post(f"{PFX}/admin/tenants/{tid2}/clear", headers=h, json={"mode": "tx"})).status_code == 200
        assert (await client.post(f"{PFX}/admin/tenants/{tid2}/clear", headers=h, json={"mode": "tx_only"})).status_code == 200

        # Tenant #1 cannot be deleted; Tenant #2 deletes cleanly
        assert (await client.delete(f"{PFX}/admin/tenants/1", headers=h)).status_code == 400
        assert (await client.delete(f"{PFX}/admin/tenants/{tid2}", headers=h)).status_code == 200

        # Audit log recorded actions
        logs = (await client.get(f"{PFX}/admin/audit", headers=h)).json()
        actions = {x["action"] for x in logs}
        assert {"create_tenant", "extend_tenant", "delete_tenant", "broadcast"} <= actions

    asyncio.run(_with_api(tmp_path, monkeypatch, _logic))


def test_auth_brute_force_limits(tmp_path: Path, monkeypatch):
    async def _logic(client, sent, maker):
        await client.post(f"{PFX}/auth/request-code", json={"telegram_id": ADMIN_ID})
        real = _code_from(sent)
        wrong = "999999" if real != "999999" else "888888"
        for _ in range(5):
            r = await client.post(
                f"{PFX}/auth/verify-code", json={"telegram_id": ADMIN_ID, "code": wrong}
            )
            assert r.status_code == 400
        # 6th attempt burns the code even if correct
        r = await client.post(
            f"{PFX}/auth/verify-code", json={"telegram_id": ADMIN_ID, "code": real}
        )
        assert r.status_code == 400

        # Request-code rate limit: 3 per window per ID (1 used above)
        await client.post(f"{PFX}/auth/request-code", json={"telegram_id": ADMIN_ID})
        await client.post(f"{PFX}/auth/request-code", json={"telegram_id": ADMIN_ID})
        r = await client.post(f"{PFX}/auth/request-code", json={"telegram_id": ADMIN_ID})
        assert r.status_code == 429

    asyncio.run(_with_api(tmp_path, monkeypatch, _logic))


def test_apk_version_download_and_bot_apk_otp(tmp_path: Path, monkeypatch):
    import json
    from api import apk_meta
    from bot.handlers import apk_link

    fake_apk = tmp_path / "norin_ai.apk"
    fake_ver = tmp_path / "apk_version.json"
    monkeypatch.setattr(apk_meta, "APK_BINARY_PATH", fake_apk)
    monkeypatch.setattr(apk_meta, "APK_VERSION_PATH", fake_ver)

    async def _logic(client, sent, maker):
        # Missing binary -> apk_available=False, /download -> 404
        v0 = await client.get("/apk/version")
        assert v0.status_code == 200 and v0.json()["apk_available"] is False
        assert (await client.get("/download/norin_ai.apk")).status_code == 404

        # Present binary + metadata
        payload = b"PK\x03\x04dummy-apk-binary"
        fake_apk.write_bytes(payload)
        fake_ver.write_text(
            json.dumps({"version": "1.2.3", "build": 7, "full": "1.2.3+7", "built_at": "2026-11-23"}),
            encoding="utf-8",
        )
        for vp in ("/apk/version", f"{PFX}/apk/version"):
            vr = await client.get(vp)
            assert vr.status_code == 200
            body = vr.json()
            assert body["apk_available"] is True
            assert body["version"] == "1.2.3" and body["build"] == 7
            assert body["size_bytes"] == len(payload)

        for dp in ("/download/norin_ai.apk", f"{PFX}/download/norin_ai.apk"):
            dr = await client.get(dp)
            assert dr.status_code == 200 and dr.content == payload
            assert "Sotuv_AI_v1.2.3.apk" in dr.headers["content-disposition"]

        # Bot /apk OTP works end-to-end with /api/v1/auth/verify-code
        bot_code = await apk_link._issue_bot_otp(ADMIN_ID)
        assert len(bot_code) == 6 and bot_code.isdigit()
        ok = await client.post(
            f"{PFX}/auth/verify-code",
            json={"telegram_id": ADMIN_ID, "code": bot_code, "device_name": "Bot APK"},
        )
        assert ok.status_code == 200 and ok.json()["role"] == "super_admin"

    asyncio.run(_with_api(tmp_path, monkeypatch, _logic))


def test_multitenant_idless_code_and_telegram_ticket_isolation(tmp_path: Path, monkeypatch):
    from sqlalchemy import select
    from api.security import hash_secret
    from bot.handlers import apk_link
    from database.crud import add_authorized_user, create_client, create_tenant
    from database.models import ApiLoginCode

    OWNER_TG = 888999111

    async def _logic(client, sent, maker):
        sa_h = auth(await login(client, sent))

        # Super Admin creates Tenant #2 + adds Tenant #2 client + assigns OWNER_TG
        async with maker() as db:
            t2 = await create_tenant(db, "Samarqand Filiali", monthly_price=300_000, trial_days=15)
            await add_authorized_user(
                db, telegram_id=OWNER_TG, full_name="Samarqand Egasi", role="owner", tenant_id=t2.id
            )
            c2 = await create_client(db, "Samarqand Mijoz", opening_debt=250_000, tenant_id=t2.id)

        # 1. ID-less 6-digit code login works for regular tenant user (without entering Telegram ID)
        code = await apk_link._issue_bot_otp(OWNER_TG)
        res = await client.post(
            f"{PFX}/auth/login-code", json={"code": code, "device_name": "Tenant2 Phone"}
        )
        assert res.status_code == 200, res.text
        t2_tokens = res.json()
        assert t2_tokens["role"] == "owner" and t2_tokens["tenant_id"] == t2.id

        # Same code cannot be reused
        assert (
            await client.post(f"{PFX}/auth/login-code", json={"code": code})
        ).status_code == 400

        # 2. Tenant isolation + Admin panel strictly blocked (403)
        h2 = auth(t2_tokens)
        assert (await client.get(f"{PFX}/admin/analytics", headers=h2)).status_code == 403
        assert (await client.get(f"{PFX}/admin/tenants", headers=h2)).status_code == 403

        # Even passing X-Tenant-Id: 1 is ignored for non-super-admin; sees ONLY Tenant #2 client
        cl = (await client.get(f"{PFX}/clients", headers={**h2, "X-Tenant-Id": "1"})).json()
        assert len(cl) == 1 and cl[0]["id"] == c2.id and cl[0]["name"] == "Samarqand Mijoz"

        # Super Admin CAN still see Tenant #1 cleanly
        cl1 = (await client.get(f"{PFX}/clients", headers=sa_h)).json()
        assert all(x["name"] != "Samarqand Mijoz" for x in cl1)

        # 3. 1-Click Telegram Deep-Link Ticket + Poll flow
        tkt_resp = await client.post(f"{PFX}/auth/telegram-ticket", json={"device_name": "1Tap"})
        assert tkt_resp.status_code == 200
        tkt_data = tkt_resp.json()
        ticket = tkt_data["ticket"]
        assert f"start=apk_{ticket}" in tkt_data["bot_url"]

        # Pending before user taps START in bot
        p0 = (await client.post(f"{PFX}/auth/telegram-poll", json={"ticket": ticket})).json()
        assert p0["status"] == "pending"

        # Simulate bot /start apk_<ticket> approval by OWNER_TG
        async with maker() as db:
            row = await db.scalar(
                select(ApiLoginCode).where(ApiLoginCode.code_hash == hash_secret(f"tkt:{ticket}"))
            )
            assert row is not None and row.telegram_id == 0
            row.telegram_id = OWNER_TG
            await db.commit()

        p1 = (
            await client.post(
                f"{PFX}/auth/telegram-poll", json={"ticket": ticket, "device_name": "1Tap"}
            )
        ).json()
        assert p1["status"] == "approved"
        assert p1["role"] == "owner" and p1["tenant_id"] == t2.id
        assert (await client.get(f"{PFX}/auth/me", headers=auth(p1))).json()["telegram_id"] == OWNER_TG

        # Poll after consumption returns expired
        p2 = (await client.post(f"{PFX}/auth/telegram-poll", json={"ticket": ticket})).json()
        assert p2["status"] == "expired"

        # 4. Return-to-app trampoline page (/app/open) returns HTML with custom scheme & intent
        open_res = await client.get("/app/open", params={"ticket": "abc_123<script>"})
        assert open_res.status_code == 200
        assert "sotuvai://auth-done?ticket=abc_123script" in open_res.text
        assert "<script>" not in open_res.text.split("</style>", 1)[0]

        # 5. Real-time SaaS suspension blocks operational calls (403) while keeping /settings & /export open (200)
        await client.post(f"{PFX}/admin/tenants/{t2.id}/suspend", headers=sa_h, json={"is_suspended": True})
        assert (await client.get(f"{PFX}/clients", headers=h2)).status_code == 403
        assert (await client.post(f"{PFX}/clients", headers=h2, json={"name": "Yangi"})).status_code == 403
        assert (await client.get(f"{PFX}/settings", headers=h2)).status_code == 200
        assert (await client.get(f"{PFX}/export/period", headers=h2)).status_code == 200
        assert (await client.get(f"{PFX}/export/client/{c2.id}", headers=h2)).status_code == 200

        # Resume restores operational access immediately
        await client.post(f"{PFX}/admin/tenants/{t2.id}/suspend", headers=sa_h, json={"is_suspended": False})
        assert (await client.get(f"{PFX}/clients", headers=h2)).status_code == 200

        # 6. Deleting an authorized user revokes their active mobile sessions immediately
        await client.delete(f"{PFX}/admin/users/{OWNER_TG}", headers=sa_h)
        assert (await client.get(f"{PFX}/auth/me", headers=h2)).status_code == 401
        assert (await client.get(f"{PFX}/clients", headers=h2)).status_code == 401

    asyncio.run(_with_api(tmp_path, monkeypatch, _logic))

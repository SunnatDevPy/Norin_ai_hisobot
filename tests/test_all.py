"""Comprehensive automated tests for Norin AI Hisobot Bot."""

from __future__ import annotations

import asyncio
import io
from datetime import timedelta
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from database.crud import (
    add_authorized_user,
    add_cash_transaction,
    add_client_payment,
    bind_client_group,
    close_cash_session,
    compute_client_debt,
    compute_period_summary,
    compute_session_summary,
    confirm_sale,
    create_client,
    create_pending_sale,
    delete_client_payment,
    delete_sale,
    delete_tenant,
    evaluate_subscription_status,
    extend_subscription,
    get_ai_usage_summary,
    get_app_setting,
    get_authorized_user,
    get_cash_transaction,
    get_or_create_open_session,
    get_period_excel_data,
    get_raw_app_setting,
    get_tenant_overview_stats,
    infer_expense_category,
    is_user_authorized,
    list_all_broadcast_recipients,
    list_all_client_debts,
    list_clients,
    list_products,
    list_recent_sales,
    list_subscription_payments,
    list_tenants,
    log_ai_usage,
    match_client,
    match_product,
    now_utc,
    reassign_authorized_user,
    remove_authorized_user,
    reopen_cash_session,
    reset_full_database,
    reset_test_transactions,
    resolve_sell_price,
    resolve_user_tenant_id,
    set_app_setting,
    set_client_product_price,
    set_raw_app_setting,
    set_sale_group_message,
    tenant_scope,
    update_client_payment,
    update_product,
    update_sale_client,
    update_sale_item,
    update_subscription_settings,
)
from database.session import create_engine_and_session, init_db
from services.excel_export import (
    build_client_statement_excel,
    build_daily_norin_excel,
    build_history_excel,
)
from services.gemini_ai import (
    format_kg,
    format_uzs,
    parse_norin_voice_or_text,
    parse_uzbek_amount,
    parse_weight_kg,
)


async def _run_with_db(tmp_path: Path, fn) -> None:
    """Run an async coroutine with a fresh isolated SQLite database."""
    db_file = tmp_path / "test_norin.db"
    eng, maker = create_engine_and_session(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    try:
        await init_db(engine_override=eng, session_maker_override=maker)
        async with maker() as session:
            await fn(session)
    finally:
        await eng.dispose()


def test_amount_and_kg_parsers():
    assert parse_uzbek_amount("21 000 000") == 21_000_000
    assert parse_uzbek_amount("1.5 mln") == 1_500_000
    assert parse_uzbek_amount("450 ming") == 450_000
    assert format_uzs(2_875_000) == "2 875 000"

    assert parse_weight_kg("25 kg") == 25.0
    assert parse_weight_kg("12,5 кг") == 12.5
    assert parse_weight_kg("8.25 + 9.1 + 7.65") == 25.0
    assert parse_weight_kg("25 yarim kg") == 25.5
    assert parse_weight_kg("yarim kg") == 0.5

    assert format_kg(25.0) == "25"
    assert format_kg(12.5) == "12.5"
    assert format_kg(8.250) == "8.25"


def test_heuristic_norin_intents(tmp_path: Path):
    async def scenario(db: AsyncSession) -> None:
        products = await list_products(db)
        await create_client(db, "Iftiqor 80", aliases="IFTIQOR 80,IFTIQOR")
        clients = await list_clients(db)

        r1 = await parse_norin_voice_or_text(products, clients, text="Iftiqor 80 notin ot 25 kg")
        assert r1["intent"] == "sale"
        assert r1["client_hint"] == "Iftiqor 80"
        assert len(r1["items"]) == 1
        assert r1["items"][0]["weight_kg"] == 25.0
        assert match_product(r1["items"][0]["product_hint"], products).name == "Norin (Ot go'shtli)"

        r2 = await parse_norin_voice_or_text(products, clients, text="ot 12.5 kg mol 8 kg")
        assert r2["intent"] == "sale"
        assert r2["client_hint"] is None
        assert len(r2["items"]) == 2
        assert r2["items"][0]["weight_kg"] == 12.5
        assert r2["items"][1]["weight_kg"] == 8.0

        r3 = await parse_norin_voice_or_text(products, clients, text="Iftiqordan 2 mln karta oldim")
        assert r3["intent"] == "client_payment"
        assert r3["client_hint"] == "Iftiqor 80"
        assert r3["amount"] == 2_000_000
        assert r3["payment_method"] == "card"

        r4 = await parse_norin_voice_or_text(products, clients, text="Go'shtga 3.5 mln xarajat")
        assert r4["intent"] == "expense"
        assert r4["amount"] == 3_500_000

        r5 = await parse_norin_voice_or_text(products, clients, text="Kassadan 1 mln oldim")
        assert r5["intent"] == "kassa_debt"
        assert r5["amount"] == 1_000_000

        r6 = await parse_norin_voice_or_text(products, clients, text="Qarzlar")
        assert r6["intent"] == "debts"

        r7 = await parse_norin_voice_or_text(products, clients, text="Status")
        assert r7["intent"] == "status"

    asyncio.run(_run_with_db(tmp_path, scenario))


def test_products_clients_custom_pricing_and_snapshot(tmp_path: Path):
    async def scenario(db: AsyncSession) -> None:
        products = await list_products(db)
        assert len(products) == 2
        ot = match_product("ot", products)
        mol = match_product("mol", products)
        assert ot is not None and mol is not None
        assert ot.cost_price == 90_000
        assert ot.default_sell_price == 115_000

        c1 = await create_client(db, "Iftiqor 80", opening_debt=500_000)
        c2 = await create_client(db, "Chorsu Do'kon")
        c3 = await create_client(db, "Makro")

        await set_client_product_price(db, c1.id, ot.id, 112_000)
        await set_client_product_price(db, c2.id, ot.id, 118_000)

        assert await resolve_sell_price(db, c1.id, ot) == 112_000
        assert await resolve_sell_price(db, c2.id, ot) == 118_000
        assert await resolve_sell_price(db, c3.id, ot) == 115_000  # default fallback

        # Record a confirmed sale for c1: 25 kg * 112,000 = 2,800,000; cost = 25 * 90,000 = 2,250,000; profit = 550,000
        sale = await create_pending_sale(
            db,
            client_id=c1.id,
            items_spec=[{"product": ot, "weight_kg": 25.0}],
        )
        await confirm_sale(db, sale.id)
        assert sale.total_amount == 2_800_000
        assert sale.total_cost == 2_250_000
        assert sale.total_profit == 550_000

        # Later updating product cost must NOT alter historical sale snapshot!
        await update_product(db, ot.id, cost_price=95_000)
        debt = await compute_client_debt(db, c1.id)
        assert debt.current_debt == 3_300_000  # 500,000 opening + 2,800,000 sale
        hist_sale = debt.recent_sales[0]
        assert hist_sale.total_cost == 2_250_000
        assert hist_sale.total_profit == 550_000

    asyncio.run(_run_with_db(tmp_path, scenario))


def test_norin_sale_lifecycle_group_caption_privacy_and_debt(tmp_path: Path):
    from bot.handlers.sales_norin import (
        render_sale_admin_summary,
        render_sale_group_caption,
    )

    async def scenario(db: AsyncSession) -> None:
        products = await list_products(db)
        ot = match_product("ot", products)
        mol = match_product("mol", products)
        assert ot and mol

        c1 = await create_client(db, "Iftiqor 80")
        c2 = await create_client(db, "Chorsu Do'kon")
        await bind_client_group(db, c1.id, -100555, "Iftiqor Guruh")
        await set_client_product_price(db, c1.id, ot.id, 112_000)
        await set_client_product_price(db, c2.id, ot.id, 120_000)

        assert match_client("iftiqor", [c1, c2]).id == c1.id
        c_quote = await create_client(db, 'OKA GO"SHT')
        assert match_client("OKA GO'sht", [c_quote]).id == c_quote.id
        parsed_q = await parse_norin_voice_or_text(products, [c_quote], text="OKA GO'sht ot 25kg")
        assert parsed_q["intent"] == "sale"
        assert parsed_q["client_hint"] == 'OKA GO"SHT'

        # Multi-item sale with weights_detail (24 kg = 8.25 + 8.1 + 7.65)
        sale = await create_pending_sale(
            db,
            client_id=c1.id,
            items_spec=[
                {"product": ot, "weight_kg": 24.0, "weights_detail": "8.25 + 8.1 + 7.65"},
                {"product": mol, "weight_kg": 10.0},
            ],
            photo_file_id="photo_abc",
        )
        sale = await confirm_sale(db, sale.id)
        await set_sale_group_message(db, sale.id, -100555, 701)

        # Totals: (24 * 112,000) + (10 * 105,000) = 2,688,000 + 1,050,000 = 3,738,000
        # Cost: (24 * 90,000) + (10 * 80,000) = 2,160,000 + 800,000 = 2,960,000 -> Profit = 778,000
        assert sale.total_weight_kg == 34.0
        assert sale.total_amount == 3_738_000
        assert sale.total_cost == 2_960_000
        assert sale.total_profit == 778_000

        debt1 = await compute_client_debt(db, c1.id)
        assert debt1.current_debt == 3_738_000

        # CRITICAL PRIVACY CHECK: Client group caption MUST NEVER leak cost or profit!
        grp_caption = render_sale_group_caption(sale, debt1.current_debt)
        assert "Iftiqor 80" in grp_caption
        assert "8.25 + 8.1 + 7.65" in grp_caption
        assert "3 738 000" in grp_caption
        assert "tannarx" not in grp_caption.lower()
        assert "foyda" not in grp_caption.lower()
        assert "2 960 000" not in grp_caption
        assert "778 000" not in grp_caption

        # Admin summary DOES show cost & profit
        admin_text = render_sale_admin_summary(sale, debt1.current_debt)
        assert "2 960 000" in admin_text
        assert "778 000" in admin_text

        # Edit weight of first item: 25 -> 20 kg
        updated_sale = await update_sale_item(db, sale.items[0].id, weight_kg=20.0)
        assert updated_sale.total_weight_kg == 30.0
        assert updated_sale.total_amount == (20 * 112_000) + (10 * 105_000)  # 3,290,000

        # Reassign sale to c2 -> sell price for Ot becomes 120,000!
        reassigned = await update_sale_client(db, sale.id, c2.id)
        assert reassigned.total_amount == (20 * 120_000) + (10 * 105_000)  # 3,450,000
        assert (await compute_client_debt(db, c1.id)).current_debt == 0.0
        assert (await compute_client_debt(db, c2.id)).current_debt == 3_450_000

        # Soft-delete sale -> c2 debt goes back to 0 and group caption shows deleted
        deleted = await delete_sale(db, sale.id)
        assert deleted.status == "deleted"
        assert (await compute_client_debt(db, c2.id)).current_debt == 0.0
        del_caption = render_sale_group_caption(deleted, 0.0)
        assert "BEKOR QILINDI" in del_caption

    asyncio.run(_run_with_db(tmp_path, scenario))


def test_client_payments_wallet_reconciliation_and_carry_over(tmp_path: Path):
    async def scenario(db: AsyncSession) -> None:
        products = await list_products(db)
        ot = match_product("ot", products)
        assert ot
        cli = await create_client(db, "Iftiqor 80")

        sess1 = await get_or_create_open_session(db, report_date="2026-11-18")
        assert sess1.opening_balance == 0.0

        sale = await create_pending_sale(
            db, client_id=cli.id, items_spec=[{"product": ot, "weight_kg": 40.0}], session_id=sess1.id
        )
        await confirm_sale(db, sale.id)  # 40 * 115,000 = 4,600,000

        # Cash payment (affects physical expected_cash) + Card payment (reduces debt ONLY)
        await add_client_payment(db, cli.id, 2_000_000, payment_method="cash", session_id=sess1.id)
        await add_client_payment(db, cli.id, 1_000_000, payment_method="card", session_id=sess1.id)

        # Expense + Kassa debt
        await add_cash_transaction(db, 500_000, source_type="expense", note="Go'sht", session_id=sess1.id)
        await add_cash_transaction(db, 300_000, source_type="kassa_debt", note="Kassadan", session_id=sess1.id)

        summary = await compute_session_summary(db, sess1.id)
        assert summary.client_cash_in == 2_000_000
        assert summary.client_card_in == 1_000_000
        assert summary.total_expenses == 500_000
        # expected_cash = 0 + 2,000,000 + 300,000 - 500,000 = 1,800,000 (Card excluded from physical cash!)
        assert summary.expected_cash == 1_800_000
        assert summary.total_all_clients_debt == 1_600_000  # 4,600,000 - 3,000,000

        # Close day with discrepancy, reopen, fix expense, re-close, carry over to Day 2
        closed = await close_cash_session(db, sess1.id, actual_counted_cash=1_700_000)
        assert closed.session.difference == -100_000

        await reopen_cash_session(db, sess1.id)
        await add_cash_transaction(db, 100_000, source_type="expense", note="Yo'l kira", session_id=sess1.id)
        closed_fixed = await close_cash_session(db, sess1.id, actual_counted_cash=1_700_000)
        assert closed_fixed.session.difference == 0.0

        sess2 = await get_or_create_open_session(db, report_date="2026-11-19")
        assert sess2.id != sess1.id
        assert sess2.opening_balance == 1_700_000

        period = await compute_period_summary(db, days=30)
        assert period.total_kg == 40.0
        assert period.total_profit == 40 * (115_000 - 90_000)

    asyncio.run(_run_with_db(tmp_path, scenario))


def test_subscription_lifecycle_and_authorized_users(tmp_path: Path):
    async def scenario(db: AsyncSession) -> None:
        st1 = await evaluate_subscription_status(db)
        assert st1.status == "active"
        assert st1.is_allowed is True
        assert st1.days_left >= 29

        # Simulate 28 days later -> expiring (<= 3 days)
        future_expiring = st1.state.expires_at
        from database.crud import to_utc_dt
        exp_dt = to_utc_dt(future_expiring)
        st_expiring = await evaluate_subscription_status(db, current_time=exp_dt - timedelta(days=2))
        assert st_expiring.status == "expiring"
        assert st_expiring.is_allowed is True

        # 1 day after expiry -> grace period (allowed)
        st_grace = await evaluate_subscription_status(db, current_time=exp_dt + timedelta(days=1))
        assert st_grace.status == "grace"
        assert st_grace.is_allowed is True

        # 5 days after expiry (>3 grace days) -> expired (blocked!)
        st_expired = await evaluate_subscription_status(db, current_time=exp_dt + timedelta(days=5))
        assert st_expired.status == "expired"
        assert st_expired.is_allowed is False

        # Extend subscription +30 days
        await extend_subscription(db, days=30, amount=400_000, recorded_by=5649321700, note="Oylik to'lov")
        st_after = await evaluate_subscription_status(db)
        assert st_after.is_allowed is True
        payments = await list_subscription_payments(db)
        assert len(payments) == 1
        assert payments[0].amount == 400_000

        # Suspend manually -> blocked, resume -> allowed
        await update_subscription_settings(db, is_suspended=True)
        assert (await evaluate_subscription_status(db)).status == "suspended"
        assert (await evaluate_subscription_status(db)).is_allowed is False
        await update_subscription_settings(db, is_suspended=False)
        assert (await evaluate_subscription_status(db)).is_allowed is True

        # Dynamic authorized users & super admin bypass
        assert await is_user_authorized(db, 5649321700) is True
        await add_authorized_user(db, 99887766, "Sardor", role="staff")
        assert await is_user_authorized(db, 99887766) is True
        assert await is_user_authorized(db, 111222333) is False
        await remove_authorized_user(db, 99887766)
        assert await is_user_authorized(db, 99887766) is False

    asyncio.run(_run_with_db(tmp_path, scenario))


def test_group_deeplinks_and_excel_exports(tmp_path: Path):
    from bot.keyboards import (
        GROUP_ADMIN_RIGHTS,
        build_client_group_deeplink,
        build_report_group_deeplink,
        client_detail_kb,
    )

    assert (
        build_client_group_deeplink("@norin_test_bot", 7)
        == f"https://t.me/norin_test_bot?startgroup=bind_client_7&admin={GROUP_ADMIN_RIGHTS}"
    )
    assert (
        build_report_group_deeplink("norin_test_bot")
        == f"https://t.me/norin_test_bot?startgroup=bind_report&admin={GROUP_ADMIN_RIGHTS}"
    )

    async def scenario(db: AsyncSession) -> None:
        products = await list_products(db)
        ot = match_product("ot", products)
        assert ot
        cli = await create_client(db, "Iftiqor 80")

        kb_unbound = client_detail_kb(cli, "norin_test_bot")
        unbound_texts = [btn.text for row in kb_unbound.inline_keyboard for btn in row]
        assert any("Mijoz guruhini ulash" in t for t in unbound_texts)
        assert not any("Guruh ulangan" in t for t in unbound_texts)

        cli = await bind_client_group(db, cli.id, -100777, "Iftiqor Guruh")
        kb_bound = client_detail_kb(cli, "norin_test_bot")
        bound_texts = [btn.text for row in kb_bound.inline_keyboard for btn in row]
        assert any("✅ Guruh ulangan: Iftiqor Guruh" in t for t in bound_texts)
        assert any("Guruhni almashtirish" in t for t in bound_texts)
        assert any("Guruhdan uzish" in t for t in bound_texts)

        sess = await get_or_create_open_session(db, report_date="2026-11-19")
        sale = await create_pending_sale(
            db, client_id=cli.id, items_spec=[{"product": ot, "weight_kg": 25.0}], session_id=sess.id
        )
        await confirm_sale(db, sale.id)
        await add_client_payment(db, cli.id, 1_000_000, payment_method="cash", session_id=sess.id)

        summary = await compute_session_summary(db, sess.id)
        debts = await list_all_client_debts(db)
        cli_debt = await compute_client_debt(db, cli.id)

        daily_xlsx = build_daily_norin_excel(summary, debts)
        client_xlsx = build_client_statement_excel(cli_debt)
        closed = await close_cash_session(db, sess.id, actual_counted_cash=1_000_000)
        hist_xlsx = build_history_excel([closed.session])

        assert len(daily_xlsx) > 2000
        assert len(client_xlsx) > 1500
        assert len(hist_xlsx) > 1500

        # Ensure client Excel statement has NO cost or profit columns/labels!
        wb = load_workbook(io.BytesIO(client_xlsx))
        ws = wb["Akt Sverka"]
        all_text = " ".join(
            str(cell.value) for row in ws.iter_rows() for cell in row if cell.value is not None
        ).lower()
        assert "tannarx" not in all_text
        assert "foyda" not in all_text
        assert "marja" not in all_text

    asyncio.run(_run_with_db(tmp_path, scenario))


def test_superadmin_reset_transactions_and_full_clear(tmp_path: Path):
    async def scenario(db: AsyncSession) -> None:
        products = await list_products(db)
        ot = match_product("ot", products)
        assert ot
        cli = await create_client(db, "Test Mijoz", opening_debt=300_000)
        await bind_client_group(db, cli.id, -100888, "Test Guruh")
        await set_client_product_price(db, cli.id, ot.id, 118_000)
        await add_authorized_user(db, 777111222, "Buyurtmachi", role="owner")
        await extend_subscription(db, days=30, amount=400_000, recorded_by=5649321700, note="Test")

        sess = await get_or_create_open_session(db, report_date="2026-11-19")
        sale = await create_pending_sale(
            db, client_id=cli.id, items_spec=[{"product": ot, "weight_kg": 10.0}], session_id=sess.id
        )
        await confirm_sale(db, sale.id)
        await add_client_payment(db, cli.id, 200_000, payment_method="cash", session_id=sess.id)
        await add_cash_transaction(db, 50_000, source_type="expense", note="Xamir", session_id=sess.id)

        # 1. Transaction-only reset preserves client, group, custom price, subscription & users
        tx_stats = await reset_test_transactions(db)
        assert tx_stats["sales"] == 1
        assert tx_stats["payments"] == 1
        assert tx_stats["cash_txs"] == 1
        assert tx_stats["sessions"] == 1

        clients_after_tx = await list_clients(db, active_only=True)
        assert len(clients_after_tx) == 1
        assert clients_after_tx[0].group_chat_id == -100888
        assert clients_after_tx[0].opening_debt == 0.0
        assert await resolve_sell_price(db, cli.id, ot) == 118_000
        assert (await compute_client_debt(db, cli.id)).current_debt == 0.0

        # 2. Full database reset wipes clients & prices, re-seeds products, keeps subscription & users
        sess2 = await get_or_create_open_session(db, report_date="2026-11-19")
        sale2 = await create_pending_sale(
            db, client_id=cli.id, items_spec=[{"product": ot, "weight_kg": 5.0}], session_id=sess2.id
        )
        await confirm_sale(db, sale2.id)

        full_stats = await reset_full_database(db)
        assert full_stats["sales"] == 1
        assert full_stats["clients"] == 1

        assert len(await list_clients(db, active_only=False)) == 0
        reseeded_prods = await list_products(db, active_only=True)
        assert len(reseeded_prods) == 2  # Default Ot & Mol Norin restored!
        assert (await evaluate_subscription_status(db)).is_allowed is True
        assert len(await list_subscription_payments(db)) == 1
        assert await is_user_authorized(db, 777111222) is True

    asyncio.run(_run_with_db(tmp_path, scenario))


def test_group_edit_and_payment_notice_renderers(tmp_path: Path):
    from bot.handlers.sales_norin import (
        render_payment_edit_group_notice,
        render_payment_group_receipt,
        render_sale_edit_group_notice,
    )

    async def scenario(db: AsyncSession) -> None:
        products = await list_products(db)
        ot = match_product("ot", products)
        assert ot
        cli = await create_client(db, "Iftiqor 80")
        sess = await get_or_create_open_session(db, report_date="2026-11-19")
        sale = await create_pending_sale(
            db, client_id=cli.id, items_spec=[{"product": ot, "weight_kg": 25.0}], session_id=sess.id
        )
        sale = await confirm_sale(db, sale.id)
        updated_sale = await update_sale_item(db, sale.items[0].id, weight_kg=20.0)
        debt = await compute_client_debt(db, cli.id)

        sale_notice = render_sale_edit_group_notice(
            updated_sale,
            debt.current_debt,
            change_line="⚖️ Norin: <s>25 kg</s> → <b>20 kg</b>\n💰 Summa: <s>2 875 000</s> → <b>2 300 000 so'm</b>",
        )
        assert "TAHRIRLANDI" in sale_notice
        assert "25 kg" in sale_notice and "20 kg" in sale_notice
        assert "2 300 000" in sale_notice
        assert "tannarx" not in sale_notice.lower()
        assert "foyda" not in sale_notice.lower()
        assert "1 800 000" not in sale_notice  # cost (20 * 90k) must not leak
        assert "500 000" not in sale_notice  # profit (20 * 25k) must not leak

        pay = await add_client_payment(db, cli.id, 1_000_000, payment_method="cash", session_id=sess.id)
        pay_edited = await update_client_payment(db, pay.id, new_amount=1_500_000)
        debt2 = await compute_client_debt(db, cli.id)
        assert debt2.current_debt == 800_000  # 2,300,000 - 1,500,000

        edited_receipt = render_payment_group_receipt(pay_edited, debt2.current_debt, tag="✏️ [TAHRIRLANDI]")
        assert "TAHRIRLANDI" in edited_receipt
        assert "+1 500 000 so'm" in edited_receipt
        assert "800 000 so'm" in edited_receipt

        pay_notice = render_payment_edit_group_notice(
            pay_edited, debt2.current_debt, old_amount=1_000_000, is_deleted=False
        )
        assert "TAHRIRLANDI" in pay_notice
        assert "+1 000 000" in pay_notice
        assert "+1 500 000" in pay_notice
        assert "800 000" in pay_notice

        pay_del = await delete_client_payment(db, pay.id)
        debt3 = await compute_client_debt(db, cli.id)
        assert debt3.current_debt == 2_300_000
        del_receipt = render_payment_group_receipt(pay_del, debt3.current_debt)
        del_notice = render_payment_edit_group_notice(pay_del, debt3.current_debt, is_deleted=True)
        assert "BEKOR QILINDI" in del_receipt
        assert "BEKOR QILINDI" in del_notice
        assert "2 300 000" in del_notice

    asyncio.run(_run_with_db(tmp_path, scenario))


def test_admin_id_name_parsing():
    from config import _parse_id_name_entries, _parse_int_list

    assert _parse_int_list("5649321700:Asad, 12345") == [5649321700, 12345]
    assert _parse_id_name_entries("5649321700:Asad, 12345, 5649321700:Dup") == [
        (5649321700, "Asad"),
        (12345, ""),
    ]


def test_multitenant_isolation_between_superadmin_and_other_clients(tmp_path: Path):
    """Verify Super Admin uses Test Filial #1 while added clients get isolated Tenant #2+."""

    async def _logic(db):
        # 1. Super Admin always routes to personal/test Filial #1
        assert await resolve_user_tenant_id(db, 5649321700) == 1
        sub1 = await evaluate_subscription_status(db, tenant_id=1)
        assert sub1.state.id == 1

        # Add data inside Tenant #1
        with tenant_scope(1):
            prods1 = await list_products(db)
            assert len(prods1) == 2
            cli1 = await create_client(db, "OKA GO'SHT", opening_debt=100_000)
            await bind_client_group(db, cli1.id, -100111111, "T1 Oka Guruh")
            sale1 = await create_pending_sale(
                db,
                client_id=cli1.id,
                items_spec=[{"product_id": prods1[0].id, "weight_kg": 10.0}],
            )
            await confirm_sale(db, sale1.id)
            await set_app_setting(db, "round_mode", "floor_1000")

        # 2. Onboarding another user via /superadmin opens Tenant #2 automatically
        user2 = await add_authorized_user(
            db,
            telegram_id=888000111,
            full_name="Sardor",
            role="owner",
            create_new_tenant=True,
            new_tenant_name="Chorsu Sexi",
        )
        assert user2.tenant_id == 2
        assert await resolve_user_tenant_id(db, 888000111) == 2

        # 3. Tenant #2 starts completely empty of clients/sales and has own default products
        with tenant_scope(2):
            assert await is_user_authorized(db, 888000111) is True
            assert await list_clients(db) == []
            prods2 = await list_products(db)
            assert len(prods2) == 2
            assert prods2[0].tenant_id == 2

            # Same client name allowed across separate tenants without unique collision
            cli2 = await create_client(db, "OKA GO'SHT", opening_debt=50_000)
            assert cli2.tenant_id == 2
            await bind_client_group(db, cli2.id, -100222222, "T2 Oka Guruh")
            sale2 = await create_pending_sale(
                db,
                client_id=cli2.id,
                items_spec=[{"product_id": prods2[0].id, "weight_kg": 5.0}],
            )
            await confirm_sale(db, sale2.id)
            await set_app_setting(db, "round_mode", "nearest_1000")

        # Bound Telegram groups route directly to the owning tenant
        assert await resolve_user_tenant_id(db, None, -100111111, "supergroup") == 1
        assert await resolve_user_tenant_id(db, None, -100222222, "supergroup") == 2

        # Tenant #2 user is NOT authorized inside Tenant #1 scope
        with tenant_scope(1):
            assert await is_user_authorized(db, 888000111) is False
            assert await get_app_setting(db, "round_mode") == "floor_1000"
            assert len(await list_recent_sales(db)) == 1
            assert len(await list_clients(db)) == 1

        # Per-tenant subscription suspension & full /clear isolation
        await update_subscription_settings(db, is_suspended=True, tenant_id=2)
        assert (await evaluate_subscription_status(db, tenant_id=2)).is_allowed is False
        assert (await evaluate_subscription_status(db, tenant_id=1)).is_allowed is True

        await reset_full_database(db, tenant_id=2)
        with tenant_scope(2):
            assert await list_clients(db) == []
            assert await list_recent_sales(db) == []
            assert len(await list_products(db)) == 2
        with tenant_scope(1):
            assert len(await list_clients(db)) == 1
            assert len(await list_recent_sales(db)) == 1

        tenants = await list_tenants(db)
        assert [t.id for t in tenants] == [1, 2]

    asyncio.run(_run_with_db(tmp_path, _logic))


def test_app_imports_and_router_assembly():
    import main
    from bot.handlers import get_main_router
    from bot.middlewares import SubscriptionMiddleware

    router = get_main_router()
    assert len(router.sub_routers) == 4
    assert hasattr(main, "run_bot")
    assert hasattr(main, "subscription_watcher")
    assert SubscriptionMiddleware is not None


def test_parse_uzbek_amount_yarim_and_variants():
    from services.gemini_ai import parse_uzbek_amount

    assert parse_uzbek_amount("3 yarim million") == 3_500_000
    assert parse_uzbek_amount("yarim mln") == 500_000
    assert parse_uzbek_amount("1 yarim ming") == 1_500
    assert parse_uzbek_amount("450 000") == 450_000


def test_zero_token_text_routing(monkeypatch, tmp_path: Path):
    """Ensure free text & captions NEVER invoke Gemini (_call_gemini)."""
    import services.gemini_ai as gai

    async def _fail_gemini(*args, **kwargs):
        raise AssertionError("Gemini MUST NOT be called for text/caption input!")

    monkeypatch.setattr(gai, "_call_gemini", _fail_gemini)

    async def _logic(db):
        prods = await list_products(db)
        c = await create_client(db, "Iftiqor")
        res = await gai.parse_norin_voice_or_text(
            prods, [c], text="Iftiqor ot 25 yarim kg"
        )
        assert res["intent"] == "sale"
        assert res["client_hint"] == "Iftiqor"
        assert abs(res["items"][0]["weight_kg"] - 25.5) < 0.01

        chat_res = await gai.parse_norin_voice_or_text(prods, [c], text="salom qalesiz")
        assert chat_res["intent"] == "unknown"

    asyncio.run(_run_with_db(tmp_path, _logic))


def test_cash_tx_isolation_expense_category_ai_usage_and_tenant_delete(tmp_path: Path):
    """Verify expense auto-category, get_cash_transaction isolation, AI logs, raw settings & delete_tenant."""

    async def _logic(db):
        user2 = await add_authorized_user(
            db,
            telegram_id=999111222,
            full_name="Buxoro Admin",
            role="owner",
            create_new_tenant=True,
            new_tenant_name="Buxoro Filiali",
        )
        assert user2.tenant_id == 2
        assert infer_expense_category("qo'y go'shti oldik") == "Go'sht"

        with tenant_scope(1):
            tx = await add_cash_transaction(
                db, amount=300_000, source_type="expense", note="qo'y go'shti oldik"
            )
            assert tx.category == "Go'sht"
            assert await get_cash_transaction(db, tx.id) is not None

        # Cross-tenant cash_tx protection
        with tenant_scope(2):
            assert await get_cash_transaction(db, tx.id) is None

        # AI usage logs isolated per tenant
        await log_ai_usage(db, "image", "gemini-2.5-flash", 120, 40, 160, tenant_id=1)
        await log_ai_usage(db, "audio", "gemini-2.5-flash-lite", 50, 20, 70, tenant_id=2)
        u1 = await get_ai_usage_summary(db, days=30, tenant_id=1)
        u2 = await get_ai_usage_summary(db, days=30, tenant_id=2)
        assert u1["image_calls"] == 1 and u1["audio_calls"] == 0 and u1["total_tokens"] == 160
        assert u2["image_calls"] == 0 and u2["audio_calls"] == 1 and u2["total_tokens"] == 70

        # Raw SA app setting persistence
        await set_raw_app_setting(db, "sa_sel:5649321700", "2")
        assert await get_raw_app_setting(db, "sa_sel:5649321700") == "2"

        # Tenant #1 cannot be deleted; Tenant #2 can be deleted cleanly
        assert await delete_tenant(db, 1) is False
        assert await delete_tenant(db, 2) is True
        assert [t.id for t in await list_tenants(db)] == [1]

    asyncio.run(_run_with_db(tmp_path, _logic))


def test_excel_exports_formulas_full_akt_sverka_and_no_cost_leak(tmp_path: Path):
    """Verify full untruncated Akt Sverka (>100 rows), formulas, no cost leaks, and 4-sheet period Excel."""
    from services.excel_export import (
        build_client_statement_excel,
        build_daily_norin_excel,
        build_period_excel,
    )

    async def _logic(db):
        prods = await list_products(db)
        c = await create_client(db, "Mega Bozor", opening_debt=200_000)
        sale = await create_pending_sale(
            db,
            client_id=c.id,
            items_spec=[{"product_id": prods[0].id, "weight_kg": 10.0}],
        )
        await confirm_sale(db, sale.id)
        await add_cash_transaction(
            db, amount=150_000, source_type="expense", note="xamir oldik", category="Xamir"
        )
        # Add 105 payments -> total events = 106 (> old 100 truncation cap)
        for idx in range(105):
            await add_client_payment(
                db, client_id=c.id, amount=1_000, payment_method="cash", note=f"p{idx}"
            )

        summary = await compute_session_summary(db)
        debts = await list_all_client_debts(db)
        daily_bytes = build_daily_norin_excel(summary, debts, tenant_name="Asad Test Sexi")
        wb_daily = load_workbook(io.BytesIO(daily_bytes), data_only=False)
        assert "Kunlik Hisobot" in wb_daily.sheetnames
        assert "Pul Oldi-Berdi" in wb_daily.sheetnames
        daily_formulas = [
            str(cell.value)
            for ws in wb_daily.worksheets
            for row in ws.iter_rows()
            for cell in row
            if isinstance(cell.value, str) and cell.value.startswith("=")
        ]
        assert any("=SUM(" in f for f in daily_formulas)

        # Full Akt Sverka check
        debt_full = await compute_client_debt(db, c.id, history_limit=None)
        assert len(debt_full.recent_sales) == 1
        assert len(debt_full.recent_payments) == 105
        stmt_bytes = build_client_statement_excel(debt_full, tenant_name="Asad Test Sexi")
        wb_stmt = load_workbook(io.BytesIO(stmt_bytes), data_only=False)
        assert "Akt Sverka" in wb_stmt.sheetnames
        all_stmt_text = " ".join(
            str(cell.value or "")
            for ws in wb_stmt.worksheets
            for row in ws.iter_rows()
            for cell in row
        ).lower()
        assert "tannarx" not in all_stmt_text
        assert "foyda" not in all_stmt_text
        assert "marja" not in all_stmt_text
        sverka_ws = wb_stmt["Akt Sverka"]
        assert sverka_ws.max_row >= 115
        stmt_formulas = [
            str(cell.value)
            for row in sverka_ws.iter_rows()
            for cell in row
            if isinstance(cell.value, str) and cell.value.startswith("=")
        ]
        assert any("=H" in f and "-" in f for f in stmt_formulas)

        # 4-sheet Period Excel check
        pdata = await get_period_excel_data(db, days=30)
        period_bytes = build_period_excel(pdata)
        wb_period = load_workbook(io.BytesIO(period_bytes), data_only=False)
        assert len(wb_period.sheetnames) == 4

    asyncio.run(_run_with_db(tmp_path, _logic))


def test_caption_client_override_postavshik_and_weight_safety(tmp_path: Path):
    """Verify photo caption overrides wrong nakladnoy postavshik without false-matching product tokens."""
    from services.gemini_ai import extract_caption_client_override

    async def _logic(db):
        prods = await list_products(db)
        c_ift = await create_client(db, "Iftiqor", aliases="iftiqor 80")
        c_oka = await create_client(db, "OKA GO'SHT", aliases="oka gosht")
        await create_client(db, "Otabek")

        # Existing client in caption -> resolves exact Client
        cli, hint = extract_caption_client_override("Iftiqor", prods, [c_ift, c_oka])
        assert cli is not None and cli.id == c_ift.id and hint == "Iftiqor"

        cli2, hint2 = extract_caption_client_override("Postavshik: oka gosht", prods, [c_ift, c_oka])
        assert cli2 is not None and cli2.id == c_oka.id and hint2 == c_oka.name

        # Product/weight-only caption MUST NOT false-match client "Otabek" via "ot"
        all_clis = await list_clients(db)
        cli_w, hint_w = extract_caption_client_override("ot 25 kg", prods, all_clis)
        assert cli_w is None and hint_w is None

        cli_m, hint_m = extract_caption_client_override("mol go'shti 12 yarim kg", prods, all_clis)
        assert cli_m is None and hint_m is None

        # Explicit new postavshik name returns (None, clean_name) for 1-tap creation
        cli_new, hint_new = extract_caption_client_override("Postavshik: Sardor Bozor", prods, all_clis)
        assert cli_new is None and hint_new == "Sardor Bozor"

    asyncio.run(_run_with_db(tmp_path, _logic))


def test_superadmin_user_reassign_settings_and_keyboards(tmp_path: Path):
    """Verify tenant settings updates, user reassignment/stats, and SA picker/menu keyboards."""
    from bot.keyboards import (
        pick_client_for_sale_kb,
        superadmin_pick_user_reply_kb,
        superadmin_quick_menu_kb,
        superadmin_tenant_settings_kb,
    )

    async def _logic(db):
        u = await add_authorized_user(
            db,
            telegram_id=777000111,
            full_name="Sardor",
            role="owner",
            create_new_tenant=True,
            new_tenant_name="Chorsu Sexi",
        )
        assert u.tenant_id == 2

        sub2 = await update_subscription_settings(
            db, plan_name="VIP", grace_days=5, tenant_id=2
        )
        assert sub2.plan_name == "VIP" and sub2.grace_days == 5

        found = await get_authorized_user(db, 777000111)
        assert found is not None and found.tenant_id == 2

        with tenant_scope(2):
            cli = await create_client(db, "Bozor-1")
            await bind_client_group(db, cli.id, -100777888, "Bozor Group")
            prods = await list_products(db)
            sale = await create_pending_sale(
                db, client_id=cli.id, items_spec=[{"product_id": prods[0].id, "weight_kg": 4.0}]
            )
            await confirm_sale(db, sale.id)

        stats = await get_tenant_overview_stats(db, 2)
        assert stats["users"] == 1
        assert stats["clients"] == 1
        assert stats["groups"] == 1
        assert stats["sales"] == 1

        moved = await reassign_authorized_user(db, 777000111, 1, role="staff")
        assert moved is not None and moved.tenant_id == 1 and moved.role == "staff"

        pick_kb = superadmin_pick_user_reply_kb(request_id=101)
        req = pick_kb.keyboard[0][0].request_users
        assert req is not None and req.request_id == 101 and req.user_is_bot is False and req.request_name is True

        q_kb = superadmin_quick_menu_kb(2, 2)
        assert any(btn.callback_data == "sa:settings" for row in q_kb.inline_keyboard for btn in row)

        ts_kb = superadmin_tenant_settings_kb(2, True, False, "nearest_1000")
        assert any(btn.callback_data == "sa:edit_plan" for row in ts_kb.inline_keyboard for btn in row)

        sale_kb = pick_client_for_sale_kb(99, [cli], suggested_name="Sardor Bozor")
        assert sale_kb.inline_keyboard[0][0].callback_data == "sale:newcli_cap:99"

    asyncio.run(_run_with_db(tmp_path, _logic))


def test_ui_keyboards_safe_cancel_no_duplicate_active_period_and_icons(tmp_path: Path):
    """Verify UI polish: safe back_cb on pick_client, no duplicate pick_cli, active period pill, expense icons."""
    from bot.keyboards import (
        confirmed_sale_edit_kb,
        expense_category_kb,
        period_report_kb,
        pick_client_for_sale_kb,
    )

    async def _logic(db):
        cli = await create_client(db, "Bozor-NoGrp")
        prods = await list_products(db)
        sale = await create_pending_sale(
            db, client_id=cli.id, items_spec=[{"product_id": prods[0].id, "weight_kg": 5.0}]
        )
        await confirm_sale(db, sale.id)
        sale_loaded = await get_or_create_open_session(db)
        assert sale_loaded is not None

        # P0-1: back_cb renders 'Orqaga' instead of dangerous sale:cancel
        back_kb = pick_client_for_sale_kb(sale.id, [cli], back_cb=f"sale:back_card:{sale.id}")
        flat_cbs = [b.callback_data for row in back_kb.inline_keyboard for b in row if b.callback_data]
        assert f"sale:back_card:{sale.id}" in flat_cbs
        assert f"sale:cancel:{sale.id}" not in flat_cbs

        # P0-2: confirmed_sale_edit_kb renders sale:pick_cli only ONCE even without group
        from database.crud import get_sale

        full_sale = await get_sale(db, sale.id)
        assert full_sale is not None
        edit_kb = confirmed_sale_edit_kb(full_sale)
        edit_cbs = [b.callback_data for row in edit_kb.inline_keyboard for b in row if b.callback_data]
        assert edit_cbs.count(f"sale:pick_cli:{sale.id}") == 1

        # P1-4: active period indicator
        p7 = period_report_kb(days=7)
        assert p7.inline_keyboard[0][0].text == "• 7 kun •"
        p_cur = period_report_kb(period_key="cur")
        assert p_cur.inline_keyboard[0][1].text == "• Shu oy •"

        # P2-5: expense icons preserve exact callback_data
        exp_kb = expense_category_kb()
        exp_btns = [b for row in exp_kb.inline_keyboard for b in row]
        assert any(b.text == "🥩 Go'sht" and b.callback_data == "wal:exp_cat:Go'sht" for b in exp_btns)

    asyncio.run(_run_with_db(tmp_path, _logic))


def test_performance_sql_aggregations_auth_cache_and_one_time_menu_ux(tmp_path: Path):
    """Verify SQL debt/kassa aggregations match exact sums, epoch invalidation works, and Reply/Inline UX switches cleanly."""
    from bot.keyboards import (
        daily_report_kb,
        main_menu_keyboard,
        settings_menu_kb,
        superadmin_quick_menu_kb,
        wallet_expense_kb,
    )
    from database.crud import (
        bump_auth_cache_epoch,
        get_auth_cache_epoch,
        get_outstanding_kassa_debt,
        get_total_all_clients_debt,
    )
    from services.excel_export import build_daily_norin_excel

    # Collapsible ReplyKeyboard + menu:home escape buttons on top-level inline panels
    assert main_menu_keyboard().one_time_keyboard is True
    for kb in (
        settings_menu_kb(is_super_admin=True),
        daily_report_kb(1),
        wallet_expense_kb(),
        superadmin_quick_menu_kb(1, 2),
    ):
        cbs = [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]
        assert "menu:home" in cbs

    ep_before = get_auth_cache_epoch()
    ep_after = bump_auth_cache_epoch()
    assert ep_after == ep_before + 1

    async def _logic(db):
        prods = await list_products(db)
        c1 = await create_client(db, "Bozor-1", opening_debt=100_000)
        c2 = await create_client(db, "Bozor-2", opening_debt=50_000)
        s1 = await create_pending_sale(
            db, client_id=c1.id, items_spec=[{"product_id": prods[0].id, "weight_kg": 10.0}]
        )
        await confirm_sale(db, s1.id)
        pay1 = await add_client_payment(db, c1.id, 300_000, payment_method="cash", note="test")
        await add_cash_transaction(db, 500_000, source_type="kassa_debt", note="qarz")
        await add_cash_transaction(db, 150_000, source_type="kassa_repay", note="qaytar")

        # SQL aggregation accuracy check
        debts = await list_all_client_debts(db)
        d1_summary = next(d for d in debts if d.client.id == c1.id)
        d1_direct = await compute_client_debt(db, c1.id, history_limit=5)
        assert d1_summary.current_debt == d1_direct.current_debt
        assert d1_summary.total_sales == d1_direct.total_sales
        assert d1_summary.total_paid == d1_direct.total_paid
        assert d1_summary.last_payment_at is not None
        assert d1_direct.last_payment_at is not None

        total_all = await get_total_all_clients_debt(db)
        assert abs(total_all - sum(d.current_debt for d in debts)) < 0.01
        assert abs((await get_outstanding_kassa_debt(db)) - 350_000.0) < 0.01

        # Verify Excel Mijozlar Qarzi sheet prints the last payment date using last_payment_at
        sess_sum = await compute_session_summary(db)
        daily_bytes = build_daily_norin_excel(sess_sum, debts, tenant_name="Test Sex")
        wb = load_workbook(io.BytesIO(daily_bytes))
        ws_debts = wb["Mijozlar Qarzi"]
        debt_sheet_vals = " ".join(
            str(c.value or "") for row in ws_debts.iter_rows() for c in row
        )
        assert pay1.created_at is not None
        assert "-" in debt_sheet_vals

    asyncio.run(_run_with_db(tmp_path, _logic))

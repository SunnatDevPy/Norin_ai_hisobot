"""Reply and inline keyboards for Norin AI Hisobot Bot."""

from __future__ import annotations

from typing import Dict, Optional, Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from database.crud import ClientDebtSummary
from database.models import (
    AuthorizedUser,
    CashTransaction,
    Client,
    ClientPayment,
    DailyCashSession,
    Product,
    Sale,
    SubscriptionState,
)
from services.gemini_ai import format_kg, format_uzs


BTN_ADD_SALE = "🥩 Sotuv qo'shish"
BTN_CLIENT_PAY = "💵 Pul oldim (Mijoz)"
BTN_DEBTS = "💳 Qarzlar"
BTN_DAILY_REPORT = "📊 Kunlik hisobot"
BTN_EXPENSE_KASSA = "➖ Xarajat / Kassa"
BTN_EDIT = "✏️ Tahrirlash"
BTN_CLOSE_DAY = "🏁 Kunni yakunlash"
BTN_SETTINGS = "⚙️ Sozlamalar"

GROUP_ADMIN_RIGHTS = "change_info+delete_messages+invite_users+pin_messages+manage_chat"


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Main persistent bottom menu for Norin wholesale management."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_ADD_SALE), KeyboardButton(text=BTN_CLIENT_PAY)],
            [KeyboardButton(text=BTN_DEBTS), KeyboardButton(text=BTN_DAILY_REPORT)],
            [KeyboardButton(text=BTN_EXPENSE_KASSA), KeyboardButton(text=BTN_EDIT)],
            [KeyboardButton(text=BTN_CLOSE_DAY), KeyboardButton(text=BTN_SETTINGS)],
        ],
        resize_keyboard=True,
    )


def cancel_reply_keyboard() -> ReplyKeyboardMarkup:
    """Simple cancel keyboard during FSM input prompts."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True,
    )


# ---------------------------------------------------------------------------
# Deep-link builders for 1-click Telegram Group binding
# ---------------------------------------------------------------------------


def build_client_group_deeplink(bot_username: str, client_id: int) -> str:
    """Build Telegram deep-link to add the bot as admin and bind group to a specific client."""
    clean = bot_username.lstrip("@") or "norin_ai_bot"
    return f"https://t.me/{clean}?startgroup=bind_client_{client_id}&admin={GROUP_ADMIN_RIGHTS}"


def build_report_group_deeplink(bot_username: str) -> str:
    """Build Telegram deep-link to add the bot as admin and bind the owner report group."""
    clean = bot_username.lstrip("@") or "norin_ai_bot"
    return f"https://t.me/{clean}?startgroup=bind_report&admin={GROUP_ADMIN_RIGHTS}"


# ---------------------------------------------------------------------------
# Sales & Receipt Keyboards
# ---------------------------------------------------------------------------


def pick_client_for_sale_kb(
    sale_id: int, clients: Sequence[Client], prefix: str = "sale:setcli"
) -> InlineKeyboardMarkup:
    """Inline list of clients to bind to a pending/confirmed sale."""
    rows = []
    for c in clients:
        grp = " 🔗" if c.group_chat_id else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🏪 {c.name}{grp}",
                    callback_data=f"{prefix}:{sale_id}:{c.id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="➕ Yangi mijoz qo'shish",
                callback_data="cli:add",
            ),
            InlineKeyboardButton(
                text="❌ Bekor qilish",
                callback_data=f"sale:cancel:{sale_id}",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sale_confirm_kb(sale: Sale) -> InlineKeyboardMarkup:
    """Confirmation inline keyboard for a pending Norin sale."""
    has_group = bool(sale.client and sale.client.group_chat_id)
    confirm_lbl = (
        "✅ Tasdiqlash (Mijoz guruhiga yuborish)"
        if has_group
        else "✅ Tasdiqlash (Bazaga saqlash)"
    )
    rows = [
        [
            InlineKeyboardButton(
                text=confirm_lbl,
                callback_data=f"sale:confirm:{sale.id}",
            )
        ]
    ]
    if has_group:
        rows.append(
            [
                InlineKeyboardButton(
                    text="⏭ Guruhsiz saqlash (Faqat baza)",
                    callback_data=f"sale:save_only:{sale.id}",
                )
            ]
        )

    edit_row = [
        InlineKeyboardButton(
            text="🏪 Mijoz",
            callback_data=f"sale:pick_cli:{sale.id}",
        )
    ]
    if sale.items:
        first_item = sale.items[0]
        edit_row.append(
            InlineKeyboardButton(
                text="⚖️ Kg tahrir",
                callback_data=f"sale:edit_w:{first_item.id}",
            )
        )
        edit_row.append(
            InlineKeyboardButton(
                text="💰 Narx",
                callback_data=f"sale:edit_p:{first_item.id}",
            )
        )
    rows.append(edit_row)
    rows.append(
        [
            InlineKeyboardButton(
                text="❌ Bekor qilish",
                callback_data=f"sale:cancel:{sale.id}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def auto_confirmed_sale_kb(
    sale: Sale, sent_to_group: bool = True
) -> InlineKeyboardMarkup:
    """Quick edit/undo controls shown after instant auto-confirmation or group auto-calc."""
    first_item = sale.items[0] if sale.items else None
    row1 = [
        InlineKeyboardButton(
            text="🏪 Mijoz",
            callback_data=f"sale:pick_cli:{sale.id}",
        )
    ]
    if first_item:
        row1.append(
            InlineKeyboardButton(
                text="⚖️ Kg tahrir",
                callback_data=f"sale:edit_w:{first_item.id}",
            )
        )
        row1.append(
            InlineKeyboardButton(
                text="💰 Narx",
                callback_data=f"sale:edit_p:{first_item.id}",
            )
        )

    has_client_group = bool(sale.client and sale.client.group_chat_id)
    row2 = []
    if sent_to_group:
        row2.append(
            InlineKeyboardButton(
                text="🙈 Guruhdan olish",
                callback_data=f"sale:unpost_group:{sale.id}",
            )
        )
    elif has_client_group:
        row2.append(
            InlineKeyboardButton(
                text="📤 Guruhga yuborish",
                callback_data=f"sale:repost_group:{sale.id}",
            )
        )
    row2.append(
        InlineKeyboardButton(
            text="🗑 O'chirish",
            callback_data=f"sale:delete_conf:{sale.id}",
        )
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            row1,
            row2,
            [InlineKeyboardButton(text="✅ Tayyor", callback_data=f"sale:done:{sale.id}")],
        ]
    )


def confirmed_sale_edit_kb(sale: Sale) -> InlineKeyboardMarkup:
    """Full edit controls for an already confirmed Sale (supports multi-item sales)."""
    rows = []
    for item in sale.items:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"⚖️ {item.product_name[:14]}: {format_kg(item.weight_kg)} kg",
                    callback_data=f"sale:edit_w:{item.id}",
                ),
                InlineKeyboardButton(
                    text=f"💰 {format_uzs(item.unit_sell_price)}/kg",
                    callback_data=f"sale:edit_p:{item.id}",
                ),
            ]
        )

    in_group = bool(sale.group_chat_id and sale.group_message_id)
    has_client_group = bool(sale.client and sale.client.group_chat_id)
    grp_btn = (
        InlineKeyboardButton(
            text="🙈 Guruhdan olish",
            callback_data=f"sale:unpost_group:{sale.id}",
        )
        if in_group
        else (
            InlineKeyboardButton(
                text="📤 Guruhga yuborish",
                callback_data=f"sale:repost_group:{sale.id}",
            )
            if has_client_group
            else InlineKeyboardButton(
                text="🏪 Mijoz tanlash",
                callback_data=f"sale:pick_cli:{sale.id}",
            )
        )
    )
    rows.append(
        [
            InlineKeyboardButton(text="🏪 Mijozni almashtirish", callback_data=f"sale:pick_cli:{sale.id}"),
        ]
    )
    rows.append(
        [
            grp_btn,
            InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"sale:delete_conf:{sale.id}"),
        ]
    )
    rows.append([InlineKeyboardButton(text="⬅️ Ro'yxatga qaytish", callback_data="edit_menu:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Client Payments & Cash Edit Keyboards
# ---------------------------------------------------------------------------


def pick_client_for_payment_kb(clients: Sequence[Client]) -> InlineKeyboardMarkup:
    """Select client who paid money."""
    rows = []
    for c in clients:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🏪 {c.name}",
                    callback_data=f"pay:cli:{c.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="🔙 Yopish", callback_data="menu:dismiss")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_method_kb(client_id: int) -> InlineKeyboardMarkup:
    """Choose payment method (Naqd / Karta / Perechesleniye)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💵 Naqd pul", callback_data=f"pay:meth:{client_id}:cash"),
                InlineKeyboardButton(text="💳 Karta / Click", callback_data=f"pay:meth:{client_id}:card"),
            ],
            [
                InlineKeyboardButton(
                    text="🏦 Perechesleniye",
                    callback_data=f"pay:meth:{client_id}:transfer",
                )
            ],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="menu:dismiss")],
        ]
    )


def payment_after_record_kb(payment_id: int, has_group: bool) -> InlineKeyboardMarkup:
    """Quick option to send payment receipt to client group."""
    rows = []
    if has_group:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📤 Mijoz guruhiga kvitansiya yuborish",
                    callback_data=f"pay:post_grp:{payment_id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="✅ Tayyor", callback_data="menu:dismiss")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_items_list_kb(
    sales: Sequence[Sale],
    payments: Sequence[ClientPayment],
    cash_txs: Sequence[CashTransaction],
) -> InlineKeyboardMarkup:
    """Inline list of confirmed sales, client payments, and cash/expense transactions."""
    buttons = []
    for s in sales:
        cname = s.client.name[:16] if s.client else "Noma'lum"
        where = "📤" if s.group_message_id else "💾"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{where} {cname} | {format_kg(s.total_weight_kg)} kg — {format_uzs(s.total_amount)}",
                    callback_data=f"sale_view:{s.id}",
                )
            ]
        )

    m_icons = {"cash": "💵", "card": "💳", "transfer": "🏦"}
    for p in payments:
        cname = p.client.name[:16] if p.client else f"Mijoz #{p.client_id}"
        ico = m_icons.get(p.payment_method, "💵")
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{ico} To'lov {cname}: +{format_uzs(p.amount)}",
                    callback_data=f"pay_view:{p.id}",
                )
            ]
        )

    type_icons = {
        "main_in": "➕ Kirim",
        "expense": "➖ Xarajat",
        "kassa_debt": "🏦 Kassa qarz",
        "kassa_repay": "↩️ Qaytarish",
    }
    for tx in cash_txs:
        lbl = type_icons.get(tx.source_type, "💵")
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{lbl}: {format_uzs(tx.amount)}",
                    callback_data=f"cash_view:{tx.id}",
                )
            ]
        )

    buttons.append([InlineKeyboardButton(text="🔙 Yopish", callback_data="menu:dismiss")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def payment_edit_kb(payment_id: int) -> InlineKeyboardMarkup:
    """Edit/delete options for a ClientPayment."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💰 Summani o'zgartirish", callback_data=f"pay:edit_amt:{payment_id}"),
                InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"pay:delete:{payment_id}"),
            ],
            [InlineKeyboardButton(text="⬅️ Ro'yxatga qaytish", callback_data="edit_menu:open")],
        ]
    )


def cash_tx_edit_kb(tx_id: int) -> InlineKeyboardMarkup:
    """Edit/delete options for an expense / kassa / cash-in transaction."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💰 Summani o'zgartirish", callback_data=f"cash:edit_amt:{tx_id}"),
                InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"cash:delete:{tx_id}"),
            ],
            [InlineKeyboardButton(text="⬅️ Ro'yxatga qaytish", callback_data="edit_menu:open")],
        ]
    )


# ---------------------------------------------------------------------------
# Reports, Expenses, Kassa & Day Close Keyboards
# ---------------------------------------------------------------------------


def daily_report_kb(session_id: int) -> InlineKeyboardMarkup:
    """Actions under Daily Profit Report."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📆 30 kunlik hisobot", callback_data="rep:period:30"),
                InlineKeyboardButton(text="📥 Excel yuklash", callback_data=f"export:daily:{session_id}"),
            ],
            [
                InlineKeyboardButton(text="✏️ Tahrirlash", callback_data="edit_menu:open"),
                InlineKeyboardButton(text="📜 Arxiv / History", callback_data="set:history"),
            ],
        ]
    )


def period_report_kb() -> InlineKeyboardMarkup:
    """Actions under 30-day period report."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Bugungi hisobot", callback_data="rep:today"),
                InlineKeyboardButton(text="📥 Tarix Excel", callback_data="export:history"),
            ]
        ]
    )


def wallet_expense_kb() -> InlineKeyboardMarkup:
    """Actions for expenses, owner cash-in, and kassa debt."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➖ Xarajat yozish (Go'sht/Xamir)", callback_data="wal:expense"),
                InlineKeyboardButton(text="➕ Asosiy pul kiritish", callback_data="wal:cash_in"),
            ],
            [
                InlineKeyboardButton(text="🏦 Kassadan qarz olish", callback_data="wal:kassa_borrow"),
                InlineKeyboardButton(text="↩️ Kassaga qaytarish", callback_data="wal:kassa_repay"),
            ],
        ]
    )


def close_day_confirm_kb(session_id: int, counted: float) -> InlineKeyboardMarkup:
    """Confirmation keyboard after user enters counted physical cash."""
    counted_int = round(counted)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Kunni yopish va History'ga saqlash",
                    callback_data=f"close_day:confirm:{session_id}:{counted_int}",
                )
            ],
            [
                InlineKeyboardButton(text="🔄 Qayta sanash", callback_data="close_day:recount"),
                InlineKeyboardButton(text="✏️ Xatoni to'g'irlash", callback_data="edit_menu:open"),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Products, Clients, Debts & Group Binding Keyboards
# ---------------------------------------------------------------------------


def settings_menu_kb(is_super_admin: bool = False) -> InlineKeyboardMarkup:
    """Settings & History inline menu."""
    rows = [
        [
            InlineKeyboardButton(text="🥩 Mahsulotlar & Tannarx", callback_data="set:products"),
            InlineKeyboardButton(text="🏪 Mijozlar & Narx/Guruh", callback_data="set:clients"),
        ],
        [
            InlineKeyboardButton(text="📊 Rahbariyat hisobot guruhi", callback_data="set:report_group"),
            InlineKeyboardButton(text="⚡ Tez rejim & Yaxlitlash", callback_data="set:ai_prefs"),
        ],
        [
            InlineKeyboardButton(text="📜 Arxiv / History", callback_data="set:history"),
            InlineKeyboardButton(text="📥 Tarixni Excel yuklash", callback_data="export:history"),
        ],
        [
            InlineKeyboardButton(text="💎 Obuna holati", callback_data="sub:status"),
        ],
    ]
    if is_super_admin:
        rows.append(
            [InlineKeyboardButton(text="👑 Super Admin (Obuna boshqaruvi)", callback_data="sa:menu")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ai_prefs_kb(auto_confirm: bool, group_auto_calc: bool, round_mode: str) -> InlineKeyboardMarkup:
    """Toggle auto-confirm, group auto-calculation, and UZS rounding mode."""
    auto_lbl = (
        "⚡ Tez rejim (DM avto-tasdiq): ✅ YOQILGAN"
        if auto_confirm
        else "⚡ Tez rejim (DM avto-tasdiq): ❌ O'CHIQ"
    )
    grp_lbl = (
        "🤖 Guruhda avto-hisob: ✅ YOQILGAN"
        if group_auto_calc
        else "🤖 Guruhda avto-hisob: ❌ O'CHIQ"
    )
    r_near = "✅ Yaqin 1 000 ga" if round_mode == "nearest_1000" else "Yaqin 1 000 ga"
    r_floor = "✅ 1 000 ga pastga" if round_mode == "floor_1000" else "1 000 ga pastga"
    r_none = "✅ Yaxlitlamaslik (aniq)" if round_mode == "none" else "Yaxlitlamaslik (aniq)"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=auto_lbl, callback_data="pref:toggle_auto")],
            [InlineKeyboardButton(text=grp_lbl, callback_data="pref:toggle_grp")],
            [
                InlineKeyboardButton(text=r_near, callback_data="pref:round:nearest_1000"),
                InlineKeyboardButton(text=r_floor, callback_data="pref:round:floor_1000"),
            ],
            [InlineKeyboardButton(text=r_none, callback_data="pref:round:none")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="set:back")],
        ]
    )


def products_list_kb(products: Sequence[Product]) -> InlineKeyboardMarkup:
    """Product catalog list keyboard."""
    rows = []
    for p in products:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🥩 {p.name} (Tan: {format_uzs(p.cost_price)} | Sot: {format_uzs(p.default_sell_price)})",
                    callback_data=f"prd:view:{p.id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="➕ Yangi mahsulot", callback_data="prd:add"),
            InlineKeyboardButton(text="⬅️ Orqaga", callback_data="set:back"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_detail_kb(product_id: int) -> InlineKeyboardMarkup:
    """Detail actions for a product."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📉 Tannarxni o'zgartirish", callback_data=f"prd:edit_cost:{product_id}"),
                InlineKeyboardButton(text="💰 Standart sotuv narxi", callback_data=f"prd:edit_sell:{product_id}"),
            ],
            [
                InlineKeyboardButton(text="🔗 Sinonim qo'shish", callback_data=f"prd:alias:{product_id}"),
                InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"prd:del:{product_id}"),
            ],
            [InlineKeyboardButton(text="⬅️ Mahsulotlarga", callback_data="set:products")],
        ]
    )


def clients_list_kb(clients: Sequence[Client]) -> InlineKeyboardMarkup:
    """Clients directory list keyboard."""
    rows = []
    for c in clients:
        grp = f"🔗 {c.group_title[:14]}" if c.group_chat_id else "⚠️ Guruh yo'q"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🏪 {c.name} [{grp}]",
                    callback_data=f"cli:view:{c.id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="➕ Yangi mijoz", callback_data="cli:add"),
            InlineKeyboardButton(text="⬅️ Orqaga", callback_data="set:back"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_detail_kb(
    client: Client, bot_username: str = "norin_ai_bot"
) -> InlineKeyboardMarkup:
    """Detail actions for a client including custom pricing, 1-click group bind, and sverka."""
    rows = [
        [
            InlineKeyboardButton(text="💰 Individual narxlar", callback_data=f"cli:prices:{client.id}"),
            InlineKeyboardButton(text="💵 Pul qabul qilish", callback_data=f"pay:cli:{client.id}"),
        ],
    ]
    if client.group_chat_id:
        grp_lbl = (client.group_title or "Guruh")[:22]
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"✅ Guruh ulangan: {grp_lbl}",
                    callback_data=f"cli:grp_ping:{client.id}",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔄 Guruhni almashtirish",
                    url=build_client_group_deeplink(bot_username, client.id),
                ),
                InlineKeyboardButton(
                    text="🔓 Guruhdan uzish",
                    callback_data=f"cli:unbind:{client.id}",
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(text="🆔 ID o'zgartirish", callback_data=f"cli:set_gid:{client.id}"),
                InlineKeyboardButton(text="🔗 Sinonim qo'shish", callback_data=f"cli:alias:{client.id}"),
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="➕ Mijoz guruhini ulash (Admin)",
                    url=build_client_group_deeplink(bot_username, client.id),
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(text="🆔 Guruh ID kiritish", callback_data=f"cli:set_gid:{client.id}"),
                InlineKeyboardButton(text="🔗 Sinonim qo'shish", callback_data=f"cli:alias:{client.id}"),
            ]
        )
    rows.extend(
        [
            [
                InlineKeyboardButton(text="📤 Guruhga Akt Sverka", callback_data=f"cli:send_sverka:{client.id}"),
                InlineKeyboardButton(text="📥 Mijoz Excel", callback_data=f"export:client:{client.id}"),
            ],
            [
                InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"cli:del:{client.id}"),
                InlineKeyboardButton(text="⬅️ Mijozlarga", callback_data="set:clients"),
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_prices_kb(
    client_id: int, products: Sequence[Product], custom_map: Dict[int, float]
) -> InlineKeyboardMarkup:
    """Show product list for configuring a client's custom per-kg prices."""
    rows = []
    for p in products:
        if p.id in custom_map:
            lbl = f"✏️ {p.name}: {format_uzs(custom_map[p.id])} so'm/kg (Maxsus)"
        else:
            lbl = f"🏷 {p.name}: {format_uzs(p.default_sell_price)} so'm/kg (Standart)"
        rows.append([InlineKeyboardButton(text=lbl, callback_data=f"cli:setprice:{client_id}:{p.id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Mijoz kartasiga", callback_data=f"cli:view:{client_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bind_group_clients_kb(chat_id: int, clients: Sequence[Client]) -> InlineKeyboardMarkup:
    """One-tap group binding buttons when bot is added to a group."""
    rows = []
    for c in clients:
        tag = "✅" if c.group_chat_id == chat_id else ("🔄" if c.group_chat_id else "🆕")
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{tag} {c.name}",
                    callback_data=f"grp:qbind_cli:{c.id}:{chat_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="📊 Rahbariyat hisobot guruhi",
                callback_data=f"grp:qbind_rep:{chat_id}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def report_group_config_kb(
    bot_username: str = "norin_ai_bot", group_title: Optional[str] = None
) -> InlineKeyboardMarkup:
    """Configure optional owner/management report group."""
    top_text = (
        f"🔄 📊 Guruhni almashtirish (✅ {group_title[:16]})"
        if group_title
        else "➕ 📊 Hisobot guruhiga qo'shish (Admin)"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=top_text,
                    url=build_report_group_deeplink(bot_username),
                )
            ],
            [
                InlineKeyboardButton(text="🆔 Guruh ID kiritish", callback_data="repgrp:set_id"),
                InlineKeyboardButton(text="🧪 Test xabar", callback_data="repgrp:ping"),
            ],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="set:back")],
        ]
    )


def debts_list_kb(debts: Sequence[ClientDebtSummary]) -> InlineKeyboardMarkup:
    """List clients ordered by outstanding debt."""
    rows = []
    for d in debts:
        icon = "🔴" if d.current_debt > 0 else ("🟢" if d.current_debt == 0 else "🔵")
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{icon} {d.client.name} — {format_uzs(d.current_debt)} so'm",
                    callback_data=f"debt:view:{d.client.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ Yangi mijoz qo'shish", callback_data="cli:add")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_debt_detail_kb(client_id: int, has_group: bool) -> InlineKeyboardMarkup:
    """Actions inside a client's Akt Sverka / Debt screen."""
    rows = [
        [
            InlineKeyboardButton(text="💵 Pul qabul qilish", callback_data=f"pay:cli:{client_id}"),
            InlineKeyboardButton(text="📥 Mijoz Excel", callback_data=f"export:client:{client_id}"),
        ]
    ]
    if has_group:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📤 Guruhga Akt Sverka yuborish",
                    callback_data=f"cli:send_sverka:{client_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="⚙️ Mijoz sozlamasi", callback_data=f"cli:view:{client_id}"),
            InlineKeyboardButton(text="⬅️ Qarzlar ro'yxati", callback_data="debt:list"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# History Keyboards
# ---------------------------------------------------------------------------


def history_sessions_kb(sessions: Sequence[DailyCashSession]) -> InlineKeyboardMarkup:
    """List daily sessions plus quick Sales / Payments feeds."""
    rows = [
        [
            InlineKeyboardButton(text="🥩 Barcha Sotuvlar", callback_data="hist:all_sales:0"),
            InlineKeyboardButton(text="💵 Barcha To'lovlar", callback_data="hist:all_pays:0"),
        ]
    ]
    for s in sessions:
        if s.status == "open":
            label = f"🟢 {s.report_date} (Ochiq) | Kassa: {format_uzs(s.expected_cash)}"
        else:
            diff = s.difference or 0
            icon = "✅" if abs(diff) < 1 else ("⚠️" if diff < 0 else "➕")
            label = f"{icon} {s.report_date} | Qoldiq: {format_uzs(s.actual_counted_cash or 0)}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"hist:view:{s.id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="set:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def history_detail_kb(session_id: int, is_closed: bool = True) -> InlineKeyboardMarkup:
    """Actions for viewing a historical daily session."""
    top = [InlineKeyboardButton(text="📥 Excel yuklash", callback_data=f"export:daily:{session_id}")]
    if is_closed:
        top.append(
            InlineKeyboardButton(text="🔓 Qayta ochish", callback_data=f"hist:reopen:{session_id}")
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            top,
            [InlineKeyboardButton(text="⬅️ History ga qaytish", callback_data="set:history")],
        ]
    )


def history_feed_kb(kind: str, page: int, has_next: bool) -> InlineKeyboardMarkup:
    """Pagination keyboard for all-sales or all-payments history feeds."""
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"hist:{kind}:{page - 1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"hist:{kind}:{page + 1}"))
    rows = [nav] if nav else []
    rows.append([InlineKeyboardButton(text="⬅️ History ga qaytish", callback_data="set:history")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Subscription & Super Admin Keyboards
# ---------------------------------------------------------------------------


def subscription_status_kb() -> InlineKeyboardMarkup:
    """Client-facing subscription status actions."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 To'lov qildim (Tasdiqlash so'rash)",
                    callback_data="sub:paid_notify",
                )
            ],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="set:back")],
        ]
    )


def superadmin_menu_kb(
    is_suspended: bool,
    tenant_label: str = "Filiallar",
    tenant_id: int = 1,
) -> InlineKeyboardMarkup:
    """Super Admin subscription & multi-tenant user access control panel."""
    suspend_btn = (
        InlineKeyboardButton(text="▶️ Botni faollashtirish", callback_data="sa:toggle_suspend")
        if is_suspended
        else InlineKeyboardButton(text="⏸ Botni bloklash", callback_data="sa:toggle_suspend")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"🏢 {tenant_label}", callback_data="sa:tenants"),
                InlineKeyboardButton(text="➕ Yangi mijoz (Filial)", callback_data="sa:add_user_new"),
            ],
            [
                InlineKeyboardButton(text="➕ +7 kun", callback_data="sa:ext:7"),
                InlineKeyboardButton(text="➕ +30 kun", callback_data="sa:ext:30"),
                InlineKeyboardButton(text="➕ +90 kun", callback_data="sa:ext:90"),
            ],
            [
                InlineKeyboardButton(text="🗓 Boshqa kun qo'shish", callback_data="sa:ext_custom"),
                InlineKeyboardButton(text="💳 Oylik narx", callback_data="sa:edit_price"),
            ],
            [
                InlineKeyboardButton(text="🏢 Sex nomi", callback_data="sa:edit_tenant"),
                InlineKeyboardButton(text="📞 Kontakt", callback_data="sa:edit_contact"),
            ],
            [
                InlineKeyboardButton(text="👥 Xodim/Mijozlar", callback_data="sa:users"),
                InlineKeyboardButton(text="📜 To'lovlar tarixi", callback_data="sa:payments"),
            ],
            [
                suspend_btn,
                InlineKeyboardButton(text="🔔 Eslatma yuborish", callback_data="sa:send_reminder"),
            ],
            [
                InlineKeyboardButton(
                    text=f"🧹 Bazani tozalash (#{tenant_id})",
                    callback_data="sa:clear_menu",
                )
            ],
            [InlineKeyboardButton(text="⬅️ Sozlamalar", callback_data="set:back")],
        ]
    )


def superadmin_tenants_kb(
    tenants: Sequence[SubscriptionState],
    selected_id: int = 1,
) -> InlineKeyboardMarkup:
    """List all SaaS tenants (branches) so Super Admin can switch or add new ones."""
    rows: list[list[InlineKeyboardButton]] = []
    for t in tenants:
        prefix = "✅" if t.id == selected_id else ("⏸" if t.is_suspended else "🏢")
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{prefix} #{t.id} {t.tenant_name}",
                    callback_data=f"sa:sel_ten:{t.id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="🆕 Yangi mijoz + yangi filial", callback_data="sa:add_user_new"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="➕ Bo'sh filial ochish", callback_data="sa:new_tenant"),
            InlineKeyboardButton(text="⬅️ Super Admin menyu", callback_data="sa:menu"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def superadmin_clear_confirm_kb() -> InlineKeyboardMarkup:
    """Confirmation choices for clearing test data or wiping the whole database."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🧹 Faqat test savdo/qarz/kassa (Mijozlar qoladi)",
                    callback_data="sa:clear_exec:tx",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💣 To'liq tozalash (Hammasi 0 dan)",
                    callback_data="sa:clear_exec:full",
                )
            ],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="sa:menu")],
        ]
    )


def superadmin_users_kb(
    users: Sequence[AuthorizedUser], tenant_id: int = 1
) -> InlineKeyboardMarkup:
    """AuthorizedUser list for the selected tenant with add/remove buttons."""
    rows = []
    for u in users:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 {u.full_name} ({u.telegram_id})",
                    callback_data=f"sa:del_user:{u.telegram_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="🆕 Yangi mijoz + yangi filial",
                callback_data="sa:add_user_new",
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=f"➕ Shu filialga xodim (#{tenant_id})",
                callback_data="sa:add_user",
            ),
            InlineKeyboardButton(text="⬅️ Super Admin", callback_data="sa:menu"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def superadmin_renewal_request_kb(
    requester_id: int, tenant_id: int = 1
) -> InlineKeyboardMarkup:
    """One-tap renewal approval buttons sent to Super Admin when a client notifies payment."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ +30 kun tasdiqlash",
                    callback_data=f"sa:approve:{tenant_id}:{requester_id}:30",
                ),
                InlineKeyboardButton(
                    text="✅ +7 kun",
                    callback_data=f"sa:approve:{tenant_id}:{requester_id}:7",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Rad etish",
                    callback_data=f"sa:reject:{tenant_id}:{requester_id}",
                )
            ],
        ]
    )

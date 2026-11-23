"""Write endpoints for Norin AI API: products, clients, sales (AI/text/manual), payments, returns, cash & settings."""

from __future__ import annotations

import html
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api import serializers as ser
from api.deps import Principal, get_db, get_principal, tenant_ctx
from database.crud import (
    EXPENSE_CATEGORIES,
    add_cash_transaction,
    add_client_payment,
    add_product_return,
    bind_client_group,
    close_cash_session,
    compute_client_debt,
    compute_session_summary,
    confirm_sale,
    create_client,
    create_pending_sale,
    create_product,
    delete_cash_transaction,
    delete_client,
    delete_client_payment,
    delete_product,
    delete_product_return,
    delete_sale,
    find_duplicate_confirmed_sale,
    get_app_setting,
    get_cash_transaction,
    get_client,
    get_client_payment,
    get_client_prices_map,
    get_group_config,
    get_product,
    get_product_return,
    get_sale,
    list_clients,
    list_products,
    match_client,
    match_product,
    reopen_cash_session,
    resolve_sell_price,
    round_amount,
    set_app_setting,
    set_client_product_price,
    set_group_config,
    set_sale_group_message,
    unbind_client_group,
    update_cash_transaction,
    update_client,
    update_client_payment,
    update_product,
    update_sale_client,
    update_sale_item,
)
from database.models import Product, Sale
from services.gemini_ai import (
    extract_caption_client_override,
    extract_norin_from_image,
    format_kg,
    format_uzs,
    parse_norin_voice_or_text,
)
from services.group_notify import (
    post_payment_to_group,
    post_return_to_group,
    post_sale_to_group,
    post_sverka_to_group,
    render_return_delete_group_notice,
    sync_sale_group_edit,
)


router = APIRouter(tags=["write"], dependencies=[Depends(get_principal)])
logger = logging.getLogger("norin_api.write")

# Bounded cache holding uploaded phone receipt photos until confirmed/posted to group
_PENDING_PHOTO_BYTES: Dict[int, bytes] = {}
_MAX_CACHED_PHOTOS = 40
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def _cache_photo(sale_id: int, raw: bytes) -> None:
    if len(_PENDING_PHOTO_BYTES) >= _MAX_CACHED_PHOTOS:
        oldest = next(iter(_PENDING_PHOTO_BYTES))
        _PENDING_PHOTO_BYTES.pop(oldest, None)
    _PENDING_PHOTO_BYTES[sale_id] = raw


def _build_items_spec(
    raw_items: List[Dict[str, Any]], products: List[Product]
) -> List[Dict[str, Any]]:
    if not products:
        return []
    merged: Dict[int, Dict[str, Any]] = {}
    for entry in raw_items:
        w = float(entry.get("weight_kg") or 0.0)
        if w <= 0:
            continue
        prod = match_product(entry.get("product_hint"), products) or products[0]
        bd = entry.get("weights_breakdown") or []
        bd_parts = [format_kg(x) for x in bd if isinstance(x, (int, float)) and x > 0]
        bd_str = " + ".join(bd_parts) if len(bd_parts) > 1 else ""
        if prod.id in merged:
            prev = merged[prod.id]
            prev["weight_kg"] = round(prev["weight_kg"] + w, 3)
            if bd_str or prev["weights_detail"]:
                left = prev["weights_detail"] or format_kg(prev["weight_kg"] - w)
                right = bd_str or format_kg(w)
                prev["weights_detail"] = f"{left} + {right}"
        else:
            merged[prod.id] = {
                "product": prod,
                "weight_kg": round(w, 3),
                "weights_detail": bd_str,
            }
    return list(merged.values())


# ------------------------------------------------------------------ Schemas


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    cost_price: float = Field(ge=0)
    default_sell_price: float = Field(gt=0)
    unit: str = Field(default="kg", max_length=16)
    aliases: str = Field(default="", max_length=500)


class ProductPatch(BaseModel):
    name: Optional[str] = None
    cost_price: Optional[float] = Field(default=None, ge=0)
    default_sell_price: Optional[float] = Field(default=None, gt=0)
    unit: Optional[str] = None
    aliases: Optional[str] = None


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str = Field(default="", max_length=64)
    opening_debt: float = Field(default=0.0)
    aliases: str = Field(default="", max_length=500)


class ClientPatch(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    opening_debt: Optional[float] = None
    aliases: Optional[str] = None
    group_chat_id: Optional[int] = None
    group_title: Optional[str] = None


class ClientPriceIn(BaseModel):
    sell_price: Optional[float] = Field(default=None, ge=0)


class SaleItemIn(BaseModel):
    product_id: int
    weight_kg: float = Field(gt=0)
    unit_sell_price: Optional[float] = Field(default=None, gt=0)
    weights_detail: str = ""


class SaleCreateIn(BaseModel):
    client_id: Optional[int] = None
    items: List[SaleItemIn] = Field(min_length=1)
    note: str = ""
    confirm_now: bool = False
    post_to_group: bool = False


class SaleConfirmIn(BaseModel):
    post_to_group: bool = True


class SaleClientPatch(BaseModel):
    client_id: int


class SaleItemPatch(BaseModel):
    weight_kg: Optional[float] = Field(default=None, gt=0)
    unit_sell_price: Optional[float] = Field(default=None, gt=0)
    product_id: Optional[int] = None


class TextCommandIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class PaymentIn(BaseModel):
    client_id: int
    amount: float = Field(gt=0)
    payment_method: str = "cash"
    note: str = ""
    post_to_group: bool = False


class PaymentPatch(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0)
    payment_method: Optional[str] = None
    note: Optional[str] = None


class ReturnIn(BaseModel):
    client_id: int
    product_id: int
    weight_kg: float = Field(gt=0)
    reason: str = ""
    post_to_group: bool = False


class CashTxIn(BaseModel):
    amount: float = Field(gt=0)
    source_type: str = "expense"
    category: Optional[str] = None
    note: str = ""


class CashTxPatch(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0)
    note: Optional[str] = None


class CloseDayIn(BaseModel):
    counted_cash: float = Field(ge=0)
    session_id: Optional[int] = None
    notify_report_group: bool = True


class SettingsPatch(BaseModel):
    auto_confirm: Optional[bool] = None
    group_auto_calc: Optional[bool] = None
    round_mode: Optional[str] = None
    report_group_chat_id: Optional[int] = None
    report_group_title: Optional[str] = None


# ------------------------------------------------------------------ Products


@router.post("/products")
async def api_create_product(
    body: ProductIn,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    p = await create_product(
        db,
        name=body.name,
        cost_price=body.cost_price,
        default_sell_price=body.default_sell_price,
        unit=body.unit,
        aliases=body.aliases,
    )
    return ser.product_out(p)


@router.patch("/products/{product_id}")
async def api_update_product(
    product_id: int,
    body: ProductPatch,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    p = await update_product(
        db,
        product_id,
        name=body.name,
        cost_price=body.cost_price,
        default_sell_price=body.default_sell_price,
        unit=body.unit,
        aliases=body.aliases,
    )
    if p is None:
        raise HTTPException(status_code=404, detail="Mahsulot topilmadi")
    return ser.product_out(p)


@router.delete("/products/{product_id}")
async def api_delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    if not await delete_product(db, product_id):
        raise HTTPException(status_code=404, detail="Mahsulot topilmadi")
    return {"ok": True}


# ------------------------------------------------------------------- Clients


@router.post("/clients")
async def api_create_client(
    body: ClientIn,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    cli = await create_client(
        db,
        name=body.name,
        phone=body.phone,
        opening_debt=body.opening_debt,
        aliases=body.aliases,
    )
    debt = await compute_client_debt(db, cli.id, history_limit=0)
    return ser.client_out(cli, debt)


@router.patch("/clients/{client_id}")
async def api_update_client(
    client_id: int,
    body: ClientPatch,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    cli = await update_client(
        db,
        client_id,
        name=body.name,
        phone=body.phone,
        opening_debt=body.opening_debt,
        aliases=body.aliases,
    )
    if cli is None:
        raise HTTPException(status_code=404, detail="Mijoz topilmadi")
    if body.group_chat_id is not None:
        cli = await bind_client_group(
            db, client_id, body.group_chat_id, body.group_title or ""
        )
        assert cli is not None
    debt = await compute_client_debt(db, cli.id, history_limit=0)
    return ser.client_out(cli, debt)


@router.delete("/clients/{client_id}")
async def api_delete_client(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    if not await delete_client(db, client_id):
        raise HTTPException(status_code=404, detail="Mijoz topilmadi")
    return {"ok": True}


@router.put("/clients/{client_id}/prices/{product_id}")
async def api_set_client_price(
    client_id: int,
    product_id: int,
    body: ClientPriceIn,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    if await get_client(db, client_id) is None or await get_product(db, product_id) is None:
        raise HTTPException(status_code=404, detail="Mijoz yoki mahsulot topilmadi")
    await set_client_product_price(db, client_id, product_id, body.sell_price)
    prices = await get_client_prices_map(db, client_id)
    return {"custom_prices": {str(pid): ser.r2(v) for pid, v in prices.items()}}


@router.post("/clients/{client_id}/unbind-group")
async def api_unbind_client_group(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    cli = await unbind_client_group(db, client_id)
    if cli is None:
        raise HTTPException(status_code=404, detail="Mijoz topilmadi")
    debt = await compute_client_debt(db, cli.id, history_limit=0)
    return ser.client_out(cli, debt)


@router.post("/clients/{client_id}/send-sverka")
async def api_send_sverka(
    client_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    if await get_client(db, client_id) is None:
        raise HTTPException(status_code=404, detail="Mijoz topilmadi")
    debt = await compute_client_debt(db, client_id, history_limit=8)
    ok, msg = await post_sverka_to_group(request.app.state.bot, debt)
    return {"posted": ok, "message": msg}


# --------------------------------------------------------------------- Sales


async def _apply_rounding(
    db: AsyncSession, client_id: Optional[int], items_spec: List[Dict[str, Any]]
) -> None:
    round_mode = await get_app_setting(db, "round_mode", "none")
    if round_mode == "none":
        return
    for spec in items_spec:
        if spec.get("unit_sell_price") is not None:
            continue
        prod = spec["product"]
        unit_p = await resolve_sell_price(db, client_id, prod)
        line_t = round_amount(spec["weight_kg"] * unit_p, round_mode)
        if spec["weight_kg"] > 0 and line_t > 0:
            spec["unit_sell_price"] = round(line_t / spec["weight_kg"], 2)


@router.post("/sales")
async def api_create_sale(
    body: SaleCreateIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    specs: List[Dict[str, Any]] = []
    for item in body.items:
        prod = await get_product(db, item.product_id)
        if prod is None:
            raise HTTPException(status_code=404, detail=f"Mahsulot #{item.product_id} topilmadi")
        specs.append(
            {
                "product": prod,
                "weight_kg": item.weight_kg,
                "unit_sell_price": item.unit_sell_price,
                "weights_detail": item.weights_detail,
            }
        )
    if body.client_id is not None and await get_client(db, body.client_id) is None:
        raise HTTPException(status_code=404, detail="Mijoz topilmadi")
    await _apply_rounding(db, body.client_id, specs)
    try:
        sale = await create_pending_sale(
            db,
            client_id=body.client_id,
            items_spec=specs,
            note=body.note,
            source_channel="api",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    dup = await find_duplicate_confirmed_sale(
        db, sale.session_id, body.client_id, sale.total_weight_kg, exclude_id=sale.id
    )
    grp_ok = False
    grp_msg = ""
    if body.confirm_now:
        if sale.client_id is None:
            raise HTTPException(status_code=400, detail="Tasdiqlash uchun mijozni tanlang")
        sale = await confirm_sale(db, sale.id)  # type: ignore[assignment]
        debt = await compute_client_debt(db, sale.client_id, history_limit=1)
        if body.post_to_group:
            grp_ok, grp_msg = await post_sale_to_group(
                request.app.state.bot, db, sale, debt.current_debt
            )
    return {
        "sale": ser.sale_out(sale),
        "duplicate_sale_id": dup.id if dup else None,
        "group_posted": grp_ok,
        "group_message": grp_msg,
    }


@router.post("/sales/from-image")
async def api_sale_from_image(
    file: UploadFile = File(...),
    caption: Optional[str] = Form(default=None),
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    raw = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Rasm hajmi 10 MB dan oshmasligi kerak")
    if not raw:
        raise HTTPException(status_code=400, detail="Bo'sh fayl")

    products = await list_products(db, active_only=True)
    clients = await list_clients(db, active_only=True)
    cap_cli, cap_hint = extract_caption_client_override(caption, products, clients)

    mime = file.content_type or "image/jpeg"
    extracted = await extract_norin_from_image(
        image_bytes=raw, products=products, clients=clients, mime_type=mime, caption=caption
    )
    if extracted.get("error"):
        return {
            "sale": None,
            "suggested_client_name": cap_hint,
            "is_clear": False,
            "error": extracted["error"],
        }

    items_spec = _build_items_spec(extracted.get("items") or [], products)
    if not items_spec:
        return {
            "sale": None,
            "suggested_client_name": cap_hint or extracted.get("client_hint"),
            "is_clear": False,
            "error": "Rasmdan kg miqdori o'qilmadi",
        }

    if cap_cli is not None:
        cli_obj = cap_cli
        suggested = None
    elif cap_hint:
        cli_obj = None
        suggested = cap_hint
    else:
        cli_obj = match_client(extracted.get("client_hint"), clients)
        suggested = extracted.get("client_hint") if cli_obj is None else None

    cid = cli_obj.id if cli_obj else None
    await _apply_rounding(db, cid, items_spec)
    sale = await create_pending_sale(
        db,
        client_id=cid,
        items_spec=items_spec,
        note=extracted.get("notes") or (caption or ""),
        source_channel="api",
    )
    _cache_photo(sale.id, raw)
    dup = await find_duplicate_confirmed_sale(
        db, sale.session_id, cid, sale.total_weight_kg, exclude_id=sale.id
    )
    return {
        "sale": ser.sale_out(sale),
        "suggested_client_name": suggested,
        "is_clear": bool(extracted.get("is_clear")),
        "duplicate_sale_id": dup.id if dup else None,
        "error": None,
    }


@router.post("/sales/from-text")
async def api_sale_from_text(
    body: TextCommandIn,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    products = await list_products(db, active_only=True)
    clients = await list_clients(db, active_only=True)
    parsed = await parse_norin_voice_or_text(products, clients, text=body.text)
    return await _dispatch_parsed(db, parsed, raw_text=body.text)


@router.post("/sales/from-voice")
async def api_sale_from_voice(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    raw = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Audio hajmi 10 MB dan oshmasligi kerak")
    if not raw:
        raise HTTPException(status_code=400, detail="Bo'sh audio")
    products = await list_products(db, active_only=True)
    clients = await list_clients(db, active_only=True)
    mime = file.content_type or "audio/ogg"
    parsed = await parse_norin_voice_or_text(
        products, clients, audio_bytes=raw, mime_type=mime
    )
    if parsed.get("error"):
        return {"intent": "error", "error": parsed["error"], "parsed": parsed}
    return await _dispatch_parsed(db, parsed, raw_text=parsed.get("transcript") or "")


async def _dispatch_parsed(
    db: AsyncSession, parsed: Dict[str, Any], raw_text: str
) -> dict:
    intent = parsed.get("intent", "unknown")
    if intent == "sale" and parsed.get("items"):
        products = await list_products(db, active_only=True)
        clients = await list_clients(db, active_only=True)
        items_spec = _build_items_spec(parsed["items"], products)
        cli = match_client(parsed.get("client_hint"), clients)
        if items_spec:
            cid = cli.id if cli else None
            await _apply_rounding(db, cid, items_spec)
            sale = await create_pending_sale(
                db, client_id=cid, items_spec=items_spec, note=raw_text, source_channel="api"
            )
            dup = await find_duplicate_confirmed_sale(
                db, sale.session_id, cid, sale.total_weight_kg, exclude_id=sale.id
            )
            return {
                "intent": "sale",
                "sale": ser.sale_out(sale),
                "duplicate_sale_id": dup.id if dup else None,
                "parsed": parsed,
            }
    return {"intent": intent, "sale": None, "parsed": parsed}


@router.post("/sales/{sale_id}/confirm")
async def api_confirm_sale(
    sale_id: int,
    body: SaleConfirmIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    sale = await get_sale(db, sale_id)
    if sale is None or sale.status == "deleted":
        raise HTTPException(status_code=404, detail="Sotuv topilmadi")
    if sale.client_id is None:
        raise HTTPException(status_code=400, detail="Avval mijozni tanlang")
    confirmed = await confirm_sale(db, sale_id)
    assert confirmed is not None
    debt = await compute_client_debt(db, confirmed.client_id, history_limit=1)
    grp_ok, grp_msg = False, ""
    if body.post_to_group:
        photo_bytes = _PENDING_PHOTO_BYTES.pop(sale_id, None)
        grp_ok, grp_msg = await post_sale_to_group(
            request.app.state.bot, db, confirmed, debt.current_debt, photo_bytes=photo_bytes
        )
        confirmed = await get_sale(db, sale_id) or confirmed
    return {
        "sale": ser.sale_out(confirmed),
        "client_debt": ser.r2(debt.current_debt),
        "group_posted": grp_ok,
        "group_message": grp_msg,
    }


@router.post("/sales/{sale_id}/post-group")
async def api_post_sale_group(
    sale_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    sale = await get_sale(db, sale_id)
    if sale is None or sale.status != "confirmed" or sale.client_id is None:
        raise HTTPException(status_code=404, detail="Tasdiqlangan sotuv topilmadi")
    debt = await compute_client_debt(db, sale.client_id, history_limit=1)
    photo_bytes = _PENDING_PHOTO_BYTES.pop(sale_id, None)
    ok, msg = await post_sale_to_group(
        request.app.state.bot, db, sale, debt.current_debt, photo_bytes=photo_bytes
    )
    return {"posted": ok, "message": msg}


@router.post("/sales/{sale_id}/unpost-group")
async def api_unpost_sale_group(
    sale_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    sale = await get_sale(db, sale_id)
    if sale is None or sale.status == "deleted":
        raise HTTPException(status_code=404, detail="Sotuv topilmadi")
    bot = request.app.state.bot
    if bot is not None and sale.group_chat_id and sale.group_message_id:
        try:
            await bot.delete_message(chat_id=sale.group_chat_id, message_id=sale.group_message_id)
        except Exception:
            pass
    updated = await set_sale_group_message(db, sale.id, None, None)
    return {"sale": ser.sale_out(updated or sale)}


@router.patch("/sales/{sale_id}/client")
async def api_update_sale_client(
    sale_id: int,
    body: SaleClientPatch,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    updated = await update_sale_client(db, sale_id, body.client_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Sotuv yoki mijoz topilmadi")
    if updated.status == "confirmed" and updated.client_id is not None:
        debt = await compute_client_debt(db, updated.client_id, history_limit=1)
        await sync_sale_group_edit(request.app.state.bot, updated, debt.current_debt)
    return {"sale": ser.sale_out(updated)}


@router.patch("/sales/items/{item_id}")
async def api_update_sale_item(
    item_id: int,
    body: SaleItemPatch,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    updated = await update_sale_item(
        db,
        item_id,
        weight_kg=body.weight_kg,
        unit_sell_price=body.unit_sell_price,
        product_id=body.product_id,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Sotuv qatori topilmadi")
    if updated.status == "confirmed" and updated.client_id is not None:
        debt = await compute_client_debt(db, updated.client_id, history_limit=1)
        change = (
            f"⚖️ {format_kg(updated.total_weight_kg)} kg — "
            f"<b>{format_uzs(updated.total_amount)} so'm</b>"
        )
        await sync_sale_group_edit(
            request.app.state.bot, updated, debt.current_debt, change_line=change
        )
    return {"sale": ser.sale_out(updated)}


@router.delete("/sales/{sale_id}")
async def api_delete_sale(
    sale_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    existing = await get_sale(db, sale_id)
    if existing is None or existing.status == "deleted":
        raise HTTPException(status_code=404, detail="Sotuv topilmadi")
    was_confirmed = existing.status == "confirmed"
    deleted = await delete_sale(db, sale_id)
    if was_confirmed and deleted is not None and deleted.client_id is not None:
        debt = await compute_client_debt(db, deleted.client_id, history_limit=1)
        await sync_sale_group_edit(
            request.app.state.bot, deleted, debt.current_debt, is_deleted=True
        )
    _PENDING_PHOTO_BYTES.pop(sale_id, None)
    return {"ok": True}


# ------------------------------------------------------------------ Payments


@router.post("/payments")
async def api_add_payment(
    body: PaymentIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    if body.payment_method not in ("cash", "card", "transfer"):
        raise HTTPException(status_code=422, detail="Usul: cash, card yoki transfer")
    try:
        pay = await add_client_payment(
            db,
            client_id=body.client_id,
            amount=body.amount,
            payment_method=body.payment_method,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    debt = await compute_client_debt(db, body.client_id, history_limit=1)
    grp_ok, grp_msg = False, ""
    if body.post_to_group:
        grp_ok, grp_msg = await post_payment_to_group(
            request.app.state.bot, db, pay, debt.current_debt
        )
    return {
        "payment": ser.payment_out(pay),
        "client_debt": ser.r2(debt.current_debt),
        "group_posted": grp_ok,
        "group_message": grp_msg,
    }


@router.patch("/payments/{payment_id}")
async def api_update_payment(
    payment_id: int,
    body: PaymentPatch,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    pay = await update_client_payment(
        db,
        payment_id,
        new_amount=body.amount,
        payment_method=body.payment_method,
        note=body.note,
    )
    if pay is None:
        raise HTTPException(status_code=404, detail="To'lov topilmadi")
    return {"payment": ser.payment_out(pay)}


@router.delete("/payments/{payment_id}")
async def api_delete_payment(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    pay = await delete_client_payment(db, payment_id)
    if pay is None:
        raise HTTPException(status_code=404, detail="To'lov topilmadi")
    return {"ok": True}


@router.post("/payments/{payment_id}/post-group")
async def api_post_payment_group(
    payment_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    pay = await get_client_payment(db, payment_id)
    if pay is None or pay.is_deleted:
        raise HTTPException(status_code=404, detail="To'lov topilmadi")
    debt = await compute_client_debt(db, pay.client_id, history_limit=1)
    ok, msg = await post_payment_to_group(request.app.state.bot, db, pay, debt.current_debt)
    return {"posted": ok, "message": msg}


# ---------------------------------------------------------- Returns (Vozvrat)


@router.post("/returns")
async def api_add_return(
    body: ReturnIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    try:
        ret = await add_product_return(
            db,
            client_id=body.client_id,
            product_id=body.product_id,
            weight_kg=body.weight_kg,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    debt = await compute_client_debt(db, body.client_id, history_limit=1)
    grp_ok, grp_msg = False, ""
    if body.post_to_group:
        grp_ok, grp_msg = await post_return_to_group(
            request.app.state.bot, db, ret, debt.current_debt
        )
    return {
        "return_entry": ser.return_out(ret),
        "client_debt": ser.r2(debt.current_debt),
        "group_posted": grp_ok,
        "group_message": grp_msg,
    }


@router.post("/returns/{return_id}/post-group")
async def api_post_return_group(
    return_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    ret = await get_product_return(db, return_id)
    if ret is None or ret.is_deleted:
        raise HTTPException(status_code=404, detail="Vozvrat topilmadi")
    debt = await compute_client_debt(db, ret.client_id, history_limit=1)
    ok, msg = await post_return_to_group(request.app.state.bot, db, ret, debt.current_debt)
    return {"posted": ok, "message": msg}


@router.delete("/returns/{return_id}")
async def api_delete_return(
    return_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    ret = await delete_product_return(db, return_id)
    if ret is None:
        raise HTTPException(status_code=404, detail="Vozvrat topilmadi")
    debt = await compute_client_debt(db, ret.client_id, history_limit=1)
    bot = request.app.state.bot
    target_grp = ret.group_chat_id or (debt.client.group_chat_id if ret.client else None)
    if bot is not None and target_grp and ret.group_message_id:
        try:
            await bot.send_message(
                chat_id=target_grp,
                text=render_return_delete_group_notice(ret, debt.current_debt),
            )
        except Exception:
            pass
    return {"ok": True}


# --------------------------------------------------------- Cash & Day Close


@router.post("/cash/transactions")
async def api_add_cash_tx(
    body: CashTxIn,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    if body.source_type not in ("main_in", "expense", "kassa_debt", "kassa_repay"):
        raise HTTPException(status_code=422, detail="Noto'g'ri operatsiya turi")
    tx = await add_cash_transaction(
        db,
        amount=body.amount,
        source_type=body.source_type,
        note=body.note,
        category=body.category,
    )
    return {"transaction": ser.cash_tx_out(tx), "categories": list(EXPENSE_CATEGORIES)}


@router.patch("/cash/transactions/{tx_id}")
async def api_update_cash_tx(
    tx_id: int,
    body: CashTxPatch,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    tx = await update_cash_transaction(db, tx_id, new_amount=body.amount, new_note=body.note)
    if tx is None:
        raise HTTPException(status_code=404, detail="Yozuv topilmadi")
    return {"transaction": ser.cash_tx_out(tx)}


@router.delete("/cash/transactions/{tx_id}")
async def api_delete_cash_tx(
    tx_id: int,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    tx = await delete_cash_transaction(db, tx_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Yozuv topilmadi")
    return {"ok": True}


@router.post("/cash/close-day")
async def api_close_day(
    body: CloseDayIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    try:
        sm = await compute_session_summary(db, body.session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Smena topilmadi")
    if sm.session.status == "closed":
        raise HTTPException(status_code=400, detail="Bu kun allaqachon yopilgan")
    closed = await close_cash_session(db, sm.session.id, body.counted_cash)
    rep = await get_group_config(db, "report")
    bot = request.app.state.bot
    if body.notify_report_group and rep is not None and bot is not None:
        diff = closed.session.difference or 0
        msg = (
            f"🏁 <b>KUN YOPILDI — {closed.session.report_date}</b>\n"
            f"⚖️ Jami vazn: <b>{format_kg(closed.total_kg)} kg</b>\n"
            f"💰 Jami savdo: <b>{format_uzs(closed.total_revenue)} so'm</b>\n"
            f"📈 <b>Sof foyda: {format_uzs(closed.total_profit)} so'm ({closed.margin_pct:.1f}%)</b>\n"
            f"🖐 Sanalgan naqd: <b>{format_uzs(body.counted_cash)} so'm</b> (farq: {format_uzs(diff)})"
        )
        try:
            await bot.send_message(chat_id=rep.chat_id, text=msg)
        except Exception:
            pass
    return ser.summary_out(closed)


@router.post("/cash/reopen/{session_id}")
async def api_reopen_day(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    sess = await reopen_cash_session(db, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="Smena topilmadi")
    return {"session": ser.session_out(sess)}


# ------------------------------------------------------------------ Settings


@router.patch("/settings")
async def api_patch_settings(
    body: SettingsPatch,
    db: AsyncSession = Depends(get_db),
    _tid: int = Depends(tenant_ctx),
) -> dict:
    if body.auto_confirm is not None:
        await set_app_setting(db, "auto_confirm", "on" if body.auto_confirm else "off")
    if body.group_auto_calc is not None:
        await set_app_setting(db, "group_auto_calc", "on" if body.group_auto_calc else "off")
    if body.round_mode is not None:
        if body.round_mode not in ("none", "nearest_1000", "floor_1000"):
            raise HTTPException(status_code=422, detail="round_mode: none|nearest_1000|floor_1000")
        await set_app_setting(db, "round_mode", body.round_mode)
    if body.report_group_chat_id is not None:
        await set_group_config(
            db,
            "report",
            body.report_group_chat_id,
            html.unescape(body.report_group_title or f"Guruh ({body.report_group_chat_id})"),
        )
    return {"ok": True}

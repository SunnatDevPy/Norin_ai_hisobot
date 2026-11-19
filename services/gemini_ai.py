"""Gemini Flash multimodal AI client (KG-only scale/receipt OCR + Uzbek voice/text) & weight/amount parsers."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence

import httpx

from config import get_settings
from database.models import Client, Product


logger = logging.getLogger("norin_bot.gemini")


def format_uzs(amount: float) -> str:
    """Format an amount in UZS with space thousands separators."""
    rounded = round(float(amount))
    return f"{rounded:,}".replace(",", " ")


def format_kg(weight: float) -> str:
    """Format kg weight cleanly (25.0 -> '25', 12.5 -> '12.5', 8.250 -> '8.25')."""
    val = round(float(weight), 3)
    if abs(val - round(val)) < 1e-6:
        return str(int(round(val)))
    text = f"{val:.3f}".rstrip("0").rstrip(".")
    return text


def parse_uzbek_amount(text: str) -> Optional[float]:
    """
    Parse monetary amounts from Uzbek/Russian text or arithmetic expressions.

    Supports:
    - "21 000 000", "21,000,000", "21000000"
    - "12 895 000 + 2 109 750"
    - "21 mln", "21 million", "1.5 mln", "450 ming", "450k"
    """
    if not text:
        return None

    cleaned = text.lower().strip()
    cleaned = (
        cleaned.replace("so'm", "")
        .replace("som", "")
        .replace("sum", "")
        .replace("сўм", "")
        .replace("сум", "")
    )

    # Handle addition expressions like "12 895 000 + 2 109 750"
    stripped_alpha = (
        cleaned.replace("mln", "")
        .replace("ming", "")
        .replace("million", "")
        .replace("mlrd", "")
        .replace("milliard", "")
        .replace("млн", "")
        .replace("тыс", "")
        .replace("k", "")
    )
    if "+" in cleaned and not re.search(r"[a-zа-яё]", stripped_alpha):
        parts = cleaned.split("+")
        total = 0.0
        found_any = False
        for part in parts:
            val = parse_uzbek_amount(part)
            if val is not None:
                total += val
                found_any = True
        return total if found_any else None

    multiplier_patterns = [
        (r"(\d+(?:[.,]\d+)?)\s*(?:mlrd|milliard|миллиард)\b", 1_000_000_000),
        (r"(\d+(?:[.,]\d+)?)\s*(?:mln|million|миллион|млн)\b", 1_000_000),
        (r"(\d+(?:[.,]\d+)?)\s*(?:ming|тысяч|тыс|k)\b", 1_000),
    ]
    total_multi = 0.0
    matched_multi = False
    remainder = cleaned
    for pattern, mult in multiplier_patterns:
        for match in re.finditer(pattern, remainder):
            num_str = match.group(1).replace(",", ".")
            try:
                total_multi += float(num_str) * mult
                matched_multi = True
            except ValueError:
                pass
        remainder = re.sub(pattern, " ", remainder)

    if matched_multi:
        return total_multi

    digit_match = re.search(r"(\d[\d\s\u00a0_]*(?:[.,]\d+)?)", cleaned)
    if digit_match:
        raw_num = digit_match.group(1)
        compact = re.sub(r"[\s\u00a0_]+", "", raw_num)
        if "," in compact and "." not in compact:
            parts = compact.split(",")
            if len(parts) > 2 or (
                len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) <= 3
            ):
                compact = "".join(parts)
            else:
                compact = compact.replace(",", ".")
        elif "," in compact and "." in compact:
            compact = compact.replace(",", "")
        try:
            return float(compact)
        except ValueError:
            return None

    return None


def _parse_single_kg_token(raw_num: str) -> Optional[float]:
    """Convert a numeric token like '12,5' or '8.25' to float."""
    cleaned = raw_num.strip().replace(",", ".")
    try:
        val = float(cleaned)
        return val if val > 0 else None
    except ValueError:
        return None


def parse_weight_kg(text: str) -> Optional[float]:
    """
    Parse weight in kilograms from text or additive expressions.

    Supports:
    - "25 kg", "12,5 кг", "25.5"
    - "8.25 + 9.1 + 7.65" -> 25.0
    - "25 yarim kg" -> 25.5, "yarim kg" -> 0.5
    """
    if not text:
        return None
    low = text.lower().strip()
    low = re.sub(r"(?:kg|kilo|kilogramm|кг|кило)\b", " ", low)
    low = low.strip()

    # Uzbek "yarim" handling: "25 yarim" -> 25.5, "yarim" -> 0.5
    yarim_match = re.search(r"(?:(\d+)\s+)?\b(?:yarim|ярим)\b", low)
    if yarim_match and "+" not in low:
        whole = float(yarim_match.group(1)) if yarim_match.group(1) else 0.0
        return round(whole + 0.5, 3)

    if "+" in low:
        parts = low.split("+")
        total = 0.0
        found = False
        for p in parts:
            m = re.search(r"\d+(?:[.,]\d+)?", p)
            if m:
                val = _parse_single_kg_token(m.group(0))
                if val is not None:
                    total += val
                    found = True
        return round(total, 3) if found else None

    m = re.search(r"\d+(?:[.,]\d+)?", low)
    if m:
        val = _parse_single_kg_token(m.group(0))
        return round(val, 3) if val is not None else None
    return None


def _extract_json_object(raw_text: str) -> Dict[str, Any]:
    """Parse JSON safely from Gemini response text."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass
    return {}


_HTTP_CLIENT: Optional[httpx.AsyncClient] = None


def _get_http_client() -> httpx.AsyncClient:
    """Reuse a persistent keep-alive AsyncClient to avoid repeated TLS handshakes."""
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None or _HTTP_CLIENT.is_closed:
        _HTTP_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=40.0, write=20.0, pool=10.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _HTTP_CLIENT


async def _call_gemini(parts: list[dict[str, Any]]) -> Dict[str, Any]:
    """Send multimodal content to Gemini generateContent endpoint with model fallback and retry."""
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        return {"error": "GEMINI_API_KEY sozlanmagan"}

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }

    candidates_order: list[str] = []
    for model_name in (
        settings.GEMINI_MODEL,
        "gemini-flash-lite-latest",
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash",
        "gemini-3.7-flash",
        "gemini-flash-latest",
        "gemini-3.8-flash",
    ):
        if model_name and model_name not in candidates_order:
            candidates_order.append(model_name)

    last_exc: Optional[Exception] = None
    body: Dict[str, Any] = {}
    client = _get_http_client()

    for attempt in range(2):
        for model_name in candidates_order:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model_name}:generateContent"
            )
            try:
                resp = await client.post(
                    url,
                    params={"key": settings.GEMINI_API_KEY},
                    json=payload,
                )
                if resp.status_code in (404, 429, 503):
                    logger.warning(
                        "Gemini model %s returned HTTP %s (attempt %s)",
                        model_name,
                        resp.status_code,
                        attempt + 1,
                    )
                    last_exc = httpx.HTTPStatusError(
                        f"Model {model_name} returned {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                    continue
                resp.raise_for_status()
                body = resp.json()
                last_exc = None
                break
            except httpx.HTTPError as exc:
                logger.warning(
                    "Gemini request failed for %s (attempt %s): %s",
                    model_name,
                    attempt + 1,
                    type(exc).__name__,
                )
                last_exc = exc
                continue

        if last_exc is None:
            break
        if attempt == 0:
            await asyncio.sleep(1.0)

    if last_exc is not None:
        raise last_exc

    candidates = body.get("candidates") or []
    if not candidates:
        return {}
    content_parts = candidates[0].get("content", {}).get("parts", [])
    raw_text = "".join(p.get("text", "") for p in content_parts)
    return _extract_json_object(raw_text)


def _format_products_context(products: Sequence[Product]) -> str:
    """Render active products and aliases for Gemini prompts."""
    if not products:
        return "- Norin (Ot go'shtli)\n- Norin (Mol go'shtli)"
    lines = []
    for p in products:
        lines.append(f"- {p.name} (sinonimlar: {p.aliases})")
    return "\n".join(lines)


def _format_clients_context(clients: Sequence[Client]) -> str:
    """Render active clients and aliases for Gemini prompts."""
    if not clients:
        return "(Hozircha ro'yxat bo'sh)"
    lines = []
    for c in clients:
        alias_part = f" | sinonim: {c.aliases}" if c.aliases else ""
        lines.append(f"- {c.name}{alias_part}")
    return "\n".join(lines)


async def extract_norin_from_image(
    image_bytes: bytes,
    products: Sequence[Product],
    clients: Sequence[Client],
    mime_type: str = "image/jpeg",
    caption: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analyze a scale sticker or store receipt image using Gemini Vision.

    STRICT RULE: Ignore all monetary prices/totals printed on the receipt!
    Extract ONLY weights (kg) and product types (e.g., Ot vs Mol), summing
    multiple stickers/rows of the same product if present.
    """
    products_ctx = _format_products_context(products)
    clients_ctx = _format_clients_context(clients)

    prompt = (
        "Siz O'zbekistondagi Norin ishlab chiqaruvchi sexning hisobchi AI yordamchisisiz.\n"
        "Sizga do'kon/tarozi cheki yoki nakladnoy rasmi yuborildi.\n\n"
        "MUHIM QOIDA:\n"
        "1. Chekda yozilgan SO'M NARXLARI va SUMMALARNI MUTLAQO E'TIBORSIZ QOLDIRING! "
        "(Do'konning chakana narxi bizga kerak emas — biz faqat KG miqdorini olamiz va o'zimizning mijoz narxiga ko'paytiramiz.)\n"
        "2. Rasmdan har bir mahsulotning KG (kilogramm / вес / масса / кг) miqdorini va qaysi turdagi mahsulot ekanini aniqlang.\n"
        "3. Agar bitta rasmda bir nechta tarozi cheki/nakleyka yoki bir xil mahsulotdan bir nechta qator bo'lsa, "
        "alohida kg sonlarini `weights_breakdown` ro'yxatiga yozing va jami kg ni `weight_kg` ga jamlab chiqaring.\n\n"
        f"Mavjud mahsulotlar katalogi:\n{products_ctx}\n\n"
        f"Mavjud mijozlar ro'yxati:\n{clients_ctx}\n\n"
    )
    if caption:
        prompt += f"Foydalanuvchi rasm ostiga yozgan izoh (caption): {caption}\n\n"

    prompt += (
        "JSON formatda qaytaring:\n"
        "{\n"
        '  "client_hint": "rasm yoki izohdan topilgan mijoz/do\'kon nomi, topilmasa null",\n'
        '  "items": [\n'
        "    {\n"
        '      "product_hint": "mahsulot nomi yoki turi, masalan: Norin (Ot go\'shtli) yoki Norin (Mol go\'shtli)",\n'
        '      "weight_kg": 25.0,\n'
        '      "weights_breakdown": [8.25, 9.1, 7.65]\n'
        "    }\n"
        "  ],\n"
        '  "is_clear": true,\n'
        '  "notes": "qisqa izoh (nimalar o\'qildi)"\n'
        "}"
    )

    encoded = base64.b64encode(image_bytes).decode("ascii")
    parts: list[dict[str, Any]] = [
        {"text": prompt},
        {"inlineData": {"mimeType": mime_type, "data": encoded}},
    ]

    try:
        data = await _call_gemini(parts)
    except Exception as exc:
        fallback_items = []
        if caption:
            parsed_cap = _heuristic_parse_norin_text(caption, products, clients)
            if parsed_cap and parsed_cap.get("items"):
                fallback_items = parsed_cap["items"]
        return {
            "client_hint": caption.strip() if caption else None,
            "items": fallback_items,
            "is_clear": False,
            "notes": f"Gemini ulanish xatosi: {exc}",
        }

    client_hint = data.get("client_hint")
    if isinstance(client_hint, str):
        client_hint = client_hint.strip() or None
    else:
        client_hint = None

    normalized_items: List[Dict[str, Any]] = []
    raw_items = data.get("items")
    if isinstance(raw_items, list):
        for entry in raw_items:
            if not isinstance(entry, dict):
                continue
            p_hint = str(entry.get("product_hint") or "").strip()
            breakdown: List[float] = []
            raw_bd = entry.get("weights_breakdown")
            if isinstance(raw_bd, list):
                for val in raw_bd:
                    try:
                        fval = float(str(val).replace(",", "."))
                        if fval > 0:
                            breakdown.append(round(fval, 3))
                    except ValueError:
                        pass

            raw_w = entry.get("weight_kg")
            weight_kg: Optional[float] = None
            if isinstance(raw_w, (int, float)) and raw_w > 0:
                weight_kg = round(float(raw_w), 3)
            elif isinstance(raw_w, str):
                weight_kg = parse_weight_kg(raw_w)

            if breakdown:
                bd_sum = round(sum(breakdown), 3)
                if weight_kg is None or abs(weight_kg - bd_sum) > 0.05:
                    weight_kg = bd_sum

            if weight_kg and weight_kg > 0:
                normalized_items.append(
                    {
                        "product_hint": p_hint or "Norin",
                        "weight_kg": weight_kg,
                        "weights_breakdown": breakdown,
                    }
                )

    # Caption fallback if Gemini missed items or client_hint
    if caption:
        cap_parsed = _heuristic_parse_norin_text(caption, products, clients)
        if cap_parsed:
            if not client_hint and cap_parsed.get("client_hint"):
                client_hint = cap_parsed["client_hint"]
            if not normalized_items and cap_parsed.get("items"):
                normalized_items = cap_parsed["items"]
        elif not client_hint and not re.search(r"\d", caption):
            client_hint = caption.strip()

    is_clear = bool(data.get("is_clear")) and len(normalized_items) > 0
    return {
        "client_hint": client_hint,
        "items": normalized_items,
        "is_clear": is_clear,
        "notes": str(data.get("notes") or ""),
    }


_UZ_QUOTE_TRANS = str.maketrans(
    {
        '"': "'",
        "‘": "'",
        "’": "'",
        "ʻ": "'",
        "ʼ": "'",
        "`": "'",
    }
)


def _find_client_in_text(text: str, clients: Sequence[Client]) -> tuple[Optional[str], str]:
    """Find a known client name/alias inside text and return (matched_name, remaining_text)."""
    if not text or not clients:
        return None, text

    norm_text = text.translate(_UZ_QUOTE_TRANS)
    candidates: List[tuple[str, str]] = []
    for cli in clients:
        candidates.append((cli.name.strip(), cli.name.strip()))
        for alias in cli.aliases.split(","):
            a = alias.strip()
            if len(a) >= 2:
                candidates.append((a, cli.name.strip()))

    # Longest candidate first so "Iftiqor 80" beats "Iftiqor"
    candidates.sort(key=lambda pair: len(pair[0]), reverse=True)
    for pattern_str, canonical_name in candidates:
        pattern_norm = pattern_str.translate(_UZ_QUOTE_TRANS)
        regex = re.compile(
            r"(?i)(?<!\w)" + re.escape(pattern_norm) + r"(?:dan|ga|ni|ning)?(?!\w)"
        )
        m = regex.search(norm_text)
        if m:
            remaining = (text[: m.start()] + " " + text[m.end() :]).strip()
            remaining = re.sub(r"\s+", " ", remaining).strip()
            return canonical_name, remaining
    return None, text


def _build_product_token_list(products: Sequence[Product]) -> List[str]:
    """Collect known product keywords/aliases plus default Norin meat words."""
    tokens: set[str] = {
        "ot go'shti",
        "ot goshti",
        "mol go'shti",
        "mol goshti",
        "norin ot",
        "notin ot",
        "norin mol",
        "notin mol",
        "otli",
        "molli",
        "konina",
        "govyadina",
        "конина",
        "говядина",
        "ot",
        "mol",
        "от",
        "мол",
        "qazi",
        "hasip",
    }
    for p in products:
        tokens.add(p.name.strip().lower())
        for alias in p.aliases.split(","):
            a = alias.strip().lower()
            if a and a not in ("norin", "notin", "норин"):
                tokens.add(a)
    return sorted(tokens, key=len, reverse=True)


def _heuristic_parse_norin_text(
    text: str,
    products: Sequence[Product],
    clients: Sequence[Client],
) -> Optional[Dict[str, Any]]:
    """Fast deterministic parser for Uzbek/Russian Norin sales, client payments, expenses, and cash."""
    raw = text.strip()
    if not raw:
        return None
    low = raw.lower()

    # 1. Status & Debts commands without numbers
    has_digit = bool(re.search(r"\d", low))
    if any(k in low for k in ("status", "статус", "hisob", "hisobot", "foyda")) and not has_digit:
        return {
            "intent": "status",
            "client_hint": None,
            "items": [],
            "amount": None,
            "payment_method": None,
            "note": raw,
            "transcript": raw,
        }

    if any(k in low for k in ("qarzlar", "qarzdor", "sverka", "долги")) and not has_digit:
        return {
            "intent": "debts",
            "client_hint": None,
            "items": [],
            "amount": None,
            "payment_method": None,
            "note": raw,
            "transcript": raw,
        }

    # 2. Kassa debt & repay
    amount = parse_uzbek_amount(raw)
    if (
        ("kassaga" in low or "кассага" in low)
        and any(w in low for w in ("qaytardim", "qaytar", "berdim", "yop", "қайтардим"))
    ) or "kassa qarzini yop" in low:
        if amount:
            return {
                "intent": "kassa_repay",
                "client_hint": None,
                "items": [],
                "amount": amount,
                "payment_method": "cash",
                "note": raw,
                "transcript": raw,
            }

    if any(k in low for k in ("kassadan", "кассадан")) and amount:
        return {
            "intent": "kassa_debt",
            "client_hint": None,
            "items": [],
            "amount": amount,
            "payment_method": "cash",
            "note": raw,
            "transcript": raw,
        }

    # 3. Sale detection (presence of kg/kilo/yarim OR product + weight)
    has_kg_unit = bool(re.search(r"\b(?:kg|kilo|kilogramm|кг|кило)\b", low))
    product_tokens = _build_product_token_list(products)
    prod_alt = "|".join(re.escape(t) for t in product_tokens)

    matched_client_name, working_text = _find_client_in_text(raw, clients)

    # Search for product + weight or weight + product pairs in working_text
    # Pattern A: <product> <weights (+ weights)> [kg]
    # Pattern B: <weights (+ weights)> <kg> [<product>]
    pair_pattern = re.compile(
        rf"(?i)(?:(?P<prod1>{prod_alt})\s*[:\-]?\s*(?P<w1>\d+(?:[.,]\d+)?(?:\s*\+\s*\d+(?:[.,]\d+)?)*)\s*(?:kg|kilo|kilogramm|кг|кило)?)"
        rf"|(?:(?P<w2>\d+(?:[.,]\d+)?(?:\s*\+\s*\d+(?:[.,]\d+)?)*)\s*(?:kg|kilo|kilogramm|кг|кило)\s*(?P<prod2>{prod_alt})?)"
    )

    items: List[Dict[str, Any]] = []
    spans: List[tuple[int, int]] = []
    for m in pair_pattern.finditer(working_text):
        p_hint = m.group("prod1") or m.group("prod2")
        w_str = m.group("w1") or m.group("w2")
        # Require explicit kg unit if no product token matched
        if not p_hint and not has_kg_unit:
            continue
        w_val = parse_weight_kg(w_str or "")
        if not w_val or w_val <= 0:
            continue

        breakdown: List[float] = []
        if w_str and "+" in w_str:
            for part in w_str.split("+"):
                pv = _parse_single_kg_token(part)
                if pv:
                    breakdown.append(round(pv, 3))

        items.append(
            {
                "product_hint": (p_hint or "norin").strip(),
                "weight_kg": w_val,
                "weights_breakdown": breakdown,
            }
        )
        spans.append((m.start(), m.end()))

    if items:
        # Remove matched spans to isolate any client_hint when client wasn't matched from DB yet
        if not matched_client_name:
            chunks = []
            last_idx = 0
            for s, e in spans:
                chunks.append(working_text[last_idx:s])
                last_idx = e
            chunks.append(working_text[last_idx:])
            leftover = " ".join(chunks)
            leftover = re.sub(
                r"(?i)\b(?:norin|notin|норин|kg|kilo|kilogramm|кг|кило|berdim|yoz|hisobla|tashla)\b",
                " ",
                leftover,
            )
            leftover = re.sub(r"\s+", " ", leftover).strip(" :,-.")
            if leftover:
                matched_client_name = leftover

        return {
            "intent": "sale",
            "client_hint": matched_client_name,
            "items": items,
            "amount": None,
            "payment_method": None,
            "note": raw,
            "transcript": raw,
        }

    # 4. Production Expense
    expense_words = ("xarajat", "rasxod", "chiqim", "sarfladim", "ketdi", "расход", "харажат")
    if amount and any(w in low for w in expense_words):
        return {
            "intent": "expense",
            "client_hint": None,
            "items": [],
            "amount": amount,
            "payment_method": "cash",
            "note": raw,
            "transcript": raw,
        }

    # 5. Client Payment (requires monetary amount and NOT kg unit)
    pay_method = "cash"
    if any(w in low for w in ("karta", "click", "payme", "uzcard", "humo", "карта", "клик")):
        pay_method = "card"
    elif any(w in low for w in ("pereches", "perechis", "perichis", "hisob raqam", "bank", "перечис")):
        pay_method = "transfer"

    has_dan_suffix = bool(re.search(r"(?i)\b[a-zа-яё'‘`]+\s*(?:dan|дан)\b", raw))
    pay_markers = ("berdi", "to'ladi", "toladi", "tashladi", "o'tkazdi", "otkazdi", "берди")
    if amount and (matched_client_name or has_dan_suffix or any(w in low for w in pay_markers) or pay_method != "cash"):
        c_hint = matched_client_name
        if not c_hint:
            # Try to extract word before "dan"
            dan_m = re.search(r"(?i)([a-zа-яё0-9_'‘`\s]{2,30}?)(?:dan|дан)\b", raw)
            if dan_m:
                c_hint = dan_m.group(1).strip()
        if c_hint or any(w in low for w in pay_markers) or pay_method != "cash":
            return {
                "intent": "client_payment",
                "client_hint": c_hint,
                "items": [],
                "amount": amount,
                "payment_method": pay_method,
                "note": raw,
                "transcript": raw,
            }

    # 6. Owner Main Cash In (no client, no kg)
    if any(k in low for k in ("pul oldim", "oldim", "kirim", "приход", "олдим")) and amount:
        return {
            "intent": "cash_in",
            "client_hint": None,
            "items": [],
            "amount": amount,
            "payment_method": "cash",
            "note": raw,
            "transcript": raw,
        }

    # 7. Pure number
    stripped_num = re.sub(
        r"[\d\s.,+_mlnmingmillionmlrdkso'msomсўмсумkgкг-]+", "", low
    ).strip()
    if amount is not None and not stripped_num:
        return {
            "intent": "number_only",
            "client_hint": None,
            "items": [],
            "amount": amount,
            "payment_method": None,
            "note": raw,
            "transcript": raw,
        }

    return None


async def parse_norin_voice_or_text(
    products: Sequence[Product],
    clients: Sequence[Client],
    audio_bytes: Optional[bytes] = None,
    text: Optional[str] = None,
    mime_type: str = "audio/ogg",
) -> Dict[str, Any]:
    """
    Understand an Uzbek/Russian voice message or free-form text for Norin wholesale business.

    Returns dict:
        {
            "intent": "sale" | "client_payment" | "expense" | "cash_in" | "kassa_debt" | "kassa_repay" | "debts" | "status" | "number_only" | "unknown",
            "client_hint": str | None,
            "items": [{"product_hint": str, "weight_kg": float, "weights_breakdown": list[float]}],
            "amount": float | None,
            "payment_method": "cash" | "card" | "transfer" | None,
            "note": str,
            "transcript": str
        }
    """
    if text and not audio_bytes:
        heuristic = _heuristic_parse_norin_text(text, products, clients)
        if heuristic is not None:
            return heuristic

    products_ctx = _format_products_context(products)
    clients_ctx = _format_clients_context(clients)

    prompt = (
        "Siz O'zbekistondagi Norin ishlab chiqaruvchi sexning moliyaviy AI yordamchisisiz.\n"
        "Foydalanuvchi o'zbek yoki rus tilida ovozli xabar yoki matn yubordi.\n\n"
        f"Mahsulotlar:\n{products_ctx}\n\n"
        f"Mijozlar:\n{clients_ctx}\n\n"
        "Vazifa: Xabarni tushunib JSON qaytaring:\n"
        '- "transcript": Xabar matni (audio bo\'lsa o\'zbek/rus tilidagi matn).\n'
        '- "intent": Quyidagilardan BITTA qiymat:\n'
        '  * "sale": Mijozga kg da norin/mahsulot chiqarilsa (masalan: "Iftiqor norin ot 25 kg", "ot 12.5 kg mol 8 kg").\n'
        '  * "client_payment": Mijozdan pul/qarz olinsa (masalan: "Iftiqordan 2 million karta oldim", "Chorsudan 5 mln naqd tushdi").\n'
        '  * "expense": Sex xarajati (masalan: "Go\'shtga 3 yarim million xarajat", "Xamirga 400 ming rasxod").\n'
        '  * "cash_in": Asosiy kassaga/qo\'lga pul qo\'shish ("Pul oldim 10 million").\n'
        '  * "kassa_debt": "Kassadan 2 million oldim".\n'
        '  * "kassa_repay": "Kassaga 2 million qaytardim".\n'
        '  * "debts": "Qarzlar", "Kimdan qancha qarz bor".\n'
        '  * "status": "Status", "Kunlik hisobot", "Foyda qancha".\n'
        '  * "unknown": Boshqa narsa bo\'lsa.\n'
        '- "client_hint": Mijoz nomi (topilsa), bo\'lmasa null.\n'
        '- "items": Agar intent="sale" bo\'lsa: [{"product_hint": "...", "weight_kg": 25.0, "weights_breakdown": []}].\n'
        '- "amount": Pul summasi (so\'mda, raqamda), bo\'lmasa null.\n'
        '- "payment_method": Agar client_payment bo\'lsa "cash", "card", yoki "transfer"; bo\'lmasa null.\n'
        'Faqat JSON qaytaring.'
    )

    parts: list[dict[str, Any]] = [{"text": prompt}]
    if text:
        parts.append({"text": f"Foydalanuvchi matni: {text}"})
    if audio_bytes:
        encoded = base64.b64encode(audio_bytes).decode("ascii")
        parts.append({"inlineData": {"mimeType": mime_type, "data": encoded}})

    try:
        data = await _call_gemini(parts)
    except Exception as exc:
        fallback_amt = parse_uzbek_amount(text or "") if text else None
        return {
            "intent": "unknown",
            "client_hint": None,
            "items": [],
            "amount": fallback_amt,
            "payment_method": None,
            "note": text or "",
            "transcript": text or f"Audio xatolik: {exc}",
        }

    intent = str(data.get("intent") or "unknown").strip()
    client_hint = data.get("client_hint")
    client_hint = client_hint.strip() if isinstance(client_hint, str) and client_hint.strip() else None

    raw_amt = data.get("amount")
    amount: Optional[float] = None
    if isinstance(raw_amt, (int, float)) and raw_amt > 0:
        amount = float(raw_amt)
    elif isinstance(raw_amt, str):
        amount = parse_uzbek_amount(raw_amt)

    norm_items: List[Dict[str, Any]] = []
    if isinstance(data.get("items"), list):
        for entry in data["items"]:
            if not isinstance(entry, dict):
                continue
            w = entry.get("weight_kg")
            w_val: Optional[float] = None
            if isinstance(w, (int, float)) and w > 0:
                w_val = round(float(w), 3)
            elif isinstance(w, str):
                w_val = parse_weight_kg(w)
            if w_val and w_val > 0:
                norm_items.append(
                    {
                        "product_hint": str(entry.get("product_hint") or "norin").strip(),
                        "weight_kg": w_val,
                        "weights_breakdown": [],
                    }
                )

    pay_method = data.get("payment_method")
    if pay_method not in ("cash", "card", "transfer"):
        pay_method = "cash" if intent == "client_payment" else None

    transcript = str(data.get("transcript") or text or "")
    return {
        "intent": intent,
        "client_hint": client_hint,
        "items": norm_items,
        "amount": amount,
        "payment_method": pay_method,
        "note": transcript,
        "transcript": transcript,
    }

"""Gemini Flash multimodal AI client (KG-only scale/receipt OCR + Uzbek voice/text) & weight/amount parsers."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
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

    yarim_patterns = [
        (r"(?:(\d+)\s+)?\b(?:yarim|ярим)\s*(?:mlrd|milliard|миллиард)\b", 1_000_000_000),
        (r"(?:(\d+)\s+)?\b(?:yarim|ярим)\s*(?:mln|million|миллион|млн)\b", 1_000_000),
        (r"(?:(\d+)\s+)?\b(?:yarim|ярим)\s*(?:ming|тысяч|тыс|k)\b", 1_000),
    ]
    multiplier_patterns = [
        (r"(\d+(?:[.,]\d+)?)\s*(?:mlrd|milliard|миллиард)\b", 1_000_000_000),
        (r"(\d+(?:[.,]\d+)?)\s*(?:mln|million|миллион|млн)\b", 1_000_000),
        (r"(\d+(?:[.,]\d+)?)\s*(?:ming|тысяч|тыс|k)\b", 1_000),
    ]
    total_multi = 0.0
    matched_multi = False
    remainder = cleaned
    for pattern, mult in yarim_patterns:
        for match in re.finditer(pattern, remainder):
            whole = float(match.group(1)) if match.group(1) else 0.0
            total_multi += (whole + 0.5) * mult
            matched_multi = True
        remainder = re.sub(pattern, " ", remainder)

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
_UNAVAILABLE_MODELS: Dict[str, float] = {}


def _get_http_client() -> httpx.AsyncClient:
    """Reuse a persistent keep-alive AsyncClient to avoid repeated TLS handshakes."""
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None or _HTTP_CLIENT.is_closed:
        _HTTP_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=40.0, write=20.0, pool=10.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _HTTP_CLIENT


async def _check_ai_quota_safe() -> tuple[bool, int, int]:
    """Best-effort check whether active tenant has remaining daily Gemini quota."""
    try:
        from database.crud import check_tenant_ai_quota
        from database.session import async_session_maker

        async with async_session_maker() as db:
            return await check_tenant_ai_quota(db)
    except Exception:
        return True, 0, 0


async def _record_ai_usage_safe(
    kind: str, model_name: str, usage: Dict[str, Any]
) -> None:
    """Best-effort record Gemini token usage in database without failing AI calls."""
    try:
        from database.crud import log_ai_usage
        from database.session import async_session_maker

        async with async_session_maker() as db:
            await log_ai_usage(
                db,
                kind=kind,
                model_name=model_name,
                prompt_tokens=int(usage.get("promptTokenCount") or 0),
                output_tokens=int(usage.get("candidatesTokenCount") or 0),
                total_tokens=int(usage.get("totalTokenCount") or 0),
            )
    except Exception:
        pass


async def _call_gemini(
    parts: list[dict[str, Any]], kind: str = "image"
) -> Dict[str, Any]:
    """Send multimodal content (image or audio) to Gemini with fallback and token logging."""
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        return {"error": "GEMINI_API_KEY sozlanmagan"}

    allowed, used, limit = await _check_ai_quota_safe()
    if not allowed:
        logger.warning("Daily AI quota exceeded (%s/%s)", used, limit)
        return {
            "error": (
                f"Kunlik AI limiti ({used}/{limit}) tugadi. "
                "Matn orqali yozib kiriting yoki administrator bilan bog'laning."
            )
        }

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
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-flash-latest",
    ):
        if model_name and model_name not in candidates_order:
            candidates_order.append(model_name)

    last_exc: Optional[Exception] = None
    body: Dict[str, Any] = {}
    used_model = ""
    client = _get_http_client()

    for attempt in range(2):
        now_mono = time.monotonic()
        for model_name in candidates_order:
            blocked_at = _UNAVAILABLE_MODELS.get(model_name)
            if blocked_at is not None and (now_mono - blocked_at) < 3600:
                continue
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
                if resp.status_code == 404:
                    _UNAVAILABLE_MODELS[model_name] = time.monotonic()
                    logger.warning("Gemini model %s returned 404 (cached skip 1h)", model_name)
                    last_exc = httpx.HTTPStatusError(
                        f"Model {model_name} returned 404",
                        request=resp.request,
                        response=resp,
                    )
                    continue
                if resp.status_code in (429, 503):
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
                used_model = model_name
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

    await _record_ai_usage_safe(kind, used_model, body.get("usageMetadata") or {})

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
    clients_block = (
        f"Mavjud mijozlar ro'yxati:\n{_format_clients_context(clients)}\n\n"
        if clients
        else ""
    )

    prompt = (
        "Siz O'zbekistondagi Norin ishlab chiqaruvchi sexning hisobchi AI yordamchisisiz.\n"
        "Sizga do'kon/tarozi cheki yoki nakladnoy rasmi yuborildi.\n\n"
        "MUHIM QOIDA:\n"
        "1. Chekdagi SO'M NARXLARI va SUMMALARNI E'TIBORSIZ QOLDIRING! Faqat KG miqdorini va mahsulot turini oling.\n"
        "2. Bir nechta tarozi cheki/qator bo'lsa, har bir kg ni `weights_breakdown` ga yozib jami `weight_kg` ni chiqaring.\n\n"
        f"Mavjud mahsulotlar katalogi:\n{products_ctx}\n\n"
        f"{clients_block}"
    )
    if caption:
        prompt += (
            f"Rasm izohi (caption): {caption}\n"
            "AGAR rasm izohida (caption) mijoz, do'kon yoki postavshik nomi yozilgan bo'lsa — "
            "nakladnoy/chekdagi bosma yoki noto'g'ri postavshik/firma nomini E'TIBORSIZ QOLDIRING "
            "va `client_hint` ga aynan rasm izohidagi nomni yozing!\n\n"
        )

    prompt += (
        "JSON formatda qaytaring:\n"
        "{\n"
        '  "client_hint": "mijoz/do\'kon nomi, topilmasa null",\n'
        '  "items": [{"product_hint": "mahsulot nomi", "weight_kg": 25.0, "weights_breakdown": [8.25, 9.1]}],\n'
        '  "is_clear": true,\n'
        '  "notes": "qisqa izoh"\n'
        "}"
    )

    encoded = base64.b64encode(image_bytes).decode("ascii")
    parts: list[dict[str, Any]] = [
        {"text": prompt},
        {"inlineData": {"mimeType": mime_type, "data": encoded}},
    ]

    try:
        data = await _call_gemini(parts, kind="image")
    except Exception as exc:
        fallback_items = []
        cap_cli, cap_hint = extract_caption_client_override(caption, products, clients)
        fb_client: Optional[str] = cap_cli.name if cap_cli is not None else cap_hint
        if caption:
            parsed_cap = _heuristic_parse_norin_text(caption, products, clients)
            if parsed_cap:
                if parsed_cap.get("items"):
                    fallback_items = parsed_cap["items"]
                if fb_client is None and parsed_cap.get("client_hint"):
                    fb_client = parsed_cap["client_hint"]
        return {
            "client_hint": fb_client,
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

    # Caption explicitly overrides client/postavshik name from nakladnoy if present
    if caption:
        cap_cli, cap_hint = extract_caption_client_override(caption, products, clients)
        if cap_cli is not None:
            client_hint = cap_cli.name
        elif cap_hint:
            client_hint = cap_hint

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


_CAPTION_FILLER_RE = re.compile(
    r"(?i)(?<!\w)(?:"
    r"norin|notin|норин|nakladnoy|накладной|nakladnoi|chek|чек|tarozi|тарози|"
    r"postavshik|поставщик|postavsik|mijoz|мижоз|do'kon|dokon|doʻkon|shop|"
    r"berdim|yoz|hisobla|tashla|sotuv|rasm|kg|kilo|kilogramm|кг|кило|ta|dona|"
    r"yarim|ярим"
    r")(?!\w)"
)
_CAPTION_WEIGHT_UNIT_RE = re.compile(
    r"(?i)\b\d+(?:[.,]\d+)?(?:\s*\+\s*\d+(?:[.,]\d+)?)*\s*(?:kg|kilo|kilogramm|кг|кило|ta|dona)\b"
)


def extract_caption_client_override(
    caption: Optional[str],
    products: Sequence[Product],
    clients: Sequence[Client],
) -> tuple[Optional[Client], Optional[str]]:
    """
    Extract an explicit client/postavshik override from a photo caption.

    Returns (matched_client, clean_hint):
    - If caption names an existing client -> (Client, Client.name)
    - If caption contains an explicit unrecognized client/postavshik name -> (None, name)
    - If caption only contains weights/products/numbers -> (None, None)
    """
    if not caption or not caption.strip():
        return None, None

    from database.crud import match_client

    cap = caption.strip()
    matched_name, _ = _find_client_in_text(cap, clients)
    if matched_name:
        cli = match_client(matched_name, clients)
        if cli is not None:
            return cli, cli.name
        return None, matched_name

    # Remove weight+unit expressions and product/filler tokens using word boundaries
    leftover = cap.translate(_UZ_QUOTE_TRANS)
    leftover = _CAPTION_WEIGHT_UNIT_RE.sub(" ", leftover)
    product_tokens = _build_product_token_list(products)
    if product_tokens:
        prod_alt = "|".join(re.escape(t.translate(_UZ_QUOTE_TRANS)) for t in product_tokens if t)
        if prod_alt:
            leftover = re.sub(rf"(?i)(?<!\w)(?:{prod_alt})(?!\w)", " ", leftover)
    leftover = _CAPTION_FILLER_RE.sub(" ", leftover)
    leftover = re.sub(r"[+:;,./|]+", " ", leftover)
    leftover = re.sub(r"\s+", " ", leftover).strip(" -")

    if len(re.findall(r"[A-Za-zА-Яа-яЁёЎўҚқҒғҲҳ]", leftover)) < 2:
        return None, None

    cli = match_client(leftover, clients)
    if cli is not None:
        return cli, cli.name
    return None, leftover


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
    weight_expr = (
        r"(?:(?:\d+\s+)?(?:yarim|ярим)"
        r"|\d+(?:[.,]\d+)?(?:\s*\+\s*\d+(?:[.,]\d+)?)*)"
    )
    pair_pattern = re.compile(
        rf"(?i)(?:(?P<prod1>{prod_alt})\s*[:\-]?\s*(?P<w1>{weight_expr})\s*(?:kg|kilo|kilogramm|кг|кило)?)"
        rf"|(?:(?P<w2>{weight_expr})\s*(?:kg|kilo|kilogramm|кг|кило)\s*(?P<prod2>{prod_alt})?)"
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


async def extract_amount_from_audio(
    audio_bytes: bytes, mime_type: str = "audio/ogg"
) -> tuple[Optional[float], str]:
    """Lightweight Gemini Audio extractor returning only monetary amount (UZS) & transcript (~80 tokens)."""
    prompt = (
        "O'zbek/rus tilidagi audiodan pul summasini (so'mda) va matnini aniqlang.\n"
        'JSON qaytaring: {"amount": 2500000, "transcript": "matn"}. Topilmasa amount: null.'
    )
    encoded = base64.b64encode(audio_bytes).decode("ascii")
    parts: list[dict[str, Any]] = [
        {"text": prompt},
        {"inlineData": {"mimeType": mime_type, "data": encoded}},
    ]
    try:
        data = await _call_gemini(parts, kind="audio")
    except Exception as exc:
        return None, f"Audio xatolik: {exc}"

    transcript = str(data.get("transcript") or "").strip()
    raw_amt = data.get("amount")
    amount: Optional[float] = None
    if isinstance(raw_amt, (int, float)) and raw_amt > 0:
        amount = float(raw_amt)
    elif isinstance(raw_amt, str):
        amount = parse_uzbek_amount(raw_amt)
    if (amount is None or amount <= 0) and transcript:
        amount = parse_uzbek_amount(transcript)
    return amount, transcript


async def parse_norin_voice_or_text(
    products: Sequence[Product],
    clients: Sequence[Client],
    audio_bytes: Optional[bytes] = None,
    text: Optional[str] = None,
    mime_type: str = "audio/ogg",
) -> Dict[str, Any]:
    """
    Understand an Uzbek/Russian voice message (via Gemini Audio) or text (100% local, 0 AI tokens).
    """
    if not audio_bytes:
        raw_text = (text or "").strip()
        if raw_text:
            heuristic = _heuristic_parse_norin_text(raw_text, products, clients)
            if heuristic is not None:
                return heuristic
        return {
            "intent": "unknown",
            "client_hint": None,
            "items": [],
            "amount": parse_uzbek_amount(raw_text) if raw_text else None,
            "payment_method": None,
            "note": raw_text,
            "transcript": raw_text,
        }

    products_ctx = _format_products_context(products)
    clients_ctx = _format_clients_context(clients)

    prompt = (
        "Siz Norin sexi hisobchi AI yordamchisisiz. Audio xabardan JSON qaytaring:\n"
        f"Mahsulotlar:\n{products_ctx}\nMijozlar:\n{clients_ctx}\n\n"
        'intent: "sale"|"client_payment"|"expense"|"cash_in"|"kassa_debt"|"kassa_repay"|"debts"|"status"|"unknown"\n'
        '{"transcript":"...", "intent":"...", "client_hint":null, '
        '"items":[{"product_hint":"...", "weight_kg":25.0}], '
        '"amount":null, "payment_method":"cash"|"card"|"transfer"|null}'
    )

    encoded = base64.b64encode(audio_bytes).decode("ascii")
    parts: list[dict[str, Any]] = [
        {"text": prompt},
        {"inlineData": {"mimeType": mime_type, "data": encoded}},
    ]

    try:
        data = await _call_gemini(parts, kind="audio")
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

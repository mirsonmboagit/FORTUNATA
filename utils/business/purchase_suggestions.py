"""Regras deterministicas e contexto externo para sugestoes de compras.

Este modulo nao faz chamadas de rede. Ele reaproveita, de forma segura, os
dados que as integracoes de produtos ja guardaram nos caches locais. A decisao
final pode ser refinada pelo modelo de IA em ``utils.ai.ai_insights``.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from utils.config.paths import CACHE_DIR


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def normalize_barcode(value: Any) -> str:
    return "".join(str(value or "").split()).casefold()


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except (TypeError, ValueError):
        return None


def _round_quantity(value: float, is_weight: bool) -> float:
    if is_weight:
        return round(max(0.0, value), 2)
    return float(max(1, int(math.ceil(max(0.0, value) - 1e-9))))


def build_demand_purchase_candidates(
    products: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    target_days: int = 14,
    warning_days: int = 7,
    critical_stock_ratio: float = 0.30,
    minimum_restock_qty: float = 1.0,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Cria sugestões a partir do risco de ruptura, procura e cobertura.

    Produtos esgotados e produtos abaixo do limite crítico entram sempre na
    lista. A procura observada define a quantidade recomendada; quando ainda
    não há vendas registadas, é sugerida apenas uma reposição mínima segura.
    """
    reference_day = today or date.today()
    target_days = max(1, int(target_days or 14))
    warning_days = max(1, min(target_days, int(warning_days or 7)))
    critical_stock_ratio = min(1.0, max(0.0, safe_float(critical_stock_ratio, 0.30)))
    minimum_restock_qty = max(0.01, safe_float(minimum_restock_qty, 1.0))
    candidates: list[dict[str, Any]] = []

    for product in list(products or []):
        stock = max(0.0, safe_float(product.get("stock")))
        avg_daily = max(0.0, safe_float(product.get("avg_daily")))
        sold_stock = max(0.0, safe_float(product.get("sold_stock")))
        explicit_limit = max(0.0, safe_float(product.get("stock_limit")))
        historical_limit = (stock + sold_stock) * critical_stock_ratio if sold_stock > 0 else 0.0
        stock_limit = max(explicit_limit, historical_limit)
        is_out_of_stock = stock <= 0
        is_below_limit = stock_limit > 0 and stock < stock_limit
        coverage_days = stock / avg_daily if avg_daily > 0 else 0.0
        is_demand_risk = avg_daily > 0 and coverage_days <= warning_days

        # Uma sugestão só é criada quando há risco real: produto esgotado,
        # abaixo do limite definido pelo próprio sistema ou com saída rápida.
        if not (is_out_of_stock or is_below_limit or is_demand_risk):
            continue

        expiry_date = _parse_date(product.get("expiry_date"))
        days_to_expiry = None
        if expiry_date is not None:
            days_to_expiry = (expiry_date - reference_day).days
            # Um lote perto da validade não deve conduzir a uma compra
            # preventiva. A exceção é a ruptura: sem stock, a loja precisa de
            # repor mesmo que o último lote registado já tenha vencido.
            if not is_out_of_stock and days_to_expiry <= target_days:
                continue

        demand_target = avg_daily * target_days
        safety_target = stock_limit if is_below_limit else 0.0
        if is_out_of_stock and avg_daily <= 0:
            safety_target = max(safety_target, minimum_restock_qty)
        target_stock = max(demand_target, safety_target)
        needed_qty = _round_quantity(target_stock - stock, bool(product.get("is_weight")))
        if needed_qty <= 0:
            needed_qty = _round_quantity(minimum_restock_qty, bool(product.get("is_weight")))

        if is_out_of_stock or (is_below_limit and stock <= (stock_limit * 0.5)):
            priority = "Urgente"
            priority_rank = 0
        elif is_below_limit or coverage_days <= 4:
            priority = "Alta"
            priority_rank = 1
        else:
            priority = "Media"
            priority_rank = 2

        if is_out_of_stock:
            reason = "Stock esgotado"
            notes = (
                f"sem stock; reposição para {target_days} dias de procura"
                if avg_daily > 0
                else "sem stock; reposição mínima de segurança"
            )
        elif is_below_limit:
            reason = "Stock abaixo do limite crítico"
            notes = (
                f"limite crítico: {stock_limit:.2f}/{('kg' if product.get('is_weight') else 'un').lower()}; "
                f"stock atual: {stock:.2f}"
            )
        else:
            reason = "Procura e cobertura de stock"
            notes = (
                f"procura média de {avg_daily:.2f}/{('kg' if product.get('is_weight') else 'un').lower()}; "
                f"cobertura para {coverage_days:.1f} dias"
            )

        unit_cost = safe_float(product.get("unit_cost"))
        sale_price = safe_float(product.get("sale_price"))
        unit = "KG" if product.get("is_weight") else "UN"
        candidates.append(
            {
                "product_id": next(iter(product.get("product_ids") or (None,)), None),
                "product_ids": tuple(product.get("product_ids") or ()),
                "name": str(product.get("name") or "Produto sem nome"),
                "barcode": str(product.get("barcode") or "").strip(),
                "unit": unit,
                "current_stock": stock,
                "usable_stock": stock,
                "avg_daily": avg_daily,
                "coverage_days": coverage_days,
                "days_left": coverage_days,
                "stock_limit": stock_limit,
                "needed_qty": needed_qty,
                "base_needed_qty": needed_qty,
                "target_stock": target_stock,
                "unit_cost": unit_cost,
                "sale_price": sale_price,
                "purchase_cost": needed_qty * unit_cost,
                "potential_revenue": needed_qty * sale_price,
                "potential_profit": needed_qty * (sale_price - unit_cost),
                "priority": priority,
                "priority_rank": priority_rank,
                "reason": reason,
                "notes": notes,
                "must_restock": is_out_of_stock or is_below_limit,
                "expiry_date": expiry_date.isoformat() if expiry_date else "",
                "days_to_expiry": days_to_expiry,
                "lot_count": int(product.get("lot_count") or 1),
            }
        )

    candidates.sort(
        key=lambda item: (
            item["priority_rank"],
            item["coverage_days"],
            -item["avg_daily"],
            item["name"].casefold(),
        )
    )
    return candidates


def _read_cache(cache_file: Path) -> dict[str, Any]:
    try:
        with cache_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _price_value(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    cleaned = re.sub(r"[^0-9,.-]", "", text).replace(" ", "")
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    value = safe_float(cleaned, -1)
    return value if value >= 0 else None


def load_product_api_context(
    products: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    cache_dir: Path | str | None = None,
) -> dict[str, dict[str, Any]]:
    """Devolve dados externos em cache, indexados pelo codigo de barras.

    Sao lidos os caches ja produzidos por Bazara, Open Food Facts e pelo
    agregador de APIs. Nenhuma chamada externa e iniciada por esta tela.
    """
    wanted = {normalize_barcode(item.get("barcode")) for item in products or []}
    wanted.discard("")
    if not wanted:
        return {}

    directory = Path(cache_dir) if cache_dir is not None else CACHE_DIR
    contexts: dict[str, dict[str, Any]] = {}
    for filename in (
        "products_offline_cache.json",
        "openfoodfacts_cache.json",
        "bazara_offline_cache.json",
    ):
        for cache_key, entry in _read_cache(directory / filename).items():
            key = normalize_barcode(cache_key)
            raw = entry.get("data") if isinstance(entry, dict) and "data" in entry else entry
            if not isinstance(raw, dict):
                continue
            key = normalize_barcode(raw.get("barcode") or key)
            if key not in wanted:
                continue

            context = contexts.setdefault(
                key,
                {"sources": [], "names": [], "categories": [], "market_prices": []},
            )
            source = str((entry or {}).get("source") or raw.get("source") or "API externa").strip()
            if source and source not in context["sources"]:
                context["sources"].append(source)
            name = str(raw.get("name") or "").strip()
            if name and name not in context["names"]:
                context["names"].append(name)
            category = str(raw.get("category") or "").strip()
            if category and category not in context["categories"]:
                context["categories"].append(category)
            price = _price_value(raw.get("price"))
            if price is not None and price not in context["market_prices"]:
                context["market_prices"].append(price)

    for context in contexts.values():
        prices = context.get("market_prices") or []
        context["market_reference_price"] = sum(prices) / len(prices) if prices else None
    return contexts

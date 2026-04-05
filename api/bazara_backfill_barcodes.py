import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from api.api_bazara import BazaraAPI
from api.optional_deps import BeautifulSoup, has_beautifulsoup

GRAPHQL_URL = "https://bazara.co.mz/graphql"
BASE_URL = "https://bazara.co.mz"

BARCODE_ATTRS = [
    "barcode",
    "ean",
    "gtin",
    "gtin13",
    "gtin14",
    "gtin12",
    "gtin8",
    "upc",
    "codigo_barras",
    "codigo-de-barras",
    "codigobarras",
    "ean13",
]

QUERY_BY_SKU_ATTR_V2 = (
    "query ($sku: String!) { "
    "products(filter: { sku: { eq: $sku } }) { "
    "items { "
    "sku "
    "url_key "
    "custom_attributesV2(attributes: ["
    + ",".join(f'\"{attr}\"' for attr in BARCODE_ATTRS)
    + "]) { items { attribute_code value } } "
    "} } }"
)

QUERY_BY_SKU_ATTR_LEGACY = (
    "query ($sku: String!) { "
    "products(filter: { sku: { eq: $sku } }) { "
    "items { "
    "sku "
    "url_key "
    "custom_attributes { attribute_code value } "
    "} } }"
)


def _post_json(session, payload, timeout, attempts=2):
    for _ in range(max(attempts, 1)):
        try:
            resp = session.post(GRAPHQL_URL, json=payload, timeout=timeout)
            if resp.status_code != 200:
                continue
            data = resp.json()
            if not isinstance(data, dict):
                continue
            if data.get("errors"):
                continue
            return data
        except Exception:
            continue
    return None


def _fetch_item_by_sku(session, sku, timeout):
    payloads = [
        {"query": QUERY_BY_SKU_ATTR_V2, "variables": {"sku": sku}},
        {"query": QUERY_BY_SKU_ATTR_LEGACY, "variables": {"sku": sku}},
    ]
    for payload in payloads:
        data = _post_json(session, payload, timeout)
        if not data:
            continue
        items = (((data.get("data") or {}).get("products") or {}).get("items")) or []
        if items:
            return items[0]
    return None


def _looks_like_barcode(value: str) -> bool:
    if not value:
        return False
    cleaned = str(value).strip()
    return cleaned.isdigit() and len(cleaned) >= 8


def _extract_barcode_from_item(item: dict) -> str | None:
    if not isinstance(item, dict):
        return None
    for key in BARCODE_ATTRS:
        value = str(item.get(key) or "").strip()
        if _looks_like_barcode(value):
            return value

    attr_container = item.get("custom_attributesV2") or item.get("custom_attributes") or {}
    attr_items = []
    if isinstance(attr_container, dict):
        attr_items = attr_container.get("items") or []
    elif isinstance(attr_container, list):
        attr_items = attr_container

    for attr in attr_items or []:
        if not isinstance(attr, dict):
            continue
        code = str(attr.get("attribute_code") or attr.get("code") or "").strip().lower()
        value = str(attr.get("value") or "").strip()
        if not _looks_like_barcode(value):
            continue
        if code and code not in BARCODE_ATTRS:
            continue
        return value

    return None


def _barcode_from_json_ld(data):
    if isinstance(data, list):
        for item in data:
            value = _barcode_from_json_ld(item)
            if value:
                return value
        return None

    if not isinstance(data, dict):
        return None

    data_type = data.get("@type") or data.get("type")
    if isinstance(data_type, list) and data_type:
        data_type = data_type[0]
    data_type = str(data_type or "").lower()

    if data_type in {"itemlist", "listitem"}:
        item = data.get("item") or {}
        return _barcode_from_json_ld(item)

    if data_type == "product" or data.get("gtin13") or data.get("gtin"):
        for key in ("gtin13", "gtin14", "gtin12", "gtin8", "gtin"):
            value = str(data.get(key) or "").strip()
            if _looks_like_barcode(value):
                return value
        value = str(data.get("sku") or "").strip()
        if _looks_like_barcode(value):
            return value

    for value in data.values():
        if isinstance(value, (dict, list)):
            found = _barcode_from_json_ld(value)
            if found:
                return found

    return None


def _extract_barcode_from_html(html_text: str) -> str | None:
    if not has_beautifulsoup():
        return None
    if not html_text:
        return None

    soup = BeautifulSoup(html_text, "html.parser")
    scripts = soup.select('script[type="application/ld+json"]')
    for script in scripts:
        raw = (script.string or script.text or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        value = _barcode_from_json_ld(data)
        if value:
            return value

    match = re.search(r'"gtin(?:13|14|12|8)?"\s*:\s*"(\d{8,14})"', html_text, re.IGNORECASE)
    if match:
        return match.group(1)

    match = re.search(r'c[oó]digo de barras\s*</[^>]+>\s*<[^>]*>\s*(\d{8,14})', html_text, re.IGNORECASE)
    if match:
        return match.group(1)

    return None


def _fetch_barcode_from_product_page(session, url_key: str, timeout: int) -> str | None:
    if not url_key:
        return None
    url = f"{BASE_URL}/{url_key}.html"
    for _ in range(2):
        try:
            resp = session.get(url, timeout=timeout)
            if resp.status_code != 200:
                continue
            return _extract_barcode_from_html(resp.text)
        except Exception:
            continue
    return None


def _merge_entries(target: dict, source: dict):
    target_data = target.get("data") or {}
    source_data = source.get("data") or {}

    for key, value in source_data.items():
        if not value:
            continue
        if not target_data.get(key):
            target_data[key] = value

    target["data"] = target_data
    target["source"] = target.get("source") or "Bazara"
    target["timestamp"] = datetime.now().isoformat()
    return target


def _emit_progress(on_progress, stats, message=None):
    if not on_progress:
        return
    payload = dict(stats)
    if message:
        payload["message"] = message
    on_progress(payload)


def backfill_barcodes(delay=0.2, limit=None, on_progress=None):
    cache_file = Path(getattr(BazaraAPI, "OFFLINE_CACHE_FILE", "data/cache/bazara_offline_cache.json"))
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    if not cache_file.exists():
        print("Cache Bazara nao encontrado.")
        return

    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:
        print("Cache Bazara invalido.")
        return

    if not isinstance(cache, dict):
        print("Cache Bazara invalido.")
        return

    session = requests.Session()
    session.headers.update(getattr(BazaraAPI, "HEADERS", {}))
    session.headers.update({"Content-Type": "application/json", "Accept": "application/json"})
    timeout = getattr(BazaraAPI, "REQUEST_TIMEOUT", 6)

    stats = {
        "total": len(cache),
        "processed": 0,
        "updated": 0,
        "skipped": 0,
        "no_barcode": 0,
        "errors": 0,
        "moved": 0,
    }

    _emit_progress(on_progress, stats, "Iniciando backfill Bazara...")

    items = list(cache.items())
    for key, entry in items:
        if limit and stats["processed"] >= limit:
            break
        stats["processed"] += 1

        if not isinstance(entry, dict):
            stats["skipped"] += 1
            continue

        data = entry.get("data") if "data" in entry else entry
        if not isinstance(data, dict):
            stats["skipped"] += 1
            continue

        current_barcode = str(data.get("barcode") or key).strip()
        if _looks_like_barcode(current_barcode):
            stats["skipped"] += 1
            continue

        sku = str(data.get("sku") or key).strip()
        if not sku:
            stats["no_barcode"] += 1
            continue

        try:
            item = _fetch_item_by_sku(session, sku, timeout)
            url_key = ""
            barcode = None
            if item:
                url_key = str(item.get("url_key") or data.get("url_key") or "").strip()
                barcode = _extract_barcode_from_item(item)

            if not barcode and url_key:
                barcode = _fetch_barcode_from_product_page(session, url_key, timeout)

            if not barcode:
                stats["no_barcode"] += 1
                continue

            data["barcode"] = barcode
            data["sku"] = sku
            if url_key and not data.get("url_key"):
                data["url_key"] = url_key

            if barcode != key:
                existing = cache.get(barcode)
                if existing:
                    merged = _merge_entries(existing, {"data": data})
                    cache[barcode] = merged
                else:
                    entry["data"] = data
                    entry["source"] = entry.get("source") or "Bazara"
                    entry["timestamp"] = datetime.now().isoformat()
                    cache[barcode] = entry
                del cache[key]
                stats["moved"] += 1
            else:
                entry["data"] = data
                entry["timestamp"] = datetime.now().isoformat()
                cache[key] = entry

            stats["updated"] += 1

        except Exception:
            stats["errors"] += 1

        if stats["processed"] % 5 == 0 or stats["processed"] == stats["total"]:
            _emit_progress(on_progress, stats)

        if delay:
            time.sleep(delay)

    cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    _emit_progress(on_progress, stats, "Backfill concluido.")
    print(
        "Processados: {processed}/{total} | Atualizados: {updated} | "
        "Movidos: {moved} | Sem codigo de barras: {no_barcode} | "
        "Erros: {errors}".format(**stats)
    )
    return stats


def main():
    if not has_beautifulsoup():
        print("BeautifulSoup indisponivel. Instale beautifulsoup4 para executar o backfill Bazara.")
        return
    parser = argparse.ArgumentParser(description="Backfill de codigos de barras no cache Bazara")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay entre requisicoes")
    parser.add_argument("--limit", type=int, default=None, help="Limite de itens (debug)")
    args = parser.parse_args()
    backfill_barcodes(delay=args.delay, limit=args.limit)


if __name__ == "__main__":
    main()

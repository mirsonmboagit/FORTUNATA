import argparse
import json
import os
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

QUERY_NO_SEARCH = (
    "query ($pageSize: Int!, $currentPage: Int!) { "
    "products(pageSize: $pageSize, currentPage: $currentPage) { "
    "total_count "
    "page_info { current_page total_pages } "
    "items { "
    "name "
    "sku "
    "url_key "
    "small_image { url } "
    "image { url } "
    "price_range { minimum_price { final_price { value currency } } } "
    "categories { name } "
    "} } }"
)

QUERY_WITH_SEARCH = (
    "query ($search: String!, $pageSize: Int!, $currentPage: Int!) { "
    "products(search: $search, pageSize: $pageSize, currentPage: $currentPage) { "
    "total_count "
    "page_info { current_page total_pages } "
    "items { "
    "name "
    "sku "
    "url_key "
    "small_image { url } "
    "image { url } "
    "price_range { minimum_price { final_price { value currency } } } "
    "categories { name } "
    "} } }"
)

QUERY_NO_SEARCH_ATTR_V2 = (
    "query ($pageSize: Int!, $currentPage: Int!) { "
    "products(pageSize: $pageSize, currentPage: $currentPage) { "
    "total_count "
    "page_info { current_page total_pages } "
    "items { "
    "name "
    "sku "
    "url_key "
    "small_image { url } "
    "image { url } "
    "price_range { minimum_price { final_price { value currency } } } "
    "categories { name } "
    "custom_attributesV2(attributes: ["
    + ",".join(f'\"{attr}\"' for attr in BARCODE_ATTRS)
    + "]) { items { attribute_code value } } "
    "} } }"
)

QUERY_WITH_SEARCH_ATTR_V2 = (
    "query ($search: String!, $pageSize: Int!, $currentPage: Int!) { "
    "products(search: $search, pageSize: $pageSize, currentPage: $currentPage) { "
    "total_count "
    "page_info { current_page total_pages } "
    "items { "
    "name "
    "sku "
    "url_key "
    "small_image { url } "
    "image { url } "
    "price_range { minimum_price { final_price { value currency } } } "
    "categories { name } "
    "custom_attributesV2(attributes: ["
    + ",".join(f'\"{attr}\"' for attr in BARCODE_ATTRS)
    + "]) { items { attribute_code value } } "
    "} } }"
)

QUERY_NO_SEARCH_ATTR_LEGACY = (
    "query ($pageSize: Int!, $currentPage: Int!) { "
    "products(pageSize: $pageSize, currentPage: $currentPage) { "
    "total_count "
    "page_info { current_page total_pages } "
    "items { "
    "name "
    "sku "
    "url_key "
    "small_image { url } "
    "image { url } "
    "price_range { minimum_price { final_price { value currency } } } "
    "categories { name } "
    "custom_attributes { attribute_code value } "
    "} } }"
)

QUERY_WITH_SEARCH_ATTR_LEGACY = (
    "query ($search: String!, $pageSize: Int!, $currentPage: Int!) { "
    "products(search: $search, pageSize: $pageSize, currentPage: $currentPage) { "
    "total_count "
    "page_info { current_page total_pages } "
    "items { "
    "name "
    "sku "
    "url_key "
    "small_image { url } "
    "image { url } "
    "price_range { minimum_price { final_price { value currency } } } "
    "categories { name } "
    "custom_attributes { attribute_code value } "
    "} } }"
)


def _post_json(session, payload, timeout, attempts=2, allow_errors=False):
    for _ in range(max(attempts, 1)):
        try:
            resp = session.post(GRAPHQL_URL, json=payload, timeout=timeout)
            if resp.status_code != 200:
                continue
            data = resp.json()
            if not isinstance(data, dict):
                continue
            if data.get("errors") and not allow_errors:
                continue
            return data
        except Exception:
            continue
    return None


def _fetch_page(session, query, variables, timeout):
    payload = {"query": query, "variables": variables}
    data = _post_json(session, payload, timeout, allow_errors=True)
    if not data:
        return None, None, None, True
    has_errors = bool(data.get("errors"))
    products = (data.get("data") or {}).get("products") or {}
    items = products.get("items") or []
    page_info = products.get("page_info") or {}
    total_count = products.get("total_count") or 0
    return items, page_info, total_count, has_errors


def _merge_entry(cache, barcode, new_data):
    created = False
    updated = False
    entry = cache.get(barcode)
    if not entry:
        created = True
        entry = {
            "source": "Bazara",
            "data": {"barcode": barcode},
            "timestamp": datetime.now().isoformat(),
        }
        cache[barcode] = entry

    data = entry.get("data") or {}
    if not data.get("barcode"):
        data["barcode"] = barcode
        updated = True

    for key, value in (new_data or {}).items():
        if not value:
            continue
        if not data.get(key):
            data[key] = value
            updated = True

    entry["data"] = data
    if updated:
        entry["timestamp"] = datetime.now().isoformat()

    return created, updated


def _emit_progress(on_progress, stats, message=None):
    if not on_progress:
        return
    payload = dict(stats)
    if message:
        payload["message"] = message
    on_progress(payload)


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


def prefill_bazara_cache(
    page_size=200,
    delay=0.2,
    max_pages=None,
    reset=False,
    on_progress=None,
    fetch_pages=True,
):
    cache_file = getattr(BazaraAPI, "OFFLINE_CACHE_FILE", "data/cache/bazara_offline_cache.json")
    cache_file = Path(cache_file)
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    cache = {}
    if cache_file.exists() and not reset:
        try:
            cache = json.loads(cache_file.read_text(encoding="utf-8"))
            if not isinstance(cache, dict):
                cache = {}
        except Exception:
            cache = {}

    session = requests.Session()
    session.headers.update(getattr(BazaraAPI, "HEADERS", {}))
    session.headers.update({"Content-Type": "application/json", "Accept": "application/json"})
    timeout = getattr(BazaraAPI, "REQUEST_TIMEOUT", 6)

    query_modes = [
        ("no_search_attr_v2", QUERY_NO_SEARCH_ATTR_V2, lambda page: {"pageSize": page_size, "currentPage": page}),
        ("search_empty_attr_v2", QUERY_WITH_SEARCH_ATTR_V2, lambda page: {"search": "", "pageSize": page_size, "currentPage": page}),
        ("search_space_attr_v2", QUERY_WITH_SEARCH_ATTR_V2, lambda page: {"search": " ", "pageSize": page_size, "currentPage": page}),
        ("no_search_attr_legacy", QUERY_NO_SEARCH_ATTR_LEGACY, lambda page: {"pageSize": page_size, "currentPage": page}),
        ("search_empty_attr_legacy", QUERY_WITH_SEARCH_ATTR_LEGACY, lambda page: {"search": "", "pageSize": page_size, "currentPage": page}),
        ("search_space_attr_legacy", QUERY_WITH_SEARCH_ATTR_LEGACY, lambda page: {"search": " ", "pageSize": page_size, "currentPage": page}),
        ("no_search", QUERY_NO_SEARCH, lambda page: {"pageSize": page_size, "currentPage": page}),
        ("search_empty", QUERY_WITH_SEARCH, lambda page: {"search": "", "pageSize": page_size, "currentPage": page}),
        ("search_space", QUERY_WITH_SEARCH, lambda page: {"search": " ", "pageSize": page_size, "currentPage": page}),
    ]

    first = None
    mode = None
    used_mode = None
    for name, query, build_vars in query_modes:
        items, page_info, total_count, has_errors = _fetch_page(session, query, build_vars(1), timeout)
        if has_errors and not items and not total_count:
            continue
        if items or total_count:
            first = (items, page_info, total_count)
            mode = (query, build_vars)
            used_mode = name
            break

    stats = {
        "total": 0,
        "processed": 0,
        "success": 0,
        "new": 0,
        "updated": 0,
        "no_sku": 0,
        "errors": 0,
        "pages": 0,
    }

    if not first or not mode:
        _emit_progress(on_progress, stats, "Nenhum resultado retornado pelo GraphQL.")
        print("Nenhum resultado retornado pelo GraphQL.")
        return stats

    api = BazaraAPI()
    items, page_info, total_count = first
    total_pages = page_info.get("total_pages") if isinstance(page_info, dict) else None
    if not total_pages and total_count and page_size:
        total_pages = (total_count + page_size - 1) // page_size
    if not total_pages:
        total_pages = 1

    if total_count:
        stats["total"] = total_count
    else:
        stats["total"] = total_pages * page_size

    def handle_items(items_list):
        for item in items_list or []:
            sku = (item.get("sku") or "").strip()
            url_key = (item.get("url_key") or "").strip()
            stats["processed"] += 1
            barcode = sku if _looks_like_barcode(sku) else _extract_barcode_from_item(item)
            if not barcode and fetch_pages:
                barcode = _fetch_barcode_from_product_page(session, url_key, timeout)
            if not barcode:
                stats["no_sku"] += 1
                continue
            data = {
                "barcode": barcode,
                "sku": sku,
                "url_key": url_key,
                "name": item.get("name") or "",
                "price": api._extract_graphql_price(item),
                "image": api._extract_graphql_image(item),
                "category": api._extract_graphql_category(item),
            }
            created, updated = _merge_entry(cache, barcode, data)
            if created:
                stats["new"] += 1
                stats["success"] += 1
            elif updated:
                stats["updated"] += 1
                stats["success"] += 1

    current_page = 1
    query, build_vars = mode

    _emit_progress(on_progress, stats, "Iniciando prefill Bazara...")
    if used_mode:
        _emit_progress(on_progress, stats, f"Modo GraphQL: {used_mode}")

    while True:
        stats["pages"] += 1
        try:
            handle_items(items)
        except Exception:
            stats["errors"] += 1

        _emit_progress(on_progress, stats)

        if max_pages and current_page >= max_pages:
            break
        if current_page >= total_pages:
            break

        current_page += 1
        items, page_info, total_count, has_errors = _fetch_page(session, query, build_vars(current_page), timeout)
        if has_errors and not items and not total_count:
            stats["errors"] += 1
            break
        if items is None:
            stats["errors"] += 1
            break

        if delay:
            time.sleep(delay)

    cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    _emit_progress(on_progress, stats, "Prefill concluido.")
    print(f"Cache Bazara salvo em {cache_file} ({len(cache)} produtos).")
    print(
        "Processados: {processed} | Novos: {new} | Atualizados: {updated} | "
        "Sem codigo de barras: {no_sku} | Erros: {errors} | Paginas: {pages}".format(**stats)
    )
    return stats


def main():
    if not has_beautifulsoup():
        print("BeautifulSoup indisponivel. Instale beautifulsoup4 para executar o prefill Bazara.")
        return
    parser = argparse.ArgumentParser(description="Prefill do cache offline do Bazara via GraphQL")
    parser.add_argument("--page-size", type=int, default=200, help="Tamanho da pagina")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay entre paginas")
    parser.add_argument("--max-pages", type=int, default=None, help="Limite de paginas (debug)")
    parser.add_argument("--reset", action="store_true", help="Ignora cache atual e recria do zero")
    parser.add_argument("--no-page-barcode", action="store_true", help="Nao abrir pagina do produto para buscar codigo de barras")
    args = parser.parse_args()
    prefill_bazara_cache(
        page_size=args.page_size,
        delay=args.delay,
        max_pages=args.max_pages,
        reset=args.reset,
        fetch_pages=not args.no_page_barcode,
    )


if __name__ == "__main__":
    main()

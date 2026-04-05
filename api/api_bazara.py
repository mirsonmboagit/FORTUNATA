import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests

from api.optional_deps import BeautifulSoup, has_beautifulsoup


class BazaraAPI:
    BASE_URL = "https://bazara.co.mz"
    BASE_URLS = (BASE_URL, "https://www.bazara.co.mz")
    SEARCH_PATH = "/catalogsearch/result/"
    GRAPHQL_PATH = "/graphql"
    GRAPHQL_QUERY = (
        "query ($search: String!) { "
        "products(search: $search, pageSize: 5) { "
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
    GRAPHQL_QUERY_SKU = (
        "query ($sku: String!) { "
        "products(filter: { sku: { eq: $sku } }) { "
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

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
        "Cache-Control": "max-age=0",
        "Upgrade-Insecure-Requests": "1",
    }
    REQUEST_TIMEOUT = 6
    WARM_TIMEOUT = 6

    CATEGORY_MAP = {
        "Bebidas": "Bebidas",
        "Refrigerantes": "Bebidas",
        "Mercearia": "Alimentos",
        "Laticinios": "Alimentos",
        "Laticínios": "Alimentos",
    }
    OFFLINE_CACHE_FILE = Path("data/cache/bazara_offline_cache.json")


    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(self.HEADERS)
        self._offline_cache_file = self.OFFLINE_CACHE_FILE
        self._offline_cache_mtime = None
        self._offline_cache = self._load_offline_cache()

    def _load_offline_cache(self):
        try:
            self._offline_cache_file.parent.mkdir(parents=True, exist_ok=True)
            if self._offline_cache_file.exists():
                with open(self._offline_cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
        except Exception as e:
            print(f"[Bazara] Erro ao carregar cache offline: {e}")
        return {}

    def _save_offline_cache(self):
        try:
            self._offline_cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._offline_cache_file, "w", encoding="utf-8") as f:
                json.dump(self._offline_cache, f, ensure_ascii=False, indent=2)
            try:
                self._offline_cache_mtime = self._offline_cache_file.stat().st_mtime
            except Exception:
                pass
        except Exception as e:
            print(f"[Bazara] Erro ao salvar cache offline: {e}")

    def _upsert_offline_cache(self, barcode: str, data: dict):
        if not barcode:
            return
        payload = dict(data) if isinstance(data, dict) else {}
        payload["barcode"] = barcode
        entry = self._offline_cache.get(barcode)
        if not entry:
            entry = {
                "source": "Bazara",
                "data": {"barcode": barcode},
                "timestamp": datetime.now().isoformat(),
            }
            self._offline_cache[barcode] = entry

        data_entry = entry.get("data") or {}
        if not data_entry.get("barcode"):
            data_entry["barcode"] = barcode
        for key, value in payload.items():
            if not value:
                continue
            if not data_entry.get(key):
                data_entry[key] = value
        entry["data"] = data_entry
        entry["source"] = entry.get("source") or "Bazara"
        entry["timestamp"] = datetime.now().isoformat()
        self._save_offline_cache()

    def _maybe_reload_offline_cache(self):
        try:
            if not self._offline_cache_file.exists():
                return
            mtime = self._offline_cache_file.stat().st_mtime
            if self._offline_cache_mtime is None or mtime > self._offline_cache_mtime:
                self._offline_cache = self._load_offline_cache()
                self._offline_cache_mtime = mtime
        except Exception:
            return

    def _get_from_offline_cache(self, barcode: str) -> dict | None:
        if not barcode:
            return None
        self._maybe_reload_offline_cache()
        entry = self._offline_cache.get(barcode)
        if not entry:
            return None
        if isinstance(entry, dict):
            data = entry.get("data") if "data" in entry else entry
        else:
            return None
        if isinstance(data, dict) and not data.get("barcode"):
            data = dict(data)
            data["barcode"] = barcode
        return data or None

    def fetch(self, barcode: str) -> dict | None:
        """
        Busca um produto pelo codigo de barras no cache offline do Bazara.
        Nao faz chamadas online; para preencher use o script bazara_prefill.py.
        """
        try:
            barcode = str(barcode).strip()
            if not barcode:
                return None
            return self._get_from_offline_cache(barcode)

        except Exception as e:
            print(f"[Bazara] Erro: {e}")
            return None

    def _fetch_from_base(self, base_url: str, barcode: str) -> dict | None:
        if not has_beautifulsoup():
            return None
        response = self._get_search_page(base_url, barcode)
        if not response:
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        product = self._extract_from_json_ld(soup, base_url)
        if not product:
            product = self._extract_from_search_page(soup, base_url)

        if not product:
            return None

        product_url = product.get("url")
        if product_url and not product.get("category"):
            category = self._fetch_category(product_url)
            product["category"] = self._normalize_category(category)

        product.pop("url", None)
        return product

    def _fetch_graphql(self, base_url: str, barcode: str) -> dict | None:
        items = self._graphql_items(
            base_url,
            {"query": self.GRAPHQL_QUERY, "variables": {"search": barcode}},
        )
        if not items:
            items = self._graphql_items(
                base_url,
                {"query": self.GRAPHQL_QUERY_SKU, "variables": {"sku": barcode}},
            )

        if not items:
            return None

        item = items[0] or {}
        name = item.get("name") or ""
        image = self._extract_graphql_image(item)
        price = self._extract_graphql_price(item)
        category = self._extract_graphql_category(item)

        if not name and not price:
            return None

        return {
            "name": name,
            "price": price,
            "image": image,
            "category": self._normalize_category(category),
        }

    def _graphql_items(self, base_url: str, payload: dict) -> list:
        url = urljoin(base_url, self.GRAPHQL_PATH)
        headers = dict(self.HEADERS)
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"

        try:
            response = self._session.post(url, headers=headers, json=payload, timeout=self.REQUEST_TIMEOUT)
        except Exception:
            return []

        if response.status_code != 200:
            return []

        try:
            data = response.json()
        except Exception:
            return []

        if not isinstance(data, dict) or data.get("errors"):
            return []

        return (data.get("data") or {}).get("products", {}).get("items") or []

    def _get_search_page(self, base_url: str, barcode: str):
        search_url = urljoin(base_url, self.SEARCH_PATH)
        response = self._get(search_url, params={"q": barcode}, referer=base_url, timeout=self.REQUEST_TIMEOUT)
        if response:
            return response

        self._warm_session(base_url)
        return self._get(search_url, params={"q": barcode}, referer=base_url, timeout=self.REQUEST_TIMEOUT)

    def _get(self, url: str, params=None, referer: str | None = None, timeout: int | None = None):
        headers = dict(self.HEADERS)
        if referer:
            headers["Referer"] = referer
        timeout = timeout or self.REQUEST_TIMEOUT
        response = self._session.get(url, headers=headers, params=params, timeout=timeout, allow_redirects=True)
        if response.status_code != 200:
            return None
        if self._looks_blocked(response.text):
            return None
        return response

    def _warm_session(self, base_url: str):
        try:
            self._session.get(base_url, headers=self.HEADERS, timeout=self.WARM_TIMEOUT, allow_redirects=True)
        except Exception:
            return

    @staticmethod
    def _looks_blocked(text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        return (
            "cf-chl" in lowered
            or "just a moment" in lowered
            or "access denied" in lowered
            or "captcha" in lowered
        )

    def _extract_from_search_page(self, soup: BeautifulSoup, base_url: str) -> dict | None:
        elements = soup.select("li.product-item, div.product-item-info, div.product-item-details")
        for element in elements:
            product = self._parse_product_element(element, base_url)
            if product:
                return product
        return None

    def _extract_from_json_ld(self, soup: BeautifulSoup, base_url: str) -> dict | None:
        scripts = soup.select('script[type="application/ld+json"]')
        for script in scripts:
            raw = (script.string or script.text or "").strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            product = self._product_from_json_ld(data, base_url)
            if product:
                return product
        return None

    def _product_from_json_ld(self, data, base_url: str) -> dict | None:
        if isinstance(data, list):
            for item in data:
                product = self._product_from_json_ld(item, base_url)
                if product:
                    return product
            return None

        if not isinstance(data, dict):
            return None

        data_type = data.get("@type") or data.get("type")
        if isinstance(data_type, list) and data_type:
            data_type = data_type[0]
        data_type = str(data_type or "").lower()

        if data_type == "itemlist" and data.get("itemListElement"):
            for item in data.get("itemListElement") or []:
                product = self._product_from_json_ld(item, base_url)
                if product:
                    return product
            return None

        if data_type == "listitem":
            item = data.get("item") or {}
            product = self._product_from_json_ld(item, base_url)
            if product:
                if not product.get("url") and data.get("url"):
                    product["url"] = self._ensure_absolute_url(base_url, data.get("url"))
                return product
            return None

        if data_type == "product":
            name = data.get("name") or ""
            image = data.get("image") or ""
            if isinstance(image, dict):
                image = image.get("url") or ""
            if isinstance(image, list):
                image = image[0] if image else ""
            offers = data.get("offers") or {}
            price = ""
            url = data.get("url") or ""
            if isinstance(offers, list) and offers:
                price = offers[0].get("price") or offers[0].get("lowPrice") or ""
                url = url or offers[0].get("url") or ""
            elif isinstance(offers, dict):
                price = offers.get("price") or offers.get("lowPrice") or ""
                url = url or offers.get("url") or ""
            product = self._build_product(name, price, image, url, base_url)
            if not product.get("name") and not product.get("price"):
                return None
            return product

        return None

    def _parse_product_element(self, element, base_url: str) -> dict | None:
        name_tag = element.select_one("a.product-item-link, a.product-item-name, a.product-item-photo, a")
        name = ""
        product_url = ""
        if name_tag:
            name = name_tag.get_text(strip=True) or name_tag.get("title", "").strip()
            if name_tag.has_attr("href"):
                product_url = name_tag["href"]

        price_text = self._extract_price_text(element)
        image_url = self._extract_image_url(element)

        product = self._build_product(name, price_text, image_url, product_url, base_url)
        if not product.get("name"):
            return None
        return product

    @staticmethod
    def _extract_graphql_price(item: dict) -> str:
        price_range = item.get("price_range") or {}
        minimum = price_range.get("minimum_price") or {}
        final_price = minimum.get("final_price") or {}
        value = final_price.get("value")
        if value is None:
            return ""
        try:
            return str(value)
        except Exception:
            return ""

    @staticmethod
    def _extract_graphql_image(item: dict) -> str:
        small = item.get("small_image") or {}
        image = item.get("image") or {}
        return small.get("url") or image.get("url") or ""

    @staticmethod
    def _extract_graphql_category(item: dict) -> str | None:
        categories = item.get("categories") or []
        preferred = None
        for cat in categories:
            name = (cat or {}).get("name")
            if not name:
                continue
            lowered = str(name).strip().lower()
            if lowered in {"todos produtos", "todos os produtos", "todos"}:
                continue
            preferred = name
            break
        if preferred:
            return preferred
        if categories:
            return (categories[0] or {}).get("name")
        return None

    def _build_product(
        self,
        name: str | None,
        price_text,
        image_url: str | None,
        product_url: str | None,
        base_url: str,
    ) -> dict:
        clean_price = ""
        if price_text is not None and str(price_text).strip():
            clean_price = self.normalize_price(str(price_text))
        image = self._ensure_absolute_url(base_url, image_url) if image_url else ""
        url = self._ensure_absolute_url(base_url, product_url) if product_url else None
        return {
            "name": name or "",
            "price": clean_price,
            "image": image,
            "category": None,
            "url": url,
        }

    @staticmethod
    def _extract_price_text(element) -> str:
        price_tag = element.select_one("span.price-wrapper span.price, span.price")
        if price_tag:
            price_text = price_tag.get_text(strip=True)
            if price_text:
                return price_text

        price_holder = element.select_one("[data-price-amount]")
        if price_holder and price_holder.has_attr("data-price-amount"):
            return str(price_holder.get("data-price-amount", "")).strip()

        return ""

    @staticmethod
    def _extract_image_url(element) -> str:
        img_tag = element.select_one("img")
        if not img_tag:
            return ""
        return (
            img_tag.get("data-src")
            or img_tag.get("data-original")
            or img_tag.get("data-lazy")
            or img_tag.get("src")
            or ""
        )

    @staticmethod
    def _ensure_absolute_url(base_url: str, url_value: str | None) -> str | None:
        if not url_value:
            return None
        if url_value.startswith("http://") or url_value.startswith("https://"):
            return url_value
        return urljoin(base_url, url_value)

    def _fetch_category(self, product_url: str) -> str | None:
        """
        Abre a pagina do produto e extrai a categoria a partir do breadcrumb.
        """
        if not has_beautifulsoup():
            return None
        try:
            response = self._session.get(product_url, headers=self.HEADERS, timeout=self.REQUEST_TIMEOUT, allow_redirects=True)
            if response.status_code != 200:
                return None
            if self._looks_blocked(response.text):
                return None

            soup = BeautifulSoup(response.text, "html.parser")
            crumbs = soup.select("nav.breadcrumbs li")
            categories = [c.text.strip() for c in crumbs][1:]  # remove "Home"

            return categories[-1] if categories else None

        except Exception:
            return None

    def _normalize_category(self, category: str | None) -> str | None:
        if not category:
            return None
        return self.CATEGORY_MAP.get(category, category)

    @staticmethod
    def normalize_price(price_text: str) -> str:
        """
        Converte formatos como '1.250,00 MT' para '1250.00'.
        """
        if not price_text:
            return ""

        cleaned = re.sub(r"[^\d,\.]", "", price_text)

        if "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")

        return cleaned

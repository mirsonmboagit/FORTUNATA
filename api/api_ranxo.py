import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


class RanxoAPI:
    BASE_URL = "https://www.ranxo.co.mz"
    SEARCH_ENDPOINT = "/wp-admin/admin-ajax.php"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    }
    REQUEST_TIMEOUT = 6

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(self.HEADERS)

    def fetch(self, barcode: str) -> dict | None:
        """
        Busca um produto pelo codigo de barras no Ranxo via AJAX search.
        Retorna um dicionario com nome, preco, imagem e categoria, ou None.
        """
        try:
            barcode = str(barcode).strip()
            if not barcode:
                return None

            suggestion = self._search_suggestions(barcode)
            if not suggestion:
                return None

            name = suggestion.get("value") or ""
            image = suggestion.get("img") or ""
            price_html = suggestion.get("price") or ""
            price = self.normalize_price(self._extract_price_text(price_html))
            product_url = suggestion.get("link") or ""
            category = self._fetch_category(product_url) if product_url else None

            return {
                "name": name,
                "price": price,
                "image": image,
                "category": category,
            }

        except requests.exceptions.Timeout:
            print(f"[Ranxo] Timeout ao buscar barcode {barcode}")
            return None
        except Exception as e:
            print(f"[Ranxo] Erro: {e}")
            return None

    def _search_suggestions(self, barcode: str) -> dict | None:
        url = urljoin(self.BASE_URL, self.SEARCH_ENDPOINT)
        params = {
            "action": "sw_search_products_callback",
            "limit": "5",
            "search_type": "1",
            "query": barcode,
        }

        response = self._session.get(url, params=params, timeout=self.REQUEST_TIMEOUT)
        if response.status_code != 200 or not response.text:
            return None

        try:
            data = response.json()
        except Exception:
            try:
                data = json.loads(response.text)
            except Exception:
                return None

        suggestions = data.get("suggestions") or []
        if not suggestions:
            return None

        for item in suggestions:
            if str(item.get("sku", "")).strip() == barcode:
                return item

        return suggestions[0]

    def _fetch_category(self, product_url: str) -> str | None:
        try:
            response = self._session.get(product_url, timeout=self.REQUEST_TIMEOUT, allow_redirects=True)
            if response.status_code != 200:
                return None
            soup = BeautifulSoup(response.text, "html.parser")
            crumbs = [a.get_text(strip=True) for a in soup.select("nav.woocommerce-breadcrumb a")]
            if len(crumbs) >= 2:
                return crumbs[-1]

            posted = soup.select(".posted_in a")
            if posted:
                return posted[0].get_text(strip=True)
        except Exception:
            return None

        return None

    @staticmethod
    def _extract_price_text(price_html: str) -> str:
        if not price_html:
            return ""
        soup = BeautifulSoup(price_html, "html.parser")
        return soup.get_text(" ", strip=True)

    @staticmethod
    def normalize_price(price_text: str) -> str:
        if not price_text:
            return ""
        cleaned = re.sub(r"[^\d,\.]", "", price_text)
        if "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")
        return cleaned

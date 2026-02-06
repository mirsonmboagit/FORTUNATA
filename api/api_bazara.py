import re
import requests
from bs4 import BeautifulSoup


class BazaraAPI:
    BASE_URL = "https://bazara.co.mz"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8"
    }

    CATEGORY_MAP = {
        "Bebidas": "Bebidas",
        "Refrigerantes": "Bebidas",
        "Mercearia": "Alimentos",
        "Laticínios": "Alimentos",
    }

    def fetch(self, barcode: str) -> dict | None:
        """
        Busca um produto pelo código de barras no site Bazara.
        Retorna um dicionário com nome, preço, imagem e categoria, ou None.
        """
        try:
            search_url = f"{self.BASE_URL}/catalogsearch/result/?q={barcode}"
            response = requests.get(search_url, headers=self.HEADERS, timeout=12)

            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, "html.parser")
            product_element = soup.select_one("div.product-item-info")

            if not product_element:
                return None

            return self._parse_product(product_element)

        except requests.exceptions.Timeout:
            print(f"[Bazara] Timeout ao buscar barcode {barcode}")
            return None
        except Exception as e:
            print(f"[Bazara] Erro: {e}")
            return None

    def _parse_product(self, element) -> dict:
        name_tag  = element.select_one("a.product-item-link")
        price_tag = element.select_one("span.price-wrapper span.price")
        img_tag   = element.select_one("img")

        product_url = name_tag["href"] if name_tag and name_tag.has_attr("href") else None
        category    = self._fetch_category(product_url) if product_url else None

        return {
            "name":     name_tag.text.strip()                                  if name_tag              else "",
            "price":    self.normalize_price(price_tag.text.strip())           if price_tag             else "",
            "image":    img_tag["src"]                                         if img_tag and img_tag.has_attr("src") else "",
            "category": self.CATEGORY_MAP.get(category, category)              if category              else None,
        }

    def _fetch_category(self, product_url: str) -> str | None:
        """
        Abre a página do produto e extrai a categoria a partir do breadcrumb.
        """
        try:
            response = requests.get(product_url, headers=self.HEADERS, timeout=10)
            if response.status_code != 200:
                return None

            soup      = BeautifulSoup(response.text, "html.parser")
            crumbs    = soup.select("nav.breadcrumbs li")
            categories = [c.text.strip() for c in crumbs][1:]  # remove "Home"

            return categories[-1] if categories else None

        except Exception:
            return None

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
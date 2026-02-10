import requests

import requests

class OpenFoodFactsAPI:
    BASE_URL = "https://world.openfoodfacts.org/api/v2"

    HEADERS = {
        "User-Agent": "ProductScanner/2.0"
    }

    WEIGHT_UNITS = {"kg", "g", "gram", "kilo"}

    def fetch(self, barcode: str) -> dict | None:
        """
        Busca um produto pelo código de barras na API do Open Food Facts.
        Retorna um dicionário normalizado ou None.
        """
        try:
            url      = f"{self.BASE_URL}/product/{barcode}"
            response = requests.get(url, headers=self.HEADERS, timeout=10)

            if response.status_code != 200:
                return None

            data = response.json()

            if data.get("status") != 1 or "product" not in data:
                return None

            return self._parse_product(data["product"])

        except requests.exceptions.Timeout:
            print(f"[OpenFoodFacts] Timeout ao buscar barcode {barcode}")
            return None
        except Exception as e:
            print(f"[OpenFoodFacts] Erro: {e}")
            return None

    def _parse_product(self, raw: dict) -> dict:
        name = (
            raw.get("product_name_pt")
            or raw.get("product_name")
            or raw.get("product_name_en")
            or raw.get("product_name_fr")
            or raw.get("product_name_es")
            or raw.get("product_name_it")
            or raw.get("product_name_de")
            or raw.get("generic_name")
            or raw.get("abbreviated_product_name")
            or ""
        )

        brand = raw.get("brands", "")
        if not brand:
            brand_tags = raw.get("brands_tags") or []
            if brand_tags:
                brand = str(brand_tags[0]).replace("-", " ").replace("_", " ").title()

        category = self._extract_category(raw.get("categories_tags") or raw.get("categories_hierarchy") or [])
        if not category:
            categories_text = (
                raw.get("categories")
                or raw.get("categories_en")
                or raw.get("categories_fr")
                or raw.get("categories_pt")
                or ""
            )
            if categories_text:
                parts = [p.strip() for p in str(categories_text).split(",") if p.strip()]
                if parts:
                    category = parts[-1].title()
        expiry = raw.get("expiration_date", "") or raw.get("expiration_date_en", "")

        quantity_text = raw.get("quantity") or ""
        if not quantity_text:
            product_qty = raw.get("product_quantity")
            product_unit = raw.get("product_quantity_unit") or ""
            if product_qty:
                if product_unit:
                    quantity_text = f"{product_qty} {product_unit}".strip()
                else:
                    quantity_text = str(product_qty)
        if not quantity_text:
            quantity_text = raw.get("serving_size") or ""

        price = raw.get("price") or raw.get("product_price") or ""

        quantity_lower = str(quantity_text).lower() if quantity_text else ""
        sold_by_weight = any(unit in quantity_lower for unit in self.WEIGHT_UNITS)

        return {
            "name":           name,
            "brand":          brand,
            "category":       category,
            "expiry_date":    expiry,
            "sold_by_weight": sold_by_weight,
            "quantity":       quantity_text if isinstance(quantity_text, str) else str(quantity_text),
            "price":          str(price) if price else "",
            "image":          raw.get("image_url") or raw.get("image_front_url") or raw.get("image_small_url") or "",
        }

    @staticmethod
    def _extract_category(categories_tags: list) -> str | None:
        """
        Extrai a última categoria da lista de tags.
        Exemplo: ['en:foods', 'en:dairy-products'] -> 'Dairy Products'
        """
        if not categories_tags:
            return None

        last_tag = categories_tags[-1]
        cleaned  = last_tag.split(":")[1] if ":" in last_tag else last_tag

        return cleaned.replace("-", " ").title()

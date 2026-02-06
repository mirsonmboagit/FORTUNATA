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
            or raw.get("generic_name")
            or ""
        )

        brand = raw.get("brands", "")

        category = self._extract_category(raw.get("categories_tags", []))

        expiry = raw.get("expiration_date", "")

        quantity      = raw.get("quantity", "").lower()
        sold_by_weight = any(unit in quantity for unit in self.WEIGHT_UNITS)

        return {
            "name":           name,
            "brand":          brand,
            "category":       category,
            "expiry_date":    expiry,
            "sold_by_weight": sold_by_weight,
            "image":          raw.get("image_url", ""),
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
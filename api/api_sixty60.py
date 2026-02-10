import requests


class Sixty60API:
    BASE_URL = "https://www.sixty60.co.za/api"

    HEADERS = {
        "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept":       "application/json",
        "Content-Type": "application/json",
    }

    WEIGHT_UNITS = {"kg", "g", "gram", "kilo", "per kg"}

    def fetch(self, barcode: str) -> dict | None:
        """
        Busca um produto pelo código de barras na API do Sixty60.
        Tenta primeiro o endpoint direto, depois o endpoint de busca.
        Retorna um dicionário normalizado ou None.
        """
        product = self._fetch_by_barcode(barcode)

        if not product:
            product = self._fetch_by_search(barcode)

        if not product:
            return None

        return self._parse_product(product)

    def _fetch_by_barcode(self, barcode: str) -> dict | None:
        """Endpoint direto por código de barras."""
        try:
            url      = f"{self.BASE_URL}/products/barcode/{barcode}"
            response = requests.get(url, headers=self.HEADERS, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if data and isinstance(data, dict):
                    return data
        except Exception:
            pass

        return None

    def _fetch_by_search(self, barcode: str) -> dict | None:
        """Endpoint de busca por texto."""
        try:
            url      = f"{self.BASE_URL}/products/search"
            params   = {"q": barcode, "barcode": barcode}
            response = requests.get(url, params=params, headers=self.HEADERS, timeout=10)

            if response.status_code == 200:
                data     = response.json()
                products = data.get("products") or data.get("results") or []

                if products:
                    return products[0]
        except Exception:
            pass

        return None

    def _parse_product(self, raw: dict) -> dict:
        name = (
            raw.get("name")
            or raw.get("title")
            or raw.get("description")
            or ""
        )

        brand    = raw.get("brand", "")
        category = raw.get("category") or raw.get("categoryName") or raw.get("department") or ""

        price         = raw.get("price") or raw.get("sellingPrice") or 0
        sold_by_weight = False

        size_info = raw.get("size") or raw.get("unit") or raw.get("quantity") or ""
        if size_info:
            sold_by_weight = any(unit in str(size_info).lower() for unit in self.WEIGHT_UNITS)

        # Preços maiores que 100 provavelmente estão em centavos
        if price and price > 100:
            price = price / 100

        return {
            "name":           name,
            "brand":          brand,
            "category":       category,
            "price":          str(price) if price else "",
            "sold_by_weight": sold_by_weight,
            "quantity":       size_info,
            "image":          raw.get("imageUrl") or raw.get("image") or raw.get("thumbnail") or "",
        }

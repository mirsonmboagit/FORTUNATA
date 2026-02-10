import requests


class UPCitemdbAPI:
    BASE_URL = "https://api.upcitemdb.com/prod/trial"

    HEADERS = {
        "User-Agent": "ProductScanner/2.0",
        "Accept":     "application/json",
    }

    WEIGHT_UNITS = {"kg", "g", "gram", "kilo", "lb", "oz"}

    def fetch(self, barcode: str) -> dict | None:
        """
        Busca um produto pelo código de barras na API do UPCitemdb.
        Retorna um dicionário normalizado ou None.

        
        """
        try:
            url      = f"{self.BASE_URL}/lookup"
            response = requests.get(url, params={"upc": barcode}, headers=self.HEADERS, timeout=10)

            if response.status_code == 429:
                print("[UPCitemdb] Limite de requisições atingido")
                return None

            if response.status_code != 200:
                return None

            data = response.json()

            if data.get("code") != "OK":
                return None

            items = data.get("items", [])
            if not items:
                return None

            return self._parse_product(items[0])

        except requests.exceptions.Timeout:
            print(f"[UPCitemdb] Timeout ao buscar barcode {barcode}")
            return None
        except Exception as e:
            print(f"[UPCitemdb] Erro: {e}")
            return None

    def _parse_product(self, raw: dict) -> dict:
        title = raw.get("title", "")
        brand = raw.get("brand", "")
        size  = raw.get("size", "")

        sold_by_weight = any(unit in size.lower() for unit in self.WEIGHT_UNITS) if size else False

        return {
            "name":           title,
            "brand":          brand,
            "category":       raw.get("category", ""),
            "sold_by_weight": sold_by_weight,
            "quantity":       size,
            "image":          raw.get("images", [None])[0] if raw.get("images") else None,
        }

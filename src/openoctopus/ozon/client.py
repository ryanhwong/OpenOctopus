import httpx

from openoctopus.ozon.paths import PATHS

BASE_URL = "https://api-seller.ozon.ru"


class OzonClient:
    def __init__(self, http: httpx.AsyncClient, client_id: str, api_key: str):
        self.http = http
        self.headers = {"Client-Id": client_id, "Api-Key": api_key}

    async def _post(self, path: str, payload: dict | None = None) -> dict:
        r = await self.http.post(path, json=payload or {}, headers=self.headers)
        r.raise_for_status()
        data = r.json()
        if data is None:
            raise RuntimeError(f"ozon returned null body for {path}")
        return data

    async def category_tree(self, language: str = "RU") -> dict:
        return await self._post(PATHS["category_tree"], {"language": language})

    async def category_attributes(self, description_category_id: int, type_id: int) -> list[dict]:
        out = await self._post(PATHS["category_attributes"],
                               {"description_category_id": description_category_id,
                                "type_id": type_id, "language": "RU"})
        res = out.get("result", [])
        if isinstance(res, dict):
            return res.get("attributes", [])
        return res

    async def import_products(self, items: list[dict]) -> dict:
        return await self._post(PATHS["import"], {"items": items})

    async def import_task_info(self, task_id: int) -> dict:
        return await self._post(PATHS["import_info"], {"task_id": task_id})

    async def category_attribute_values(self, attribute_id: int, description_category_id: int,
                                          type_id: int, limit: int = 100) -> list[dict]:
        out = await self._post(PATHS["category_attributes"].replace("/attribute", "/attribute/values"),
                               {"attribute_id": attribute_id,
                                "description_category_id": description_category_id,
                                "type_id": type_id, "language": "RU", "limit": limit})
        res = out.get("result", [])
        return res if isinstance(res, list) else []

    async def update_price(self, product_id: int, price: float,
                           old_price: float | None = None) -> dict:
        item = {"product_id": product_id, "price": str(price)}
        if old_price and old_price > price:
            item["old_price"] = str(old_price)
        return await self._post("/v1/product/import/prices", {"prices": [item]})

    async def set_stocks(self, stocks: list[dict]) -> dict:
        """stocks 每项: {offer_id, product_id, stock, warehouse_id}"""
        return await self._post("/v2/products/stocks", {"stocks": stocks})

    async def product_info_list(self, product_ids: list[int]) -> list[dict]:
        out = await self._post("/v3/product/info/list", {"product_id": product_ids})
        return out.get("items", []) if isinstance(out, dict) else []

    async def rating_by_sku(self, skus: list[str]) -> list[dict]:
        out = await self._post("/v1/product/rating-by-sku", {"skus": skus})
        return out.get("products", []) if isinstance(out, dict) else []

    async def product_prices_info(self, offer_ids: list[str]) -> list[dict]:
        out = await self._post("/v5/product/info/prices",
                               {"filter": {"offer_id": offer_ids}, "limit": len(offer_ids) or 1})
        return out.get("items", []) if isinstance(out, dict) else []

    async def actions_list(self) -> list[dict]:
        r = await self.http.request("GET", "/v1/actions", headers=self.headers)
        r.raise_for_status()
        data = r.json()
        return data.get("result", []) if isinstance(data, dict) else []

    async def action_candidates(self, action_id: int, limit: int = 500,
                                offset: int = 0) -> list[dict]:
        out = await self._post("/v1/actions/candidates",
                               {"action_id": action_id, "limit": limit, "offset": offset})
        res = out.get("result") or {}
        return res.get("products", []) if isinstance(res, dict) else []

    async def action_activate(self, action_id: int, products: list[dict]) -> dict:
        return await self._post("/v1/actions/products/activate",
                                {"action_id": action_id, "products": products})

    async def action_deactivate(self, action_id: int, product_ids: list[int]) -> dict:
        return await self._post("/v1/actions/products/deactivate",
                                {"action_id": action_id, "product_ids": product_ids})

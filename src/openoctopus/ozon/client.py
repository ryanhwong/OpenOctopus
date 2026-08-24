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
        return r.json()

    async def category_tree(self, language: str = "RU") -> dict:
        return await self._post(PATHS["category_tree"], {"language": language})

    async def category_attributes(self, category_id: int) -> list[dict]:
        out = await self._post(PATHS["category_attributes"], {"description_category_id": category_id,
                                                              "language": "RU"})
        res = out.get("result", [])
        if isinstance(res, dict):
            return res.get("attributes", [])
        return res

    async def import_products(self, items: list[dict]) -> dict:
        return await self._post(PATHS["import"], {"items": items})

    async def import_task_info(self, task_id: int) -> dict:
        return await self._post(PATHS["import_info"], {"task_id": task_id})

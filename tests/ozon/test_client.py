import json

import httpx

from openoctopus.ozon.client import OzonClient


def make_ozon(handler):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api-seller.ozon.ru")
    return OzonClient(http, "cid", "key")


async def test_import_products_sends_auth_and_items():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = (request.headers.get("Client-Id"), request.headers.get("Api-Key"))
        return httpx.Response(200, json={"result": {"task_id": 7}})

    ozon = make_ozon(handler)
    out = await ozon.import_products([{"offer_id": "1"}])
    await ozon.http.aclose()
    assert out["result"]["task_id"] == 7
    assert seen["auth"] == ("cid", "key")
    assert "/import" in seen["path"]


async def test_category_tree_flatten():
    tree = {"result": [{"category_id": 1, "category_name": "Дом", "childs": [
        {"category_id": 2, "category_name": "Посуда", "type_name": "Термос"}]}]}
    make_ozon(lambda req: httpx.Response(200, json=json.loads(json.dumps(tree))))
    rows = []
    from openoctopus.category.sync import flatten_tree
    for top in tree["result"]:
        rows += flatten_tree(top)
    assert ("2", "1", "Посуда") in rows

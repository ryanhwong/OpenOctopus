from openoctopus.ozon.client import OzonClient


def flatten_tree(node: dict, parent_id: str = "") -> list[tuple[str, str, str]]:
    rows = [(str(node["category_id"]), str(parent_id), node.get("category_name", ""))]
    for ch in node.get("childs", []) or []:
        if "category_id" in ch:
            rows += flatten_tree(ch, str(node["category_id"]))
    return rows


def sync_categories(ozon: "OzonClient", conn, tree: dict) -> int:
    n = 0
    for top in tree.get("result", []):
        for cid, pid, title in flatten_tree(top):
            conn.execute(
                "INSERT INTO ozon_categories(id, parent_id, title) VALUES(?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET parent_id=excluded.parent_id, title=excluded.title",
                (cid, pid, title))
            n += 1
    conn.commit()
    return n

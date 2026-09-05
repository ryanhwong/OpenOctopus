from openoctopus.ozon.client import OzonClient


def flatten_tree(node: dict, parent_id: str = "", prefix: str = "") -> list[tuple[str, str, str]]:
    """拍平 description-category 树。

    类目节点 -> (description_category_id, parent, 面包屑标题)；
    叶子类型节点 -> ("<desc_id>:<type_id>", desc_id, 面包屑标题)。
    disabled 节点跳过。映射时只选带冒号的叶子 key。
    """
    rows: list[tuple[str, str, str]] = []
    desc_id = str(node.get("description_category_id", "") or "")
    if not desc_id or node.get("disabled", False):
        return rows
    name = node.get("category_name", "")
    title = f"{prefix} › {name}" if prefix else name
    rows.append((desc_id, str(parent_id), title))
    for ch in node.get("children", []) or []:
        if ch.get("disabled", False):
            continue
        if "type_id" in ch:
            rows.append((f"{desc_id}:{ch['type_id']}", desc_id,
                         f"{title} › {ch.get('type_name', '')}"))
        else:
            rows += flatten_tree(ch, desc_id, title)
    return rows


def sync_categories(ozon: "OzonClient", conn, tree: dict) -> int:
    n = 0
    for top in tree.get("result", []):
        for cid, pid, title in flatten_tree(top):
            conn.execute(
                "INSERT INTO ozon_categories(id,parent_id,title) VALUES(?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET parent_id=excluded.parent_id, title=excluded.title",
                (cid, pid, title))
            n += 1
    conn.commit()
    return n

# 已对照线上逐个验证（2026-09）：tree/attribute 为 description-category 体系；
# import/import_info 以首次真实上架返回为准，若 404 再按已验证存在的前缀逐个探测
PATHS = {
    "category_tree": "/v1/description-category/tree",
    "category_attributes": "/v1/description-category/attribute",
    "import": "/v4/product/import",
    "import_info": "/v1/product/import/task/info",
}

"""Single source of truth for external compute-platform hierarchy and local chip bindings.

The dictionary lists local binding identities, not guarantees of converter support.
Remote provider IDs and classifications are always synchronized from ChangLian.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping


CHIP_BINDING_DICTIONARY: dict[str, tuple[str, ...]] = {
    "rockchip": ("RK3568", "RK3576", "RK3578"),
    "sophon": ("BM1684X", "BM1688"),
}
_ROOT_PARENT_IDS = frozenset({"", "0", "-1"})


def local_chip_key(value: Any) -> str:
    """Stable matching key: rk-3568 and RK3568 are the same local chip."""
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def compute_platform_catalog(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Validate the provider's flat parentId graph without changing its owner data."""
    catalog: dict[str, dict[str, Any]] = {}
    for source in rows:
        if not isinstance(source, Mapping):
            raise ValueError("算力环境记录必须是对象")
        row = dict(source)
        node_id = str(row.get("computePlatformId") or row.get("compute_platform_id") or row.get("id") or "").strip()
        if not node_id or node_id in catalog:
            raise ValueError("算力环境 ID 缺失或重复")
        catalog[node_id] = row

    for node_id, row in catalog.items():
        parent = compute_platform_parent(row)
        if parent and parent not in catalog:
            raise ValueError(f"算力环境 {node_id} 的父节点 {parent} 不在完整同步结果中")
        seen = {node_id}
        while parent:
            if parent in seen:
                raise ValueError(f"算力环境 {node_id} 的父子关系存在循环")
            seen.add(parent)
            parent = compute_platform_parent(catalog[parent])
    return catalog


def compute_platform_parent(node: Mapping[str, Any]) -> str:
    value = str(node.get("parentId") if node.get("parentId") is not None else "").strip()
    return "" if value in _ROOT_PARENT_IDS else value


def compute_platform_active(catalog: Mapping[str, Mapping[str, Any]], node_id: str) -> bool:
    current = str(node_id or "").strip()
    if current not in catalog:
        return False
    while current:
        node = catalog[current]
        if str(node.get("delFlag") if node.get("delFlag") is not None else 0).strip() != "0":
            return False
        current = compute_platform_parent(node)
    return True


def compute_platform_is_descendant(
    catalog: Mapping[str, Mapping[str, Any]], node_id: str, ancestor_id: str,
) -> bool:
    """Only a genuine child/grandchild is valid; a parent is not its own child."""
    current = compute_platform_parent(catalog.get(str(node_id), {}))
    while current:
        if current == str(ancestor_id):
            return True
        current = compute_platform_parent(catalog[current])
    return False


def compute_platform_has_children(
    catalog: Mapping[str, Mapping[str, Any]], parent_id: str,
) -> bool:
    return any(compute_platform_parent(row) == str(parent_id) for row in catalog.values())

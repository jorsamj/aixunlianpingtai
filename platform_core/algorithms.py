import json
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .annotations import atomic_write_json
from .errors import PlatformError


def list_algorithms(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PlatformError(
            code="ALGORITHM_STORE_INVALID",
            message="算法资产文件无法读取",
            detail=str(error),
            solution="请恢复 algorithms.json 备份，或检查文件是否为有效 JSON。",
            status_code=500,
        ) from error
    if not isinstance(value, list):
        raise PlatformError(
            code="ALGORITHM_STORE_INVALID",
            message="算法资产文件格式不正确",
            detail="algorithms.json 的根节点必须是数组。",
            solution="请恢复有效的算法资产文件。",
            status_code=500,
        )
    return value


def save_algorithms(path: Path, algorithms: Sequence[Mapping[str, Any]]) -> None:
    atomic_write_json(path, list(algorithms))


def create_algorithm(
    path: Path,
    payload: Mapping[str, Any],
    now: str,
    algorithm_id: str | None = None,
) -> dict:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise PlatformError(
            code="ALGORITHM_NAME_REQUIRED",
            message="算法名称不能为空",
            detail="创建算法时必须填写名称。",
            solution="请输入一个能够区分业务用途的算法名称。",
        )
    algorithms = list_algorithms(path)
    if any(str(item.get("name") or "").strip().casefold() == name.casefold() for item in algorithms):
        raise PlatformError(
            code="ALGORITHM_NAME_EXISTS",
            message="算法名称已存在",
            detail=f"当前项目中已经存在名为“{name}”的算法。",
            solution="请使用不同名称，或编辑已有算法。",
            status_code=409,
        )
    item = {
        "id": algorithm_id or uuid.uuid4().hex[:12],
        "name": name,
        "remark": str(payload.get("remark") or ""),
        "industry": str(payload.get("industry") or "").strip(),
        "algorithm_type": str(payload.get("algorithm_type") or "").strip(),
        "versions": [],
        "created_at": now,
        "updated_at": now,
    }
    algorithms.insert(0, item)
    save_algorithms(path, algorithms)
    return item


def update_algorithm(path: Path, algorithm_id: str, payload: Mapping[str, Any], now: str) -> dict:
    algorithms = list_algorithms(path)
    item = next((row for row in algorithms if str(row.get("id")) == str(algorithm_id)), None)
    if item is None:
        raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
    proposed_name = str(payload.get("name") or item.get("name") or "").strip()
    if any(
        str(row.get("id")) != str(algorithm_id)
        and str(row.get("name") or "").strip().casefold() == proposed_name.casefold()
        for row in algorithms
    ):
        raise PlatformError("ALGORITHM_NAME_EXISTS", "算法名称已存在", f"算法名称“{proposed_name}”已被使用。", "请使用不同名称。", 409)
    item.update({
        "name": proposed_name,
        "remark": str(payload.get("remark") or ""),
        "industry": str(payload.get("industry") or "").strip(),
        "algorithm_type": str(payload.get("algorithm_type") or "").strip(),
        "updated_at": now,
    })
    save_algorithms(path, algorithms)
    return item


def delete_algorithm(path: Path, algorithm_id: str) -> None:
    algorithms = list_algorithms(path)
    remaining = [row for row in algorithms if str(row.get("id")) != str(algorithm_id)]
    if len(remaining) == len(algorithms):
        raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
    save_algorithms(path, remaining)


def attach_version(path: Path, algorithm_id: str, version: Mapping[str, Any]) -> dict:
    algorithms = list_algorithms(path)
    item = next((row for row in algorithms if str(row.get("id")) == str(algorithm_id)), None)
    if item is None:
        raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
    versions = list(item.get("versions") or [])
    versions.append(dict(version))
    versions.sort(key=lambda row: str(row.get("finished_at") or row.get("created_at") or row.get("version_name") or ""), reverse=True)
    item["versions"] = versions
    item["updated_at"] = str(version.get("finished_at") or version.get("created_at") or item.get("updated_at") or "")
    save_algorithms(path, algorithms)
    return dict(version)

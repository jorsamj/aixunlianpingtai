import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .annotations import atomic_write_json
from .errors import PlatformError


_ALGORITHM_WRITE_LOCK = threading.RLock()


def _version_sort_key(version: Mapping[str, Any]) -> str:
    return str(version.get("finished_at") or version.get("created_at") or version.get("version_name") or "")


def resolve_current_version(algorithm: Mapping[str, Any], framework: str = "") -> dict | None:
    """Return the explicit current version, falling back to the newest usable legacy version."""
    versions = [dict(row) for row in (algorithm.get("versions") or []) if isinstance(row, Mapping)]
    current_id = str(algorithm.get("current_version_id") or "").strip()
    if current_id:
        current = next((row for row in versions if str(row.get("id")) == current_id), None)
        if current is not None:
            return current
    ordered = sorted(versions, key=_version_sort_key, reverse=True)
    if framework:
        trainable = [row for row in ordered if is_trainable_version(row, framework)]
        if trainable:
            return trainable[0]
    return next((row for row in ordered if str(row.get("stored_path") or row.get("path") or "").strip()), ordered[0] if ordered else None)


def ensure_current_version(algorithm: dict, framework: str = "") -> bool:
    """Backfill a legacy algorithm's current pointer without overriding a valid rollback."""
    current_id = str(algorithm.get("current_version_id") or "").strip()
    if current_id and any(str(row.get("id")) == current_id for row in (algorithm.get("versions") or [])):
        return False
    current = resolve_current_version(algorithm, framework)
    if current is None:
        return False
    algorithm["current_version_id"] = str(current.get("id") or "")
    return True


def is_trainable_version(version: Mapping[str, Any], framework: str) -> bool:
    status = str(version.get("training_status") or "").strip().upper()
    successful = status in {
        "SUCCEEDED",
        "PARTIAL_SUCCESS",
        # Compatibility with versions archived before the durable task runtime.
        "DONE",
        "FINISHED",
        "COMPLETED",
    }
    if not successful or version.get("artifact_verified") is not True:
        return False
    if version.get("trainable") is False:
        return False
    recorded_framework = str(version.get("framework") or framework).strip().lower()
    return recorded_framework == str(framework).strip().lower()


def choose_iteration_base(
    versions: Sequence[Mapping[str, Any]],
    mother_model: str,
    framework: str = "ultralytics",
    *,
    strict_latest: bool = False,
    artifact_validator: Callable[[Path], bool] | None = None,
    current_version_id: str | None = None,
) -> dict:
    """Choose the checkpoint used for an iterative training run.

    The historical/default mode keeps the backwards-compatible "newest usable"
    fallback. Product training uses ``strict_latest=True`` to select the newest
    successful, verified, trainable version. Failed/cancelled attempts are task
    history, not algorithm versions and never poison a later iteration.
    """
    allowed_suffixes = {".pt"} if framework == "ultralytics" else {".pdparams", ".pdmodel", ".pdiparams"}
    ordered = sorted(
        versions or [],
        key=lambda row: str(row.get("finished_at") or row.get("created_at") or row.get("version_name") or ""),
        reverse=True,
    )
    if current_version_id:
        current = next((row for row in ordered if str(row.get("id")) == str(current_version_id)), None)
        if current is not None:
            ordered = [current, *(row for row in ordered if str(row.get("id")) != str(current_version_id))]
    if strict_latest and ordered:
        eligible = [row for row in ordered if is_trainable_version(row, framework)]
        if not eligible:
            newest_attempt = ordered[0]
            attempt_name = newest_attempt.get("version_name") or newest_attempt.get("id") or "未知版本"
            raise PlatformError(
                code="ITERATION_BASE_UNAVAILABLE",
                message="没有可用于迭代训练的成功版本",
                detail=f"算法已有训练记录（最新记录 {attempt_name}），但没有成功、完整性已校验且可继续训练的模型产物。",
                solution="请先完成一次成功训练，或恢复最近成功版本的有效训练权重。平台不会回退到母算法。",
                status_code=409,
            )
        latest = eligible[0]
        if current_version_id and str(latest.get("id")) != str(current_version_id):
            raise PlatformError(
                code="CURRENT_VERSION_UNAVAILABLE",
                message="当前算法版本不可用于继续训练",
                detail="算法已明确选择当前版本，但该版本不是成功、已校验且可继续训练的模型产物。",
                solution="请修复当前版本产物，或回退到一个有效版本后再开始训练。",
                status_code=409,
            )
        candidate = next(
            (
                str(latest.get(field) or "").strip()
                for field in ("best_path", "last_path", "stored_path", "path")
                if str(latest.get(field) or "").strip()
            ),
            "",
        )
        path = Path(candidate).expanduser() if candidate else None
        reason = ""
        if not candidate:
            reason = "没有记录模型产物路径"
        elif path is None or not path.is_file():
            reason = "模型产物文件不存在"
        elif path.suffix.lower() not in allowed_suffixes:
            reason = f"模型产物格式 {path.suffix or '<无扩展名>'} 与 {framework} 框架不匹配"
        elif latest.get("artifact_verified") is False:
            reason = "模型产物未通过完整性校验"
        elif artifact_validator is not None:
            try:
                valid = bool(artifact_validator(path.resolve()))
            except Exception as error:  # validators are intentionally fail-closed
                valid = False
                reason = f"模型产物校验异常：{error}"
            if not valid and not reason:
                reason = "模型产物无法被当前训练环境加载"
        if reason:
            raise PlatformError(
                code="ITERATION_BASE_UNAVAILABLE",
                message="上一版本模型不可用，无法开始迭代训练",
                detail=f"上一版本 {latest.get('version_name') or latest.get('id') or '未知版本'}：{reason}。",
                solution="请修复或重新归档上一版本的有效训练权重后再开始迭代。平台不会自动回退到更早版本或母算法。",
                status_code=409,
            )
        return {
            "base_version_id": latest.get("id"),
            "base_version_name": latest.get("version_name") or "",
            "base_model_path": str(path.resolve()),
            "base_model_kind": "train_checkpoint",
            "base_selection_reason": "current_verified_version" if current_version_id else "latest_verified_version",
        }
    for version in ordered:
        candidate = next(
            (
                str(version.get(field) or "").strip()
                for field in ("best_path", "last_path", "stored_path", "path")
                if str(version.get(field) or "").strip()
            ),
            "",
        )
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.is_file() and path.suffix.lower() in allowed_suffixes:
            return {
                "base_version_id": version.get("id"),
                "base_version_name": version.get("version_name") or "",
                "base_model_path": str(path.resolve()),
                "base_model_kind": "train_checkpoint",
                "base_selection_reason": "latest_usable_version",
            }
    return {
        "base_version_id": None,
        "base_version_name": "",
        "base_model_path": str(mother_model or "").strip(),
        "base_model_kind": "mother_model",
        "base_selection_reason": "mother_model",
    }


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
    with _ALGORITHM_WRITE_LOCK:
        algorithms = list_algorithms(path)
        item = next((row for row in algorithms if str(row.get("id")) == str(algorithm_id)), None)
        if item is None:
            raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
        ensure_current_version(item, str(version.get("framework") or ""))
        attached = dict(version)
        attached.setdefault("parent_version_id", str(item.get("current_version_id") or ""))
        versions = list(item.get("versions") or [])
        versions.append(attached)
        versions.sort(key=_version_sort_key, reverse=True)
        item["versions"] = versions
        item["current_version_id"] = str(attached.get("id") or "")
        item["updated_at"] = str(attached.get("finished_at") or attached.get("created_at") or item.get("updated_at") or "")
        save_algorithms(path, algorithms)
        return attached


def rollback_current_version(path: Path, algorithm_id: str, version_id: str, *, actor: str, now: str | None = None) -> dict:
    """Atomically move only the current pointer; immutable version history is untouched."""
    with _ALGORITHM_WRITE_LOCK:
        algorithms = list_algorithms(path)
        item = next((row for row in algorithms if str(row.get("id")) == str(algorithm_id)), None)
        if item is None:
            raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
        target = next((row for row in (item.get("versions") or []) if str(row.get("id")) == str(version_id)), None)
        if target is None:
            raise PlatformError("ALGORITHM_VERSION_NOT_FOUND", "算法版本不存在", f"找不到版本 {version_id}。", "请刷新版本列表后重试。", 404)
        previous = str(item.get("current_version_id") or "")
        if previous == str(version_id):
            return {"algorithm": item, "changed": False, "from_version_id": previous, "to_version_id": previous}
        changed_at = now or datetime.now(timezone.utc).isoformat()
        item["current_version_id"] = str(version_id)
        item["updated_at"] = changed_at
        item.setdefault("version_pointer_audit", []).append({
            "action": "rollback",
            "from_version_id": previous,
            "to_version_id": str(version_id),
            "user": str(actor or "unknown"),
            "time": changed_at,
        })
        save_algorithms(path, algorithms)
        return {"algorithm": item, "changed": True, "from_version_id": previous, "to_version_id": str(version_id)}

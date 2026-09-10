from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .annotations import atomic_write_json
from .errors import PlatformError


_ALGORITHM_WRITE_LOCK = threading.RLock()
_ALGORITHM_LOCK_TIMEOUT_SECONDS = 30.0


def _version_sort_key(version: Mapping[str, Any]) -> str:
    return str(version.get("finished_at") or version.get("created_at") or version.get("version_name") or "")


def _algorithm_revision(item: Mapping[str, Any]) -> int:
    try:
        return max(0, int(item.get("revision") or 0))
    except (TypeError, ValueError):
        return 0


def _assert_expected_revision(item: Mapping[str, Any], expected_revision: int | None) -> None:
    if expected_revision is None:
        return
    actual = _algorithm_revision(item)
    if int(expected_revision) != actual:
        raise PlatformError(
            code="ALGORITHM_REVISION_CONFLICT",
            message="算法已被其他任务更新",
            detail=f"期望 revision={int(expected_revision)}，当前 revision={actual}。",
            solution="请刷新算法状态后重新提交操作，平台不会覆盖其他 Worker 已写入的版本。",
            status_code=409,
        )


def _bump_revision(item: dict) -> int:
    revision = _algorithm_revision(item) + 1
    item["revision"] = revision
    return revision


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _training_artifact_manifest(version: Mapping[str, Any]) -> dict[str, Any] | None:
    """Freeze model/schema lineage for durable training versions when available.

    TrainingHandler stores weights at ``<task artifact root>/outputs`` and a
    sibling snapshot.json/payload.json. Legacy/manual versions may not have
    that layout; they remain readable but are not retroactively fabricated.
    """
    task_id = str(version.get("task_id") or "").strip()
    stored_value = str(
        version.get("stored_path") or version.get("best_path") or version.get("last_path") or ""
    ).strip()
    if not task_id or not stored_value:
        return None
    model = Path(stored_value).expanduser()
    if not model.is_file() or model.stat().st_size <= 0:
        return None
    task_root = model.parent.parent if model.parent.name == "outputs" else None
    if task_root is None or task_root.name != task_id:
        return None

    snapshot_path = task_root / "snapshot.json"
    if not snapshot_path.is_file():
        raise PlatformError(
            code="TRAINING_ARTIFACT_MANIFEST_MISSING",
            message="训练版本缺少冻结数据快照",
            detail=f"任务 {task_id} 的模型位于标准任务产物目录，但 snapshot.json 不存在。",
            solution="不要发布该版本；请恢复该训练任务完整产物后重试后处理。",
            status_code=409,
        )
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PlatformError(
            code="TRAINING_ARTIFACT_MANIFEST_INVALID",
            message="训练版本快照无法读取",
            detail=str(error),
            solution="请恢复有效 snapshot.json 后重试，平台不会猜测标签映射。",
            status_code=409,
        ) from error
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    recorded_snapshot_id = str(version.get("snapshot_id") or "")
    if not snapshot_id or (recorded_snapshot_id and snapshot_id != recorded_snapshot_id):
        raise PlatformError(
            code="TRAINING_ARTIFACT_MANIFEST_INVALID",
            message="训练版本与数据快照不一致",
            detail=f"version snapshot_id={recorded_snapshot_id or '<空>'}，artifact snapshot_id={snapshot_id or '<空>'}。",
            solution="请检查任务产物归属，禁止把其他训练任务的模型和快照拼接成一个版本。",
            status_code=409,
        )
    labels = [dict(row) for row in (snapshot.get("label_schema") or []) if isinstance(row, Mapping)]
    if not labels:
        raise PlatformError(
            code="TRAINING_ARTIFACT_MANIFEST_INVALID",
            message="训练版本缺少冻结标签映射",
            detail="snapshot.json 中 label_schema 为空。",
            solution="请恢复该训练任务真实标签快照后重试。",
            status_code=409,
        )
    labels.sort(key=lambda row: int(row.get("yolo_class_id", row.get("class_id", 10**9))))
    yolo_ids = [int(row.get("yolo_class_id", row.get("class_id", -1))) for row in labels]
    if yolo_ids != list(range(len(labels))):
        raise PlatformError(
            code="TRAINING_ARTIFACT_MANIFEST_INVALID",
            message="训练版本的 YOLO 标签映射不连续",
            detail=f"实际 class ids={yolo_ids[:20]}。",
            solution="请恢复训练时冻结的 task-local class id 映射，不能使用当前项目标签顺序替代。",
            status_code=409,
        )

    payload = {}
    payload_path = task_root / "payload.json"
    if payload_path.is_file():
        try:
            value = json.loads(payload_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                payload = value
        except (OSError, json.JSONDecodeError):
            payload = {}
    names = [str(row.get("code") or row.get("display_name") or "") for row in labels]
    if any(not name for name in names):
        raise PlatformError(
            code="TRAINING_ARTIFACT_MANIFEST_INVALID",
            message="训练版本标签名称不完整",
            detail="冻结标签映射中存在空 code/display_name。",
            solution="请恢复有效标签快照后重试。",
            status_code=409,
        )
    manifest = {
        "schema_version": 1,
        "task_id": task_id,
        "framework": str(version.get("framework") or payload.get("framework") or ""),
        "task_type": str(payload.get("task_type") or payload.get("task") or "detect"),
        "input_size": payload.get("imgsz"),
        "snapshot_id": snapshot_id,
        "parent_version_id": str(version.get("parent_version_id") or ""),
        "num_classes": len(labels),
        "names": names,
        "labels": [
            {
                "label_id": str(row.get("label_id") or ""),
                "code": str(row.get("code") or ""),
                "display_name": str(row.get("display_name") or row.get("code") or ""),
                "platform_class_id": row.get("platform_class_id"),
                "yolo_class_id": int(row.get("yolo_class_id", row.get("class_id", -1))),
            }
            for row in labels
        ],
        "model": {
            "name": model.name,
            "size_bytes": model.stat().st_size,
            "sha256": _file_sha256(model),
        },
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return manifest


def _artifact_manifest_mismatch(version: Mapping[str, Any], path: Path, framework: str) -> str:
    manifest = version.get("artifact_manifest")
    if not isinstance(manifest, Mapping):
        return ""
    recorded_framework = str(manifest.get("framework") or "").strip().lower()
    if recorded_framework and recorded_framework != str(framework).strip().lower():
        return f"artifact manifest framework={recorded_framework} 与 {framework} 不一致"
    model = manifest.get("model")
    if not isinstance(model, Mapping):
        return "artifact manifest 缺少 model 完整性信息"
    try:
        expected_size = int(model.get("size_bytes") or 0)
    except (TypeError, ValueError):
        expected_size = 0
    expected_hash = str(model.get("sha256") or "").strip().lower()
    if expected_size <= 0 or len(expected_hash) != 64:
        return "artifact manifest 的模型大小或 SHA256 无效"
    try:
        if path.stat().st_size != expected_size:
            return "模型文件大小与 artifact manifest 不一致"
        if _file_sha256(path) != expected_hash:
            return "模型文件 SHA256 与 artifact manifest 不一致"
    except OSError as error:
        return f"模型完整性校验失败：{error}"
    return ""


@contextmanager
def _algorithm_store_lock(path: Path, timeout: float = _ALGORITHM_LOCK_TIMEOUT_SECONDS):
    """Serialize algorithms.json read-modify-write across threads and processes.

    The JSON file itself is still atomically replaced. A persistent sibling
    lock file provides the cross-process fence on both Windows and POSIX.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    deadline = time.monotonic() + max(0.1, float(timeout))
    with _ALGORITHM_WRITE_LOCK:
        with lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            acquired = False
            while not acquired:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except (OSError, BlockingIOError) as error:
                    if time.monotonic() >= deadline:
                        raise PlatformError(
                            code="ALGORITHM_STORE_BUSY",
                            message="算法版本正在被其他进程更新",
                            detail=f"等待 {lock_path.name} 超时：{error}",
                            solution="请稍后重试；平台没有覆盖正在进行的算法版本写入。",
                            status_code=409,
                        ) from error
                    time.sleep(0.05)
            try:
                yield
            finally:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass


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
    """Choose the checkpoint used for an iterative training run."""
    allowed_suffixes = {".pt"} if framework == "ultralytics" else {".pdparams", ".pdmodel", ".pdiparams"}
    ordered = sorted(versions or [], key=_version_sort_key, reverse=True)
    if current_version_id:
        current = next((row for row in ordered if str(row.get("id")) == str(current_version_id)), None)
        if current is None:
            raise PlatformError(
                code="CURRENT_VERSION_UNAVAILABLE",
                message="当前算法版本不存在",
                detail=f"current_version_id={current_version_id} 未在算法版本历史中找到。",
                solution="请刷新算法版本，或回滚到一个仍存在且可训练的有效版本。",
                status_code=409,
            )
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
        candidate = next((str(latest.get(field) or "").strip() for field in ("best_path", "last_path", "stored_path", "path") if str(latest.get(field) or "").strip()), "")
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
        elif path is not None:
            reason = _artifact_manifest_mismatch(latest, path.resolve(), framework)
        if not reason and artifact_validator is not None and path is not None:
            try:
                valid = bool(artifact_validator(path.resolve()))
            except Exception as error:
                valid = False
                reason = f"模型产物校验异常：{error}"
            if not valid and not reason:
                reason = "模型产物无法被当前训练环境加载"
        if reason:
            raise PlatformError(
                code="CURRENT_VERSION_UNAVAILABLE" if current_version_id else "ITERATION_BASE_UNAVAILABLE",
                message="当前算法版本不可用于继续训练" if current_version_id else "上一版本模型不可用，无法开始迭代训练",
                detail=f"版本 {latest.get('version_name') or latest.get('id') or '未知版本'}：{reason}。",
                solution="请修复当前版本产物，或回滚到一个有效版本后再开始训练。平台不会自动改用其他历史版本或母算法。",
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
        candidate = next((str(version.get(field) or "").strip() for field in ("best_path", "last_path", "stored_path", "path") if str(version.get(field) or "").strip()), "")
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
        raise PlatformError("ALGORITHM_STORE_INVALID", "算法资产文件无法读取", str(error), "请恢复 algorithms.json 备份，或检查文件是否为有效 JSON。", 500) from error
    if not isinstance(value, list):
        raise PlatformError("ALGORITHM_STORE_INVALID", "算法资产文件格式不正确", "algorithms.json 的根节点必须是数组。", "请恢复有效的算法资产文件。", 500)
    return value


def _save_algorithms_unlocked(path: Path, algorithms: Sequence[Mapping[str, Any]]) -> None:
    atomic_write_json(path, list(algorithms))


def save_algorithms(path: Path, algorithms: Sequence[Mapping[str, Any]]) -> None:
    with _algorithm_store_lock(path):
        _save_algorithms_unlocked(path, algorithms)


def create_algorithm(path: Path, payload: Mapping[str, Any], now: str, algorithm_id: str | None = None) -> dict:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise PlatformError("ALGORITHM_NAME_REQUIRED", "算法名称不能为空", "创建算法时必须填写名称。", "请输入一个能够区分业务用途的算法名称。")
    with _algorithm_store_lock(path):
        algorithms = list_algorithms(path)
        if any(str(item.get("name") or "").strip().casefold() == name.casefold() for item in algorithms):
            raise PlatformError("ALGORITHM_NAME_EXISTS", "算法名称已存在", f"当前项目中已经存在名为“{name}”的算法。", "请使用不同名称，或编辑已有算法。", 409)
        item = {
            "id": algorithm_id or uuid.uuid4().hex[:12], "name": name,
            "remark": str(payload.get("remark") or ""), "industry": str(payload.get("industry") or "").strip(),
            "algorithm_type": str(payload.get("algorithm_type") or "").strip(), "versions": [], "revision": 1,
            "created_at": now, "updated_at": now,
        }
        algorithms.insert(0, item)
        _save_algorithms_unlocked(path, algorithms)
        return item


def update_algorithm(path: Path, algorithm_id: str, payload: Mapping[str, Any], now: str, *, expected_revision: int | None = None) -> dict:
    with _algorithm_store_lock(path):
        algorithms = list_algorithms(path)
        item = next((row for row in algorithms if str(row.get("id")) == str(algorithm_id)), None)
        if item is None:
            raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
        _assert_expected_revision(item, expected_revision)
        proposed_name = str(payload.get("name") or item.get("name") or "").strip()
        if any(str(row.get("id")) != str(algorithm_id) and str(row.get("name") or "").strip().casefold() == proposed_name.casefold() for row in algorithms):
            raise PlatformError("ALGORITHM_NAME_EXISTS", "算法名称已存在", f"算法名称“{proposed_name}”已被使用。", "请使用不同名称。", 409)
        item.update({"name": proposed_name, "remark": str(payload.get("remark") or ""), "industry": str(payload.get("industry") or "").strip(), "algorithm_type": str(payload.get("algorithm_type") or "").strip(), "updated_at": now})
        _bump_revision(item)
        _save_algorithms_unlocked(path, algorithms)
        return item


def delete_algorithm(path: Path, algorithm_id: str, *, expected_revision: int | None = None) -> None:
    with _algorithm_store_lock(path):
        algorithms = list_algorithms(path)
        item = next((row for row in algorithms if str(row.get("id")) == str(algorithm_id)), None)
        if item is None:
            raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
        _assert_expected_revision(item, expected_revision)
        _save_algorithms_unlocked(path, [row for row in algorithms if str(row.get("id")) != str(algorithm_id)])


def attach_version(path: Path, algorithm_id: str, version: Mapping[str, Any], *, expected_revision: int | None = None) -> dict:
    with _algorithm_store_lock(path):
        algorithms = list_algorithms(path)
        item = next((row for row in algorithms if str(row.get("id")) == str(algorithm_id)), None)
        if item is None:
            raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
        attached = dict(version)
        versions = list(item.get("versions") or [])
        task_id = str(attached.get("task_id") or "").strip()
        if task_id:
            existing = next((row for row in versions if str(row.get("task_id") or "") == task_id), None)
            if existing is not None:
                # Idempotent replay must succeed even if another operation has
                # advanced the algorithm revision since the original commit.
                return dict(existing)
        _assert_expected_revision(item, expected_revision)
        ensure_current_version(item, str(version.get("framework") or ""))
        attached.setdefault("parent_version_id", str(item.get("current_version_id") or ""))
        manifest = _training_artifact_manifest(attached)
        if manifest is not None:
            attached["artifact_manifest"] = manifest
        versions.append(attached)
        versions.sort(key=_version_sort_key, reverse=True)
        item["versions"] = versions
        item["current_version_id"] = str(attached.get("id") or "")
        item["updated_at"] = str(attached.get("finished_at") or attached.get("created_at") or item.get("updated_at") or "")
        _bump_revision(item)
        _save_algorithms_unlocked(path, algorithms)
        return attached


def rollback_current_version(path: Path, algorithm_id: str, version_id: str, *, actor: str, now: str | None = None, expected_revision: int | None = None) -> dict:
    """Atomically move only the current pointer; immutable version history is untouched."""
    with _algorithm_store_lock(path):
        algorithms = list_algorithms(path)
        item = next((row for row in algorithms if str(row.get("id")) == str(algorithm_id)), None)
        if item is None:
            raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
        _assert_expected_revision(item, expected_revision)
        target = next((row for row in (item.get("versions") or []) if str(row.get("id")) == str(version_id)), None)
        if target is None:
            raise PlatformError("ALGORITHM_VERSION_NOT_FOUND", "算法版本不存在", f"找不到版本 {version_id}。", "请刷新版本列表后重试。", 404)
        previous = str(item.get("current_version_id") or "")
        if previous == str(version_id):
            return {"algorithm": item, "changed": False, "from_version_id": previous, "to_version_id": previous}
        changed_at = now or datetime.now(timezone.utc).isoformat()
        item["current_version_id"] = str(version_id)
        item["updated_at"] = changed_at
        item.setdefault("version_pointer_audit", []).append({"action": "rollback", "from_version_id": previous, "to_version_id": str(version_id), "user": str(actor or "unknown"), "time": changed_at})
        _bump_revision(item)
        _save_algorithms_unlocked(path, algorithms)
        return {"algorithm": item, "changed": True, "from_version_id": previous, "to_version_id": str(version_id)}

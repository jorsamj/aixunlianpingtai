import json
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from filelock import FileLock

from .annotations import atomic_write_json
from .errors import PlatformError


def _update_lock(path: Path) -> FileLock:
    return FileLock(str(path.resolve()) + ".lock", timeout=30)


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


def _version_sort_key(version: Mapping[str, Any]) -> str:
    return str(version.get("finished_at") or version.get("created_at") or version.get("version_name") or "")


def resolve_current_version_id(
    algorithm: Mapping[str, Any],
    *,
    framework: str | None = None,
) -> str | None:
    """Return the durable current pointer or lazily infer it for legacy data.

    Missing pointers are deliberately not written here. Historical stores remain
    untouched until an algorithm mutation, version archive, or rollback occurs.
    """
    versions = list(algorithm.get("versions") or [])
    explicit = str(algorithm.get("current_version_id") or "").strip()
    if explicit:
        current = next((row for row in versions if str(row.get("id") or "") == explicit), None)
        if current is None:
            raise PlatformError(
                "ALGORITHM_CURRENT_VERSION_INVALID",
                "算法当前版本指针无效",
                f"current_version_id={explicit} 对应的版本不存在。",
                "请恢复对应版本记录，或明确回退到仍然存在的有效版本。",
                409,
            )
        if framework and not is_trainable_version(current, framework):
            raise PlatformError(
                "ALGORITHM_CURRENT_VERSION_UNAVAILABLE",
                "算法当前版本不可用于训练",
                f"当前版本 {current.get('version_name') or explicit} 不是已校验的 {framework} 可训练版本。",
                "请回退到一个训练成功、产物已校验且框架匹配的版本。",
                409,
            )
        return explicit

    if framework:
        eligible = [row for row in versions if is_trainable_version(row, framework)]
    else:
        eligible = [
            row for row in versions
            if any(is_trainable_version(row, candidate) for candidate in {str(row.get("framework") or "ultralytics"), "ultralytics", "paddle"})
        ]
    eligible.sort(key=_version_sort_key, reverse=True)
    return str(eligible[0].get("id") or "").strip() or None if eligible else None


def project_current_version(
    algorithm: Mapping[str, Any],
    *,
    framework: str | None = None,
) -> dict:
    """Create a read-only API projection without migrating legacy metadata."""
    projected = dict(algorithm)
    explicit = str(algorithm.get("current_version_id") or "").strip()
    try:
        current = resolve_current_version_id(algorithm, framework=framework)
        projected["current_version_error"] = None
    except PlatformError as error:
        current = explicit or None
        projected["current_version_error"] = error.detail
    projected["current_version_id"] = current
    projected["current_version_inferred"] = bool(current and not explicit)
    return projected


def choose_iteration_base(
    versions: Sequence[Mapping[str, Any]],
    mother_model: str,
    framework: str = "ultralytics",
    *,
    strict_latest: bool = False,
    artifact_validator: Callable[[Path], bool] | None = None,
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
            "base_selection_reason": "latest_verified_version",
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


def choose_algorithm_iteration_base(
    algorithm: Mapping[str, Any],
    mother_model: str,
    framework: str = "ultralytics",
    *,
    strict_latest: bool = False,
    artifact_validator: Callable[[Path], bool] | None = None,
) -> dict:
    """Choose an iteration base using the algorithm's single current pointer."""
    versions = list(algorithm.get("versions") or [])
    if not versions:
        return choose_iteration_base(
            [], mother_model, framework,
            strict_latest=strict_latest,
            artifact_validator=artifact_validator,
        )
    current_id = resolve_current_version_id(algorithm, framework=framework)
    if not current_id:
        return choose_iteration_base(
            versions, mother_model, framework,
            strict_latest=strict_latest,
            artifact_validator=artifact_validator,
        )
    current = next(row for row in versions if str(row.get("id") or "") == current_id)
    selected = choose_iteration_base(
        [current], mother_model, framework,
        strict_latest=strict_latest,
        artifact_validator=artifact_validator,
    )
    if selected.get("base_version_id"):
        selected["base_selection_reason"] = "current_verified_version"
    return selected


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
    with _update_lock(path):
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
            "current_version_id": None,
            "version_operations": [],
            "versions": [],
            "created_at": now,
            "updated_at": now,
        }
        algorithms.insert(0, item)
        save_algorithms(path, algorithms)
    return item


def update_algorithm(path: Path, algorithm_id: str, payload: Mapping[str, Any], now: str) -> dict:
    with _update_lock(path):
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
        if "current_version_id" not in item:
            item["current_version_id"] = resolve_current_version_id(item)
        item.setdefault("version_operations", [])
        save_algorithms(path, algorithms)
    return item


def delete_algorithm(path: Path, algorithm_id: str) -> None:
    with _update_lock(path):
        algorithms = list_algorithms(path)
        remaining = [row for row in algorithms if str(row.get("id")) != str(algorithm_id)]
        if len(remaining) == len(algorithms):
            raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
        save_algorithms(path, remaining)


def attach_version(path: Path, algorithm_id: str, version: Mapping[str, Any]) -> dict:
    with _update_lock(path):
        algorithms = list_algorithms(path)
        item = next((row for row in algorithms if str(row.get("id")) == str(algorithm_id)), None)
        if item is None:
            raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
        versions = list(item.get("versions") or [])
        task_id = str(version.get("task_id") or version.get("job_id") or "").strip()
        if task_id:
            existing = next(
                (
                    row for row in versions
                    if str(row.get("task_id") or row.get("job_id") or "").strip() == task_id
                ),
                None,
            )
            if existing is not None:
                return dict(existing)
        versions.append(dict(version))
        versions.sort(key=_version_sort_key, reverse=True)
        item["versions"] = versions
        item["current_version_id"] = str(version.get("id") or "").strip() or None
        item.setdefault("version_operations", [])
        item["updated_at"] = str(version.get("finished_at") or version.get("created_at") or item.get("updated_at") or "")
        save_algorithms(path, algorithms)
    return dict(version)


def update_algorithm_version(
    path: Path,
    algorithm_id: str,
    version_id: str,
    patch: Mapping[str, Any],
    *,
    now: str,
) -> dict:
    """Patch one version inside the same atomic algorithm metadata boundary."""
    protected = {"id", "version_id", "base_version_id", "parent_version_id"}
    values = {key: value for key, value in patch.items() if key not in protected}
    with _update_lock(path):
        algorithms = list_algorithms(path)
        algorithm = next((row for row in algorithms if str(row.get("id") or "") == str(algorithm_id)), None)
        if algorithm is None:
            raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
        version = next(
            (row for row in algorithm.get("versions") or [] if str(row.get("id") or "") == str(version_id)),
            None,
        )
        if version is None:
            raise PlatformError("ALGORITHM_VERSION_NOT_FOUND", "算法版本不存在", f"找不到版本 {version_id}。", "请刷新版本列表后重试。", 404)
        version.update(values)
        version["updated_at"] = now
        algorithm["updated_at"] = now
        if "current_version_id" not in algorithm:
            algorithm["current_version_id"] = resolve_current_version_id(algorithm)
        algorithm.setdefault("version_operations", [])
        save_algorithms(path, algorithms)
        return dict(version)


def rollback_algorithm_version(
    path: Path,
    algorithm_id: str,
    target_version_id: str,
    *,
    now: str,
    delete_current_version: bool = False,
    operator: str = "local_user",
    expected_current_version_id: str | None = None,
    dependency_check: Callable[[Mapping[str, Any], Mapping[str, Any]], Sequence[Mapping[str, Any]]] | None = None,
    cleanup: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> dict:
    """Atomically switch the current pointer, optionally removing the old version.

    Dependency checks run before the metadata transaction commits. Physical file
    cleanup deliberately runs after the trusted pointer/version metadata write;
    its independently persisted status never rolls the pointer back.
    """
    operation_id = uuid.uuid4().hex[:12]
    removed_version: dict | None = None
    with _update_lock(path):
        algorithms = list_algorithms(path)
        algorithm = next((row for row in algorithms if str(row.get("id") or "") == str(algorithm_id)), None)
        if algorithm is None:
            raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
        versions = list(algorithm.get("versions") or [])
        current_id = resolve_current_version_id(algorithm)
        if not current_id:
            raise PlatformError(
                "ALGORITHM_CURRENT_VERSION_MISSING", "算法没有可回退的当前版本",
                "当前算法没有成功且产物已校验的版本。", "请先完成一次有效训练。", 409,
            )
        if expected_current_version_id is not None and str(expected_current_version_id) != current_id:
            raise PlatformError(
                "ALGORITHM_VERSION_CONFLICT", "算法当前版本已经发生变化",
                f"请求基于 {expected_current_version_id}，当前实际版本为 {current_id}。",
                "请刷新算法版本列表后重新确认。", 409,
            )
        if str(target_version_id) == current_id:
            raise PlatformError(
                "ALGORITHM_VERSION_ALREADY_CURRENT", "目标版本已经是当前版本",
                f"版本 {target_version_id} 无需再次回退。", "请选择其他历史版本。", 409,
            )
        target = next((row for row in versions if str(row.get("id") or "") == str(target_version_id)), None)
        if target is None:
            raise PlatformError("ALGORITHM_VERSION_NOT_FOUND", "算法版本不存在", f"找不到版本 {target_version_id}。", "请刷新版本列表后重试。", 404)
        target_framework = str(target.get("framework") or "ultralytics")
        choose_iteration_base(
            [target], "", target_framework,
            strict_latest=True,
            artifact_validator=lambda candidate: candidate.is_file() and candidate.stat().st_size > 0,
        )
        current = next(row for row in versions if str(row.get("id") or "") == current_id)
        dependencies: list[Mapping[str, Any]] = []
        if delete_current_version:
            dependencies = list((dependency_check or (lambda _algorithm, _version: []))(algorithm, current) or [])
            if dependencies:
                reasons = [str(item.get("reason") or item.get("id") or "存在活动引用") for item in dependencies]
                raise PlatformError(
                    "ALGORITHM_VERSION_IN_USE", "当前版本仍被活动业务引用，不能删除",
                    "；".join(reasons), "请先结束相关任务或停止对应业务，再重新执行回退并删除。", 409,
                )

        action = "rollback_and_delete" if delete_current_version else "rollback"
        operation = {
            "id": operation_id,
            "algorithm_id": str(algorithm_id),
            "from_version_id": current_id,
            "to_version_id": str(target_version_id),
            "deleted_version_id": current_id if delete_current_version else None,
            "action": action,
            "operator": str(operator or "local_user"),
            "created_at": now,
            "cleanup_status": "cleanup_pending" if delete_current_version else "not_required",
            "cleanup_targets": [],
            "cleanup_errors": [],
        }
        algorithm["current_version_id"] = str(target_version_id)
        algorithm.setdefault("version_operations", []).append(operation)
        if delete_current_version:
            removed_version = dict(current)
            algorithm["versions"] = [row for row in versions if str(row.get("id") or "") != current_id]
        algorithm["updated_at"] = now
        save_algorithms(path, algorithms)

    cleanup_result: Mapping[str, Any] = {}
    cleanup_status = "not_required"
    if delete_current_version and removed_version is not None:
        try:
            cleanup_result = dict((cleanup or (lambda _algorithm, _version: {"status": "cleanup_pending"}))(
                dict(algorithm), removed_version,
            ) or {})
        except Exception as error:  # cleanup must never roll back the trusted pointer
            cleanup_result = {"status": "cleanup_failed", "targets": [], "errors": [str(error)]}
        status = str(cleanup_result.get("status") or "cleanup_failed")
        if status not in {"cleanup_completed", "cleanup_pending", "cleanup_failed"}:
            status = "cleanup_failed"
        cleanup_status = status
        with _update_lock(path):
            algorithms = list_algorithms(path)
            persisted = next((row for row in algorithms if str(row.get("id") or "") == str(algorithm_id)), None)
            if persisted is None:
                raise PlatformError(
                    "ALGORITHM_CLEANUP_STATE_LOST", "版本已回退，但清理状态无法保存",
                    f"算法 {algorithm_id} 在清理期间被删除。", "请检查版本操作审计和文件清理结果。", 500,
                )
            operation = next(
                (row for row in persisted.get("version_operations") or [] if str(row.get("id") or "") == operation_id),
                None,
            )
            if operation is None:
                raise PlatformError(
                    "ALGORITHM_CLEANUP_STATE_LOST", "版本已回退，但清理审计不存在",
                    f"找不到操作记录 {operation_id}。", "请检查 algorithms.json 一致性。", 500,
                )
            operation["cleanup_status"] = status
            operation["cleanup_targets"] = [str(item) for item in cleanup_result.get("targets") or []]
            operation["cleanup_errors"] = [str(item) for item in cleanup_result.get("errors") or []]
            save_algorithms(path, algorithms)

    return {
        "algorithm_id": str(algorithm_id),
        "previous_current_version_id": current_id,
        "current_version_id": str(target_version_id),
        "deleted_version_id": current_id if delete_current_version else None,
        "action": "rollback_and_delete" if delete_current_version else "rollback",
        "operation_id": operation_id,
        "cleanup_status": cleanup_status,
        "cleanup_targets": [str(item) for item in cleanup_result.get("targets") or []],
        "cleanup_errors": [str(item) for item in cleanup_result.get("errors") or []],
    }


def delete_algorithm_version(
    path: Path,
    algorithm_id: str,
    version_id: str,
    *,
    now: str,
    operator: str = "local_user",
    dependency_check: Callable[[Mapping[str, Any], Mapping[str, Any]], Sequence[Mapping[str, Any]]] | None = None,
    cleanup: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> dict:
    """Delete a non-current historical version with audit and deferred cleanup."""
    operation_id = uuid.uuid4().hex[:12]
    with _update_lock(path):
        algorithms = list_algorithms(path)
        algorithm = next((row for row in algorithms if str(row.get("id") or "") == str(algorithm_id)), None)
        if algorithm is None:
            raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
        versions = list(algorithm.get("versions") or [])
        target = next((row for row in versions if str(row.get("id") or "") == str(version_id)), None)
        if target is None:
            raise PlatformError("ALGORITHM_VERSION_NOT_FOUND", "算法版本不存在", f"找不到版本 {version_id}。", "请刷新版本列表后重试。", 404)
        current_id = resolve_current_version_id(algorithm)
        if str(version_id) == str(current_id or ""):
            raise PlatformError(
                "ALGORITHM_CURRENT_VERSION_DELETE_FORBIDDEN", "不能直接删除当前版本",
                f"版本 {version_id} 当前正在作为算法默认版本。",
                "请先回退到另一个有效版本，再删除该版本。", 409,
            )
        dependencies = list((dependency_check or (lambda _algorithm, _version: []))(algorithm, target) or [])
        if dependencies:
            reasons = [str(item.get("reason") or item.get("id") or "存在活动引用") for item in dependencies]
            raise PlatformError(
                "ALGORITHM_VERSION_IN_USE", "算法版本仍被活动业务引用，不能删除",
                "；".join(reasons), "请先结束相关任务或停止对应业务，再重新删除。", 409,
            )
        operation = {
            "id": operation_id,
            "algorithm_id": str(algorithm_id),
            "from_version_id": current_id,
            "to_version_id": current_id,
            "deleted_version_id": str(version_id),
            "action": "delete_version",
            "operator": str(operator or "local_user"),
            "created_at": now,
            "cleanup_status": "cleanup_pending",
            "cleanup_targets": [],
            "cleanup_errors": [],
        }
        algorithm["current_version_id"] = current_id
        algorithm["versions"] = [row for row in versions if str(row.get("id") or "") != str(version_id)]
        algorithm.setdefault("version_operations", []).append(operation)
        algorithm["updated_at"] = now
        save_algorithms(path, algorithms)

    try:
        cleanup_result = dict((cleanup or (lambda _algorithm, _version: {"status": "cleanup_pending"}))(
            dict(algorithm), dict(target),
        ) or {})
    except Exception as error:
        cleanup_result = {"status": "cleanup_failed", "targets": [], "errors": [str(error)]}
    status = str(cleanup_result.get("status") or "cleanup_failed")
    if status not in {"cleanup_completed", "cleanup_pending", "cleanup_failed"}:
        status = "cleanup_failed"
    with _update_lock(path):
        algorithms = list_algorithms(path)
        persisted = next((row for row in algorithms if str(row.get("id") or "") == str(algorithm_id)), None)
        operation = next(
            (row for row in (persisted or {}).get("version_operations") or [] if str(row.get("id") or "") == operation_id),
            None,
        )
        if operation is None:
            raise PlatformError(
                "ALGORITHM_CLEANUP_STATE_LOST", "版本已删除，但清理状态无法保存",
                f"找不到操作记录 {operation_id}。", "请检查 algorithms.json 一致性。", 500,
            )
        operation["cleanup_status"] = status
        operation["cleanup_targets"] = [str(item) for item in cleanup_result.get("targets") or []]
        operation["cleanup_errors"] = [str(item) for item in cleanup_result.get("errors") or []]
        save_algorithms(path, algorithms)
    return {
        "algorithm_id": str(algorithm_id),
        "previous_current_version_id": current_id,
        "current_version_id": current_id,
        "deleted_version_id": str(version_id),
        "action": "delete_version",
        "operation_id": operation_id,
        "cleanup_status": status,
        "cleanup_targets": [str(item) for item in cleanup_result.get("targets") or []],
        "cleanup_errors": [str(item) for item in cleanup_result.get("errors") or []],
    }

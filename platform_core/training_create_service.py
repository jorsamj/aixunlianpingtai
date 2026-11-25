"""Training-creation admission service.

Owns the creation-time business that does not depend on the HTTP request object:
the frozen background-confirmation block, the material-input admission, the
optional synchronous compatibility preflight, and the coded conflict contract
returned to the caller. The application injects its collaborators, so this
module never imports ``app``.

Product contracts preserved here:

* consent is bound to the exact selected source/GT rows (task, algorithm,
  request identity and selection fingerprint), never to a global flag;
* a queued creation still defers the authoritative GT/duplicate/history checks
  to the durable TRAINING_PREPARE worker; the synchronous preflight is only the
  opt-in path it always was;
* conflicts keep their existing codes and Chinese messages.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from fastapi import HTTPException

from .material_batches import BatchRequestError as MaterialBatchRequestError
from .material_batches import assert_material_input_admission
from .performance_diagnostics import measure as performance_measure
from .training_tasks import TrainingAdmissionError


@dataclass(frozen=True)
class TrainingCreateAdmission:
    """Collaborators the creation admission needs, supplied by the application.

    Every collaborator is a callable resolved at use time, so an application (or
    a test) that replaces its own data root, repository, artifact store or
    material store is honoured by this service instead of a stale binding.
    """

    data_dir: Callable[[], Path]
    repository: Callable[[], Any]
    artifacts: Callable[[], Any]
    material_store: Callable[[str], Any]
    compatibility_request: Callable[
        [str, Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]
    ]
    selected_input_fingerprint: Callable[[Path, list[str]], str]
    compatibility_evaluator: Callable[..., Any]
    compatibility_page: Callable[..., Mapping[str, Any]]


@dataclass(frozen=True)
class TrainingIdentityDependencies:
    """Collaborators the training identity resolution needs (resolved at use)."""

    list_algorithms: Callable[[str], list[dict[str, Any]]]
    current_version_id: Callable[[Mapping[str, Any]], str]
    confirmed_iteration_action: Callable[[Mapping[str, Any], Any], Any]
    freeze_mother_model: Callable[[str, str], str]


def resolve_algorithm_asset(
    *,
    project_id: str,
    payload: Any,
    dependencies: TrainingIdentityDependencies,
) -> tuple[dict[str, Any], str]:
    """Resolve the asset the request iterates and the version it is based on.

    The asset must exist in this project (404 otherwise) and the reference
    version is the asset's current version at creation time, which TRAINING_PREPARE
    re-checks under the creation fence.
    """
    asset_algorithm = next(
        (
            row for row in dependencies.list_algorithms(project_id)
            if str(row.get("id") or "") == str(payload.algorithm_asset_id or "")
        ),
        None,
    )
    if asset_algorithm is None:
        raise HTTPException(status_code=404, detail="训练算法不存在")
    reference_version_id = str(
        dependencies.current_version_id(asset_algorithm) or ""
    ).strip()
    return dict(asset_algorithm), reference_version_id


def confirmed_training_iteration_action(
    *,
    payload: Any,
    asset_algorithm: Mapping[str, Any],
    dependencies: TrainingIdentityDependencies,
) -> Any | None:
    """Validate the confirmed iteration action, keeping its existing errors."""
    if not payload.iteration_action:
        return None
    return dependencies.confirmed_iteration_action(asset_algorithm, payload)


def freeze_training_mother_model(
    *,
    project_id: str,
    payload: Any,
    asset_algorithm: Mapping[str, Any],
    dependencies: TrainingIdentityDependencies,
) -> str:
    """Freeze the local mother-model path for a brand-new algorithm.

    An algorithm that already owns versions keeps its existing model reference;
    only the first training freezes the uploaded/selected mother model, exactly
    as before.
    """
    if list(asset_algorithm.get("versions") or []):
        return ""
    return str(dependencies.freeze_mother_model(project_id, payload.model))


def training_background_confirmation(
    *,
    project_id: str,
    task_id: str,
    payload: Any,
    asset_algorithm: Mapping[str, Any],
    requested_split: Any,
    request_identity: str,
    review_actor_id: str,
    project_path: Path,
    admission: TrainingCreateAdmission,
) -> dict[str, Any]:
    """Bind the explicit batch confirmation to these exact source/GT rows."""
    train_ids = list(requested_split.train_image_ids)
    test_ids = list(requested_split.test_image_ids)
    return {
        "schema_version": 2,
        "task_id": task_id,
        "project_id": project_id,
        "algorithm_asset_id": str(asset_algorithm.get("id") or ""),
        "actor_id": review_actor_id.strip(),
        "request_identity": request_identity,
        "train_image_ids": train_ids,
        "test_image_ids": test_ids,
        "selected_input_fingerprint": admission.selected_input_fingerprint(
            project_path, [*train_ids, *test_ids],
        ),
    }


def assert_training_create_admission(
    *,
    project_id: str,
    project_path: Path,
    payload: Any,
    requested_split: Any,
    asset_algorithm: Mapping[str, Any],
    raw_request: Mapping[str, Any],
    admission: TrainingCreateAdmission,
) -> Any | None:
    """Run the source admission and the opt-in synchronous preflight.

    Returns the compatibility report when the synchronous path ran, ``None`` for
    the durable background path. Raises the same coded HTTP errors as before.
    """
    try:
        with performance_measure("training.create.source_admission"):
            assert_material_input_admission(
                project_id,
                list(requested_split.image_ids),
                admission.material_store(project_id),
                admission.repository(),
                admission.artifacts(),
            )
        # The prepare child independently performs the authoritative GT,
        # duplicate, history, benchmark and label checks before the parent
        # becomes runnable. Repeating that full scan on the HTTP thread defeats
        # durable asynchronous creation for large selections.
        compatibility = None
        if payload.admission_mode == "synchronous":
            compatibility_request = admission.compatibility_request(
                project_id, asset_algorithm, raw_request,
            )
            with performance_measure("training.create.full_preflight"):
                compatibility = admission.compatibility_evaluator(
                    admission.data_dir(),
                    project_path,
                    compatibility_request,
                    asset_algorithm,
                )
    except MaterialBatchRequestError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": str(error)},
        ) from error
    except ValueError as error:
        if isinstance(error, TrainingAdmissionError):
            # Keep the legacy 409 plus Chinese message; expose the stable
            # admission code through the existing coded error shape.
            raise HTTPException(
                status_code=409,
                detail={"code": error.code, "message": str(error)},
            ) from error
        raise HTTPException(status_code=409, detail=str(error)) from error
    return compatibility


def raise_training_create_conflict(
    compatibility: Any | None, *, admission: TrainingCreateAdmission
) -> None:
    """Translate a compatibility report into the existing coded 409."""
    if compatibility is None or not compatibility.issues:
        return
    page = admission.compatibility_page(compatibility, limit=100)
    duplicate_types = {item["issue_type"] for item in compatibility.issues}
    error_code = (
        "CONTENT_HASH_LEAKAGE" if "content_hash_leakage" in duplicate_types else
        "DUPLICATE_ANNOTATION_CONFLICT" if "duplicate_annotation_conflict" in duplicate_types else
        "TRAINING_MATERIAL_SCOPE_INCOMPATIBLE"
    )
    raise HTTPException(
        status_code=409,
        detail={
            "code": error_code,
            "message": (
                "训练与独立试验素材存在同内容图片，请重新划分素材角色"
                if error_code == "CONTENT_HASH_LEAKAGE" else
                "重复图片的原始标注不一致，请核对标注或明确排除本次训练输入"
                if error_code == "DUPLICATE_ANNOTATION_CONFLICT" else
                "所选素材的审核范围未覆盖本次训练标签，请先补审或排除素材"
            ),
            **compatibility.summary(),
            **page,
        },
    )


def prepare_training_create_admission(
    *,
    project_id: str,
    task_id: str,
    payload: Any,
    asset_algorithm: Mapping[str, Any],
    requested_split: Any,
    raw_request: Mapping[str, Any],
    request_identity: str,
    review_actor_id: str,
    project_path: Path,
    admission: TrainingCreateAdmission,
) -> tuple[dict[str, Any], Any | None]:
    """The creation admission as one step: confirmation, admission, preflight."""
    confirmation: dict[str, Any] = {}
    if payload.review_all_training_backgrounds:
        confirmation = training_background_confirmation(
            project_id=project_id,
            task_id=task_id,
            payload=payload,
            asset_algorithm=asset_algorithm,
            requested_split=requested_split,
            request_identity=request_identity,
            review_actor_id=review_actor_id,
            project_path=project_path,
            admission=admission,
        )
    compatibility = assert_training_create_admission(
        project_id=project_id,
        project_path=project_path,
        payload=payload,
        requested_split=requested_split,
        asset_algorithm=asset_algorithm,
        raw_request=raw_request,
        admission=admission,
    )
    raise_training_create_conflict(compatibility, admission=admission)
    return confirmation, compatibility


__all__ = [
    "TrainingCreateAdmission",
    "assert_training_create_admission",
    "prepare_training_create_admission",
    "raise_training_create_conflict",
    "training_background_confirmation",
]


def build_training_create_payload(
    *,
    project_id: str,
    task_id: str,
    payload: Any,
    asset_algorithm: Mapping[str, Any],
    reference_version_id: str,
    confirmed_iteration_action: Any,
    requested_split: Any,
    raw_request: Mapping[str, Any],
    request_identity: str,
    reference_request_identity: str,
    prepare_task_id: str,
    frozen_robustness: Mapping[str, Any],
    framework: str,
    target: str,
    resource_key: str,
) -> dict[str, Any]:
    """Assemble the frozen creation payload once, before any task exists.

    Every identity field the durable worker will re-check (algorithm, version,
    split/selection projection, resource target, prepare child) is bound here,
    so the request identity, the replay check and TRAINING_PREPARE all see the
    same frozen document.
    """
    return {
    **raw_request,
    **frozen_robustness,
    "schema_version": 4,
    "request_identity": request_identity,
    "reference_request_identity": reference_request_identity,
    "admission_request": raw_request,
    "training_input_state": "PREPARING",
    "training_prepare_task_id": prepare_task_id,
    "requested_split": {
        "mode": requested_split.mode.value,
        **({'validation_image_ids': list(requested_split.validation_image_ids)} if requested_split.validation_image_ids else {}),
        "train_image_ids": list(requested_split.train_image_ids),
        "test_image_ids": list(requested_split.test_image_ids),
        "experiment_percent": requested_split.experiment_percent,
        "validation_percent": requested_split.validation_percent,
    },
    "asset_algorithm_id": str(asset_algorithm.get("id") or ""),
    "algorithm_asset_id": str(asset_algorithm.get("id") or ""),
    "asset_algorithm_name": str(asset_algorithm.get("name") or "已删除算法"),
    # Creation-time iteration-base fence. TRAINING_PREPARE refuses to freeze
    # a different base if the algorithm current pointer moves while queued.
    # Historical payloads without this field keep the previous behavior.
    "reference_version_id": reference_version_id,
    "algorithm_identity": {
        "id": str(asset_algorithm.get("id") or ""),
        "name": str(asset_algorithm.get("name") or "已删除算法"),
        "source_type": str(asset_algorithm.get("source_type") or "LOCAL"),
        "provider_type": str(asset_algorithm.get("provider_type") or ""),
        "external_product_id": str(asset_algorithm.get("external_product_id") or ""),
        "external_category_id": str(asset_algorithm.get("external_category_id") or ""),
    },
    "confirmed_iteration_action": confirmed_iteration_action,
    "requested_device": payload.device,
    "requested_resources": {
        "resource_strategy": str(payload.resource_strategy or "auto").lower(),
        "resource_profile": str(payload.resource_profile or "performance").lower(),
        "gpu_policy": str(payload.gpu_policy or "exclusive").lower(),
        "requested_device": str(payload.device or "auto"),
        "batch": int(payload.batch),
        "workers": int(payload.workers),
        "precision": str(payload.precision or "auto").lower(),
        "cache": raw_request.get("cache", False),
    },
    "target_resource_key": resource_key,
    "target_required_capabilities": [f"training.{framework}"],
    **(
        {
            "remote_input_state": "PREPARING",
            "remote_prepare_task_id": prepare_task_id,
        }
        if target == "remote" else {}
    ),
    }

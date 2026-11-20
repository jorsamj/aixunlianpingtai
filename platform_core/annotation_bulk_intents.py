"""Sealed admission records for selected formal annotation. No execution authority."""
import hashlib
import json
import re
import time

from fastapi import HTTPException

from .annotation_candidates import CandidateStore
from .annotation_task_service import _canonical_review_scope
from .task_runtime import TaskKind, TaskStatus
from .task_runtime.payload_publications import EVIDENCE_REF, PayloadPublicationError

_BATCH_SIZE = 100
_MAX_IMAGES = 50_000
_MAX_MANIFEST_BYTES = 64 * 1024 * 1024
_SHA256 = re.compile(r"[a-f0-9]{64}")


def _digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _candidate_digest(row):
    return _digest({key: row.get(key) for key in (
        "image_id", "status", "review_state", "accepted", "gt_committed", "manual_review_required",
        "review_scope_policy", "review_scope", "boxes", "original_boxes", "draft_revision", "draft",
        "source_content_sha256",
    )})


def _receipt_path(request_id):
    from app import _annotation_review_operation_path

    name = _annotation_review_operation_path(request_id).rsplit("/", 1)[-1]
    return "review/bulk-formal/intents/" + name


def _intent_identity(actor, project_id, task_id, request_id):
    return {
        "actor": actor, "project_id": project_id, "task_id": task_id, "request_id": request_id,
    }


def load_sealed_intent(artifacts, identity, *, allow_missing=False):
    """Read the publication pointer and verify the referenced immutable manifest."""
    task_id = identity["task_id"]
    try:
        pointer = artifacts.read_json(task_id, _receipt_path(identity["request_id"]))
        if pointer is None and allow_missing:
            return None
        if not isinstance(pointer, dict) or pointer.get("identity") != identity:
            raise HTTPException(404, detail="批量入库意图不存在或无访问权限")
        ref = pointer.get("manifest_ref")
        if not isinstance(ref, str) or not EVIDENCE_REF.fullmatch(ref):
            raise ValueError("invalid manifest reference")
        manifest = artifacts.payload_reader.read_evidence_json(task_id, ref, max_bytes=_MAX_MANIFEST_BYTES)
        operation = manifest["operation"]
        if (operation["identity"] != identity or operation["status"] != "accepted"
                or manifest["schema"] != 1 or len(manifest["images"]) != operation["count"]
                or not 1 <= operation["count"] <= _MAX_IMAGES
                or _digest(manifest["intent"]) != operation["request_digest"]
                or manifest["intent"]["identity"] != identity
                or operation["operation_id"] != pointer.get("operation_id")
                or operation["operation_id"] != _digest(["bulk-formal:v1", operation["request_digest"]])):
            raise ValueError("intent manifest identity mismatch")
        return manifest, ref
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise HTTPException(503, detail="批量入库意图的持久证据无法核验") from error


def _public(sealed):
    manifest, ref = sealed
    operation = manifest["operation"]
    return {
        **{key: value for key, value in operation.items() if key != "identity"},
        "request_id": operation["identity"]["request_id"],
        "project_id": operation["identity"]["project_id"],
        "task_id": operation["identity"]["task_id"],
        "manifest_ref": ref,
        "manifest_digest": EVIDENCE_REF.fullmatch(ref)["digest"],
    }


def read_intent(artifacts, actor, project_id, task_id, request_id):
    return _public(load_sealed_intent(artifacts, _intent_identity(actor, project_id, task_id, request_id)))


def _read_baselines(store, materials, annotations, ids, labels):
    rows = []
    for offset in range(0, len(ids), _BATCH_SIZE):
        chunk = ids[offset:offset + _BATCH_SIZE]
        candidates = store.get_many(chunk)
        if len(candidates) != len(chunk) or annotations.candidate_committed_ids(store.task_id, chunk):
            raise ValueError("候选缺失或已正式入库")
        sources = {}
        for image_id in chunk:
            row = candidates[image_id]
            source = row.get("source_content_sha256")
            if (row.get("status") not in ("success", "empty") or row.get("review_state") != "active"
                    or row.get("accepted") is False or row.get("gt_committed")
                    or row.get("review_scope_policy") not in (None, "task_uniform_legacy")
                    or not isinstance(source, str) or not _SHA256.fullmatch(source)):
                raise ValueError(f"候选 {image_id} 的资格或源摘要已变化")
            if row.get("manual_review_required") and not store._draft_has_human_resolution(
                row.get("draft_revision"), json.dumps(row.get("draft") or {}),
            ):
                raise ValueError(f"候选 {image_id} 尚未人工消歧")
            if any(str(box.get("label") or "").strip() not in labels for box in row.get("boxes", [])):
                raise ValueError(f"候选 {image_id} 包含失效标签")
            sources[image_id] = source
        materials.assert_formal_annotation_admission(sources)
        ground_truth = annotations.get_many(chunk)
        for image_id in chunk:
            candidate, gt = candidates[image_id], ground_truth[image_id]
            version = gt.get("version")
            if type(version) is not int or version < 0:
                raise ValueError(f"正式标注 {image_id} 缺少有效版本")
            # Version zero is the repository's legacy/non-persisted GT view.
            digest = annotations.record_digest(gt) if version == 0 else gt.get("content_digest")
            if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
                raise ValueError(f"正式标注 {image_id} 缺少可信摘要")
            rows.append({
                "image_id": image_id,
                "candidate_digest": _candidate_digest(candidate),
                "draft_revision": candidate.get("draft_revision", 0),
                "source_content_sha256": sources[image_id],
                "gt_version": version,
                "gt_content_digest": digest,
            })
    return rows


def accept_intent(artifacts, actor, task, request):
    from filelock import FileLock, Timeout
    from app import (
        _annotation_label_catalog, _load_annotation_review_selection,
        _require_annotation_review_task, _v50_annotation_repository, get_project,
        label_governance_fence, material_annotation_lifecycle_fence, material_store,
        now_iso, project_dir,
    )

    task_id, project_id = task.task_id, task.project_id
    identity = _intent_identity(actor, project_id, task_id, request.request_id)
    path = _receipt_path(request.request_id)
    excluded = sorted(set(request.excluded_image_ids))
    intent = {
        "identity": identity, "selection_id": request.selection_id, "purpose": "gt",
        "review_revision": request.review_revision, "excluded_image_ids": excluded,
    }
    request_digest = _digest(intent)
    operation_id = _digest(["bulk-formal:v1", request_digest])
    project_path = project_dir(project_id)

    def active_labels():
        return {row["code"]: row["class_id"] for row in _annotation_label_catalog(get_project(project_id))}

    try:
        with FileLock(str(artifacts.artifact_path(task_id, "review.lock")), timeout=30):
            sealed = load_sealed_intent(artifacts, identity, allow_missing=True)
            if sealed is not None:
                if sealed[0]["operation"]["request_digest"] != request_digest:
                    raise HTTPException(409, detail="同一操作编号的入库意图不一致")
                return _public(sealed)

            task = _require_annotation_review_task(project_id, task_id)
            if task.status is not TaskStatus.AWAITING_CONFIRMATION:
                raise HTTPException(409, detail="任务当前不可审核")
            config = artifacts.read_json(task_id, task.payload_ref)
            if isinstance(config, dict) and task.kind is TaskKind.MATERIAL_BATCH:
                config = config.get("options")
            if not isinstance(config, dict) or config.get("review_scope_policy", "task_uniform_legacy") != "task_uniform_legacy":
                raise HTTPException(409, detail="仅支持普通审核任务的批量入库意图")
            store = CandidateStore(artifacts, task_id=task_id)
            revision = store.review_revision()
            if request.review_revision != revision:
                raise HTTPException(409, detail="审核修订已变化")
            selection = _load_annotation_review_selection(
                store, project_id, task_id, request.selection_id, actor, revision,
            )
            original = selection["image_ids"]
            if selection.get("purpose") != "gt":
                raise HTTPException(409, detail="快照用途必须是 gt")
            if any(not isinstance(value, str) or not value for value in original) or len(set(original)) != len(original):
                raise HTTPException(409, detail="筛选快照的图片身份无效")
            exclusion = set(excluded)
            if not exclusion.issubset(original):
                raise HTTPException(422, detail="排除图片必须属于原筛选快照")
            ids = [image_id for image_id in original if image_id not in exclusion]
            if not 1 <= len(ids) <= _MAX_IMAGES:
                raise HTTPException(422, detail="有效入库范围必须包含 1～50000 张图片")

            annotations, materials = _v50_annotation_repository(project_id), material_store(project_id)
            with label_governance_fence(project_path), material_annotation_lifecycle_fence(project_path):
                labels = active_labels()
                gt_revision, material_revision = annotations.current_revision(), materials.current_revision()
            manifest = artifacts.read_json(task_id, "candidates/manifest.json", default={})
            try:
                scope = _canonical_review_scope(config.get("labels") or manifest.get("labels") or [], {}, labels)
                rows = _read_baselines(store, materials, annotations, ids, labels)
            except (ValueError, RuntimeError) as error:
                raise HTTPException(409, detail=str(error)) from error
            operation = {
                "identity": identity, "operation_id": operation_id, "request_digest": request_digest,
                "selection_id": request.selection_id, "purpose": "gt", "review_revision": revision,
                "original_count": len(original), "excluded_count": len(excluded), "count": len(rows),
                "status": "accepted", "accepted_at": now_iso(),
            }
            evidence = {
                "schema": 1, "intent": intent, "operation": operation, "filter": selection.get("filter"),
                "images": rows, "gt_revision": gt_revision, "material_revision": material_revision,
                "review_contract": {"policy": "task_uniform_legacy", "labels": scope,
                                    "label_class_ids": labels, "overwrite": bool(config.get("overwrite"))},
            }
            # Content-addressed evidence may be staged first. Only the pointer
            # published after the final fence checks makes it an accepted intent.
            ref = artifacts.write_evidence_json(task_id, evidence)
            artifacts.payload_reader.read_evidence_json(task_id, ref, max_bytes=_MAX_MANIFEST_BYTES)
            with label_governance_fence(project_path), material_annotation_lifecycle_fence(project_path):
                current = _require_annotation_review_task(project_id, task_id)
                if (current.status is not TaskStatus.AWAITING_CONFIRMATION or current.payload_ref != task.payload_ref
                        or time.time() >= selection["expires_at"] or store.review_revision() != revision
                        or annotations.current_revision() != gt_revision or materials.current_revision() != material_revision
                        or active_labels() != labels):
                    raise HTTPException(409, detail="审核、素材或正式标注已变化，请重新确认")
                artifacts.atomic_write_json(task_id, path, {
                    "identity": identity, "operation_id": operation_id, "manifest_ref": ref,
                })
            return _public((evidence, ref))
    except Timeout as error:
        raise HTTPException(409, detail="审核任务繁忙，请稍后核验原操作") from error
    except (OSError, PayloadPublicationError) as error:
        raise HTTPException(503, detail="批量入库意图未能完成持久化，请核验原操作") from error

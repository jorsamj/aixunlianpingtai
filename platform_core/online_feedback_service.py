"""Business rules for reviewable online inference feedback (v6x).

This module owns the online-feedback review workflow that previously lived in
``app.py``: turning one verified prediction into feedback evidence, confirming
it into formal GT / candidate-only state, and dismissing it. Persistence stays
in :class:`platform_core.online_feedback.OnlineFeedbackRepository`; material and
annotation truth stay with their existing owners.

The host application injects its infra dependencies explicitly; this module
never imports ``app`` and keeps no app-level globals.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from fastapi import HTTPException

from .annotation_repository import AnnotationRepository
from .labels import active_label_options, label_governance_fence
from .model_artifacts import model_delivery_version_fence
from .online_feedback import (
    DIRECT_TRUTH_FEEDBACK_TYPES,
    OnlineFeedbackRepository,
    public_feedback,
    validate_prediction_evidence,
)


ONLINE_FEEDBACK_MAX_IMAGE_BYTES = 20 * 1024 * 1024
ONLINE_FEEDBACK_MAX_DETECTIONS_JSON = 2 * 1024 * 1024
CORRECTION_KINDS = (
    "", "missed_detection", "wrong_class", "inaccurate_box", "partial_correction", "other",
)


def version_model_sha256(version: Mapping[str, Any], sha256_file) -> str:
    """Resolve the single verifiable model SHA of one formal algorithm version."""
    candidates: List[str] = []
    stored_path = Path(str(version.get("stored_path") or ""))
    if stored_path.is_file() and stored_path.stat().st_size > 0:
        candidates.append(sha256_file(stored_path).lower())
    lineage = version.get("training_lineage")
    if isinstance(lineage, Mapping):
        for artifact in lineage.get("artifacts") or []:
            if not isinstance(artifact, Mapping):
                continue
            if str(artifact.get("role") or "") != "primary" or not bool(artifact.get("verified")):
                continue
            digest = str(artifact.get("sha256") or "").strip().lower()
            if len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest):
                candidates.append(digest)
    candidates = list(dict.fromkeys(candidates))
    if not candidates:
        raise HTTPException(
            status_code=409,
            detail="算法版本没有可验证的正式模型 SHA，请先恢复版本模型产物",
        )
    if len(candidates) != 1:
        raise HTTPException(
            status_code=409,
            detail="算法版本模型文件与训练 lineage SHA 不一致，请先修复版本真值",
        )
    return candidates[0]


def prediction_evidence(
    project_id: str,
    prediction_id: str,
    *,
    project_dir,
    sha256_file,
    read_json,
    algorithm_version_for_action,
    version_model_sha256_fn,
):
    """Load one verified prediction evidence file and re-check its identity."""
    prediction_id = str(prediction_id or "").strip()
    if (
        not prediction_id
        or len(prediction_id) > 64
        or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in prediction_id)
    ):
        raise HTTPException(status_code=400, detail="prediction_id 无效")
    root = project_dir(project_id) / "predictions"
    raw_evidence = read_json(root / f"{prediction_id}.evidence.json", {})
    evidence = validate_prediction_evidence(raw_evidence)
    if evidence["prediction_id"] != prediction_id:
        raise HTTPException(status_code=409, detail="预测证据身份不一致，请重新测试")
    stored_project = str(raw_evidence.get("project_id") or "").strip()
    if stored_project and stored_project != str(project_id):
        raise HTTPException(status_code=409, detail="预测证据项目归属不一致，请重新测试")
    # Persist the owning project in new feedback evidence without rewriting the
    # prediction file; legacy prediction files without this field stay valid.
    evidence["project_id"] = str(project_id)
    input_file = str(evidence.get("input_file") or "")
    if not input_file or Path(input_file).name != input_file:
        raise HTTPException(status_code=409, detail="预测输入证据无效，请重新测试")
    input_path = root / input_file
    if not input_path.is_file() or sha256_file(input_path) != evidence["input_sha256"]:
        raise HTTPException(status_code=409, detail="测试图片在抽检前已变化，请重新测试")
    algorithm, version = algorithm_version_for_action(
        project_id, evidence["algorithm_id"], evidence["version_id"]
    )
    if version_model_sha256_fn(version) != evidence["model_sha256"]:
        raise HTTPException(status_code=409, detail="算法版本模型已变化，请重新测试")
    return evidence, input_path, algorithm, version


def box_signature(boxes: List[Dict[str, Any]]) -> List[Tuple[int, str, float, float, float, float]]:
    """Compare reviewed prediction truth without depending on box IDs/order."""
    result = []
    for box in boxes or []:
        result.append((
            int(box.get("class_id") or 0),
            str(box.get("label") or box.get("code") or ""),
            round(float(box.get("x1") or 0), 4),
            round(float(box.get("y1") or 0), 4),
            round(float(box.get("x2") or 0), 4),
            round(float(box.get("y2") or 0), 4),
        ))
    return sorted(result)


def prediction_boxes(project: Dict[str, Any], evidence: Dict[str, Any], project_label_items):
    active = active_label_options(project_label_items(project))
    by_code = {str(item["code"]): item for item in active}
    by_display: Dict[str, List[Dict[str, Any]]] = {}
    for item in active:
        by_display.setdefault(str(item.get("display_name") or ""), []).append(item)
    boxes = []
    for detection in evidence.get("detections") or []:
        label = str(detection.get("label") or "").strip()
        item = by_code.get(label)
        if item is None:
            matches = by_display.get(label) or []
            item = matches[0] if len(matches) == 1 else None
        if item is None:
            raise ValueError(f"预测标签 {label or '-'} 无法唯一映射到当前项目标签")
        boxes.append({
            "id": f"feedback-{evidence['prediction_id']}-{int(detection.get('index') or 0)}",
            "class_id": int(item["class_id"]),
            "label": str(item["code"]),
            "x1": float(detection["x1"]), "y1": float(detection["y1"]),
            "x2": float(detection["x2"]), "y2": float(detection["y2"]),
        })
    return boxes, [str(item["code"]) for item in active]


def truth_matches(
    feedback_type: str, annotation: Mapping[str, Any], expected_boxes: List[Dict[str, Any]],
    expected_scope: Optional[List[str]] = None,
) -> bool:
    """Read back the persisted formal GT; the receipt is never optimistic."""
    state = str(annotation.get("annotation_state") or "unannotated")
    boxes = list(annotation.get("boxes") or [])
    if feedback_type == "correct":
        return (
            state == "annotated"
            and bool(boxes)
            and box_signature(boxes)
            == box_signature(expected_boxes)
        )
    if state != "confirmed_empty" or boxes:
        return False
    scope = {
        str(value) for value in list(annotation.get("annotation_scope") or [])
        if str(value)
    }
    required = {
        str(value) for value in list(expected_scope or []) if str(value)
    }
    return "*" in scope or required.issubset(scope)


def gt_receipt(
    *,
    feedback_id: str,
    evidence: Mapping[str, Any],
    material_id: str,
    annotation: Mapping[str, Any],
    annotation_action: str,
    gt_write: str,
    request_id: str,
    confirmed_at: str,
) -> Dict[str, Any]:
    """Persist the exact formal-GT identity produced/reused by one review."""
    boxes = list(annotation.get("boxes") or [])
    return {
        "schema_version": 1,
        "feedback_id": str(feedback_id),
        "prediction_id": str(evidence.get("prediction_id") or ""),
        "project_id": str(evidence.get("project_id") or ""),
        "material_id": str(material_id),
        "algorithm_id": str(evidence.get("algorithm_id") or ""),
        "version_id": str(evidence.get("version_id") or ""),
        "model_sha256": str(evidence.get("model_sha256") or ""),
        "input_sha256": str(evidence.get("input_sha256") or ""),
        "annotation_state": str(annotation.get("annotation_state") or ""),
        "annotation_version": int(annotation.get("version") or 0),
        "annotation_content_digest": str(annotation.get("content_digest") or ""),
        "annotation_scope": sorted(
            str(value) for value in list(annotation.get("annotation_scope") or []) if str(value)
        ),
        "box_count": len(boxes),
        "labels": sorted({
            str(box.get("label") or box.get("code") or "")
            for box in boxes
            if str(box.get("label") or box.get("code") or "")
        }),
        "annotation_action": str(annotation_action),
        "gt_write": str(gt_write),
        "review_request_id": str(request_id),
        "confirmed_at": str(confirmed_at),
    }


class OnlineFeedbackService:
    """Orchestrates the online-feedback review workflow over existing owners."""

    def __init__(
        self,
        *,
        get_project,
        project_dir,
        material_store,
        data_dir,
        now_iso,
        sha256_file,
        read_json,
        write_json,
        safe_filename,
        business_file_url,
        project_label_items,
        algorithm_version_for_action,
        active_image_batch,
        begin_image_batch,
        end_image_batch,
        add_image_record,
        write_annotation,
        ensure_default_datasets,
        material_governance_actor,
        image_exts,
        version_model_sha256_fn=None,
    ):
        self._get_project = get_project
        self._project_dir = project_dir
        self._material_store = material_store
        self._data_dir = data_dir
        self._now_iso = now_iso
        self._sha256_file = sha256_file
        self._read_json = read_json
        self._write_json = write_json
        self._safe_filename = safe_filename
        self._business_file_url = business_file_url
        self._project_label_items = project_label_items
        self._algorithm_version_for_action = algorithm_version_for_action
        self._active_image_batch = active_image_batch
        self._begin_image_batch = begin_image_batch
        self._end_image_batch = end_image_batch
        self._add_image_record = add_image_record
        self._write_annotation = write_annotation
        self._ensure_default_datasets = ensure_default_datasets
        self._material_governance_actor = material_governance_actor
        self._image_exts = image_exts
        self._version_model_sha256 = version_model_sha256_fn or (
            lambda version: version_model_sha256(version, self._sha256_file)
        )

    # -- shared helpers ---------------------------------------------------
    def repository(self, project_id: str) -> OnlineFeedbackRepository:
        return OnlineFeedbackRepository(self._project_dir(project_id))

    def _evidence(self, project_id: str, prediction_id: str):
        return prediction_evidence(
            project_id,
            prediction_id,
            project_dir=self._project_dir,
            sha256_file=self._sha256_file,
            read_json=self._read_json,
            algorithm_version_for_action=self._algorithm_version_for_action,
            version_model_sha256_fn=self._version_model_sha256,
        )

    def prediction_boxes(self, project: Dict[str, Any], evidence: Dict[str, Any]):
        return prediction_boxes(project, evidence, self._project_label_items)

    # -- reads ------------------------------------------------------------
    def list_feedback(self, project_id: str, status: str = "", limit: int = 100):
        self._get_project(project_id)
        allowed = {"", "pending_review", "confirmed", "dismissed"}
        if status not in allowed:
            raise HTTPException(status_code=400, detail="反馈状态无效")
        rows = self.repository(project_id).list(status=status, limit=limit)
        return [public_feedback(row, compact=True) for row in rows]

    def feedback_detail(self, project_id: str, feedback_id: str):
        self._get_project(project_id)
        row = self.repository(project_id).get(feedback_id)
        if row is None:
            raise HTTPException(status_code=404, detail="抽检反馈不存在")
        public = public_feedback(row)
        if public.get('source', {}).get('source_channel') == 'evaluation':
            from urllib.parse import quote, urlencode
            source = public['source']
            public['input_image_url'] = (
                f"/api/v12/projects/{quote(project_id, safe='')}/algorithms/{quote(public['algorithm_id'], safe='')}"
                f"/versions/{quote(public['version_id'], safe='')}/evaluation/images/{quote(source.get('original_filename', ''), safe='')}?"
                + urlencode({'expected_evaluation_id': source.get('external_source', ''),
                             'expected_image_id': source.get('external_sample_id', ''), 'expected_sha256': public['input_sha256']})
            )
            public['result_image_url'] = ''
            public['review_only'] = True
            return public
        try:
            evidence, _, _, _ = self._evidence(project_id, row["prediction_id"])
            public["input_image_url"] = self._business_file_url(project_id, 'predictions', evidence['input_file'])
            result_image = self._project_dir(project_id) / "predictions" / f"{row['prediction_id']}_result.jpg"
            public["result_image_url"] = (
                self._business_file_url(project_id, 'predictions', result_image.name)
                if result_image.is_file() else ""
            )
        except (HTTPException, ValueError):
            public["input_image_url"] = ""
            public["result_image_url"] = ""
        return public

    # -- writes -----------------------------------------------------------
    def stage_feedback(
        self,
        project_id: str,
        *,
        prediction_id: str,
        feedback_type: str,
        note: str,
        correction_kind: str,
    ):
        self._get_project(project_id)
        try:
            source, _, _, _ = self._evidence(project_id, prediction_id)
            with model_delivery_version_fence(
                self._data_dir, project_id, source["algorithm_id"], source["version_id"],
            ):
                evidence, _, _, _ = self._evidence(project_id, prediction_id)
                with label_governance_fence(self._project_dir(project_id)):
                    if feedback_type == "correct":
                        self.prediction_boxes(self._get_project(project_id), evidence)
                    row, idempotent = self.repository(project_id).stage(
                        evidence,
                        feedback_type=feedback_type,
                        note=note,
                        created_at=self._now_iso(),
                        correction_kind=correction_kind,
                    )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return idempotent, public_feedback(row)

    async def stage_external_feedback(
        self,
        project_id: str,
        *,
        algorithm_id: str,
        version_id: str,
        model_sha256: str,
        external_source: str,
        external_sample_id: str,
        feedback_type: str,
        detections_json: str,
        confidence: float,
        note: str,
        correction_kind: str,
        upload,
    ):
        from PIL import Image

        self._get_project(project_id)
        source_name = str(external_source or "").strip()
        sample_id = str(external_sample_id or "").strip()
        if (
            not source_name or len(source_name) > 200
            or not sample_id or len(sample_id) > 200
            or any(ord(ch) < 32 for ch in source_name + sample_id)
        ):
            raise HTTPException(status_code=400, detail="外部来源或样本编号无效")
        if len(str(detections_json or "")) > ONLINE_FEEDBACK_MAX_DETECTIONS_JSON:
            raise HTTPException(status_code=413, detail="detections_json 过大")
        try:
            detections = json.loads(detections_json or "[]")
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=400, detail="detections_json 不是有效 JSON") from error
        if not isinstance(detections, list):
            raise HTTPException(status_code=400, detail="detections_json 必须是数组")

        _, version = self._algorithm_version_for_action(project_id, algorithm_id, version_id)
        expected_model_sha = self._version_model_sha256(version)
        submitted_model_sha = str(model_sha256 or "").strip().lower()
        if (
            len(submitted_model_sha) != 64
            or any(ch not in "0123456789abcdef" for ch in submitted_model_sha)
        ):
            raise HTTPException(status_code=400, detail="model_sha256 无效")
        if submitted_model_sha != expected_model_sha:
            raise HTTPException(status_code=409, detail="外部样本声明的模型 SHA 与正式算法版本不一致")

        filename = self._safe_filename(upload.filename or "external.jpg")
        extension = Path(filename).suffix.lower()
        if extension not in self._image_exts:
            raise HTTPException(status_code=400, detail="外部抽检仅支持图片文件")
        raw = await upload.read(ONLINE_FEEDBACK_MAX_IMAGE_BYTES + 1)
        if not raw:
            raise HTTPException(status_code=400, detail="外部抽检图片为空")
        if len(raw) > ONLINE_FEEDBACK_MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="外部抽检图片超过 20MB")
        try:
            with Image.open(BytesIO(raw)) as image:
                image.verify()
            with Image.open(BytesIO(raw)) as image:
                width, height = int(image.width), int(image.height)
        except Exception as error:
            raise HTTPException(status_code=400, detail="外部抽检图片无法解码") from error

        input_sha = hashlib.sha256(raw).hexdigest()
        identity = {
            "external_source": source_name,
            "external_sample_id": sample_id,
            "algorithm_id": str(algorithm_id),
            "version_id": str(version_id),
        }
        prediction_id = "ext_" + hashlib.sha256(json.dumps(
            identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()[:24]
        root = self._project_dir(project_id) / "predictions"
        root.mkdir(parents=True, exist_ok=True)
        input_file = f"{prediction_id}_input{extension}"
        input_path = root / input_file
        evidence_path = root / f"{prediction_id}.evidence.json"

        try:
            incoming = validate_prediction_evidence({
                "schema_version": 1,
                "prediction_id": prediction_id,
                "project_id": project_id,
                "algorithm_id": str(algorithm_id),
                "version_id": str(version_id),
                "model_sha256": expected_model_sha,
                "input_sha256": input_sha,
                "original_filename": filename,
                "input_file": input_file,
                "width": width,
                "height": height,
                "confidence": float(confidence),
                "engine": "external",
                "detections": detections,
                "created_at": self._now_iso(),
                "source_channel": "external_upload",
                "external_source": source_name,
                "external_sample_id": sample_id,
            })
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        evidence_reused = False
        if evidence_path.is_file():
            existing = validate_prediction_evidence(self._read_json(evidence_path, {}))
            stable_keys = (
                "prediction_id", "algorithm_id", "version_id", "model_sha256",
                "input_sha256", "width", "height", "confidence", "engine",
                "detections", "source_channel", "external_source", "external_sample_id",
            )
            if any(existing.get(key) != incoming.get(key) for key in stable_keys):
                raise HTTPException(
                    status_code=409,
                    detail="同一外部样本编号已经绑定不同的图片或预测证据",
                )
            existing_input = root / str(existing.get("input_file") or "")
            if (
                not existing_input.is_file()
                or self._sha256_file(existing_input) != existing["input_sha256"]
            ):
                raise HTTPException(status_code=409, detail="已存在的外部样本证据文件不完整")
            incoming = existing
            evidence_reused = True
        else:
            if input_path.exists():
                raise HTTPException(status_code=409, detail="外部样本存在未完成的证据文件，请人工检查")
            temporary = root / f".{prediction_id}.{uuid.uuid4().hex}.upload"
            temporary.write_bytes(raw)
            try:
                os.replace(temporary, input_path)
                self._write_json(evidence_path, incoming)
            finally:
                temporary.unlink(missing_ok=True)

        if not incoming.get("project_id"):
            incoming["project_id"] = str(project_id)
        try:
            with model_delivery_version_fence(self._data_dir, project_id, algorithm_id, version_id):
                _, current_version = self._algorithm_version_for_action(project_id, algorithm_id, version_id)
                if self._version_model_sha256(current_version) != incoming["model_sha256"]:
                    raise HTTPException(
                        status_code=409, detail="正式算法版本在外部反馈写入期间发生变化",
                    )
                with label_governance_fence(self._project_dir(project_id)):
                    if feedback_type == "correct":
                        self.prediction_boxes(self._get_project(project_id), incoming)
                    row, repository_reused = self.repository(project_id).stage(
                        incoming,
                        feedback_type=feedback_type,
                        note=note,
                        created_at=self._now_iso(),
                        correction_kind=correction_kind,
                    )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return bool(evidence_reused or repository_reused), public_feedback(row)

    def confirm_feedback(self, project_id: str, feedback_id: str, payload, request):
        project = self._get_project(project_id)
        repository = self.repository(project_id)
        staged = repository.get(feedback_id)
        if staged is None:
            raise HTTPException(status_code=404, detail="抽检反馈不存在")
        review_request_id = str(payload.request_id or "").strip()
        if review_request_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", review_request_id):
            raise HTTPException(status_code=400, detail="request_id 无效")
        if staged["status"] == "confirmed":
            return True, public_feedback(staged)
        if staged["status"] != "pending_review":
            raise HTTPException(status_code=409, detail="抽检反馈已结束")
        if staged["feedback_type"] != payload.expected_feedback_type:
            raise HTTPException(status_code=409, detail="反馈类型已变化，请刷新后再确认")
        if (staged.get('payload') or {}).get('source', {}).get('source_channel') == 'evaluation':
            raise HTTPException(status_code=409, detail='冻结评测只允许在高级评测保存复核意见，不能通过抽检确认写入GT或采纳训练')
        # Human review evidence: reuse the existing verified login identity. It is
        # persisted with the formal GT receipt / candidate intent below.
        review_actor = self._material_governance_actor(request, project_id)["actor_id"]
        try:
            evidence, input_path, _, _ = self._evidence(
                project_id, staged["prediction_id"]
            )
            source = dict((staged.get("payload") or {}).get("source") or {})
            for key in ("algorithm_id", "version_id", "model_sha256", "input_sha256"):
                if str(source.get(key) or "") != str(evidence.get(key) or ""):
                    raise ValueError("抽检来源在确认前发生变化，请重新提交反馈")
            dataset_id = str(payload.dataset_id or "default")
            if dataset_id not in {str(row.get("id") or "") for row in self._ensure_default_datasets(project_id)}:
                raise ValueError("目标数据集不存在")

            feedback_type = str(staged["feedback_type"])
            correction_kind = str(
                staged.get("correction_kind")
                or (staged.get("payload") or {}).get("correction_kind")
                or ""
            )
            truth_feedback = feedback_type in DIRECT_TRUTH_FEEDBACK_TYPES
            truth_boxes: List[Dict[str, Any]] = []
            truth_scope: List[str] = []
            gt_write = "not_applicable"
            if feedback_type == "correct":
                preview_boxes, _ = self.prediction_boxes(project, evidence)
                if not preview_boxes:
                    raise ValueError("当前预测没有检测框；如画面确实无目标，请使用“误检/画面无目标”确认负样本")
            elif feedback_type == "false_positive":
                if not payload.confirm_all_labels_absent:
                    raise ValueError("请明确确认画面中不存在当前启用标签目标")
                _, preview_scope = self.prediction_boxes(project, {
                    **evidence, "detections": [],
                })
                if not preview_scope:
                    raise ValueError("项目没有可用于负样本确认的启用标签")
                truth_scope = list(preview_scope)

            materials = self._material_store(project_id)
            material = materials.get_by_content_sha256(evidence["input_sha256"])
            reused = material is not None
            image_batch_open = False
            try:
                if material is None:
                    if truth_feedback:
                        if self._active_image_batch(project_id) is not None:
                            raise RuntimeError("online feedback cannot nest image batches")
                        self._begin_image_batch(project_id)
                        image_batch_open = True
                    material = self._add_image_record(
                        project_id,
                        input_path,
                        evidence.get("original_filename") or input_path.name,
                        "online_feedback",
                        dataset_id,
                        "default_local",
                        content_sha256=evidence["input_sha256"],
                        defer_unannotated_annotation=image_batch_open,
                    )
                    if material is None:
                        raise ValueError("反馈图片无法写入素材库")
                material_id = str(material["id"])
                annotation_action = "manual_review"

                if truth_feedback:
                    with label_governance_fence(self._project_dir(project_id)):
                        # Re-read after acquiring the governance fence. Human review
                        # freezes intent, not a stale active-label catalog/class id.
                        current_project = self._get_project(project_id)
                        annotations = AnnotationRepository(self._project_dir(project_id))
                        current = annotations.get(material_id)
                        expected_version = int(current.get("version") or 0)
                        if feedback_type == "correct":
                            boxes, _ = self.prediction_boxes(
                                current_project, evidence,
                            )
                            if not boxes:
                                raise ValueError(
                                    "当前预测没有检测框；如画面确实无目标，请使用“误检/画面无目标”确认负样本"
                                )
                            truth_boxes = boxes
                            current_state = str(
                                current.get("annotation_state") or "unannotated"
                            )
                            if current_state == "unannotated":
                                self._write_annotation(
                                    project_id, material_id, boxes, "annotated",
                                    expected_version=expected_version,
                                )
                                annotation_action = "prediction_confirmed_as_truth"
                                gt_write = "written"
                            elif (
                                current_state == "annotated"
                                and box_signature(
                                    current.get("boxes") or []
                                )
                                == box_signature(boxes)
                            ):
                                # Recovery/idempotency: formal truth may have been
                                # committed immediately before feedback finalization
                                # failed. Matching truth is safe to acknowledge.
                                annotation_action = "prediction_matches_existing_truth"
                                gt_write = "already_present"
                            else:
                                raise ValueError(
                                    "该素材已有不同的正式标注，线上抽检不能覆盖现有 Annotation truth"
                                )
                        else:
                            _, active_codes = self.prediction_boxes(
                                current_project, {**evidence, "detections": []},
                            )
                            if not active_codes:
                                raise ValueError(
                                    "项目没有可用于负样本确认的启用标签"
                                )
                            truth_scope = list(active_codes)
                            state = str(
                                current.get("annotation_state") or "unannotated"
                            )
                            if state == "annotated":
                                raise ValueError(
                                    "该素材已有正式目标标注，不能直接改成负样本"
                                )
                            if state != "confirmed_empty":
                                self._write_annotation(
                                    project_id,
                                    material_id,
                                    [],
                                    "confirmed_empty",
                                    annotation_scope=active_codes,
                                    expected_version=expected_version,
                                )
                                gt_write = "written"
                            else:
                                gt_write = "already_present"
                            annotation_action = "confirmed_empty"

                    if image_batch_open:
                        self._end_image_batch(save=True)
                        image_batch_open = False
                else:
                    annotation_action = "manual_annotation_required"
            except Exception:
                if image_batch_open and self._active_image_batch(project_id) is not None:
                    self._end_image_batch(save=False)
                    image_batch_open = False
                raise

            confirmed_at = self._now_iso()
            truth_receipt: Dict[str, Any] = {}
            if truth_feedback:
                # Read the persisted formal GT after batching/flush. The receipt is
                # proof of stored truth, never of an in-memory intent.
                truth = AnnotationRepository(self._project_dir(project_id)).get(material_id)
                if not truth_matches(
                    feedback_type, truth, truth_boxes, truth_scope,
                ):
                    raise ValueError("正式标注在复核期间发生变化，本次反馈未确认；请刷新后重新复核")
                truth_receipt = gt_receipt(
                    feedback_id=feedback_id,
                    evidence=evidence,
                    material_id=material_id,
                    annotation=truth,
                    annotation_action=annotation_action,
                    gt_write=gt_write,
                    request_id=review_request_id,
                    confirmed_at=confirmed_at,
                )
            latest_material = materials.get(material_id) or material
            refs = [
                dict(value) for value in list(latest_material.get("online_feedback_refs") or [])
                if isinstance(value, dict) and str(value.get("feedback_id") or "") != str(feedback_id)
            ][-49:]
            refs.append({
                "schema_version": 1,
                "feedback_id": str(feedback_id),
                "prediction_id": evidence["prediction_id"],
                "algorithm_id": evidence["algorithm_id"],
                "version_id": evidence["version_id"],
                "model_sha256": evidence["model_sha256"],
                "input_sha256": evidence["input_sha256"],
                "feedback_type": staged["feedback_type"],
                "correction_kind": correction_kind,
                "confirmed_at": confirmed_at,
            })
            patch = {
                "online_feedback_refs": refs,
                "online_feedback_needs_review": feedback_type == "needs_correction",
                "updated_at": confirmed_at,
            }
            if truth_feedback:
                patch["processing_status"] = "processed"
            else:
                patch["processing_status"] = "pending_decision"
            materials.patch({material_id: patch})

            result = {
                "annotation_action": annotation_action,
                "material_reused": reused,
                "needs_manual_annotation": feedback_type == "needs_correction",
                "candidate_only": feedback_type not in DIRECT_TRUTH_FEEDBACK_TYPES,
                "dataset_id": dataset_id,
                "feedback_type": feedback_type,
                "correction_kind": correction_kind,
                "gt_recorded": bool(truth_receipt),
                "gt_written": bool(truth_receipt) and truth_receipt.get("gt_write") == "written",
                "review": {
                    "schema_version": 1,
                    "channel": "online_feedback_confirm",
                    "actor_id": review_actor,
                    "request_id": review_request_id,
                    "feedback_type": feedback_type,
                    "correction_kind": correction_kind,
                    "dataset_id": dataset_id,
                    "confirm_all_labels_absent": bool(payload.confirm_all_labels_absent),
                    "confirmed_at": confirmed_at,
                },
            }
            if truth_receipt:
                result["gt_receipt"] = truth_receipt
            row, idempotent = repository.finalize(
                feedback_id,
                expected_feedback_type=payload.expected_feedback_type,
                material_id=material_id,
                result=result,
                confirmed_at=confirmed_at,
            )
        except (ValueError, KeyError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return idempotent, public_feedback(row)

    def dismiss_feedback(self, project_id: str, feedback_id: str, payload):
        self._get_project(project_id)
        repository = self.repository(project_id)
        staged = repository.get(feedback_id)
        if staged is None:
            raise HTTPException(status_code=404, detail="抽检反馈不存在")
        if staged["feedback_type"] != payload.expected_feedback_type:
            raise HTTPException(status_code=409, detail="反馈类型已变化，请刷新后再处理")
        if staged["status"] == "dismissed":
            return True, public_feedback(staged)
        if staged["status"] != "pending_review":
            raise HTTPException(status_code=409, detail="已确认反馈不能再忽略")
        try:
            row, idempotent = repository.finalize(
                feedback_id,
                expected_feedback_type=payload.expected_feedback_type,
                material_id="",
                result={
                    "dismissed": True,
                    "dismiss_reason": str(payload.reason or "").strip()[:1000],
                },
                confirmed_at=self._now_iso(),
                status="dismissed",
            )
        except (ValueError, KeyError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return idempotent, public_feedback(row)

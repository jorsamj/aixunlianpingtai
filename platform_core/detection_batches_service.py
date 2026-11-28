"""Domain orchestration over the existing persistence, worker and receipt owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, List
from fastapi import Query, HTTPException
from .detection_batches_contracts import DetectionBatchReviewReq

from platform_core.task_runtime import TaskKind, TaskStatus

@dataclass(frozen=True)
class DetectionBatchesDependencies:
    get_project: Callable[..., Any]
    now_iso: Callable[..., Any]
    public_deployment_test: Callable[..., Any]
    shared_task_artifacts: Callable[..., Any]
    shared_task_repository: Callable[..., Any]


class DetectionBatchesService:
    def __init__(self, dependencies: DetectionBatchesDependencies):
        self.dependencies = dependencies

    def list_detection_batches(self, project_id: str, limit: int = Query(default=12, ge=1, le=50)):
        self.dependencies.get_project(project_id)
        grouped: Dict[str, list] = {}
        order: List[str] = []
        for row in self._iter_detection_batch_rows(project_id, scan_limit=1500):
            meta = row[1].get("detection_batch") or {}
            batch_id = str(meta.get("batch_id") or "")
            if not batch_id:
                continue
            if batch_id not in grouped:
                if len(order) >= limit:
                    continue
                grouped[batch_id] = []
                order.append(batch_id)
            grouped[batch_id].append(row)
        return {
            "ok": True,
            "items": [
                {key: value for key, value in self._public_detection_batch(project_id, batch_id, grouped[batch_id]).items() if key != "items"}
                for batch_id in order
            ],
        }

    def get_detection_batch(self, project_id: str, batch_id: str):
        self.dependencies.get_project(project_id)
        rows = list(self._iter_detection_batch_rows(project_id, batch_id, scan_limit=5000))
        if not rows:
            raise HTTPException(status_code=404, detail="检测批次不存在")
        return {"ok": True, "batch": self._public_detection_batch(project_id, batch_id, rows)}

    def review_detection_batch_item(self, project_id: str, batch_id: str, item_index: int, payload: DetectionBatchReviewReq):
        self.dependencies.get_project(project_id)
        rows = [
            row for row in self._iter_detection_batch_rows(project_id, batch_id, scan_limit=5000)
            if int((row[1].get("detection_batch") or {}).get("item_index") or 0) == int(item_index)
        ]
        if not rows:
            raise HTTPException(status_code=404, detail="检测结果不存在")
        terminal = {
            TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS, TaskStatus.FAILED,
            TaskStatus.CANCELLED, TaskStatus.BLOCKED_BY_ENVIRONMENT, TaskStatus.BLOCKED_BY_HARDWARE,
        }
        if any(task.status not in terminal for task, _, _, _ in rows):
            raise HTTPException(status_code=409, detail="检测任务尚未结束，暂不能人工核验")
        if not any(task.status in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS} for task, _, _, _ in rows):
            raise HTTPException(status_code=409, detail="该图片没有成功的真实检测结果，暂不能人工核验")
        review = {
            "schema_version": 1,
            "batch_id": str(batch_id),
            "item_index": int(item_index),
            "review": payload.review,
            "note": str(payload.note or "").strip()[:1000],
            "updated_at": self.dependencies.now_iso(),
        }
        artifacts = self.dependencies.shared_task_artifacts()
        for task, _, _, _ in rows:
            artifacts.atomic_write_json(task.task_id, "detection_review.json", review)
        return {"ok": True, "review": review}

    def _iter_detection_batch_rows(self, project_id: str, batch_id: str = "", *, scan_limit: int = 2000):
        repository = self.dependencies.shared_task_repository()
        artifacts = self.dependencies.shared_task_artifacts()
        cursor = None
        scanned = 0
        expected = str(batch_id or "").strip()
        while scanned < scan_limit:
            page = repository.list(
                project_id=project_id,
                kinds=(TaskKind.DEPLOYMENT_TEST,),
                limit=min(100, scan_limit - scanned),
                cursor=cursor,
            )
            if not page.items:
                break
            scanned += len(page.items)
            for task in page.items:
                request = artifacts.read_json(task.task_id, task.payload_ref, default={})
                batch = request.get("detection_batch") if isinstance(request, dict) else None
                if not isinstance(batch, dict) or not batch.get("batch_id"):
                    continue
                if expected and str(batch.get("batch_id")) != expected:
                    continue
                result = artifacts.read_json(task.task_id, task.result_ref, default={}) if task.result_ref else {}
                review = artifacts.read_json(task.task_id, "detection_review.json", default={})
                yield task, request, result if isinstance(result, dict) else {}, review if isinstance(review, dict) else {}
            cursor = page.next_cursor
            if not cursor:
                break

    def _public_detection_batch(self, project_id: str, batch_id: str, rows):
        repository = self.dependencies.shared_task_repository()
        grouped: Dict[int, Dict[str, Any]] = {}
        created_values: List[str] = []
        total = 0
        for task, request, result, review in rows:
            meta = request.get("detection_batch") or {}
            index = int(meta.get("item_index") or 0)
            total = max(total, int(meta.get("item_total") or 0))
            item = grouped.setdefault(index, {
                "index": index,
                "original_filename": str(meta.get("original_filename") or ""),
                "review": {},
                "models": {},
                "expected_sides": [],
            })
            side = str(meta.get("side") or "").upper()
            item['expected_sides'] = sorted(set(item['expected_sides']) | set(meta.get('expected_sides') or [side]))
            truth = self.dependencies.public_deployment_test(task)
            model = request.get("model_identity") if isinstance(request.get("model_identity"), dict) else {}
            public_result = {
                "task_id": task.task_id,
                "status": truth.get("status"),
                "progress_percent": truth.get("progress_percent"),
                "phase": truth.get("phase"),
                "creation_id": request.get("creation_id"),
                "model": model,
                "input_image_url": str(request.get("input_image_url") or ""),
                "result_image_url": str((result or {}).get("image_url") or request.get("image_url") or ""),
                "detections": list((result or {}).get("detections") or []),
                "preprocess_ms": (result or {}).get("preprocess_ms"),
                "inference_ms": (result or {}).get("inference_ms"),
                "postprocess_ms": (result or {}).get("postprocess_ms"),
                "total_elapsed_ms": (result or {}).get("total_elapsed_ms"),
                "error": truth.get("error") or truth.get("error_message") or "",
            }
            if side in {"A", "B"}:
                item["models"][side] = public_result
            if review and review.get("review"):
                item["review"] = {
                    "review": str(review.get("review") or ""),
                    "note": str(review.get("note") or ""),
                    "updated_at": str(review.get("updated_at") or ""),
                }
            created = str(getattr(task, "created_at", "") or truth.get("created_at") or "")
            if created:
                created_values.append(created)
        items = [grouped[index] for index in sorted(grouped)]
        completed = sum(
            1 for item in items
            if set(item['expected_sides']) <= set(item['models']) and item["models"] and all(
                str(model.get("status") or "") in {"SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED_BY_ENVIRONMENT", "BLOCKED_BY_HARDWARE"}
                for model in item["models"].values()
            )
        )
        failed = sum(
            1 for item in items
            if any(str(model.get("status") or "") == "FAILED" for model in item["models"].values())
        )
        return {
            "batch_id": batch_id,
            "total": total or len(items),
            "created_items": len(items),
            "completed_items": completed,
            "failed_items": failed,
            "created_at": min(created_values) if created_values else "",
            "updated_at": max(created_values) if created_values else "",
            "items": items,
            "expected_sides": sorted({side for item in items for side in item['expected_sides']}),
        }

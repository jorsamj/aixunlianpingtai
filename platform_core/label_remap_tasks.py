"""Durable correction of one external-import class mapping."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .annotation_repository import AnnotationRepository
from .annotations import annotation_summary, atomic_write_json
from .labels import ensure_stable_label_ids, project_label_file_lock
from .material_repository import MaterialRepository
from .storage.import_candidates import ImportCandidateStore
from .storage.import_tasks import MANIFEST_REF
from .task_runtime import TaskKind, TaskStatus


RESULT_REF = "remap/result.json"
BATCH_SIZE = 250


class LabelRemapHandler:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)

    def _labels(self, project_id: str) -> dict[str, dict]:
        meta_path = self.data_dir / "projects" / project_id / "meta.json"
        with project_label_file_lock(meta_path):
            project = json.loads(meta_path.read_text(encoding="utf-8"))
            if ensure_stable_label_ids(project):
                atomic_write_json(meta_path, project)
            labels = project.get("labels") or []
            meta = project.get("label_meta") or []
            return {
                str(meta[index]["label_id"]): {
                    "label_id": str(meta[index]["label_id"]),
                    "code": str(code),
                    "display_name": str(meta[index].get("display_name") or code),
                    "class_id": index,
                    "status": str(meta[index].get("status") or "active"),
                }
                for index, code in enumerate(labels)
                if index < len(meta) and isinstance(meta[index], dict) and meta[index].get("label_id")
            }

    def run(self, context):
        request = context.artifacts.read_json(context.task.task_id, context.task.payload_ref, default=None)
        if not isinstance(request, dict):
            raise ValueError("label remap request is missing")
        import_id = str(request.get("import_id") or "")
        if not import_id or str(request.get("project_id") or "") != context.task.project_id:
            raise ValueError("label remap import/project identity is invalid")
        manifest = context.artifacts.artifact_path(import_id, MANIFEST_REF)
        if not manifest.is_file():
            raise FileNotFoundError("source import candidate manifest is missing")
        store = ImportCandidateStore(manifest, import_id=import_id)
        checkpoint = context.load_checkpoint()
        processed = max(0, int(checkpoint.get("processed_images") or 0))
        changed_boxes = max(0, int(checkpoint.get("changed_boxes") or 0))
        after = str(checkpoint.get("after_object_key") or "")
        class_id = int(request["external_class_id"])
        old_target = request.get("old_target_label_id")
        new_target = request.get("new_target_label_id")
        labels = self._labels(context.task.project_id)
        target = labels.get(str(new_target)) if new_target is not None else None
        if new_target is not None and (target is None or target["status"] != "active"):
            raise ValueError("target platform label is no longer active")
        annotations = AnnotationRepository(self.data_dir / "projects" / context.task.project_id)
        materials = MaterialRepository(self.data_dir / "projects" / context.task.project_id)
        external_label = str(request.get("external_label") or "")
        store.mark_label_remap(context.task.task_id, "RUNNING",
                               processed_images=processed, changed_boxes=changed_boxes)
        try:
            while True:
                if context.cancel_requested():
                    store.mark_label_remap(context.task.task_id, "CANCELLED",
                                           processed_images=processed, changed_boxes=changed_boxes)
                    return TaskStatus.CANCELLED, None
                batch = store.remap_target_batch(class_id, after_object_key=after, limit=BATCH_SIZE)
                if not batch:
                    break
                operations = [{
                    "image_id": row["image_id"], "width": row["width"], "height": row["height"],
                    "source_boxes": row["boxes"], "import_id": import_id,
                    "remap_task_id": context.task.task_id,
                    "external_class_id": class_id, "external_label": external_label,
                    "old_target_label_id": old_target, "target_label": target,
                } for row in batch]
                outcomes = annotations.remap_imported_class(operations)
                summary_at = datetime.now(timezone.utc).isoformat()
                materials.patch({
                    outcome["image_id"]: {
                        **annotation_summary(
                            outcome["boxes"], outcome["annotation_state"],
                            outcome.get("annotation_scope"),
                        ),
                        "annotation_summary_at": summary_at,
                        "label_remap_task_id": context.task.task_id,
                    }
                    for outcome in outcomes
                })
                processed += len(outcomes)
                changed_boxes += sum(int(outcome["changed_boxes"]) for outcome in outcomes)
                after = str(batch[-1]["object_key"])
                checkpoint = {"stage": "label_remap", "import_id": import_id,
                              "external_class_id": class_id, "processed_images": processed,
                              "changed_boxes": changed_boxes, "after_object_key": after}
                context.save_checkpoint(checkpoint)
                total = max(0, int((request.get("impact") or {}).get("affected_images") or 0))
                context.repository.heartbeat(
                    context.task.task_id, context.lease.lease_token,
                    progress=min(99.0, processed * 100.0 / max(1, total)), stage="label_remap",
                    current_item=f"正在修正导入标签：{processed} / {total}",
                )
            impact = request.get("impact") or {}
            result = {"task_id": context.task.task_id, "import_id": import_id,
                      "external_class_id": class_id, "external_label": external_label,
                      "old_target_label_id": old_target, "new_target_label_id": new_target,
                      "affected_images": int(impact.get("affected_images") or 0),
                      "affected_annotations": int(impact.get("affected_annotations") or 0),
                      "affected_boxes": int(impact.get("affected_boxes") or 0),
                      "processed_images": processed, "changed_boxes": changed_boxes,
                      "source_files_modified": False, "image_ids_changed": False}
            context.artifacts.atomic_write_json(context.task.task_id, RESULT_REF, result)
            store.mark_label_remap(context.task.task_id, "SUCCEEDED",
                                   processed_images=processed, changed_boxes=changed_boxes)
            return TaskStatus.SUCCEEDED, RESULT_REF
        except BaseException:
            store.mark_label_remap(context.task.task_id, "FAILED",
                                   processed_images=processed, changed_boxes=changed_boxes)
            raise

    def recover(self, context):
        return self.run(context)


def worker_registration(data_dir: Path):
    return {"handlers": {TaskKind.LABEL_REMAP: LabelRemapHandler(data_dir)},
            "capabilities": {"storage.label_remap"}}

"""Worker adapter for shared cleaning rules and durable per-image outcomes."""
from __future__ import annotations

import json

from .cleaning import ImageDecodeError, image_metrics, metric_issues
from .material_repository_batch import _transform_many
from .storage.errors import redact_storage_error
from .task_runtime.models import utc_now
from .task_runtime.task_logs import append_task_log


def _save_result(manifest, image_id, result, index, near_indexed=False):
    # Result and hash publication are atomic. On recovery a published result is
    # reused, preventing an image from matching itself or changing its group.
    with manifest.transaction():
        if result["status"] == "succeeded":
            index.remember(image_id, result["metrics"], near_indexed)
        manifest.database.execute(
            "INSERT INTO clean_results(image_id,result_json,flagged) VALUES (?,?,?) "
            "ON CONFLICT(image_id) DO UPDATE SET result_json=excluded.result_json,flagged=excluded.flagged",
            (image_id, json.dumps(result, ensure_ascii=False), int(bool(result["issues"]))),
        )


def clean_batch(context, manifest, materials, batch, options, manager, index, check_active):
    if len(batch) > 500:
        raise ValueError("cleaning batches are limited to 500 images")
    indexed = {row["id"]: row for row in materials.get_many([item["image_id"] for item in batch])}
    for item in batch:
        image_id = item["image_id"]
        check_active(context, "cleaning", image_id)
        saved = manifest.database.execute("SELECT result_json FROM clean_results WHERE image_id=?", (image_id,)).fetchone()
        result = json.loads(saved[0]) if saved else None
        # Inspection failures are retried only when the manifest row is replayed.
        if result is not None and result["status"] == "failed":
            result = None
        try:
            material = indexed.get(image_id)
            if material is None:
                raise FileNotFoundError("MATERIAL_NOT_FOUND")
            if result is None:
                local = manager.materialize(material)
                check_active(context, "cleaning", image_id)
                metrics = image_metrics(local.path, require_blur=options["blur_check"])
                issues, near_indexed = metric_issues(metrics, options, image_id, index)
                check_active(context, "cleaning", image_id)
                result = {"image_id": image_id, "filename": material.get("filename"),
                          "status": "succeeded", "metrics": metrics, "issues": issues,
                          "suggest_delete": bool(issues), "inspected_at": utc_now()}
                _save_result(manifest, image_id, result, index, near_indexed)
            check_active(context, "saving_clean_result", image_id)
            patch = {"clean_status": "needs_review" if result["issues"] else "passed",
                     "clean_result_task_id": context.task.task_id,
                     "clean_checked_at": result["inspected_at"], "clean_issues": result["issues"]}
            # Scanning makes no deletion/acceptance decision. Existing processing
            # and annotation states are preserved until the user reviews results.
            _transform_many(materials, [image_id], lambda row: {**row, **patch}, batch_size=1)
            if materials.get(image_id) is None:
                raise FileNotFoundError("MATERIAL_NOT_FOUND: deleted while cleaning")
            manifest.transition([image_id], "succeeded")
            if result["issues"]:
                append_task_log(context, "clean_flagged", f"image_id={image_id} issues=" + ",".join(issue["code"] for issue in result["issues"]))
        except InterruptedError:
            raise
        except Exception as error:
            # A lost lease raises here before any writes. Ordinary file access
            # errors belong to this image and must not stop the remaining batch.
            check_active(context, "saving_clean_error", image_id)
            public_error = redact_storage_error(error)
            if result is None:
                # A storage outage or missing blur engine is not a corrupt image.
                corrupt = isinstance(error, ImageDecodeError) and options["corrupt_check"]
                result = {"image_id": image_id, "filename": (indexed.get(image_id) or {}).get("filename"),
                          "status": "failed", "error": public_error, "metrics": {},
                          "issues": [{"code": "corrupt", "name": "图片损坏", "detail": public_error}] if corrupt else [],
                          "suggest_delete": False, "inspected_at": utc_now()}
                _save_result(manifest, image_id, result, index)
            check_active(context, "saving_clean_error", image_id)
            try:
                _transform_many(materials, [image_id], lambda row: {
                    **row, "clean_status": "failed", "clean_result_task_id": context.task.task_id,
                    "clean_checked_at": result["inspected_at"], "clean_issues": result["issues"],
                }, batch_size=1)
            except Exception as save_error:
                append_task_log(context, "clean_status_error", f"image_id={image_id} {redact_storage_error(save_error)}")
            manifest.transition([image_id], "failed", public_error)
            append_task_log(context, "clean_error", f"image_id={image_id} {public_error}")
        summary = manifest.summary(image_id)
        check_active(context, "cleaning", image_id,
                     progress=int(summary["processed"] * 100 / max(1, summary["total"])))
        context.save_checkpoint(summary)
    # A task spanning many sources must not accumulate every provider in memory.
    manager._providers.clear()

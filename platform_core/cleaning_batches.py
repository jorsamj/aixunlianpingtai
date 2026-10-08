"""Worker adapter for shared cleaning rules and durable per-image outcomes."""
from __future__ import annotations

import json

from .cleaning import ImageDecodeError, metric_issues
from .cleaning_analysis_runtime import CleaningAnalysisRuntime
from .material_repository_batch import _transform_many
from .storage.errors import redact_storage_error
from .task_runtime.models import utc_now
from .task_runtime.task_logs import append_task_log


def clean_result_source_sha256(result):
    """Content identity the worker actually inspected, not its stable image ID."""
    metrics = result.get("metrics") or {}
    return str(
        result.get("source_content_sha256") or metrics.get("sha256") or ""
    ).strip().lower()


def invalidate_clean_evidence(manifest, image_ids, *, reset_succeeded=False):
    """Retire stale result and LSH evidence in the same selection transaction."""
    if not image_ids:
        return
    with manifest.transaction():
        placeholders = ",".join("?" for _ in image_ids)
        flagged = manifest.database.execute(
            f"SELECT COALESCE(SUM(flagged),0) FROM clean_results WHERE image_id IN ({placeholders})",
            tuple(image_ids),
        ).fetchone()[0]
        manifest.database.executemany(
            "DELETE FROM clean_bands WHERE image_id=?", ((image_id,) for image_id in image_ids),
        )
        manifest.database.executemany(
            "DELETE FROM clean_hashes WHERE image_id=?", ((image_id,) for image_id in image_ids),
        )
        manifest.database.executemany(
            "DELETE FROM clean_results WHERE image_id=?", ((image_id,) for image_id in image_ids),
        )
        manifest.database.execute(
            "UPDATE meta SET value=CAST(value AS INTEGER)-? WHERE key='clean_flagged'",
            (int(flagged or 0),),
        )
        if reset_succeeded:
            manifest.database.executemany(
                "UPDATE selection SET state='pending',error=NULL "
                "WHERE image_id=? AND state='succeeded'",
                ((image_id,) for image_id in image_ids),
            )


def reset_stale_clean_successes(context, manifest, materials, check_active):
    """Retry resumes unchanged successes, but never reuses another content generation."""
    cursor = ""
    while True:
        check_active(context, "clean_retry_identity")
        rows = manifest.database.execute(
            "SELECT s.image_id,r.result_json FROM selection s "
            "LEFT JOIN clean_results r ON r.image_id=s.image_id "
            "WHERE s.state='succeeded' AND s.image_id>? "
            "ORDER BY s.image_id LIMIT 500", (cursor,),
        ).fetchall()
        if not rows:
            return
        cursor = str(rows[-1][0])
        current = {
            str(item["id"]): str(item.get("content_sha256") or "").strip().lower()
            for item in materials.get_many([str(row[0]) for row in rows])
        }
        stale = []
        for image_id, raw_result in rows:
            try:
                result = json.loads(raw_result) if raw_result else {}
                source = clean_result_source_sha256(result)
            except (TypeError, ValueError):
                source = ""
            # Missing content identity is not proof that an old result still
            # belongs to the current image, including legacy corrupt findings.
            if not source or source != current.get(str(image_id), ""):
                stale.append(str(image_id))
        if stale:
            invalidate_clean_evidence(manifest, stale, reset_succeeded=True)
            append_task_log(
                context, "clean_retry_stale_evidence",
                f"reset={len(stale)} cursor={cursor}",
            )


def _save_result(manifest, image_id, result, index, near_indexed=False):
    # Result and hash publication are atomic. On recovery a published result is
    # reused, preventing an image from matching itself or changing its group.
    with manifest.transaction():
        metrics = result.get("metrics") or {}
        if result["status"] == "succeeded" and metrics.get("sha256") is not None and metrics.get("dhash") is not None:
            index.remember(image_id, metrics, near_indexed)
        manifest.database.execute(
            "INSERT INTO clean_results(image_id,result_json,flagged) VALUES (?,?,?) "
            "ON CONFLICT(image_id) DO UPDATE SET result_json=excluded.result_json,flagged=excluded.flagged",
            (image_id, json.dumps(result, ensure_ascii=False), int(bool(result["issues"]))),
        )


def _publish_item_stage(context, manifest, check_active, stage, image_id):
    """Publish truthful current-item/stage without inventing progress."""
    summary = manifest.summary(image_id)
    progress = int(summary["processed"] * 100 / max(1, summary["total"]))
    context.save_checkpoint(summary)
    check_active(context, stage, image_id, progress=progress)
    return summary


def clean_batch(context, manifest, materials, batch, options, manager, index, check_active):
    if len(batch) > 500:
        raise ValueError("cleaning batches are limited to 500 images")
    indexed = {row["id"]: row for row in materials.get_many([item["image_id"] for item in batch])}
    analysis = CleaningAnalysisRuntime()
    try:
        for item in batch:
            image_id = item["image_id"]
            _publish_item_stage(context, manifest, check_active, "materializing", image_id)
            saved = manifest.database.execute("SELECT result_json FROM clean_results WHERE image_id=?", (image_id,)).fetchone()
            result = json.loads(saved[0]) if saved else None
            # A result may be saved before a worker crash or lease loss, while
            # the object referenced by this image ID changes during recovery.
            material = indexed.get(image_id)
            expected_source = str(
                (material or {}).get("content_sha256") or ""
            ).strip().lower()
            if result is not None and result.get("status") == "succeeded":
                source = clean_result_source_sha256(result)
                if not source or source != expected_source:
                    invalidate_clean_evidence(manifest, [image_id])
                    result = None
            # Inspection failures are retried only when the manifest row is replayed.
            if result is not None and result["status"] == "failed":
                result = None
            local = None
            try:
                material = indexed.get(image_id)
                if material is None:
                    raise FileNotFoundError("MATERIAL_NOT_FOUND")
                if result is None:
                    local = manager.materialize(material)
                    _publish_item_stage(context, manifest, check_active, "analyzing", image_id)
                    # materialize() already verified the actual content hash. The
                    # decoder/visual metrics run in one reusable child process with
                    # a per-image hard deadline so a pathological image cannot pin
                    # the Materials Worker and freeze the whole batch indefinitely.
                    metrics = analysis.analyze(
                        local.path,
                        require_blur=options["blur_check"],
                        content_sha256=local.content_sha256,
                        check_active=lambda: check_active(context, "analyzing", image_id),
                    )
                    _publish_item_stage(context, manifest, check_active, "evaluating", image_id)
                    issues, near_indexed = metric_issues(metrics, options, image_id, index)
                    check_active(context, "saving_clean_result", image_id)
                    result = {"image_id": image_id, "filename": material.get("filename"),
                              "status": "succeeded", "source_content_sha256": local.content_sha256,
                              "metrics": metrics, "issues": issues,
                              "suggest_delete": bool(issues), "inspected_at": utc_now()}
                    _save_result(manifest, image_id, result, index, near_indexed)
                    if metrics.get("analysis_downsampled"):
                        append_task_log(
                            context, "clean_analysis_bounded",
                            f"image_id={image_id} source={metrics.get('width')}x{metrics.get('height')}",
                        )
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
                # A lost lease raises here before any writes. A decoder failure is a
                # valid cleaning finding when corrupt_check is enabled; provider/I/O,
                # analysis timeout and runtime failures remain retryable item failures.
                check_active(context, "saving_clean_error", image_id)
                public_error = redact_storage_error(error)
                corrupt_finding = isinstance(error, ImageDecodeError) and options["corrupt_check"]
                if corrupt_finding:
                    result = {"image_id": image_id, "filename": (indexed.get(image_id) or {}).get("filename"),
                              "status": "succeeded",
                              "source_content_sha256": str(
                                  getattr(local, "content_sha256", "") or ""
                              ).lower(),
                              "metrics": {},
                              "issues": [{"code": "corrupt", "name": "图片损坏", "detail": public_error}],
                              "suggest_delete": True, "inspected_at": utc_now()}
                    _save_result(manifest, image_id, result, index)
                    check_active(context, "saving_clean_result", image_id)
                    _transform_many(materials, [image_id], lambda row: {
                        **row, "clean_status": "needs_review", "clean_result_task_id": context.task.task_id,
                        "clean_checked_at": result["inspected_at"], "clean_issues": result["issues"],
                    }, batch_size=1)
                    manifest.transition([image_id], "succeeded")
                    append_task_log(context, "clean_flagged", f"image_id={image_id} issues=corrupt")
                else:
                    if result is None:
                        result = {"image_id": image_id, "filename": (indexed.get(image_id) or {}).get("filename"),
                                  "status": "failed", "error": public_error, "metrics": {},
                                  "issues": [], "suggest_delete": False, "inspected_at": utc_now()}
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
    finally:
        analysis.close()
        # A task spanning many sources must not accumulate every provider in memory.
        manager._providers.clear()

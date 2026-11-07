from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from . import auto_label as auto_label_core
from .annotation_candidates import CandidateStore
from .task_runtime import TaskKind, TaskStatus


@dataclass(frozen=True)
class WorkerOutcome:
    status: TaskStatus
    result_ref: str
    error: str | None = None
    generation_partial: bool = False


def load_task_images(project_id: str, image_ids: Iterable[str]) -> list[dict[str, Any]]:
    # Imported only while executing a claimed task. Worker registration and
    # health checks stay independent from the web application module.
    from app import material_store, storage_manager

    ordered_ids = list(dict.fromkeys(str(value) for value in image_ids if str(value)))
    if not ordered_ids:
        return []
    materials = material_store(project_id)
    manager = storage_manager(project_id)
    by_id: dict[str, dict[str, Any]] = {}
    # Keep SQLite variable counts bounded and fetch only the immutable task
    # selection. Never scan the whole project just to resolve a small AI task.
    for offset in range(0, len(ordered_ids), 500):
        for image in materials.get_many(ordered_ids[offset:offset + 500]):
            image_id = str(image.get("id") or "")
            if image_id:
                by_id[image_id] = image
    missing = [image_id for image_id in ordered_ids if image_id not in by_id]
    if missing:
        raise FileNotFoundError("annotation images no longer exist: " + ", ".join(sorted(missing)))
    rows = []
    for image_id in ordered_ids:
        row = dict(by_id[image_id])
        local = manager.materialize(row)
        row["path"] = str(local.path)
        # Bind evidence to the verified bytes used by the inference worker,
        # not merely to the stable Material image ID.
        row["source_content_sha256"] = str(
            getattr(local, "content_sha256", "") or row.get("content_sha256") or ""
        ).strip().lower()
        rows.append(row)
    return rows


def prepare_annotation_image(path):
    """Read actual raster dimensions; submit EXIF-corrected pixels without disk writes."""
    import io
    from PIL import Image, ImageOps
    content = Path(path).read_bytes()
    with Image.open(io.BytesIO(content)) as source:
        width, height = source.size
        orientation = int(source.getexif().get(274, 1))
        if orientation not in range(1, 9):
            raise ValueError("DISPLAY_TRANSFORM_ERROR: invalid EXIF orientation")
        canonical = ImageOps.exif_transpose(source)
        submitted_width, submitted_height = canonical.size
        if orientation != 1:
            buffer = io.BytesIO()
            canonical.convert("RGB").save(buffer, format="PNG")
            content = buffer.getvalue()
    return content, {"original_width": submitted_width, "original_height": submitted_height,
        "encoded_width": width, "encoded_height": height, "exif_orientation": orientation,
        "submitted_width": submitted_width, "submitted_height": submitted_height,
        "inference_width": submitted_width, "inference_height": submitted_height,
        "submitted_sha256": hashlib.sha256(content).hexdigest(),
        "model_internal_geometry": "unknown_provider_managed",
        "mapping": "exif_transposed_original_pixels" if orientation != 1 else "identity_original_bytes"}


def annotate_one(request: dict[str, Any], image: dict[str, Any]) -> dict[str, Any]:
    from .annotation_runtime import build_annotation_prompt

    provider = request["_provider"]
    config = request["_provider_config"]
    path = Path(str(image.get("path") or ""))
    if not path.is_file():
        raise FileNotFoundError(f"annotation image file does not exist: {image.get('filename') or image.get('id')}")
    image_bytes, geometry = prepare_annotation_image(path)
    width, height = geometry["submitted_width"], geometry["submitted_height"]
    geometry["stored_width"] = image.get("width")
    geometry["stored_height"] = image.get("height")
    geometry["stored_size_matches"] = (width, height) == (image.get("width"), image.get("height"))
    # The decoded image is authoritative; never infer pixels from DPI or stale metadata.
    image["width"], image["height"] = width, height
    contract = auto_label_core.coordinate_contract(config, legacy=True)
    diagnostics = {
        "contract": contract, "created_at_epoch": time.time(),
        "status": "UNVERIFIED_CONTRACT" if (config.get("coordinate_validation") or {}).get("status") not in {"verified", "sample_validated"} else "configured",
        "geometry": geometry, "model_config_revision": request.get("model_config_revision", ""),
        "prompt_version": request.get("effective_prompt_revision", ""),
    }
    prompt = build_annotation_prompt(
        config,
        request["label_catalog"],
        width=int(image["width"]),
        height=int(image["height"]),
        business_instruction=str(request.get("business_instruction") or ""),
        template=str(request.get("prompt_template") or ""),
    )
    dedicated = str(config.get("provider_adapter") or config.get("provider_type") or "") == "wevisone_vl"
    provider_args = {"image_bytes": image_bytes, "prompt": prompt,
                     "output_schema": auto_label_core.CANDIDATE_OUTPUT_SCHEMA}
    if dedicated:
        provider_args["labels"] = list(request["label_ids"])
        provider_args["label_aliases"] = request["label_aliases"]
    response = provider.annotate(**provider_args)
    mapping = None
    if contract.get("coordinate_image_space") == "processed_image":
        mapping = response.get("geometry")
        if not isinstance(mapping, dict):
            raise ValueError("UNVERIFIED_CONTRACT: provider preprocessing geometry is unknown")
        diagnostics["geometry"]["provider_preprocessing"] = mapping
    text = str(response.get("text") or "")
    diagnostics.update({"model": str(config.get("model_name") or ""),
                        "provider": str(config.get("provider_adapter") or config.get("provider_type") or ""),
                        "latency_ms": int(response.get("latency_ms") or 0)})
    diagnostics.update({key: response[key] for key in (
        "request_id", "backend_instance_id", "actual_model", "status_code",
    ) if response.get(key) not in (None, "")})
    try:
        parsed = auto_label_core.parse_candidate_response(
            text,
            width=int(image["width"]),
            height=int(image["height"]),
            label_ids=request["label_ids"],
            label_aliases=request["label_aliases"],
            coordinate_space=contract["coordinate_space"],
            coordinate_order=contract["coordinate_order"],
            diagnostics=diagnostics,
            coordinate_origin=contract.get("coordinate_origin", "top_left"),
            geometry=mapping,
            allow_missing_confidence=dedicated,
        )
    except ValueError as error:
        diagnostics["status"] = "COORDINATE_CONVERSION_ERROR" if "COORDINATE_CONVERSION_ERROR:" in str(error) else "STRUCTURED_OUTPUT_ERROR"
        diagnostics["first_failure_only"] = True
        diagnostics["counts"] = {"raw": diagnostics.get("raw_candidate_count", 0), "invalid": None,
                                 "threshold_filtered": 0, "nms_filtered": 0, "final": 0}
        error.diagnostics = diagnostics
        raise
    threshold = float(request.get("threshold") if request.get("threshold") is not None else 0.45)
    # Dedicated providers without a calibrated score are reviewable candidates,
    # not synthetic 0% predictions. Human confirmation remains mandatory.
    eligible = [b for b in parsed if b.get("confidence") is None or float(b["confidence"]) >= threshold]
    boxes = auto_label_core.nms_candidates(eligible, iou_threshold=0.5)
    retained = len(eligible)
    diagnostics["confidence_unavailable_count"] = sum(box.get("confidence") is None for box in boxes)
    diagnostics["converted_boxes"] = parsed[:100]
    diagnostics["final_boxes"] = [dict(box) for box in boxes[:100]]
    diagnostics["counts"] = {"raw": len(parsed), "invalid": 0, "threshold_filtered": len(parsed) - retained,
                             "nms_filtered": retained - len(boxes), "final": len(boxes)}
    for box in boxes:
        box.update({
            "id": str(box.get("id") or uuid.uuid4().hex[:12]),
            "source": "ai_candidate",
            "model_config_id": config.get("id"),
            "prompt_template_id": request.get("prompt_template_id") or "",
            "prompt_template_version_id": request.get("prompt_template_version_id") or "",
        })
    return {
        "boxes": boxes,
        "diagnostics": diagnostics,
        "raw_response_hash": auto_label_core.raw_response_hash(text),
        "request_id": str(response.get("request_id") or ""),
        "latency_ms": int(response.get("latency_ms") or 0),
        "provider": str(response.get("provider") or ""),
        "model": str(response.get("model") or config.get("model_name") or ""),
    }


def _assert_generation_commit(context) -> None:
    # CandidateStore owns a separate SQLite file. Re-check both execution
    # generation and cancellation immediately before that SQLite transaction
    # commits so a stale/late Worker cannot publish model output.
    if context.cancel_requested():
        raise InterruptedError("AI annotation task cancelled before candidate commit")


def sync_annotation_statistics(repository, task, store: CandidateStore) -> dict[str, int]:
    """Refresh a task-list projection from the authoritative per-task SQLite store."""
    counts = store.statistics()
    projection = getattr(repository, "set_annotation_statistics", None)
    if task.kind is TaskKind.AI_ANNOTATION and callable(projection):
        projection(task.task_id, counts)
    return counts


def run_ai_annotation(
    context,
    *,
    annotate: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] = annotate_one,
    data_dir: Path | None = None,
) -> WorkerOutcome:
    request = context.artifacts.read_json(context.task.task_id, context.task.payload_ref, default={})
    if not isinstance(request, dict):
        raise ValueError("AI annotation request is invalid")
    runtime_request = dict(request)
    mining_mode = runtime_request.get("mode") == "hard_sample_yolo"
    if mining_mode:
        from app import project_dir, material_store
        from .hard_sample_mining import assert_not_frozen_test, HardSampleSafetyError
        image_ids = [str(value) for value in runtime_request.get("image_ids") or []]
        frozen_hashes = {
            str(k): str(v).lower()
            for k, v in (runtime_request.get("source_hashes") or {}).items()
        }
        if not image_ids or set(image_ids) != set(frozen_hashes):
            raise HardSampleSafetyError("HARD_SAMPLE_SOURCE_IDENTITY_MISSING")
        material_rows = []
        for offset in range(0, len(image_ids), 500):
            material_rows.extend(material_store(context.task.project_id).get_many(image_ids[offset:offset + 500]))
        current = {str(row.get("id") or ""): str(row.get("content_sha256") or "").lower()
                   for row in material_rows}
        if current != frozen_hashes:
            raise HardSampleSafetyError("HARD_SAMPLE_SOURCE_CHANGED")
        assert_not_frozen_test(project_dir(context.task.project_id), image_ids, current)
        runtime_request["_project_dir"] = str(project_dir(context.task.project_id))
        from .hard_sample_mining import sha256_file
        snapshot_id = str(runtime_request.get("mining_snapshot_id") or "")
        expected = str(runtime_request.get("mining_snapshot_sha256") or "").lower()
        if len(snapshot_id) != 64 or len(expected) != 64:
            raise HardSampleSafetyError("HARD_SAMPLE_LABEL_SNAPSHOT_MISSING")
        path = project_dir(context.task.project_id) / "snapshots" / f"{snapshot_id}.json"
        if not path.is_file() or sha256_file(path) != expected:
            raise HardSampleSafetyError("HARD_SAMPLE_LABEL_SNAPSHOT_CHANGED")
    elif annotate is annotate_one:
        runtime_request = _prepare_runtime_request(
            context.task.project_id,
            runtime_request,
            data_dir=data_dir,
        )
    images = load_task_images(context.task.project_id, runtime_request.get("image_ids") or [])
    if request.get("review_scope_policy") == "per_image_required":
        expected_hashes = request.get("per_image_source_hashes")
        expected_scopes = request.get("per_image_missing_review_scopes")
        expected_versions = request.get("per_image_annotation_versions")
        if (not isinstance(expected_hashes, dict) or not isinstance(expected_scopes, dict)
                or not isinstance(expected_versions, dict)
                or set(expected_hashes) != set(expected_scopes) or set(expected_hashes) != set(expected_versions)
                or set(expected_hashes) != {str(image["id"]) for image in images}):
            raise ValueError("AI_SUPPLEMENT_FROZEN_SELECTION_MISSING")
        for image in images:
            image_id = str(image["id"])
            if str(image.get("source_content_sha256") or "").strip().lower() != expected_hashes[image_id]:
                raise ValueError("AI_SUPPLEMENT_MATERIAL_CHANGED: refuse inference on changed source")
    preview_count = max(0, int(runtime_request.get("preview_count") or 0))
    if preview_count:
        images = images[:preview_count]
    if not images:
        raise ValueError("AI annotation task has no images")

    store = CandidateStore(context.artifacts, task_id=context.task.task_id, page_size=50)
    manifest = context.artifacts.read_json(
        context.task.task_id,
        "candidates/manifest.json",
        default=None,
    )
    labels = [str(value) for value in runtime_request.get("labels") or []]
    if not isinstance(manifest, dict):
        context.assert_current_execution()
        store.initialize(labels=labels, total_images=len(images))
    else:
        if "total_images" in manifest and int(manifest.get("total_images") or 0) != len(images):
            raise ValueError("annotation candidate manifest does not match immutable task image count")
        if "labels" in manifest and [str(value) for value in manifest.get("labels") or []] != labels:
            raise ValueError("annotation candidate manifest does not match immutable task labels")

    if context.cancel_requested():
        return WorkerOutcome(TaskStatus.CANCELLED, "candidates/manifest.json")
    durable = store.generation_state(
        (str(image["id"]) for image in images),
        commit_guard=lambda: _assert_generation_commit(context),
    )
    checkpoint = dict(context.load_checkpoint() or {})
    start = int(durable["next_index"])
    succeeded = int(durable["succeeded"])
    failed = int(durable["failed"])
    checkpoint_start = max(0, int(checkpoint.get("next_index") or 0))
    if (
        checkpoint_start != start
        or int(checkpoint.get("succeeded") or 0) != succeeded
        or int(checkpoint.get("failed") or 0) != failed
    ):
        context.save_checkpoint({
            "next_index": start,
            "succeeded": succeeded,
            "failed": failed,
            "source": "candidate_store",
        })
    if start:
        context.heartbeat(
            progress=int(start / max(1, len(images)) * 70),
            stage="AI_ANNOTATION",
            current_item=str(images[start - 1].get("id") or ""),
        )

    retry_selection = context.artifacts.read_json(context.task.task_id, 'generation/retry-selection.json', default={})
    retry_ids = retry_selection.get('image_ids') if isinstance(retry_selection,dict) else None
    retry_ids = set(map(str,retry_ids)) if isinstance(retry_ids,list) else None
    image_by_id = {str(image["id"]): image for image in images}
    if context.task.attempt > 1:
        # The original task is the candidate owner across retries and lease
        # recovery. A changed material is not allowed to reuse saved geometry.
        for saved in store.iter_items():
            previous_hash = str(saved.get("source_content_sha256") or "").lower()
            current = image_by_id[str(saved["image_id"])]
            current_hash = str(current.get("source_content_sha256") or current.get("content_sha256") or "").lower()
            if previous_hash and current_hash and previous_hash != current_hash:
                raise ValueError("AI_ANNOTATION_SOURCE_CHANGED: 原图片内容已改变，不能沿用旧候选结果")

    from .annotation_inference import call_with_policy
    from .inference_policy import resolve_inference_policy
    from .task_runtime import ExecutionFencedError
    snapshot = runtime_request.get("model_config_snapshot") or {}
    frozen_policy = snapshot.get("inference_execution_policy") if isinstance(snapshot, dict) else None
    if isinstance(frozen_policy, dict) and frozen_policy.get("version") == 1:
        policy = dict(frozen_policy)
        if snapshot.get("secret_ref") and not snapshot.get("inference_account_identity"):
            # A headless preparation may freeze a reference before its key is
            # available. Once executable, share its real account's base quota
            # without upgrading this historical/unknown-capacity task.
            runtime_identity = runtime_request.get("_provider_config") or snapshot
            policy.update(concurrency=1, max_attempts=1,
                          domain=resolve_inference_policy(runtime_identity)["domain"])
        if policy.get("evidence_expires_at") and float(policy["evidence_expires_at"]) <= time.time():
            policy.update(concurrency=1, evidence_status="expired")
    else:
        policy = resolve_inference_policy(runtime_request.get("_provider_config") or snapshot or {})
        policy.update(concurrency=1, max_attempts=1, evidence_status="legacy")
    if mining_mode or not callable(getattr(context.repository, "acquire_inference_permit", None)):
        policy.update(concurrency=1, max_attempts=1)
    concurrency = max(1, min(8, int(policy.get("concurrency") or 1)))
    halt = threading.Event()
    generation_started = time.monotonic()
    latencies, execution_retries, gateway_errors = [], 0, 0

    def produce_candidate(image, previous=None):
        image_started = time.monotonic()
        next_attempt=int((previous or {}).get("attempt_count") or 0)+1
        try:
            if mining_mode and annotate is annotate_one:
                from .hard_sample_mining import infer_with_frozen_yolo
                generated = infer_with_frozen_yolo(runtime_request, image)
            else:
                generated = call_with_policy(context, runtime_request, image, annotate, policy, stop=halt)
            boxes = list(generated.get("boxes") or [])
            item = {
                "image_id": str(image["id"]), "filename": image.get("filename"),
                "url": image.get("url"), "width": image.get("width"), "height": image.get("height"),
                "source_content_sha256": str(image.get("source_content_sha256") or image.get("content_sha256") or "").strip().lower(),
                "status": "success" if boxes else "empty", "boxes": boxes, "attempt_count":next_attempt,
                **{key: generated.get(key) for key in (
                    "raw_response_hash", "request_id", "latency_ms", "provider", "model", "diagnostics",
                    "hard_sample_signals", "hard_sample_priority", "ground_truth_compared",
                    "gt_comparison", "root_cause_confirmed",
                ) if generated.get(key) is not None and generated.get(key) != ""},
            }
            failure_code = ""
        except (InterruptedError, ExecutionFencedError):
            raise
        except PermissionError as error:
            # Capacity acquisition checks the same persisted execution fence.
            raise ExecutionFencedError("inference dispatch is fenced") from error
        except Exception as error:
            item = {
                "image_id": str(image.get("id") or ""), "filename": image.get("filename"),
                "url": image.get("url"), "width": image.get("width"), "height": image.get("height"),
                "source_content_sha256": str(image.get("source_content_sha256") or image.get("content_sha256") or "").strip().lower(),
                "status": "failed", "boxes": [], "error": _public_error(error),
                **_failure_evidence(error, attempt=next_attempt),
            }
            if isinstance(getattr(error, "diagnostics", None), dict):
                item["diagnostics"] = error.diagnostics
            failure_code = str(getattr(error, "code", "") or type(error).__name__)
        diagnostics = item.setdefault("diagnostics", {})
        execution = diagnostics.setdefault("execution", {})
        execution.setdefault("elapsed_ms", round((time.monotonic() - image_started) * 1000))
        execution.setdefault("attempts", 1)
        if request.get("review_scope_policy") == "per_image_required":
            item["review_scope_policy"] = "per_image_required"
            item["missing_review_scope"] = list(expected_scopes[str(image["id"])])
        return item, failure_code

    service_faults = {
        "MODEL_SERVICE_UNREACHABLE", "MODEL_REQUEST_TIMEOUT", "MODEL_NOT_LOADED",
        "MODEL_AUTHENTICATION_FAILED", "MODEL_RESOURCE_NOT_FOUND", "MODEL_SERVICE_ERROR",
        "MODEL_OUTPUT_PARSE_ERROR", "MODEL_OUTPUT_FAILED", "MODEL_PROTOCOL_REQUIRED",
        "MODEL_RATE_LIMITED", "MODEL_QUOTA_EXCEEDED", "MODEL_PERMISSION_DENIED",
        "MODEL_REQUEST_CONTRACT_INVALID", "ConnectionError", "TimeoutError",
    }
    hard_faults = {"MODEL_NOT_LOADED", "MODEL_AUTHENTICATION_FAILED", "MODEL_RESOURCE_NOT_FOUND", "MODEL_PROTOCOL_REQUIRED",
                   "MODEL_PERMISSION_DENIED", "MODEL_QUOTA_EXCEEDED", "MODEL_REQUEST_CONTRACT_INVALID"}
    consecutive_faults = 0
    stop_reason = ""
    # Candidate SQLite owns recovery truth even when responses complete out of order.
    # Only this coordinator writes candidates/checkpoints; pool threads do I/O only.
    retry_work = []
    if context.task.attempt > 1:
        retry_work = ((image_by_id[str(row["image_id"])], row) for row in store.iter_items()
                      if row.get("status") == "failed" and
                      (retry_ids is None or str(row["image_id"]) in retry_ids))
    present = durable["done_ids"] | durable["failed_ids"]
    new_work = ((image, None) for image in images if str(image["id"]) not in present
                and (retry_ids is None or str(image["id"]) in retry_ids))
    from itertools import chain
    work = iter(chain(retry_work, new_work))
    pending = {}
    pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="annotation-inference")
    persisted = set(present)
    completed = len(persisted)
    checkpoint_index = start
    try:
        with store.write_session(commit_guard=lambda: _assert_generation_commit(context)) as append_candidate:
            while True:
                if context.cancel_requested():
                    halt.set()
                    sync_annotation_statistics(context.repository, context.task, store)
                    return WorkerOutcome(TaskStatus.CANCELLED, "candidates/manifest.json")
                while not stop_reason and len(pending) < concurrency:
                    try:
                        image, previous = next(work)
                    except StopIteration:
                        break
                    context.assert_current_execution()
                    pending[pool.submit(produce_candidate, image, previous)] = (image, previous)
                if not pending:
                    break
                done, _ = wait(pending, timeout=.1, return_when=FIRST_COMPLETED)
                for future in done:
                    image, previous = pending.pop(future)
                    try:
                        item, code = future.result()
                    except InterruptedError:
                        if context.cancel_requested():
                            return WorkerOutcome(TaskStatus.CANCELLED, "candidates/manifest.json")
                        if stop_reason:
                            continue
                        raise
                    if context.cancel_requested():
                        halt.set()
                        return WorkerOutcome(TaskStatus.CANCELLED, "candidates/manifest.json")
                    append_candidate([item])
                    was_failed = previous is not None
                    if item["status"] == "failed":
                        failed += int(not was_failed)
                    else:
                        succeeded += 1
                        failed -= int(was_failed)
                    persisted.add(str(image["id"]))
                    completed = len(persisted)
                    while checkpoint_index < len(images) and str(images[checkpoint_index]["id"]) in persisted:
                        checkpoint_index += 1
                    context.save_checkpoint({"next_index": checkpoint_index, "succeeded": succeeded,
                                             "failed": failed, "source": "candidate_store"})
                    context.heartbeat(progress=int(completed / max(1, len(images)) * 70),
                                      stage="AI_ANNOTATION", current_item=str(image["id"]))
                    execution = (item.get("diagnostics") or {}).get("execution") or {}
                    if execution.get("elapsed_ms") is not None:
                        latencies.append(float(execution["elapsed_ms"]))
                    execution_retries += max(0, int(execution.get("attempts") or 1) - 1)
                    gateway_errors += int(item.get("http_status") in {500,502,503,504})
                    if completed % 100 == 0:
                        sync_annotation_statistics(context.repository, context.task, store)
                    consecutive_faults = consecutive_faults + 1 if code in service_faults else 0
                    if code in hard_faults or consecutive_faults >= 3:
                        stop_reason = code or "MODEL_SERVICE_ERROR"
                        # Stop new dispatch/retries; already running valid responses
                        # are still drained through the same fenced writer.
                        halt.set()
    finally:
        halt.set()
        pool.shutdown(wait=False, cancel_futures=True)
        try:
            if context.cancel_requested():
                cancelled_summary = sync_annotation_statistics(context.repository, context.task, store)
                context.artifacts.atomic_write_json(context.task.task_id, "generation.json", {
                    "summary": cancelled_summary, "generation_partial": True,
                    "stopped_reason": "CANCEL_REQUESTED",
                    "remaining": max(0, len(images) - cancelled_summary["total"]),
                    "execution": {"concurrency": concurrency,
                        "wall_seconds": round(time.monotonic() - generation_started, 3),
                        "processed_this_execution": len(latencies), "in_flight_at_stop": len(pending),
                        "retries": execution_retries, "gateway_errors": gateway_errors,
                        "capacity_evidence": policy.get("evidence_status", "unknown")},
                })
        except ExecutionFencedError:
            # Lease recovery owns all subsequent publication, including metrics.
            pass


    summary = sync_annotation_statistics(context.repository, context.task, store)
    elapsed = max(.001, time.monotonic() - generation_started)
    ordered_latencies = sorted(latencies)
    def percentile(fraction):
        return ordered_latencies[min(len(ordered_latencies)-1, int((len(ordered_latencies)-1)*fraction))] if ordered_latencies else None
    context.artifacts.atomic_write_json(context.task.task_id, "generation.json", {
        "summary": summary,
        "generation_partial": bool(failed),
        "stopped_reason": stop_reason,
        "remaining": max(0, len(images) - summary["total"]),
        "execution": {"concurrency": concurrency, "capacity_evidence": policy.get("evidence_status", "unknown"),
            "wall_seconds": round(elapsed, 3), "processed_this_execution": len(latencies),
            "mean_ms": round(sum(latencies)/len(latencies), 2) if latencies else None,
            "p50_ms": percentile(.5), "p95_ms": percentile(.95),
            "images_per_second": round(len(latencies)/elapsed, 3),
            "retries": execution_retries, "gateway_errors": gateway_errors,
            "persisted_succeeded": summary.get("success", 0) + summary.get("empty", 0),
            "persisted_failed": summary.get("failed", 0), "persisted_empty": summary.get("empty", 0)},
    })
    if stop_reason:
        return WorkerOutcome(TaskStatus.AWAITING_CONFIRMATION if succeeded else TaskStatus.BLOCKED_BY_ENVIRONMENT,
                             "candidates/manifest.json", stop_reason, True)
    if failed and not succeeded:
        return WorkerOutcome(TaskStatus.FAILED, "candidates/manifest.json", "all images failed", True)
    return WorkerOutcome(
        TaskStatus.AWAITING_CONFIRMATION,
        "candidates/manifest.json",
        generation_partial=bool(failed),
    )


def _prepare_runtime_request(
    project_id: str,
    request: dict[str, Any],
    *,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    from .annotation_runtime import prepare_request

    if data_dir is None:
        # Focused tests and legacy in-process callers may not pass the Worker
        # root explicitly. Production worker_registration always does.
        from app import DATA_DIR as app_data_dir
        data_dir = Path(app_data_dir)
    return prepare_request(data_dir, project_id, request, runtime=True)


def _public_error(error: Exception) -> str:
    text = str(error).replace("\r", " ").replace("\n", " ").strip()
    patterns = (
        r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+",
        r"(?i)((?:api[_-]?key|access[_-]?token|secret)\s*[=:]\s*)[^\s,;]+",
        r"\bsk-[A-Za-z0-9_-]{12,}\b",
    )
    for pattern in patterns:
        text = re.sub(pattern, lambda match: match.group(1) + "[REDACTED]" if match.lastindex else "[REDACTED]", text)
    return text[:1000] or type(error).__name__


def _failure_evidence(error: Exception, *, attempt: int) -> dict[str, Any]:
    """Bounded, sanitized per-image recovery evidence, never a raw response."""
    code = str(getattr(error, "code", "") or type(error).__name__)[:100]
    stage = getattr(error, "stage", "")
    if not stage:
        stage = ("coordinate_validation" if "COORDINATE" in code else
                 "response_parse" if "OUTPUT" in code or "PARSE" in code else
                 "source_read" if isinstance(error, (FileNotFoundError, OSError)) else "model_request")
    def safe(value):
        return _public_error(RuntimeError(str(value))) if value else ""
    status = getattr(error, "status_code", 0)
    return {"error_code": code, "error_stage": safe(stage),
            "http_status": int(status) if isinstance(status, int) and 100 <= status <= 599 else None,
            "request_id": safe(getattr(error, "request_id", ""))[:128],
            "retry_suggestion": safe(getattr(error, "solution", "检查图片来源和模型配置后重试失败图片。")),
            "attempt_count": max(1, int(attempt))}


def read_formal_annotation(project_id: str, image_id: str) -> dict[str, Any]:
    from app import read_annotation

    return read_annotation(project_id, image_id)


def read_formal_annotations(project_id: str, image_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    from app import read_annotations_many

    return read_annotations_many(project_id, image_ids)


def write_formal_annotation(
    project_id: str, image_id: str, boxes: list[dict[str, Any]],
    *, annotation_origin: str | None = None,
) -> None:
    from app import write_annotation

    write_annotation(
        project_id, image_id, boxes, annotation_origin=annotation_origin,
    )


def write_formal_annotations(project_id: str, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    from app import write_annotations_many

    return write_annotations_many(project_id, rows)


def read_candidate_material_hashes(
    project_id: str, image_ids: Iterable[str],
) -> dict[str, str]:
    """Canonical Material identity lookup; only the bounded pending write batch."""
    from app import material_store

    ids = list(dict.fromkeys(str(value) for value in image_ids if str(value)))
    if len(ids) > 200:
        raise ValueError("AI candidate hash validation batch must be at most 200")
    rows = material_store(project_id).get_many(ids)
    return {
        str(row.get("id") or ""): str(row.get("content_sha256") or "").strip().lower()
        for row in rows
    }


def _candidate_id(image_id: str, box: dict[str, Any]) -> str:
    supplied = str(box.get("id") or box.get("candidate_id") or "")
    if supplied:
        return supplied
    body = json.dumps([image_id, box], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _canonical_review_scope(
    labels: Iterable[str],
    mapping: dict[str, str],
    label_ids: dict[str, int],
) -> list[str]:
    """Resolve the labels this human-confirmed AI task actually reviewed."""
    resolved: list[str] = []
    normalized_mapping = {
        str(source).strip(): str(target).strip()
        for source, target in dict(mapping or {}).items()
        if str(source).strip() and str(target).strip()
    }
    for value in labels or ():
        source = str(value or "").strip()
        if not source:
            continue
        target = normalized_mapping.get(source, source)
        if target not in label_ids:
            raise ValueError(
                f"annotation review scope label is unavailable: {source}"
            )
        if target not in resolved:
            resolved.append(target)
    if not resolved:
        raise ValueError("annotation review has no canonical label scope")
    return resolved


def commit_candidate_decisions(
    project_id: str,
    task_id: str,
    store: CandidateStore,
    *,
    overwrite: bool,
    progress: Callable[[int, int, str], Any] | None = None,
    cancelled: Callable[[], bool] | None = None,
    review_scope: Iterable[str] | None = None,
    require_per_image_scope: bool = False,
    frozen_annotation_versions: dict[str, int] | None = None,
    frozen_missing_review_scopes: dict[str, list[str]] | None = None,
    frozen_material_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    journal_ref = "commit/result.json"
    store._ready()
    if review_scope is None:
        manifest = store.artifacts.read_json(
            task_id, "candidates/manifest.json", default={},
        )
        review_scope = (
            manifest.get("labels") or []
            if isinstance(manifest, dict)
            else []
        )
    review_scope_codes = tuple(dict.fromkeys(
        str(value).strip() for value in review_scope if str(value).strip()
    ))
    if not review_scope_codes:
        raise ValueError("AI annotation review scope is required before formal commit")
    applied_images, image_summaries = [], []
    applied_count = boxes_added = 0
    accepted_total = max(0, int(store.summary().get("accepted") or 0))
    processed = 0

    def assert_not_cancelled() -> None:
        if cancelled is not None and cancelled():
            raise InterruptedError("AI annotation review commit cancelled")

    def commit_guard() -> None:
        assert_not_cancelled()

    def apply_batch(items: list[dict[str, Any]]) -> None:
        nonlocal applied_count, boxes_added, processed
        if not items:
            return
        assert_not_cancelled()
        image_ids = [str(item["image_id"]) for item in items]
        applied_count += len(image_ids)
        for image_id in image_ids:
            if len(applied_images) < 100:
                applied_images.append(image_id)

        committed = store.get_commit_summaries(image_ids)
        pending_ids = [image_id for image_id in image_ids if image_id not in committed]
        if pending_ids:
            # Annotation version CAS does not fence Material content changes.
            # Fail closed for pre-fix candidate rows with no trustworthy source
            # hash, deleted materials, and storage rescan H1 -> H2.
            current_hashes = read_candidate_material_hashes(project_id, pending_ids)
            if frozen_material_hashes is not None:
                from app import material_store
                current_materials = {
                    str(row.get("id") or ""): row
                    for row in material_store(project_id).get_many(pending_ids)
                }
                for image_id in pending_ids:
                    material = current_materials.get(image_id) or {}
                    if (current_hashes.get(image_id) != frozen_material_hashes.get(image_id)
                            or material.get("source_available") is False
                            or material.get("_dataset_delete_claim")
                            or material.get("_material_batch_delete_claim")):
                        raise ValueError("AI_SUPPLEMENT_MATERIAL_CHANGED: source identity or availability changed")
            for item in items:
                image_id = str(item["image_id"])
                if image_id in committed:
                    continue
                source_hash = str(item.get("source_content_sha256") or "").strip().lower()
                current_hash = current_hashes.get(image_id, "")
                if (
                    len(source_hash) != 64
                    or any(char not in "0123456789abcdef" for char in source_hash)
                    or source_hash != current_hash
                ):
                    raise ValueError(
                        "AI_CANDIDATE_SOURCE_CHANGED: "
                        f"素材 {image_id} 内容已变化、已删除或缺少可信来源哈希；"
                        "请重新执行 AI 标注并审核"
                    )
        previous_by_id = read_formal_annotations(project_id, pending_ids) if pending_ids else {}
        to_write = []
        to_journal = []
        batch_summaries: dict[str, dict[str, Any]] = dict(committed)
        batch_boxes_added = 0

        for item in items:
            assert_not_cancelled()
            image_id = str(item["image_id"])
            if image_id in committed:
                continue
            explicit_scope = item.get("review_scope")
            if explicit_scope is None:
                if require_per_image_scope:
                    raise ValueError("AI per-image review scope is missing; refuse formal GT write")
                image_scope = set(review_scope_codes)
                scope_source = "task_uniform_legacy"
            else:
                if (not isinstance(explicit_scope, list) or not explicit_scope
                        or len(explicit_scope) > 128
                        or any(not isinstance(code, str) or not code.strip()
                               or code != code.strip() for code in explicit_scope)
                        or len(set(explicit_scope)) != len(explicit_scope)
                        or not set(explicit_scope).issubset(review_scope_codes)):
                    raise ValueError("AI per-image review scope is outside the task label contract")
                image_scope = set(explicit_scope)
                scope_source = "explicit_per_image"
                candidate_labels = {
                    str(box.get("label") or box.get("code") or "").strip()
                    for box in (item.get("boxes") or [])
                }
                if not candidate_labels.issubset(image_scope):
                    raise ValueError("AI candidate boxes are outside the explicit per-image review scope")
            if frozen_missing_review_scopes is not None:
                expected_scope = frozen_missing_review_scopes.get(image_id)
                if not isinstance(expected_scope, list) or not image_scope.issubset(set(expected_scope)):
                    raise ValueError("AI candidate review exceeded frozen per-image missing labels")
            previous_row = previous_by_id.get(image_id) or {}
            previous = list(previous_row.get("boxes") or [])
            expected_version = int(previous_row.get("version") or 0)
            if frozen_annotation_versions is not None:
                frozen_version = frozen_annotation_versions.get(image_id)
                if not isinstance(frozen_version, int) or expected_version != frozen_version:
                    raise ValueError("AI_SUPPLEMENT_GT_CHANGED: formal GT changed after task creation")
                expected_version = frozen_version
            recorded_scope = {
                str(value).strip()
                for value in (previous_row.get("annotation_scope") or [])
                if str(value).strip()
            }
            previous_scope = set(recorded_scope)
            previous_scope.update(
                str(box.get("label") or box.get("code") or "").strip()
                for box in previous
                if str(box.get("label") or box.get("code") or "").strip()
            )
            if "*" in previous_scope:
                annotation_scope = ["*"]
            else:
                annotation_scope = sorted(
                    previous_scope | image_scope
                )
            existing = {
                (str(box.get("source_task_id") or ""), str(box.get("candidate_id") or ""))
                for box in previous
            }
            incoming = []
            for box in item.get("boxes") or []:
                candidate_id = _candidate_id(image_id, dict(box))
                if (task_id, candidate_id) in existing:
                    continue
                incoming.append({
                    **box,
                    "candidate_id": candidate_id,
                    "source_task_id": task_id,
                    "source": "ai_candidate_confirmed",
                })
            overwrite_changed = False
            if overwrite:
                reviewed_labels = image_scope
                previous_count = len(previous)
                previous = [
                    box for box in previous
                    if str(box.get("label") or box.get("code") or "").strip()
                    not in reviewed_labels
                ]
                overwrite_changed = len(previous) != previous_count
            final_boxes = previous + incoming
            source_values = [str(box.get("source") or "").strip().lower() for box in final_boxes]
            is_ai_source = lambda source: source.startswith("ai_") or source in {"auto", "semi-auto"}
            has_ai = any(is_ai_source(source) for source in source_values)
            has_non_ai = any(not is_ai_source(source) for source in source_values)
            annotation_origin = (
                "mixed" if has_ai and has_non_ai
                else "ai_confirmed" if incoming or has_ai or not final_boxes
                else "manual"
            )
            annotation_state = "annotated" if final_boxes else "confirmed_empty"
            task_boxes_present = any(
                str(box.get("source_task_id") or "") == task_id for box in final_boxes
            )
            # Re-write an idempotent task-owned projection after a crash between
            # formal GT commit and CandidateStore journaling. AnnotationRepository
            # will keep the same content digest, while MaterialRepository projection
            # is repaired in the same batch helper.
            # An accepted, human-reviewed empty AI candidate may extend the
            # review scope of a historical positive GT without adding boxes.
            # Persist that explicit scope change; otherwise the task is
            # journaled as committed while the training admission still fails.
            # Do not trigger a write merely because an old box label was
            # synthesized into previous_scope -- only the reviewed codes do.
            scope_reviewed_now = "*" not in recorded_scope and bool(
                image_scope - recorded_scope
            )
            if incoming or not final_boxes or task_boxes_present or overwrite_changed or scope_reviewed_now:
                to_write.append({
                    "image_id": image_id,
                    "boxes": final_boxes,
                    "annotation_state": annotation_state,
                    "annotation_scope": annotation_scope,
                    "annotation_origin": annotation_origin,
                    "expected_version": expected_version,
                    "source_content_sha256": str(
                        item.get("source_content_sha256") or ""
                    ).strip().lower(),
                })
                batch_boxes_added += len(incoming)
            summary = {
                "image_id": image_id,
                "box_count": len(final_boxes),
                "labels": sorted({str(box.get("label")) for box in final_boxes if box.get("label")}),
                "annotation_state": annotation_state,
                "annotation_origin": annotation_origin,
                "review_scope": sorted(image_scope),
                "review_scope_source": scope_source,
            }
            to_journal.append(summary)
            batch_summaries[image_id] = summary

        assert_not_cancelled()
        written_by_id: dict[str, dict[str, Any]] = {}
        if to_write:
            written_by_id = {
                str(row.get("image_id") or ""): row
                for row in (write_formal_annotations(project_id, to_write) or [])
            }
        # Future journal rows can prove an unchanged formal GT revision. Older
        # journals deliberately stay unknown when no durable revision evidence
        # exists; do not invent it during a later read-only audit.
        written_ids = {str(row["image_id"]) for row in to_write}
        for summary in to_journal:
            image_id = str(summary["image_id"])
            summary["gt_write_performed"] = image_id in written_ids
            saved = written_by_id.get(image_id)
            if saved and int(saved.get("version") or 0) > 0:
                digest = str(saved.get("content_digest") or "")
                if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
                    summary["gt_snapshot_version"] = int(saved["version"])
                    summary["gt_snapshot_digest"] = digest
        # Formal GT and CandidateStore are intentionally separate durable owners.
        # Once a bounded formal batch is durable, its journal is mandatory catch-up:
        # do not observe a newly-arrived user cancellation between these two commits.
        # The next batch boundary will observe cancellation. This prevents the task
        # from becoming CANCELLED with durable Ground Truth but no replay journal.
        if to_journal:
            store.record_commit_summaries(to_journal)
        boxes_added += batch_boxes_added

        for image_id in image_ids:
            summary = batch_summaries.get(image_id)
            if summary is not None and len(image_summaries) < 100:
                image_summaries.append({
                    key: summary.get(key)
                    for key in ("image_id", "box_count", "labels", "annotation_state", "annotation_origin")
                })
        processed += len(image_ids)
        if progress is not None:
            progress(processed, accepted_total, image_ids[-1])

    batch: list[dict[str, Any]] = []
    for item in store.iter_accepted_items(include_committed=True):
        batch.append(item)
        if len(batch) == 200:
            apply_batch(batch)
            batch = []
    apply_batch(batch)

    result = {
        "applied_images": applied_count,
        "applied_image_ids": applied_images,
        "boxes_added": boxes_added,
        "review": store.summary(),
        "completed_image_ids": applied_images,
        "image_summaries": image_summaries,
        "image_summaries_truncated": applied_count > len(image_summaries),
        "commit_journal_ref": "candidates/items.sqlite3",
    }
    store.artifacts.atomic_write_json(task_id, journal_ref, result)
    return result


def commit_confirmed_review(context):
    confirmation = context.artifacts.read_json(
        context.task.task_id, "review/confirmation.json", default=None,
    )
    if not isinstance(confirmation, dict) or confirmation.get("accepted") is not True:
        return None
    request = context.artifacts.read_json(
        context.task.task_id, context.task.payload_ref, default={},
    )
    if context.task.kind is TaskKind.MATERIAL_BATCH:
        request = (request or {}).get("options") or {}
    scope_policy = str((request or {}).get("review_scope_policy") or "task_uniform_legacy")
    if scope_policy not in {"task_uniform_legacy", "per_image_required"}:
        raise RuntimeError("confirmed annotation review scope policy is invalid")
    frozen_versions = (request or {}).get("per_image_annotation_versions") if scope_policy == "per_image_required" else None
    frozen_missing_scopes = (request or {}).get("per_image_missing_review_scopes") if scope_policy == "per_image_required" else None
    frozen_material_hashes = (request or {}).get("per_image_source_hashes") if scope_policy == "per_image_required" else None
    if scope_policy == "per_image_required" and (
            not isinstance(frozen_versions, dict) or not isinstance(frozen_missing_scopes, dict)
            or not isinstance(frozen_material_hashes, dict)
            or set(frozen_versions) != set(frozen_missing_scopes)
            or set(frozen_versions) != set(frozen_material_hashes)):
        raise RuntimeError("AI supplemental review frozen GT identity is missing")
    store = CandidateStore(context.artifacts, task_id=context.task.task_id)
    if (request or {}).get("mode") == "hard_sample_yolo":
        from app import project_dir, material_store
        from .hard_sample_mining import assert_not_frozen_test, HardSampleSafetyError
        image_ids = [str(value) for value in request.get("image_ids") or []]
        hashes = {str(k): str(v).lower() for k, v in (request.get("source_hashes") or {}).items()}
        if not image_ids or set(image_ids) != set(hashes):
            raise HardSampleSafetyError("HARD_SAMPLE_SOURCE_IDENTITY_MISSING")
        actual_rows = []
        for offset in range(0, len(image_ids), 500):
            actual_rows.extend(material_store(context.task.project_id).get_many(image_ids[offset:offset + 500]))
        actual = {str(row.get("id") or ""): str(row.get("content_sha256") or "").lower()
                  for row in actual_rows}
        if actual != hashes:
            raise HardSampleSafetyError("HARD_SAMPLE_SOURCE_CHANGED")
        assert_not_frozen_test(project_dir(context.task.project_id), image_ids, actual)
    # Human confirmation freezes intent, not stale class indexes. Revalidate
    # every candidate against the current active platform label catalog before
    # writing Ground Truth, and repair class_id if the catalog order changed.
    from app import _annotation_label_catalog, get_project
    label_ids = {
        str(item["code"]): int(item["class_id"])
        for item in _annotation_label_catalog(get_project(context.task.project_id))
    }
    mapping = dict(confirmation.get("label_mapping") or {})
    manifest = context.artifacts.read_json(
        context.task.task_id, "candidates/manifest.json", default={},
    )
    raw_review_labels = list((request or {}).get("labels") or [])
    if not raw_review_labels and isinstance(manifest, dict):
        raw_review_labels = list(manifest.get("labels") or [])
    try:
        review_scope = _canonical_review_scope(
            raw_review_labels, mapping, label_ids,
        )
        store.remap_labels(mapping, label_ids)
    except ValueError as error:
        raise RuntimeError(
            "confirmed annotation label mapping is no longer valid: " + str(error)
        ) from error

    def update_progress(done: int, total: int, image_id: str) -> None:
        percent = 70.0 + 29.0 * done / max(1, total)
        context.heartbeat(
            progress=min(99.0, percent),
            stage="APPLYING_REVIEW",
            current_item=f"正在统一标签并写入正式标注 {done}/{max(1, total)} · {image_id}",
        )

    context.heartbeat(
        progress=70.0,
        stage="APPLYING_REVIEW",
        current_item="正在准备标注入库",
    )
    result = commit_candidate_decisions(
        context.task.project_id,
        context.task.task_id,
        store,
        overwrite=bool((request or {}).get("overwrite")),
        progress=update_progress,
        cancelled=context.cancel_requested,
        review_scope=review_scope,
        require_per_image_scope=scope_policy == "per_image_required",
        frozen_annotation_versions=frozen_versions,
        frozen_missing_review_scopes=frozen_missing_scopes,
        frozen_material_hashes=frozen_material_hashes,
    )
    sync_annotation_statistics(context.repository, context.task, store)
    if mapping:
        try:
            from app import remember_project_label_aliases
            remembered = remember_project_label_aliases(
                context.task.project_id,
                [{"class_id": source, "name": source} for source in mapping],
                mapping,
            )
            if remembered:
                result["remembered_label_aliases"] = remembered
        except Exception:
            # Alias memory is secondary metadata. Ground Truth was already
            # committed above, so never turn a successful formal annotation
            # commit into a false task failure because alias persistence failed.
            result["label_alias_memory_warning"] = (
                "正式标注已入库，但标签别名记忆未保存；不影响本次标注结果"
            )
    context.artifacts.atomic_write_json(
        context.task.task_id, "review/result.json", result,
    )
    status = TaskStatus.PARTIAL_SUCCESS if result["review"].get("failed") else TaskStatus.SUCCEEDED
    return status, "review/result.json"


class AnnotationHandler:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir).resolve() if data_dir is not None else None

    def run(self, context):
        review = commit_confirmed_review(context)
        if review is not None:
            return review
        outcome = run_ai_annotation(context, data_dir=self.data_dir)
        return outcome.status, outcome.result_ref

    def recover(self, context):
        return self.run(context)


def worker_registration(_data_dir: Path):
    # The same AI_ANNOTATION handler owns both provider annotations and YOLO
    # mining; never advertise mining on the CPU-only control-plane Worker.
    capabilities = {"vision_provider"}
    try:
        import importlib.util
        if importlib.util.find_spec("ultralytics") and importlib.util.find_spec("torch"):
            import torch
            if torch.cuda.is_available():
                capabilities.add("mining.ultralytics")
    except (ImportError, RuntimeError, OSError):
        pass
    return {
        "handlers": {TaskKind.AI_ANNOTATION: AnnotationHandler(_data_dir)},
        "capabilities": capabilities,
    }

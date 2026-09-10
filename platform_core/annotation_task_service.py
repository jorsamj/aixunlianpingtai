from __future__ import annotations

import hashlib
import json
import re
import uuid
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
    from app import load_images, storage_manager

    ordered_ids = [str(value) for value in image_ids]
    wanted = set(ordered_ids)
    order = {image_id: index for index, image_id in enumerate(ordered_ids)}
    manager = storage_manager(project_id)
    rows = []
    for image in load_images(project_id):
        image_id = str(image.get("id") or "")
        if image_id not in wanted:
            continue
        row = dict(image)
        row["path"] = str(manager.materialize(row).path)
        rows.append(row)
    rows.sort(key=lambda image: order[str(image["id"])])
    if len(rows) != len(wanted):
        missing = wanted - {str(image.get("id")) for image in rows}
        raise FileNotFoundError("annotation images no longer exist: " + ", ".join(sorted(missing)))
    return rows


def annotate_one(request: dict[str, Any], image: dict[str, Any]) -> dict[str, Any]:
    from .annotation_runtime import build_annotation_prompt

    provider = request["_provider"]
    config = request["_provider_config"]
    path = Path(str(image.get("path") or ""))
    if not path.is_file():
        raise FileNotFoundError(f"annotation image file does not exist: {image.get('filename') or image.get('id')}")
    prompt = build_annotation_prompt(
        config,
        request["label_catalog"],
        width=int(image["width"]),
        height=int(image["height"]),
        business_instruction=str(request.get("business_instruction") or ""),
        template=str(request.get("prompt_template") or ""),
    )
    response = provider.annotate(
        image_bytes=path.read_bytes(),
        prompt=prompt,
        output_schema=auto_label_core.CANDIDATE_OUTPUT_SCHEMA,
    )
    text = str(response.get("text") or "")
    parsed = auto_label_core.parse_candidate_response(
        text,
        width=int(image["width"]),
        height=int(image["height"]),
        label_ids=request["label_ids"],
        label_aliases=request["label_aliases"],
    )
    threshold = float(request.get("threshold") if request.get("threshold") is not None else 0.45)
    boxes = auto_label_core.nms_candidates(
        [box for box in parsed if float(box.get("confidence") or 0) >= threshold],
        iou_threshold=0.5,
    )
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
        "raw_response_hash": auto_label_core.raw_response_hash(text),
        "request_id": str(response.get("request_id") or ""),
        "latency_ms": int(response.get("latency_ms") or 0),
        "provider": str(response.get("provider") or ""),
        "model": str(response.get("model") or config.get("model_name") or ""),
    }


def run_ai_annotation(
    context,
    *,
    annotate: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] = annotate_one,
) -> WorkerOutcome:
    request = context.artifacts.read_json(context.task.task_id, context.task.payload_ref, default={})
    if not isinstance(request, dict):
        raise ValueError("AI annotation request is invalid")
    runtime_request = dict(request)
    if annotate is annotate_one:
        runtime_request = _prepare_runtime_request(context.task.project_id, runtime_request)
    images = load_task_images(context.task.project_id, runtime_request.get("image_ids") or [])
    preview_count = max(0, int(runtime_request.get("preview_count") or 0))
    if preview_count:
        images = images[:preview_count]
    if not images:
        raise ValueError("AI annotation task has no images")
    checkpoint = dict(context.load_checkpoint() or {})
    start = max(0, int(checkpoint.get("next_index") or 0))
    store = CandidateStore(context.artifacts, task_id=context.task.task_id, page_size=50)
    if start == 0:
        store.initialize(labels=list(runtime_request.get("labels") or []), total_images=len(images))

    succeeded = int(checkpoint.get("succeeded") or 0)
    failed = int(checkpoint.get("failed") or 0)
    for index in range(start, len(images)):
        if context.cancel_requested():
            return WorkerOutcome(TaskStatus.CANCELLED, "candidates/manifest.json")
        image = images[index]
        try:
            generated = annotate(runtime_request, image)
            boxes = list(generated.get("boxes") or [])
            item = {
                "image_id": str(image["id"]),
                "filename": image.get("filename"),
                "url": image.get("url"),
                "status": "success" if boxes else "empty",
                "boxes": boxes,
                **{key: generated.get(key) for key in (
                    "raw_response_hash", "request_id", "latency_ms", "provider", "model"
                ) if generated.get(key) not in (None, "")},
            }
            succeeded += 1
        except Exception as error:
            item = {
                "image_id": str(image.get("id") or ""),
                "filename": image.get("filename"),
                "url": image.get("url"),
                "status": "failed",
                "boxes": [],
                "error": _public_error(error),
            }
            failed += 1
        store.append_items([item])
        context.save_checkpoint({"next_index": index + 1, "succeeded": succeeded, "failed": failed})
        context.repository.heartbeat(
            context.task.task_id,
            context.lease.lease_token,
            progress=int((index + 1) / max(1, len(images)) * 100),
            stage="AI_ANNOTATION",
            current_item=str(image.get("id") or ""),
        )

    summary = store.summary()
    context.artifacts.atomic_write_json(context.task.task_id, "generation.json", {
        "summary": summary,
        "generation_partial": bool(failed),
    })
    if failed and not succeeded:
        return WorkerOutcome(TaskStatus.FAILED, "candidates/manifest.json", "all images failed", True)
    return WorkerOutcome(
        TaskStatus.AWAITING_CONFIRMATION,
        "candidates/manifest.json",
        generation_partial=bool(failed),
    )


def _prepare_runtime_request(project_id: str, request: dict[str, Any]) -> dict[str, Any]:
    from app import _v47_label_catalog, _v47_runtime_provider, get_project

    provider, config = _v47_runtime_provider(request)
    labels = [str(value) for value in request.get("labels") or []]
    catalog = _v47_label_catalog(get_project(project_id))
    selected = [item for item in catalog if str(item.get("code")) in labels]
    label_ids = {str(item["code"]): int(item["class_id"]) for item in selected}
    missing = sorted(set(labels) - set(label_ids))
    if missing:
        raise ValueError("task labels are unavailable or inactive: " + ", ".join(missing))
    prepared = dict(request)
    prepared.update({
        "_provider": provider,
        "_provider_config": config,
        "label_catalog": selected,
        "label_ids": label_ids,
        "label_aliases": {
            str(item["code"]): [str(item.get("display_name_zh") or "")]
            for item in selected
        },
        "prompt_template": str((request.get("prompt_template_snapshot") or {}).get("prompt") or ""),
    })
    return prepared


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


def read_formal_annotation(project_id: str, image_id: str) -> dict[str, Any]:
    from app import read_annotation

    return read_annotation(project_id, image_id)


def write_formal_annotation(project_id: str, image_id: str, boxes: list[dict[str, Any]]) -> None:
    from app import write_annotation

    write_annotation(project_id, image_id, boxes)


def _candidate_id(image_id: str, box: dict[str, Any]) -> str:
    supplied = str(box.get("id") or box.get("candidate_id") or "")
    if supplied:
        return supplied
    body = json.dumps([image_id, box], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def commit_candidate_decisions(
    project_id: str,
    task_id: str,
    store: CandidateStore,
    *,
    overwrite: bool,
) -> dict[str, Any]:
    journal_ref = "commit/result.json"
    store._ready()
    applied_images, image_summaries = [], []
    applied_count = boxes_added = 0
    for item in store.iter_items():
        if item.get("accepted") is not True or item.get("status") not in {"success", "empty"}:
            continue
        image_id = str(item["image_id"])
        applied_count += 1
        if len(applied_images) < 100:
            applied_images.append(image_id)
        with closing(store._connect()) as db:
            committed = db.execute("SELECT summary_json FROM commits WHERE image_id=?", (image_id,)).fetchone()
        if committed:
            if len(image_summaries) < 100:
                image_summaries.append(json.loads(committed[0]))
            continue
        previous = list(read_formal_annotation(project_id, image_id).get("boxes") or [])
        existing = {(str(box.get("source_task_id") or ""), str(box.get("candidate_id") or "")) for box in previous}
        incoming = []
        for box in item.get("boxes") or []:
            candidate_id = _candidate_id(image_id, dict(box))
            if (task_id, candidate_id) in existing:
                continue
            incoming.append({**box, "candidate_id": candidate_id, "source_task_id": task_id,
                             "source": "ai_candidate_confirmed"})
        if overwrite and incoming:
            replaced_classes = {box.get("class_id") for box in incoming}
            previous = [box for box in previous if box.get("class_id") not in replaced_classes]
        final_boxes = previous + incoming
        # Accepting an empty result explicitly confirms empty only if no formal boxes exist.
        if incoming or not final_boxes:
            write_formal_annotation(project_id, image_id, final_boxes)
            boxes_added += len(incoming)
        summary = {"image_id": image_id, "box_count": len(final_boxes),
                   "labels": sorted({str(box.get("label")) for box in final_boxes if box.get("label")})}
        with closing(store._connect()) as db, db:
            db.execute("INSERT OR REPLACE INTO commits VALUES (?,?)", (image_id, json.dumps(summary, ensure_ascii=False)))
        if len(image_summaries) < 100:
            image_summaries.append(summary)
    result = {"applied_images": applied_count, "applied_image_ids": applied_images,
              "boxes_added": boxes_added, "review": store.summary(),
              "completed_image_ids": applied_images, "image_summaries": image_summaries,
              "image_summaries_truncated": applied_count > len(image_summaries),
              "commit_journal_ref": "candidates/items.sqlite3"}
    store.artifacts.atomic_write_json(task_id, journal_ref, result)
    return result


class AnnotationHandler:
    def run(self, context):
        outcome = run_ai_annotation(context)
        return outcome.status, outcome.result_ref

    def recover(self, context):
        return self.run(context)


def worker_registration(_data_dir: Path):
    return {
        "handlers": {TaskKind.AI_ANNOTATION: AnnotationHandler()},
        "capabilities": {"vision_provider"},
    }

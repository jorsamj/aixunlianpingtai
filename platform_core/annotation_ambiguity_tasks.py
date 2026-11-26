"""Plan and save scoped candidate drafts in the existing material worker."""
import hashlib
import json
from contextlib import closing

from filelock import FileLock

from .annotation_ambiguity_geometry import plan_ambiguity
from .annotation_candidates import CandidateStore
from .annotation_repository import AnnotationRepository
from .annotations import normalize_boxes
from .labels import active_project_label_ids
from .material_repository import MaterialRepository, material_annotation_lifecycle_fence
from .task_runtime import TaskKind, TaskRecord, TaskStatus

PLAN = "PLAN_AI_AMBIGUITY"
APPLY = "SAVE_AI_AMBIGUITY_DRAFTS"
OPERATIONS = {PLAN, APPLY}
PAGE_SIZE = 25


def ambiguity_task_id(project, source_task, actor, request_id, operation):
    body = json.dumps([project, source_task, actor, request_id, operation])
    return "ambiguity_" + hashlib.sha256(body.encode()).hexdigest()


def publish_ambiguity_task(repository, artifacts, task_id, payload, ids):
    from .material_batches import BatchRequestError, BatchSelection, CHECKPOINT_REF, SELECTION_REF, publish_prepared_batch

    selection_path = artifacts.artifact_path(task_id, SELECTION_REF)
    selection_path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(selection_path) + ".prepare.lock", timeout=30):
        existing = artifacts.read_json(task_id, "request.json", default=None)
        if existing is not None and existing != payload:
            raise BatchRequestError("AMBIGUITY_REQUEST_CONFLICT", "原消歧请求参数已变化", 409)
        if existing is None:
            artifacts.atomic_write_json(task_id, "request.json", payload)
        with closing(BatchSelection(selection_path)) as manifest:
            if not manifest.frozen():
                with manifest.transaction():
                    manifest.database.executemany("INSERT INTO selection(image_id) VALUES (?)", ((image_id,) for image_id in ids))
                    manifest.database.execute("INSERT INTO meta VALUES ('frozen','1')")
                artifacts.atomic_write_json(task_id, CHECKPOINT_REF, manifest.summary())
        task = TaskRecord.new(task_id, payload["project_id"], TaskKind.MATERIAL_BATCH, "request.json",
                              "materials:" + payload["project_id"], required_capabilities=("materials.batch",))
        return publish_prepared_batch(task, repository, artifacts)


def selected_plan_ids(artifacts, plan_id):
    from .material_batches import BatchSelection, SELECTION_REF

    with closing(BatchSelection(artifacts.artifact_path(plan_id, SELECTION_REF))) as manifest:
        return [row[0] for row in manifest.database.execute(
            "SELECT image_id FROM selection WHERE state='succeeded' ORDER BY image_id"
        )]


def _current_parent(repository, artifacts, project, source_task):
    from .material_batches import BatchRequestError

    parent = repository.get(source_task)
    if (parent is None or parent.project_id != project or parent.status is not TaskStatus.AWAITING_CONFIRMATION
            or (parent.kind is not TaskKind.AI_ANNOTATION and (
                parent.kind is not TaskKind.MATERIAL_BATCH
                or artifacts.read_json(source_task, parent.payload_ref).get("operation") != "AI_ANNOTATE"))):
        raise BatchRequestError("AMBIGUITY_REVIEW_CHANGED", "原 AI 任务当前不可编辑", 409)


def _source_digest(item, material, committed):
    if not item or not material or committed or item.get("gt_committed"):
        return None
    expected = item.get("source_content_sha256") or item.get("content_sha256")
    if (not expected or material.get("content_sha256") != expected
            or material.get("source_available") is False
            or material.get("_dataset_delete_claim") or material.get("_material_batch_delete_claim")):
        return None
    return expected


def run_ambiguity_task(context, manifest, payload, data_dir):
    from .material_batches import BatchRequestError, BatchSelection, RESULT_REF, SELECTION_REF, _check_active

    project = context.task.project_id
    task_id, source = context.task.task_id, payload["source_task_id"]
    if (payload["project_id"] != project or not project or not all(c.isalnum() or c in "_-" for c in project)
            or not manifest.frozen() or not payload.get("actor_id")):
        raise BatchRequestError("AMBIGUITY_SCOPE_INVALID", "消歧任务身份不一致", 409)
    project_path = (data_dir / "projects" / project).resolve()
    if project_path.parent != (data_dir / "projects").resolve():
        raise BatchRequestError("AMBIGUITY_SCOPE_INVALID", "消歧项目路径无效", 409)
    materials = MaterialRepository(project_path)
    annotations = AnnotationRepository(project_path)
    store = CandidateStore(context.artifacts, task_id=source)
    lock = FileLock(str(context.artifacts.artifact_path(source, "review.lock")), timeout=30)
    planning = payload["operation"] == PLAN

    def active():
        if context.cancel_requested():
            raise InterruptedError("ambiguity task cancelled")

    while rows := manifest.rows(limit=PAGE_SIZE):
        _check_active(context)
        ids = [row["image_id"] for row in rows]
        with lock, material_annotation_lifecycle_fence(project_path):
            _current_parent(context.repository, context.artifacts, project, source)
            if planning and store.review_revision() != payload["review_revision"]:
                raise BatchRequestError("AMBIGUITY_REVIEW_CHANGED", "候选范围已变化，请重新冻结", 409)
            labels = active_project_label_ids(project_path) or {}
            if labels != payload["labels"]:
                raise BatchRequestError("AMBIGUITY_LABELS_CHANGED", "项目标签已变化，请重新预检", 409)
            entries = store.get_many(ids)
            sources = {row["id"]: row for row in materials.get_many(ids)}
            committed = annotations.candidate_committed_ids(source, ids)
            receipts = {} if planning else store.draft_receipts(ids, task_id)
            plans = {}
            if not planning:
                with closing(BatchSelection(context.artifacts.artifact_path(payload["plan_task_id"], SELECTION_REF))) as parent:
                    placeholders = ",".join("?" for _ in ids)
                    plans = {row[0]: json.loads(row[1]) for row in parent.database.execute(
                        f"SELECT image_id,tombstone_json FROM selection WHERE image_id IN ({placeholders}) AND state='succeeded'", ids,
                    )}
            for image_id in ids:
                active()
                item, material = entries.get(image_id), sources.get(image_id)
                digest = _source_digest(item, material, image_id in committed)
                result = receipts.get(image_id)
                try:
                    if planning:
                        if not digest:
                            raise ValueError("已有正式提交、源素材已变化或缺少源证据")
                        plan = plan_ambiguity(item, payload["mode"], payload["label"], payload["threshold"])
                        if "reason" in plan:
                            raise ValueError(plan["reason"])
                        result = {**plan, "revision": item["draft_revision"], "sha256": digest,
                                  "before": len(item["boxes"])}
                    else:
                        plan = plans.get(image_id)
                        if not plan:
                            raise ValueError("原消歧预检证据缺失")
                        if result is None:
                            if (digest != plan["sha256"] or item.get("accepted") is True
                                    or item.get("draft_revision") != plan["revision"]):
                                raise ValueError("候选身份、版本或资格已变化")
                            boxes = [{**box, "id": str(box.get("id") or hashlib.sha256(
                                f"{task_id}:{index}".encode()).hexdigest()[:20])}
                                for index, box in enumerate(plan["boxes"])]
                            boxes = normalize_boxes(boxes, int(material.get("width") or item.get("width") or 0),
                                                    int(material.get("height") or item.get("height") or 0), labels)
                            result = store.save_draft(image_id, boxes, expected_revision=plan["revision"],
                                actor=payload["actor_id"], request_id=task_id, automatic=payload["mode"] == "auto",
                                commit_guard=active)
                        if result.get("actor") != payload["actor_id"] or result["revision"] != plan["revision"] + 1:
                            raise ValueError("草稿回执身份或修订不一致")
                        result = {"image_id": image_id, "draft_revision": result["revision"],
                                  "source_content_sha256": plan["sha256"]}
                except (ValueError, KeyError) as error:
                    manifest.transition([image_id], "failed", str(error), commit_guard=active)
                    continue
                with manifest.transaction():
                    manifest.database.execute(
                        "UPDATE selection SET state='succeeded',tombstone_json=? WHERE image_id=?",
                        (json.dumps(result, ensure_ascii=False), image_id),
                    )
                    active()
        summary = manifest.summary()
        _check_active(context, progress=100 * summary["processed"] / summary["total"])
        context.save_checkpoint(summary)

    summary = manifest.summary()
    if planning:
        if store.review_revision() != payload["review_revision"]:
            raise BatchRequestError("AMBIGUITY_REVIEW_CHANGED", "候选范围已变化，请重新冻结", 409)
        summary["removed"], summary["fallback_groups"] = manifest.database.execute(
            "SELECT COALESCE(SUM(json_extract(tombstone_json,'$.removed')),0), "
            "COALESCE(SUM(json_extract(tombstone_json,'$.fallbackGroups')),0) "
            "FROM selection WHERE state='succeeded'"
        ).fetchone()
        summary["skipped_reasons"] = dict(manifest.database.execute(
            "SELECT error,COUNT(*) FROM selection WHERE state='failed' GROUP BY error"
        ))
        summary["examples"] = []
        for row in manifest.database.execute(
            "SELECT image_id,tombstone_json FROM selection WHERE state='succeeded' ORDER BY image_id LIMIT 16"
        ):
            plan = json.loads(row[1])
            summary["examples"].append({"id": row[0], "before": plan["before"], "after": len(plan["boxes"]),
                                        "labels": list(dict.fromkeys(box.get("label") for box in plan["boxes"]))})
    context.save_checkpoint(summary)
    context.artifacts.atomic_write_json(task_id, RESULT_REF, summary)
    if planning or not summary["failed"]:
        return TaskStatus.SUCCEEDED, RESULT_REF
    return (TaskStatus.PARTIAL_SUCCESS if summary["succeeded"] else TaskStatus.FAILED), RESULT_REF

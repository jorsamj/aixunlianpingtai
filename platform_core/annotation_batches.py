"""Streaming material-batch adapter; generated boxes require explicit human review."""
from PIL import Image

from .annotation_candidates import CandidateStore
from .annotation_runtime import prepare_request
from .annotation_task_service import annotate_one, _public_error
from .storage.errors import redact_storage_error
from .storage.import_tasks import _provider
from .storage.manager import StorageManager
from .task_runtime import TaskStatus
from .task_runtime.task_logs import append_task_log


class AnnotationBatch:
    def __init__(self, data_dir, project, materials, context, manifest, options):
        self.context, self.manifest = context, manifest
        self.store = CandidateStore(context.artifacts, task_id=context.task.task_id)
        if not context.artifacts.artifact_path(context.task.task_id, "candidates/manifest.json").is_file():
            self.store.initialize(labels=list(options.get("labels") or []), total_images=manifest.summary()["total"])
        self.manager = StorageManager(data_dir=data_dir, project_id=project, materials=materials,
            provider_resolver=lambda source, _secret: _provider(data_dir, project, source))
        self.runtime = None
        self.configuration_error = None
        try:
            # Client/model and credentials are reused across this task's images.
            self.runtime = prepare_request(data_dir, project, options)
        except Exception as error:
            self.configuration_error = self.public_error(error)

    @staticmethod
    def public_error(error):
        code = str(getattr(error, "code", "") or type(error).__name__)
        return code + ": " + _public_error(RuntimeError(redact_storage_error(error)))

    def process(self, materials, batch, check_active):
        context, manifest = self.context, self.manifest
        indexed = {row["id"]: row for row in materials.get_many([item["image_id"] for item in batch])}
        for selected in batch:
            image_id = selected["image_id"]

            def candidate_commit_guard():
                check_active(context, "AI_ANNOTATION_CANDIDATE_COMMIT", image_id)

            def selection_commit_guard():
                check_active(context, "AI_ANNOTATION_SELECTION_COMMIT", image_id)

            check_active(context, "AI_ANNOTATION", image_id)
            old = self.store.get(image_id)
            # A crash after candidate durability must not repeat a billable inference.
            current_sha = str(
                (indexed.get(image_id) or {}).get("content_sha256") or ""
            ).strip().lower()
            old_sha = str(
                (old or {}).get("source_content_sha256") or ""
            ).strip().lower()
            if (
                old and old.get("status") in {"success", "empty"}
                and old_sha and old_sha == current_sha
            ):
                manifest.transition(
                    [image_id], "succeeded", commit_guard=selection_commit_guard
                )
            else:
                image = indexed.get(image_id) or {"id": image_id}
                item = {"image_id": image_id, "filename": image.get("filename"),
                        "url": f"/api/v61/projects/{context.task.project_id}/materials/{image_id}/content",
                        "boxes": []}
                try:
                    if self.configuration_error:
                        raise ValueError(self.configuration_error)
                    if image_id not in indexed:
                        raise ValueError("MATERIAL_NOT_FOUND: selected material no longer exists")
                    image = dict(image)
                    # Current vision providers consume image bytes; storage-backed sources
                    # therefore materialize one verified file at a time, never a project list.
                    local = self.manager.materialize(image)
                    image["path"] = str(local.path)
                    source_sha = str(getattr(local, "content_sha256", "") or "").strip().lower()
                    if not source_sha:
                        raise ValueError("AI_CANDIDATE_SOURCE_IDENTITY_MISSING")
                    with Image.open(image["path"]) as decoded:
                        image["width"], image["height"] = decoded.size
                    # Materialization/decoding can be slow. Re-prove ownership and
                    # cancellation immediately before starting a potentially billable
                    # provider request.
                    check_active(context, "AI_ANNOTATION", image_id)
                    generated = annotate_one(self.runtime, image)
                    # The user may cancel, or this Worker may lose its lease, while the
                    # provider call is in flight. Never publish that late result into
                    # candidate truth after cancellation/fencing became durable.
                    check_active(context, "AI_ANNOTATION", image_id)
                    item.update(generated)
                    item.update({"status": "success" if generated.get("boxes") else "empty",
                                 "source_content_sha256": source_sha,
                                 "width": image["width"], "height": image["height"]})
                    self.store.append_items(
                        [item], commit_guard=candidate_commit_guard
                    )
                    manifest.transition(
                        [image_id], "succeeded", commit_guard=selection_commit_guard
                    )
                except (PermissionError, InterruptedError):
                    # Cancellation / lease loss is task control flow, not an inference
                    # failure. Do not persist a failed candidate for work we no longer
                    # own or the user explicitly stopped.
                    raise
                except Exception as error:
                    reason = self.public_error(error)
                    item.update({"status": "failed", "boxes": [], "error": reason})
                    self.store.append_items(
                        [item], commit_guard=candidate_commit_guard
                    )
                    manifest.transition(
                        [image_id], "failed", reason,
                        commit_guard=selection_commit_guard,
                    )
                    append_task_log(context, "annotation_error", f"image_id={image_id} {reason}")
            checkpoint = manifest.summary(image_id)
            context.save_checkpoint(checkpoint)
            check_active(context, "AI_ANNOTATION", image_id,
                         int(checkpoint["processed"] * 70 / max(1, checkpoint["total"])))

    def finish(self):
        summary = self.store.summary()
        self.context.artifacts.atomic_write_json(self.context.task.task_id, "generation.json", {
            "summary": summary, "generation_partial": bool(summary["failed"]),
        })
        return (TaskStatus.AWAITING_CONFIRMATION if summary["success"] + summary["empty"] else TaskStatus.FAILED,
                "candidates/manifest.json")

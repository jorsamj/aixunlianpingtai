"""Seed an isolated AI review task with N formal-GT candidates.

Used only by tests/browser/real-bulk-formal.spec.mjs. It writes through the
same repositories the product uses; no production data is touched.
"""
import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import app  # noqa: E402
from platform_core.annotation_candidates import CandidateStore  # noqa: E402
from platform_core.task_runtime import TaskKind, TaskRecord, TaskStatus  # noqa: E402

project_id = os.environ["MC_PROJECT_ID"]
task_id = os.environ["MC_TASK_ID"]
count = int(os.environ.get("MC_BULK_COUNT", "205"))

materials = app.material_store(project_id)
records, items = [], []
for index in range(count):
    image_id = f"bulk-{index:04d}"
    digest = hashlib.sha256(image_id.encode("utf-8")).hexdigest()
    records.append({
        "id": image_id,
        "filename": f"{image_id}.jpg",
        "storage_source_id": "default_local",
        "storage_type": "local",
        "object_key": f"uploads/{image_id}.jpg",
        "content_sha256": digest,
        "source_content_sha256": digest,
        "size_bytes": 1024,
        "dataset_id": "default",
        "processing_status": "processed",
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    })
    items.append({
        "image_id": image_id,
        "status": "success",
        "boxes": [{"id": f"box-{index}", "label": "fire",
                   "x1": 10, "y1": 10, "x2": 50, "y2": 50}],
        "width": 640,
        "height": 480,
        "source_content_sha256": digest,
        "review_state": "active",
    })
materials.upsert_many(records)

artifacts = app.shared_task_artifacts()
artifacts.atomic_write_json(task_id, "request.json", {
    "image_ids": [record["id"] for record in records],
    "labels": ["fire"],
})
repository = app.shared_task_repository()
repository.create(
    TaskRecord.new(task_id, project_id, TaskKind.AI_ANNOTATION, "request.json", "isolated-bulk"),
    artifacts=artifacts,
)
store = CandidateStore(artifacts, task_id=task_id)
store.initialize(labels=["fire"], total_images=count)
store.append_items(items)
lease = repository.claim_next("browser-bulk-fixture", {TaskKind.AI_ANNOTATION}, set())
repository.finish(task_id, lease.lease_token, TaskStatus.AWAITING_CONFIRMATION,
                  "candidates/manifest.json")
print(f"seeded {count} candidates for {project_id}/{task_id}")

"""Frozen remote training input transport; images never materialize on the controller.

This is an adapter over the canonical freeze contract and StorageManager, not a
second dataset/cache owner. The tiny bounded LRU retains verified JSON metadata
only; canonical artifact replacement invalidates it via file identity/stat.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

from .storage import StorageManager
from .training_tasks import _training_input_freeze_digest, resolve_training_input_freeze
from .training_splits import SplitMode, SplitRequest


@lru_cache(maxsize=2)
def _verified_freeze(path, stamp, expected_id):
    frozen = json.loads(Path(path).read_text(encoding="utf-8"))
    if frozen.get("input_freeze_id") != expected_id or _training_input_freeze_digest(frozen) != expected_id:
        raise ValueError("remote frozen input digest mismatch")
    return frozen, {str(row["id"]): row for row in frozen["images"]}


def _load(service, task, payload):
    ref = str(payload.get("input_freeze_ref") or "")
    if not ref:
        raise ValueError("remote frozen input is missing")
    path = service.task_artifacts.artifact_path(task.task_id, ref)
    info = path.stat()
    frozen, index = _verified_freeze(str(path),
        (info.st_ino, info.st_mtime_ns, info.st_size), str(payload.get("input_freeze_id") or ""))
    training = (payload.get("remote_execution") or {}).get("training") or {}
    if (training.get("schema_version") != 3
            or (training.get("inputs") or {}).get("input_freeze_id") != frozen["input_freeze_id"]
            or training.get("snapshot_id") != frozen["snapshot_id"]
            or training.get("dataset_revision_id") != frozen["dataset_revision_id"]):
        raise ValueError("remote frozen input identity mismatch")
    return frozen, index


def training_inputs(service, task, payload, *, image_id=None):
    # The caller is the original AgentExecutionService and must fence the real
    # execution before invoking this adapter (and before each streamed chunk).
    frozen, index = _load(service, task, payload)
    if image_id is None:
        portable = copy.deepcopy(frozen)
        for row in portable["images"]:
            for field in ("path", "stored_path"):
                row.pop(field, None)
        portable["source_input_freeze_id"] = frozen["input_freeze_id"]
        portable["input_freeze_id"] = _training_input_freeze_digest(portable)
        split = portable["split"]
        request = SplitRequest(mode=SplitMode(split["mode"]),
            train_image_ids=tuple(split["train_image_ids"]), test_image_ids=tuple(split["test_image_ids"]),
            experiment_percent=split.get("experiment_percent"), validation_percent=split["validation_percent"])
        # Validate that removing storage locations did not alter GT/split truth.
        resolve_training_input_freeze(portable, request, seed=split["seed"],
            supplement_candidate_set=payload.get("supplement_candidate_set"))
        return {"freeze": portable, "supplement_candidate_set": payload.get("supplement_candidate_set")}
    row = index.get(str(image_id))
    if row is None:
        raise ValueError("image is not in frozen training input")
    if row.get("source_available") is False:
        raise ValueError("frozen training source is unavailable")
    manager = StorageManager(data_dir=service.data_dir, project_id=task.project_id,
        credentials=service.storage_credentials_factory())
    normalized = manager.material(row)
    provider = manager.provider_for(normalized["storage_source_id"])
    metadata = provider.stat(normalized["object_key"])
    expected_size = int(row.get("size_bytes") or 0)
    expected_sha = str(row.get("content_sha256") or "")
    if (expected_size <= 0 or metadata.size_bytes != expected_size
            or (metadata.sha256 and metadata.sha256.lower() != expected_sha)
            or (row.get("etag") and metadata.etag != row["etag"])):
        raise ValueError("frozen training source size/hash/version changed")
    return {"reader": manager.open_reader(row), "size_bytes": expected_size, "sha256": expected_sha}

from __future__ import annotations

from types import SimpleNamespace

import platform_core.storage.optimized_import_tasks as optimized
from platform_core.storage.optimized_import_tasks import (
    OptimizedStorageImportHandler,
    worker_registration,
)
from platform_core.storage.zip_import import ExtractionProgress, MemberRecord
from platform_core.task_runtime import TaskKind, TaskStatus


def test_storage_role_keeps_existing_capability_contract(tmp_path):
    registration = worker_registration(tmp_path)
    assert isinstance(
        registration["handlers"][TaskKind.MATERIAL_IMPORT],
        OptimizedStorageImportHandler,
    )
    assert {
        "storage.import",
        "storage.rescan",
        "storage.label_remap",
    }.issubset(registration["capabilities"])


def test_large_zip_progress_does_not_hit_task_database_per_member(tmp_path, monkeypatch):
    handler = OptimizedStorageImportHandler(tmp_path)
    total = 50_000
    heartbeat_calls = []
    cancel_calls = []
    checkpoints = []
    records = {}

    class Repository:
        def heartbeat(self, *args, **kwargs):
            heartbeat_calls.append((args, kwargs))
            return SimpleNamespace(status=TaskStatus.RUNNING)

    class Context:
        task = SimpleNamespace(task_id="scale-import")
        lease = SimpleNamespace(lease_token="lease")
        repository = Repository()

        def load_checkpoint(self):
            return {}

        def save_checkpoint(self, value):
            checkpoints.append((value["stage"], value["zip_import"].get("extracted_files", 0)))

        def cancel_requested(self):
            cancel_calls.append(True)
            return False

    context = Context()
    monkeypatch.setattr(
        handler,
        "_server_zip_source",
        lambda _context, _request: (
            SimpleNamespace(id="local", type="local"),
            None,
            tmp_path,
            "dataset",
            "source.zip",
            tmp_path / "source.zip",
        ),
    )
    monkeypatch.setattr(handler, "_scan", lambda *_args: (TaskStatus.SUCCEEDED, "scan/result.json"))
    monkeypatch.setattr(optimized, "finalize_server_zip_publication", lambda *_args, **_kwargs: True)

    clock = [1000.0]

    def monotonic():
        clock[0] += 0.0001
        return clock[0]

    monkeypatch.setattr(optimized.time, "monotonic", monotonic)

    def fake_extract(_archive, _root, _prefix, *, task_id, completed, on_progress):
        del task_id, completed
        for index in range(1, total + 1):
            name = f"images/{index:06d}.jpg"
            record = MemberRecord(name=name, size_bytes=1, sha256="0" * 64)
            records[name] = record
            assert on_progress(ExtractionProgress(
                current_member=name,
                extracted_files=index,
                extracted_bytes=index,
                declared_files=total,
                declared_bytes=total,
                completed_member=record,
            )) is True
        return SimpleNamespace(
            members=records,
            extracted_files=total,
            extracted_bytes=total,
        )

    monkeypatch.setattr(optimized, "extract_server_zip", fake_extract)

    status, result_ref = handler._server_zip(context, {"recursive": True})

    assert status is TaskStatus.SUCCEEDED
    assert result_ref == "scan/result.json"
    # 50k files over the simulated five-second interval should cause only
    # human-scale DB polling, not one SQLite round trip per progress callback.
    assert 1 <= len(heartbeat_calls) < 20
    assert 1 <= len(cancel_calls) < 30
    # Durable member-map checkpoints stay bounded by the 8192-member default,
    # plus the final published checkpoint.
    assert 2 <= len(checkpoints) < 10

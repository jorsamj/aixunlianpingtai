from pathlib import Path

from platform_core.resource_discovery.cache import DiscoveryCache
from platform_core.resource_discovery.tasks import CACHE_FILENAME, RESULT_REF, ResourceDiscoveryHandler
from platform_core.task_runtime import ArtifactStore, Scheduler, TaskKind, TaskRecord, TaskRepository, TaskStatus


def test_durable_full_model_discovery_uses_only_frozen_roots_and_publishes_cache(tmp_path: Path):
    data_dir = tmp_path / "platform-data"
    runtime_dir = data_dir / "task_runtime"
    repository = TaskRepository(runtime_dir / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime_dir / "artifacts")

    frozen_root = tmp_path / "visible-local-root"
    nested = frozen_root / "models" / "nested"
    nested.mkdir(parents=True)
    included_model = nested / "included.onnx"
    included_model.write_bytes(b"onnx-integration-probe")

    outside_root = tmp_path / "not-frozen"
    outside_root.mkdir()
    excluded_model = outside_root / "must-not-be-scanned.pt"
    excluded_model.write_bytes(b"outside-frozen-roots")

    cache = DiscoveryCache(data_dir / CACHE_FILENAME)
    generation = cache.next_generation("models")
    task_id = "discovery-full-frozen-roots"
    request = {
        "discovery_type": "local_models",
        "scope": "full",
        "generation": generation,
        "roots": [str(frozen_root)],
    }
    artifacts.atomic_write_json(task_id, "request.json", request)
    repository.create(
        TaskRecord.new(
            task_id,
            "system",
            TaskKind.RESOURCE_DISCOVERY,
            "request.json",
            "cpu:discovery",
            required_capabilities=("resource.discovery",),
        )
    )

    scheduler = Scheduler(
        repository,
        artifacts,
        "discovery-integration-worker",
        {TaskKind.RESOURCE_DISCOVERY: ResourceDiscoveryHandler(data_dir)},
        {"resource.discovery"},
    )

    assert scheduler.run_once() is True
    completed = repository.get(task_id)
    assert completed.status is TaskStatus.SUCCEEDED
    assert completed.result_ref == RESULT_REF

    durable_request = artifacts.read_json(task_id, "request.json")
    assert durable_request["scope"] == "full"
    assert durable_request["roots"] == [str(frozen_root)]

    result = artifacts.read_json(task_id, completed.result_ref)
    assert result["ok"] is True
    assert result["scope"] == "full"
    assert result["scan_root_mode"] == "explicit"
    assert result["explicit_root_count"] == 1
    assert result["models_found"] == 1

    progress = artifacts.read_json(task_id, "progress.json")
    assert progress["stage"] == "completed"
    assert progress["models_found"] == 1

    page = cache.list_models(limit=20)
    assert len(page.items) == 1
    discovered = Path(page.items[0]["path"]).resolve()
    assert discovered == included_model.resolve()
    assert discovered != excluded_model.resolve()

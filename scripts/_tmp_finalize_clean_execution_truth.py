from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


def replace_function(text: str, name: str, replacement: str) -> str:
    pattern = rf"def {re.escape(name)}\(.*?(?=\n\ndef |\Z)"
    text, count = re.subn(pattern, replacement.rstrip(), text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{name}: expected one function, got {count}")
    return text


# Product correction: failed durable cleaning may be replayed by the same
# deterministic upload-batch association. Retry stays in TaskRepository and
# keeps the same task id; successful/awaiting terminal truth is never revived.
path = Path("app.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "    existing = repository.get(task_id)\n"
    "    if existing is not None:\n"
    "        return _v47_clean_compat_task(existing)\n"
    "    request = _v47_material_batch_request(task_id)\n",
    "    existing = repository.get(task_id)\n"
    "    if existing is not None:\n"
    "        compat = _v47_clean_compat_task(existing)\n"
    "        if compat.get('status') == 'failed':\n"
    "            existing = repository.retry(task_id)\n"
    "        return _v47_clean_compat_task(existing)\n"
    "    request = _v47_material_batch_request(task_id)\n",
    "durable failed cleaning retry",
)

# Web startup must never resurrect the retired daemon-thread cleaning owner.
# Expired durable tasks are recovered by TaskWorker/Scheduler lease recovery.
text, count = re.subn(
    r"def _v47_recover_clean_tasks\(project_id: str\) -> list\[str\]:.*?(?=\n\ndef _v47_create_clean_task_record)",
    "def _v47_recover_clean_tasks(project_id: str) -> list[str]:\n"
    "    get_project(project_id)\n"
    "    return []\n",
    text,
    count=1,
    flags=re.S,
)
if count != 1:
    raise SystemExit(f"legacy cleaning startup recovery: expected one match, got {count}")
path.write_text(text, encoding="utf-8")


# Existing upload-clean tests keep their business guarantees, but stop testing
# the retired in-process thread implementation. They now execute the actual
# materials Scheduler when a result is needed and inspect TaskRepository truth.
path = Path("tests/api/test_upload_clean_flow.py")
text = path.read_text(encoding="utf-8")
text = replace_function(
    text,
    "wait_for_clean_result",
    '''def _material_scheduler():
    import app as app_module
    from platform_core.task_runtime import ArtifactStore, FencedTaskRepository, Scheduler
    from platform_core.worker_registry import build_worker_registration

    runtime = app_module.DATA_DIR / "task_runtime"
    repository = FencedTaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")
    handlers, capabilities = build_worker_registration(app_module.DATA_DIR, {"materials"})
    return Scheduler(
        repository,
        artifacts,
        f"pytest-material-{uuid.uuid4().hex[:8]}",
        handlers,
        capabilities,
        lease_seconds=5,
        poll_seconds=0.01,
    )


def drive_clean_task(task_id: str, timeout: float = 15):
    import app as app_module

    scheduler = _material_scheduler()
    terminal = {
        "SUCCEEDED", "FAILED", "PARTIAL_SUCCESS", "CANCELLED",
        "BLOCKED_BY_ENVIRONMENT", "BLOCKED_BY_HARDWARE", "LOST",
    }
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = app_module.shared_task_repository().get(task_id)
        if current is None:
            raise AssertionError(f"durable clean task {task_id} is missing")
        if current.status.value in terminal:
            return current
        if not scheduler.run_once():
            time.sleep(0.01)
    raise AssertionError(f"durable clean task {task_id} timed out")


def wait_for_clean_result(client, pid: str, task_id: str, timeout: float = 15):
    drive_clean_task(task_id, timeout)
    response = client.get(f"/api/v47/projects/{pid}/clean-tasks/{task_id}/result")
    response.raise_for_status()
    body = response.json()
    status = body["task"].get("status")
    if status == "awaiting_confirmation":
        return body
    raise AssertionError(body["task"])''',
)

text = replace_function(
    text,
    "test_retry_after_prepared_task_before_batch_publication_completes_once",
    '''def test_retry_after_prepared_task_before_batch_publication_completes_once(client):
    import app as app_module

    pid = client.post(
        "/api/projects",
        json={"name": "prepared-before-publish", "labels": []},
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["clean.png"])
    image_id = uploaded["uploaded"][0]["id"]
    task_id = app_module._v55_upload_clean_task_id(pid, uploaded["batch_id"], [image_id])
    task, created = app_module._v62_prepare_clean_compat(
        pid,
        app_module.V47CleanReq(
            image_ids=[image_id],
            task_name=f"上传批次 {uploaded['batch_id']} 清洗",
        ),
        task_id=task_id,
    )
    assert created is True
    assert task["id"] == task_id
    assert app_module.shared_task_repository().get(task_id) is None

    response = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{uploaded['batch_id']}/decisions",
        json={"clean_image_ids": [image_id], "ready_image_ids": []},
    )
    response.raise_for_status()

    assert response.json()["clean_task_id"] == task_id
    durable = app_module.shared_task_repository().get(task_id)
    assert durable is not None
    assert durable.kind.value == "MATERIAL_BATCH"
    tasks = client.get(f"/api/v47/projects/{pid}/clean-tasks").json()["items"]
    assert [item["id"] for item in tasks].count(task_id) == 1''',
)

text = replace_function(
    text,
    "test_retry_starts_existing_prepared_task_exactly_once",
    '''def test_retry_starts_existing_prepared_task_exactly_once(client):
    import app as app_module

    pid = client.post(
        "/api/projects",
        json={"name": "start-prepared-on-retry", "labels": []},
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["clean.png"])
    image_id = uploaded["uploaded"][0]["id"]
    task_id = "b1c2d3e4f5a6"
    payload = app_module.V47CleanReq(
        image_ids=[image_id],
        task_name=f"上传批次 {uploaded['batch_id']} 清洗",
    )
    _, created = app_module._v62_prepare_clean_compat(pid, payload, task_id=task_id)
    assert created is True
    assert app_module.shared_task_repository().get(task_id) is None
    seed_published_clean_intent(app_module, pid, uploaded["batch_id"], image_id, task_id)

    first = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{uploaded['batch_id']}/decisions",
        json={"clean_image_ids": [image_id], "ready_image_ids": []},
    )
    first.raise_for_status()
    second = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{uploaded['batch_id']}/decisions",
        json={"clean_image_ids": [image_id], "ready_image_ids": []},
    )
    second.raise_for_status()

    assert first.json()["clean_task_id"] == second.json()["clean_task_id"] == task_id
    assert app_module.shared_task_repository().get(task_id) is not None
    tasks = client.get(f"/api/v47/projects/{pid}/clean-tasks").json()["items"]
    assert [item["id"] for item in tasks].count(task_id) == 1''',
)

text = replace_function(
    text,
    "test_concurrent_identical_decisions_spawn_one_task_worker",
    '''def test_concurrent_identical_decisions_spawn_one_task_worker(client):
    import app as app_module

    pid = client.post(
        "/api/projects",
        json={"name": "concurrent-clean-retry", "labels": []},
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["clean.png"])
    image_id = uploaded["uploaded"][0]["id"]
    url = f"/api/v55/projects/{pid}/upload-batches/{uploaded['batch_id']}/decisions"
    body = {"clean_image_ids": [image_id], "ready_image_ids": []}

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: client.post(url, json=body), range(2)))
    for response in responses:
        response.raise_for_status()
    task_ids = {response.json()["clean_task_id"] for response in responses}
    assert len(task_ids) == 1
    task_id = next(iter(task_ids))
    durable = app_module.shared_task_repository().get(task_id)
    assert durable is not None
    assert durable.kind.value == "MATERIAL_BATCH"
    tasks = client.get(f"/api/v47/projects/{pid}/clean-tasks").json()["items"]
    assert [item["id"] for item in tasks].count(task_id) == 1''',
)

# Remove the legacy JSON-status test helper; terminal state is now produced by
# the real material worker and read back from TaskRepository.
text = replace_function(text, "_set_clean_task_status", "")

text = replace_function(
    text,
    "test_replaying_clean_after_terminal_task_preserves_material_state",
    '''def test_replaying_clean_after_terminal_task_preserves_material_state(client):
    import app as app_module

    pid = client.post(
        "/api/projects", json={"name": "terminal-replay", "labels": []}
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["clean.png", "ready.png"])
    image_id = uploaded["uploaded"][0]["id"]
    batch_id = uploaded["batch_id"]
    first = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{batch_id}/decisions",
        json={"clean_image_ids": [image_id], "ready_image_ids": []},
    )
    first.raise_for_status()
    task_id = first.json()["clean_task_id"]
    wait_for_clean_result(client, pid, task_id)

    app_module.material_store(pid).patch(
        {
            image_id: {
                "processing_status": "processed",
                "cleaned_at": "sentinel-cleaned",
                "updated_at": "sentinel-updated",
            }
        }
    )
    response = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{batch_id}/decisions",
        json={"clean_image_ids": [image_id], "ready_image_ids": []},
    )
    response.raise_for_status()
    assert response.json()["clean_task_id"] == task_id
    row = {item["id"]: item for item in client.get(f"/api/projects/{pid}/images").json()}[image_id]
    assert row["processing_status"] == "processed"
    assert row["cleaned_at"] == "sentinel-cleaned"
    assert row["updated_at"] == "sentinel-updated"
    assert len(client.get(f"/api/v47/projects/{pid}/clean-tasks").json()["items"]) == 1''',
)

text = replace_function(
    text,
    "test_failed_clean_task_can_be_retried_with_same_task_id",
    '''def test_failed_clean_task_can_be_retried_with_same_task_id(client):
    import app as app_module

    pid = client.post(
        "/api/projects", json={"name": "failed-retry", "labels": []}
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["clean.png"])
    record = uploaded["uploaded"][0]
    image_id = record["id"]
    batch_id = uploaded["batch_id"]
    source_path = app_module.project_dir(pid) / "uploads" / record["stored_name"]
    original_bytes = source_path.read_bytes()

    first = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{batch_id}/decisions",
        json={"clean_image_ids": [image_id], "ready_image_ids": []},
    )
    first.raise_for_status()
    task_id = first.json()["clean_task_id"]
    source_path.unlink()
    failed = drive_clean_task(task_id)
    assert failed.status.value == "FAILED"

    source_path.write_bytes(original_bytes)
    retry = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{batch_id}/decisions",
        json={"clean_image_ids": [image_id], "ready_image_ids": []},
    )
    retry.raise_for_status()
    assert retry.json()["clean_task_id"] == task_id
    retried = app_module.shared_task_repository().get(task_id)
    assert retried is not None
    assert retried.status.value == "QUEUED"
    result = wait_for_clean_result(client, pid, task_id)
    assert result["task"]["status"] == "awaiting_confirmation"
    assert [item["id"] for item in client.get(f"/api/v47/projects/{pid}/clean-tasks").json()["items"]].count(task_id) == 1''',
)

text = replace_function(
    text,
    "test_running_clean_task_is_recovered_when_worker_registry_is_empty",
    '''def test_clean_task_recovery_is_owned_by_durable_worker_not_web_registry(client):
    import app as app_module

    pid = client.post(
        "/api/projects", json={"name": "running-recovery", "labels": []}
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["clean.png"])
    image_id = uploaded["uploaded"][0]["id"]
    response = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{uploaded['batch_id']}/decisions",
        json={"clean_image_ids": [image_id], "ready_image_ids": []},
    )
    response.raise_for_status()
    task_id = response.json()["clean_task_id"]
    before = app_module.shared_task_repository().get(task_id)
    assert before is not None and before.status.value == "QUEUED"

    assert app_module._v47_recover_clean_tasks(pid) == []
    after = app_module.shared_task_repository().get(task_id)
    assert after is not None and after.status.value == "QUEUED"
    result = wait_for_clean_result(client, pid, task_id)
    assert result["task"]["status"] == "awaiting_confirmation"''',
)

text = replace_function(
    text,
    "test_clean_decision_rollback_preserves_concurrent_updated_at",
    '''def test_clean_decision_rollback_preserves_concurrent_updated_at(client, monkeypatch):
    import app as app_module

    pid = client.post(
        "/api/projects", json={"name": "decision-rollback", "labels": []}
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["clean.png"])
    image_id = uploaded["uploaded"][0]["id"]
    batch_id = uploaded["batch_id"]

    def fail_publish(project_id, task_id):
        app_module.material_store(project_id).patch(
            {
                image_id: {
                    "filename": "concurrent-name.png",
                    "updated_at": "concurrent-updated",
                }
            }
        )
        raise RuntimeError("simulated durable publication failure")

    monkeypatch.setattr(app_module, "_v62_publish_clean_compat", fail_publish)
    response = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{batch_id}/decisions",
        json={"clean_image_ids": [image_id], "ready_image_ids": []},
    )
    assert response.status_code == 500
    batch = client.get(f"/api/v55/projects/{pid}/upload-batches/{batch_id}").json()
    assert batch["items"][0]["decision"] == "pending"
    row = {item["id"]: item for item in client.get(f"/api/projects/{pid}/images").json()}[image_id]
    assert row["processing_status"] == "pending_decision"
    assert row["filename"] == "concurrent-name.png"
    assert row["updated_at"] == "concurrent-updated"''',
)

for legacy_name in (
    "_v47_run_clean_task",
    "_V47_ACTIVE_CLEAN_WORKERS",
    "_set_clean_task_status",
):
    if legacy_name in text:
        raise SystemExit(f"upload clean regression still depends on retired {legacy_name}")
path.write_text(text, encoding="utf-8")


# Permanent release gate must run both the durable publication contract and the
# upload-batch atomicity/idempotency contract whenever cleaning execution moves.
path = Path(".github/workflows/v42.25-release-regression.yml")
text = path.read_text(encoding="utf-8")
if "      - platform_core/material_batches.py\n" not in text:
    text = replace_once(
        text,
        "      - platform_core/gpu_resources.py\n",
        "      - platform_core/gpu_resources.py\n      - platform_core/material_batches.py\n",
        "material batch release path",
    )
if "      - tests/api/test_upload_clean_flow.py\n" not in text:
    text = replace_once(
        text,
        "      - tests/api/test_clean_unified_execution_truth.py\n",
        "      - tests/api/test_clean_unified_execution_truth.py\n      - tests/api/test_upload_clean_flow.py\n",
        "upload clean release path",
    )
if "          tests/api/test_upload_clean_flow.py\n" not in text:
    text = replace_once(
        text,
        "          tests/api/test_clean_unified_execution_truth.py\n",
        "          tests/api/test_clean_unified_execution_truth.py\n          tests/api/test_upload_clean_flow.py\n",
        "upload clean runtime contract",
    )
path.write_text(text, encoding="utf-8")

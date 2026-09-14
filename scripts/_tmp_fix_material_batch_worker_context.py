from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


path = Path("platform_core/material_batches.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "        project = context.artifacts._validate_task_id(context.task.project_id)\n"
    "        materials = MaterialRepository(self.data_dir / \"projects\" / project)\n",
    "        project = str(context.task.project_id or '').strip()\n"
    "        if (\n"
    "            not project\n"
    "            or any(character in project for character in ('/', '\\\\'))\n"
    "            or not all(character.isalnum() or character in {'_', '-'} for character in project)\n"
    "        ):\n"
    "            raise ValueError('project id must be one safe path component')\n"
    "        projects_root = (self.data_dir / 'projects').resolve()\n"
    "        project_path = (projects_root / project).resolve()\n"
    "        if project_path.parent != projects_root:\n"
    "            raise ValueError('project id escaped projects root')\n"
    "        materials = MaterialRepository(project_path)\n",
    "material batch fenced worker project validation",
)
path.write_text(text, encoding="utf-8")


path = Path("tests/api/test_clean_unified_execution_truth.py")
text = path.read_text(encoding="utf-8")
text = replace_once(text, "import io\n", "import io\nimport uuid\n", "clean worker uuid import")
text = replace_once(
    text,
    "from platform_core.task_runtime import TaskKind, TaskStatus\n",
    "from platform_core.task_runtime import (\n"
    "    ArtifactStore, FencedTaskRepository, Scheduler, TaskKind, TaskStatus,\n"
    ")\n"
    "from platform_core.worker_registry import build_worker_registration\n",
    "clean worker runtime imports",
)
append = r'''


def test_clean_executes_through_real_fenced_material_worker(client):
    project_id = _create_project(client, "clean-real-fenced-worker")
    uploaded = _upload(client, project_id, "real-worker.png")
    image_id = uploaded["uploaded"][0]["id"]
    response = client.post(
        f"/api/v47/projects/{project_id}/clean-tasks",
        json={"image_ids": [image_id], "task_name": "real worker clean"},
    )
    response.raise_for_status()
    task_id = response.json()["id"]

    runtime = app_module.DATA_DIR / "task_runtime"
    repository = FencedTaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")
    handlers, capabilities = build_worker_registration(app_module.DATA_DIR, {"materials"})
    scheduler = Scheduler(
        repository,
        artifacts,
        f"clean-contract-{uuid.uuid4().hex[:8]}",
        handlers,
        capabilities,
        lease_seconds=5,
        poll_seconds=0.01,
    )
    for _ in range(10):
        current = app_module.shared_task_repository().get(task_id)
        assert current is not None
        if current.status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.PARTIAL_SUCCESS}:
            break
        assert scheduler.run_once() is True
    current = app_module.shared_task_repository().get(task_id)
    assert current is not None
    assert current.status is TaskStatus.SUCCEEDED, current.error
    assert current.progress == 100

    result_response = client.get(f"/api/v47/projects/{project_id}/clean-tasks/{task_id}/result")
    result_response.raise_for_status()
    body = result_response.json()
    assert body["task"]["status"] == "awaiting_confirmation"
    assert body["task"]["processed_images"] == 1
    assert body["task"]["progress"] == 100
    assert [item["image_id"] for item in body["result"]["items"]] == [image_id]
'''
if "def test_clean_executes_through_real_fenced_material_worker" in text:
    raise SystemExit("real fenced material worker contract already exists")
text = text.rstrip() + append + "\n"
path.write_text(text, encoding="utf-8")

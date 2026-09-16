from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise RuntimeError(f"{label}: expected source not found")
    return text.replace(old, new, 1)


def replace_mapping_line(block: str, key: str, value: str) -> str:
    pattern = re.compile(rf'^(\s*)["\']{re.escape(key)}["\']\s*:\s*.*$', re.M)
    match = pattern.search(block)
    if not match:
        raise RuntimeError(f"mapping key missing in _public_task: {key}")
    indent = match.group(1)
    return block[:match.start()] + f'{indent}"{key}": {value},' + block[match.end():]


def patch_public_py() -> None:
    path = "platform_core/task_runtime/public.py"
    text = read(path)
    old_sig = "def task_to_public(task: TaskRecord, repository: TaskRepository | None = None) -> dict[str, Any]:\n"
    new_sig = """def task_to_public(\n    task: TaskRecord,\n    repository: TaskRepository | None = None,\n    *,\n    now=None,\n    worker_runtime: list[dict[str, Any]] | None = None,\n    queued_candidates: tuple[TaskRecord, ...] | None = None,\n) -> dict[str, Any]:\n"""
    text = replace_once(text, old_sig, new_sig, "task_to_public signature")
    old_queue = """    queue_position = None\n    if repository is not None and task.status is TaskStatus.QUEUED:\n        queue_position = repository.resource_queue_position(task.task_id)\n    return {\n"""
    new_queue = """    queue_position = None\n    queue_position_exact = False\n    if repository is not None and task.status is TaskStatus.QUEUED:\n        queue_position = repository.resource_queue_position(task.task_id)\n        if task.kind is not TaskKind.TRAINING:\n            queue_position_exact = _non_training_queue_position_exact(\n                task,\n                repository,\n                queue_position=queue_position,\n                now=now,\n                worker_runtime=worker_runtime,\n                queued_candidates=queued_candidates,\n            )\n    return {\n"""
    text = replace_once(text, old_queue, new_queue, "task_to_public queue truth")
    text = replace_once(
        text,
        '        "resource_queue_position": queue_position,\n',
        '        "resource_queue_position": queue_position,\n        "resource_queue_position_exact": bool(queue_position_exact),\n',
        "public exact field",
    )
    marker = """def _waiting_training_truth(\n"""
    helper = '''def _non_training_queue_position_exact(\n    task: TaskRecord,\n    repository: TaskRepository,\n    *,\n    queue_position: int | None,\n    now=None,\n    worker_runtime: list[dict[str, Any]] | None = None,\n    queued_candidates: tuple[TaskRecord, ...] | None = None,\n) -> bool:\n    """Prove a non-training queue rank matches one real Worker claim order.\n\n    Resource-scoped SQL order alone is insufficient because a Worker may skip\n    tasks by kind/capability or compete across resource keys.  Exactness is\n    therefore fail-closed unless one compatible online Worker exists and every\n    queued task that Worker could claim belongs to this same resource queue.\n    """\n    if (\n        task.status is not TaskStatus.QUEUED\n        or task.kind is TaskKind.TRAINING\n        or queue_position is None\n    ):\n        return False\n    runtime = (\n        WorkerInstanceService(repository).list_runtime(now=now)\n        if worker_runtime is None\n        else worker_runtime\n    )\n    compatible = [\n        worker\n        for worker in runtime\n        if worker.get("online") is True and _worker_can_claim(worker, task)\n    ]\n    if len(compatible) != 1:\n        return False\n    worker = compatible[0]\n    candidates = (\n        repository.queued_candidates()\n        if queued_candidates is None\n        else queued_candidates\n    )\n    claimable = [candidate for candidate in candidates if _worker_can_claim(worker, candidate)]\n    if any(candidate.resource_key != task.resource_key for candidate in claimable):\n        return False\n    scan_position = next(\n        (\n            index\n            for index, candidate in enumerate(claimable, start=1)\n            if candidate.task_id == task.task_id\n        ),\n        None,\n    )\n    return scan_position is not None and scan_position == queue_position\n\n\n'''
    if helper not in text:
        if marker not in text:
            raise RuntimeError("generic queue helper insertion marker missing")
        text = text.replace(marker, helper + marker, 1)
    write(path, text)


def patch_app_py() -> None:
    path = "app.py"
    text = read(path)

    # Unified task list: snapshot Worker/candidate truth once, avoiding N+1 reads.
    old = '''    return {\n        "items": [task_to_public(task, repository) for task in page.items],\n        "next_cursor": page.next_cursor,\n    }\n'''
    new = '''    worker_runtime = WorkerInstanceService(repository).list_runtime()\n    queued_candidates = repository.queued_candidates()\n    return {\n        "items": [\n            task_to_public(\n                task, repository,\n                worker_runtime=worker_runtime, queued_candidates=queued_candidates,\n            )\n            for task in page.items\n        ],\n        "next_cursor": page.next_cursor,\n    }\n'''
    text = replace_once(text, old, new, "unified task list snapshot")

    # Compatibility projection used by resource discovery/video: source shared truth.
    start = text.index("def _public_task(task: TaskRecord) -> Dict[str, Any]:")
    end = text.index("\n\ndef _public_video_task", start)
    block = text[start:end]
    header = "def _public_task(task: TaskRecord) -> Dict[str, Any]:\n"
    new_header = '''def _public_task(\n    task: TaskRecord,\n    *,\n    worker_runtime=None,\n    queued_candidates=None,\n) -> Dict[str, Any]:\n    repository = shared_task_repository()\n    truth = task_to_public(\n        task, repository,\n        worker_runtime=worker_runtime, queued_candidates=queued_candidates,\n    )\n'''
    block = replace_once(block, header, new_header, "_public_task header")
    replacements = {
        "status": 'truth["status"]',
        "priority": 'truth["priority"]',
        "queue_rank": 'truth["queue_rank"]',
        "resource_queue_position": 'truth["resource_queue_position"]',
        "resource_wait_reason": 'truth["resource_wait_reason"]',
        "worker_id": 'truth["worker_id"]',
        "lease_expires_at": 'truth["lease_expires_at"]',
        "progress": 'truth["progress_percent"]',
        "stage": 'truth["phase"]',
        "current_item": 'truth["current_item"]',
    }
    for key, value in replacements.items():
        block = replace_mapping_line(block, key, value)
    lines = block.splitlines()
    out = []
    for line in lines:
        out.append(line)
        stripped = line.strip()
        if stripped.startswith('"status":') and '"task_status"' not in block:
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f'{indent}"task_status": truth["status"],')
            out.append(f'{indent}"persisted_status": truth["persisted_status"],')
        if stripped.startswith('"resource_queue_position":') and '"resource_queue_position_exact"' not in block:
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f'{indent}"resource_queue_position_exact": truth["resource_queue_position_exact"],')
        if stripped.startswith('"progress":') and '"progress_percent"' not in block:
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f'{indent}"progress_percent": truth["progress_percent"],')
        if stripped.startswith('"stage":') and '"phase"' not in block:
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f'{indent}"phase": truth["phase"],')
    block = "\n".join(out)
    text = text[:start] + block + text[end:]

    # Video compatibility projection/list shares one runtime snapshot.
    text = replace_once(
        text,
        "def _public_video_task(task: TaskRecord) -> Dict[str, Any]:\n    response = _public_task(task)\n",
        "def _public_video_task(task: TaskRecord, *, worker_runtime=None, queued_candidates=None) -> Dict[str, Any]:\n    response = _public_task(task, worker_runtime=worker_runtime, queued_candidates=queued_candidates)\n",
        "video public projection",
    )
    video_start = text.index('def v33_list_video_tasks(project_id: str, limit: int = 50, cursor: Optional[str] = None):')
    video_end = text.index('\n\n@app.get("/api/v33/projects/{project_id}/video-tasks/{task_id}")', video_start)
    video = text[video_start:video_end]
    video = replace_once(
        video,
        "    page = shared_task_repository().list(\n",
        "    repository = shared_task_repository()\n    page = repository.list(\n",
        "video list repository",
    )
    video = replace_once(
        video,
        '    return {"items": [_public_video_task(task) for task in page.items], "next_cursor": page.next_cursor}\n',
        '    worker_runtime = WorkerInstanceService(repository).list_runtime()\n    queued_candidates = repository.queued_candidates()\n    return {"items": [_public_video_task(task, worker_runtime=worker_runtime, queued_candidates=queued_candidates) for task in page.items], "next_cursor": page.next_cursor}\n',
        "video list snapshot",
    )
    text = text[:video_start] + video + text[video_end:]

    # Annotation projections/list use the same snapshot model.
    text = replace_once(
        text,
        "def public_annotation_task(task: TaskRecord, *, summary: Optional[dict] = None) -> Dict[str, Any]:\n",
        "def public_annotation_task(\n    task: TaskRecord, *, summary: Optional[dict] = None,\n    worker_runtime=None, queued_candidates=None,\n) -> Dict[str, Any]:\n",
        "annotation public signature",
    )
    text = replace_once(
        text,
        "    truth = task_to_public(task, repository)\n",
        "    truth = task_to_public(\n        task, repository,\n        worker_runtime=worker_runtime, queued_candidates=queued_candidates,\n    )\n",
        "annotation shared truth",
    )
    ann_start = text.index("def list_annotation_tasks(project_id: str, limit: int = 50, cursor: Optional[str] = None):")
    ann_end = text.index("\n\ndef _require_annotation_review_task", ann_start)
    ann = text[ann_start:ann_end]
    ann = replace_once(
        ann,
        "    page = shared_task_repository().list(\n",
        "    repository = shared_task_repository()\n    page = repository.list(\n",
        "annotation list repository",
    )
    ann = replace_once(
        ann,
        '    return {"items": [public_annotation_task(task) for task in page.items], "next_cursor": page.next_cursor}\n',
        '    worker_runtime = WorkerInstanceService(repository).list_runtime()\n    queued_candidates = repository.queued_candidates()\n    return {"items": [public_annotation_task(task, worker_runtime=worker_runtime, queued_candidates=queued_candidates) for task in page.items], "next_cursor": page.next_cursor}\n',
        "annotation list snapshot",
    )
    text = text[:ann_start] + ann + text[ann_end:]
    write(path, text)


def patch_material_batches_py() -> None:
    path = "platform_core/material_batches.py"
    text = read(path)
    text = replace_once(
        text,
        '            "resource_queue_position": truth["resource_queue_position"] if truth else None,\n',
        '            "resource_queue_position": truth["resource_queue_position"] if truth else None,\n            "resource_queue_position_exact": truth["resource_queue_position_exact"] if truth else False,\n',
        "material batch exact projection",
    )
    write(path, text)


def patch_frontend() -> None:
    path = "static/modules/annotation-task-view.js"
    text = read(path)
    if "exactTaskQueuePosition" not in text:
        text = "import {exactTaskQueuePosition} from './task-runtime-truth.js';\n" + text
    text = replace_once(
        text,
        "  const queuePosition = Math.max(0, Number(task.resource_queue_position) || 0);\n",
        "  const queuePosition = exactTaskQueuePosition(task) || 0;\n",
        "annotation exact queue",
    )
    write(path, text)

    path = "static/modules/material-batches.js"
    text = read(path)
    text = replace_once(
        text,
        "import {canonicalTaskStatus, isCanonicalTaskActive} from './task-runtime-truth.js';\n",
        "import {canonicalTaskStatus, exactTaskQueuePosition, isCanonicalTaskActive} from './task-runtime-truth.js';\n",
        "material batch truth import",
    )
    text = replace_once(
        text,
        "  const queuePosition = Math.max(0, Number(task.resource_queue_position) || 0);\n",
        "  const queuePosition = exactTaskQueuePosition(task) || 0;\n",
        "material batch exact queue",
    )
    write(path, text)


def patch_backend_tests() -> None:
    path = "tests/unit/task_runtime/test_public_projection.py"
    text = read(path)
    addition = '''\n\ndef add_video(repository, task_id, priority=50, resource="cpu:video"):\n    return repository.create(TaskRecord.new(\n        task_id, "project-1", TaskKind.VIDEO_FRAMES, "request.json", resource,\n        priority=priority, required_capabilities=("opencv",),\n    ))\n\n\ndef test_generic_queue_position_is_exact_for_one_dedicated_worker(tmp_path):\n    repository = TaskRepository(tmp_path / "tasks.sqlite3")\n    first = add_video(repository, "video-first", priority=5)\n    second = add_video(repository, "video-second", priority=50)\n    register_worker(\n        repository, "video-worker",\n        task_kinds=(TaskKind.VIDEO_FRAMES.value,), capabilities=("opencv",),\n    )\n\n    public = task_to_public(second, repository)\n\n    assert public["resource_queue_position"] == 2\n    assert public["resource_queue_position_exact"] is True\n    assert repository.resource_queue_position(first.task_id) == 1\n\n\ndef test_generic_queue_position_is_inexact_without_compatible_worker(tmp_path):\n    repository = TaskRepository(tmp_path / "tasks.sqlite3")\n    task = add_video(repository, "video-no-worker")\n\n    public = task_to_public(task, repository)\n\n    assert public["resource_queue_position"] == 1\n    assert public["resource_queue_position_exact"] is False\n\n\ndef test_generic_queue_position_is_inexact_with_multiple_compatible_workers(tmp_path):\n    repository = TaskRepository(tmp_path / "tasks.sqlite3")\n    task = add_video(repository, "video-many-workers")\n    for worker_id in ("video-worker-a", "video-worker-b"):\n        register_worker(\n            repository, worker_id,\n            task_kinds=(TaskKind.VIDEO_FRAMES.value,), capabilities=("opencv",),\n        )\n\n    public = task_to_public(task, repository)\n\n    assert public["resource_queue_position"] == 1\n    assert public["resource_queue_position_exact"] is False\n\n\ndef test_generic_queue_position_is_inexact_when_worker_competes_across_resources(tmp_path):\n    repository = TaskRepository(tmp_path / "tasks.sqlite3")\n    target = add_video(repository, "video-target", priority=50, resource="cpu:video")\n    add_video(repository, "video-other-resource", priority=5, resource="cpu:video-secondary")\n    register_worker(\n        repository, "video-worker",\n        task_kinds=(TaskKind.VIDEO_FRAMES.value,), capabilities=("opencv",),\n    )\n\n    public = task_to_public(target, repository)\n\n    assert public["resource_queue_position"] == 1\n    assert public["resource_queue_position_exact"] is False\n\n\ndef test_running_generic_task_never_exposes_queue_position(tmp_path):\n    repository = TaskRepository(tmp_path / "tasks.sqlite3")\n    add_video(repository, "video-running")\n    register_worker(\n        repository, "video-worker",\n        task_kinds=(TaskKind.VIDEO_FRAMES.value,), capabilities=("opencv",),\n    )\n    lease = repository.claim_next("video-worker", [TaskKind.VIDEO_FRAMES], {"opencv"})\n    assert lease is not None\n\n    public = task_to_public(repository.get("video-running"), repository)\n\n    assert public["status"] == "RUNNING"\n    assert public["resource_queue_position"] is None\n    assert public["resource_queue_position_exact"] is False\n'''
    if "test_generic_queue_position_is_exact_for_one_dedicated_worker" not in text:
        text += addition
    write(path, text)


def patch_frontend_tests() -> None:
    path = "tests/frontend/phase2-task-truth.test.mjs"
    text = read(path)
    text = text.replace(
        "resource_queue_position: 2, resource_wait_reason: 'VISION_CAPACITY_BUSY',",
        "resource_queue_position: 2, resource_queue_position_exact: true, resource_wait_reason: 'VISION_CAPACITY_BUSY',",
        1,
    )
    text = text.replace(
        "materialBatchTaskText({status:'WAITING_RESOURCE', resource_queue_position:3, resource_wait_reason:'MATERIAL_WORKER_BUSY'}),",
        "materialBatchTaskText({status:'WAITING_RESOURCE', resource_queue_position:3, resource_queue_position_exact:true, resource_wait_reason:'MATERIAL_WORKER_BUSY'}),",
        1,
    )
    addition = '''\n\ntest('annotation and material batch never promote inexact candidate ranks', () => {\n  const annotation = annotationTaskView({\n    status: 'WAITING_RESOURCE', resource_queue_position: 7, resource_queue_position_exact: false,\n    resource_wait_reason: 'VISION_CAPACITY_BUSY',\n  });\n  assert.equal(annotation.runtimeText, '等待资源 · VISION_CAPACITY_BUSY');\n  assert.equal(annotation.runtimeText.includes('第 7 位'), false);\n  const material = materialBatchTaskText({\n    status: 'WAITING_RESOURCE', resource_queue_position: 9, resource_queue_position_exact: false,\n    resource_wait_reason: 'MATERIAL_WORKER_BUSY',\n  });\n  assert.equal(material, '等待资源 · MATERIAL_WORKER_BUSY');\n  assert.equal(material.includes('第 9 位'), false);\n});\n'''
    if "never promote inexact candidate ranks" not in text:
        text += addition
    write(path, text)

    path = "tests/frontend/annotation-task-view.test.mjs"
    text = read(path)
    addition = '''\n\ntest('annotation queue number is visible only when backend proves exactness', () => {\n  const exact = annotationTaskView({\n    task_status: 'WAITING_RESOURCE', status: 'completed',\n    resource_queue_position: 2, resource_queue_position_exact: true,\n    resource_wait_reason: 'VISION_CAPACITY_BUSY',\n  });\n  assert.equal(exact.status, 'WAITING_RESOURCE');\n  assert.equal(exact.runtimeText, '资源队列第 2 位 · VISION_CAPACITY_BUSY');\n\n  const inexact = annotationTaskView({\n    status: 'QUEUED', resource_queue_position: 2, resource_queue_position_exact: false,\n  });\n  assert.equal(inexact.runtimeText, '');\n});\n'''
    if "backend proves exactness" not in text:
        text += addition
    write(path, text)


def write_handoff() -> None:
    path = ROOT / "docs" / "CODEX_HANDOFF_2026-09-16_GENERIC_QUEUE_EXACTNESS.md"
    path.write_text('''# Generic Durable Queue Exactness Closure\n\nDate: 2026-09-16\nBranch: `refactor/frontend-runtime-stabilization`\nFormal version remains `42.24.0`.\n\n## Scope\n\nThis closure completes the backend half of Task Runtime Truth v2 for non-training durable tasks. A numeric resource-scoped queue position is not automatically an executable Worker rank. The backend now emits `resource_queue_position_exact` only when it can prove the resource order and the unique compatible Worker claim order are the same.\n\n## Proof rule\n\nFor a queued non-training task, exactness is true only when all of the following hold:\n\n- exactly one online Worker can claim the task kind and all required capabilities;\n- every queued task that Worker could claim belongs to the same `resource_key`;\n- the task position in that Worker's claimable durable scan equals `resource_queue_position`.\n\nNo compatible Worker, multiple compatible Workers, cross-resource competition, and non-queued tasks fail closed to `resource_queue_position_exact=false`. Training keeps its specialized CPU/GPU/remote queue truth and GPU admission semantics. Scheduler claim order itself is unchanged.\n\n## Frontend contract\n\nAI annotation and material-batch views now use the same `exactTaskQueuePosition()` helper as storage import, resource discovery, video, deployment tests, and training UI. They may show “资源队列第 N 位” only when the backend exact flag is true. Wait reasons remain visible when rank is inexact.\n\n## Performance\n\nUnified task, video-task, and annotation-task list endpoints snapshot Worker runtime and queued candidates once per response and reuse those snapshots for every item, avoiding an N+1 Worker/candidate query pattern.\n\n## Boundaries\n\nThis batch does not change Scheduler selection, priority, promotion, Worker capabilities, leases, GPU admission, or the already-closed v47 cleaning compatibility projection. Genuine 10k validation and A800 RC remain deferred.\n''', encoding="utf-8")


def main() -> None:
    patch_public_py()
    patch_app_py()
    patch_material_batches_py()
    patch_frontend()
    patch_backend_tests()
    patch_frontend_tests()
    write_handoff()


if __name__ == "__main__":
    main()
